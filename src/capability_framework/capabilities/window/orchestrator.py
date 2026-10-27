# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
capability_framework.capabilities.window.orchestrator
=====================================================
WindowCapabilityOrchestrator — the paired domain capability orchestrator for the
window domain.

Coordinates multi-zone window sequences (intra-domain multi-instance staging).
Every zone move is issued through ``WindowManager``'s public northbound API
(``moveWindow``) — this class NEVER touches the actuator port. That layering
invariant is what makes it an *orchestrator* and not a second manager.

Public API (northbound):
    orchestrate(cmd) -> WindowSequenceState
    can_orchestrate(cmd) -> WindowSequenceState
    cascade_open(source, target_pct=100.0) -> WindowSequenceState
    cascade_close(source, target_pct=0.0) -> WindowSequenceState
    sync_all(source, target_pct) -> WindowSequenceState
    abort() -> None
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from ...capabilities.base import RequestSource
from ...events import EventBus
from .types import (
    API_VERSION,
    MoveWindowCommand,
    WindowGroup,
    WindowInhibitReason,
    WindowSequenceCommand,
    WindowSequenceMode,
    WindowSequenceStage,
    WindowSequenceState,
    WindowSequenceStatus,
    WindowState,
    WindowStatus,
    WindowZone,
)

if TYPE_CHECKING:
    from .manager import WindowManager

log = logging.getLogger(__name__)


class WindowCapabilityOrchestrator:
    """
    Domain capability orchestrator for the window domain.

    Strict layering invariant: this class calls WindowManager's public northbound
    primitives (``moveWindow`` / ``can_execute``) and never touches the actuator
    port. That is what makes it an *orchestrator* rather than a second manager.
    """

    _GROUP_ZONES: dict[WindowGroup, tuple[WindowZone, ...]] = {
        WindowGroup.ROW_1_FRONT: (WindowZone.DRIVER_FRONT, WindowZone.PASSENGER_FRONT),
        WindowGroup.ROW_2_REAR: (WindowZone.DRIVER_REAR, WindowZone.PASSENGER_REAR),
        WindowGroup.DRIVER_SIDE: (WindowZone.DRIVER_FRONT, WindowZone.DRIVER_REAR),
        WindowGroup.PASSENGER_SIDE: (WindowZone.PASSENGER_FRONT, WindowZone.PASSENGER_REAR),
        WindowGroup.ALL: (WindowZone.DRIVER_FRONT, WindowZone.PASSENGER_FRONT,
                          WindowZone.DRIVER_REAR, WindowZone.PASSENGER_REAR),
    }

    def __init__(
        self,
        window_manager: "WindowManager",
        event_bus: EventBus | None = None,
        source: RequestSource = RequestSource.OEM_AUTOMATION,
    ) -> None:
        self._window = window_manager
        self._bus = event_bus
        self._source = source
        self._aborted = False
        self._lock = asyncio.Lock()

    async def orchestrate(self, cmd: WindowSequenceCommand) -> WindowSequenceState:
        """Execute a multi-stage window sequence via ``WindowManager.moveWindow()``."""
        async with self._lock:
            self._aborted = False
            per_zone: dict[str, WindowState] = {}
            deadline = time.monotonic() + cmd.timeout_s
            timed_out = False
            log.info("WindowOrch: orchestrate mode=%s stages=%d req=%s",
                     cmd.mode.value, len(cmd.stages), cmd.request_id)

            for i, stage in enumerate(cmd.stages):
                if self._aborted:
                    return WindowSequenceState(
                        status=WindowSequenceStatus.ABORTED, active_stage_index=i,
                        per_zone=per_zone, reason="abort() called",
                        request_id=cmd.request_id, api_version=API_VERSION)

                if time.monotonic() >= deadline:
                    return WindowSequenceState(
                        status=WindowSequenceStatus.PARTIAL, active_stage_index=i,
                        per_zone=per_zone, reason=f"sequence timed out after {cmd.timeout_s}s",
                        request_id=cmd.request_id, api_version=API_VERSION)

                zones = self._GROUP_ZONES.get(stage.group, ())
                # Zones within a stage are dispatched SEQUENTIALLY through the
                # manager NB API — in real hardware this staggers inrush current.
                results: list[WindowState | Exception] = []
                for zone in zones:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        timed_out = True
                        break
                    try:
                        results.append(await self._window.moveWindow(MoveWindowCommand(
                            source=cmd.source, zone=zone,
                            target_pct=stage.target_pct, timeout_s=remaining)))
                    except Exception as exc:  # noqa: BLE001
                        results.append(exc)

                if timed_out:
                    return WindowSequenceState(
                        status=WindowSequenceStatus.PARTIAL, active_stage_index=i,
                        per_zone=per_zone, reason=f"sequence timed out after {cmd.timeout_s}s",
                        request_id=cmd.request_id, api_version=API_VERSION)

                stage_ok = (len(results) == len(zones))
                for zone, result in zip(zones, results):
                    if isinstance(result, Exception):
                        stage_ok = False
                        continue
                    per_zone[zone.value] = result
                    if result.status in (WindowStatus.REJECTED, WindowStatus.INHIBITED, WindowStatus.PINCHED) \
                            or result.reason == WindowInhibitReason.TIMEOUT:
                        if result.reason == WindowInhibitReason.TIMEOUT:
                            timed_out = True
                        stage_ok = False
                    elif (result.position_pct is not None
                          and abs(result.position_pct - stage.target_pct) > stage.completion_threshold_pct):
                        stage_ok = False

                if not stage_ok:
                    reason = (
                        f"sequence timed out after {cmd.timeout_s}s"
                        if timed_out or time.monotonic() >= deadline
                        else f"stage {i} had one or more zone failures or incomplete movement"
                    )
                    return WindowSequenceState(
                        status=WindowSequenceStatus.PARTIAL, active_stage_index=i,
                        per_zone=per_zone, reason=reason,
                        request_id=cmd.request_id, api_version=API_VERSION)

            if time.monotonic() >= deadline:
                return WindowSequenceState(
                    status=WindowSequenceStatus.PARTIAL,
                    active_stage_index=len(cmd.stages) - 1 if cmd.stages else 0,
                    per_zone=per_zone, reason=f"sequence timed out after {cmd.timeout_s}s",
                    request_id=cmd.request_id, api_version=API_VERSION)

            return WindowSequenceState(
                status=WindowSequenceStatus.COMPLETED,
                active_stage_index=len(cmd.stages) - 1 if cmd.stages else 0,
                per_zone=per_zone, request_id=cmd.request_id, api_version=API_VERSION)

    async def can_orchestrate(self, cmd: WindowSequenceCommand) -> WindowSequenceState:
        """Pre-flight check across all stages — zero side effects."""
        per_zone: dict[str, WindowState] = {}
        for i, stage in enumerate(cmd.stages):
            for zone in self._GROUP_ZONES.get(stage.group, ()):
                result = await self._window.can_execute(MoveWindowCommand(
                    source=cmd.source, zone=zone, target_pct=stage.target_pct))
                per_zone[zone.value] = result
                if result.status in (WindowStatus.REJECTED, WindowStatus.INHIBITED):
                    return WindowSequenceState(
                        status=WindowSequenceStatus.PARTIAL, active_stage_index=i,
                        per_zone=per_zone, reason=f"can_execute rejected {zone.value}",
                        request_id=cmd.request_id, api_version=API_VERSION)
        return WindowSequenceState(
            status=WindowSequenceStatus.COMPLETED,
            active_stage_index=len(cmd.stages) - 1 if cmd.stages else 0,
            per_zone=per_zone, request_id=cmd.request_id, api_version=API_VERSION)

    async def cascade_open(self, source: RequestSource, target_pct: float = 100.0) -> WindowSequenceState:
        """Convenience: open front row first, then rear row."""
        return await self.orchestrate(WindowSequenceCommand(
            source=source, mode=WindowSequenceMode.CASCADE_OPEN,
            stages=(WindowSequenceStage(group=WindowGroup.ROW_1_FRONT, target_pct=target_pct),
                    WindowSequenceStage(group=WindowGroup.ROW_2_REAR, target_pct=target_pct))))

    async def cascade_close(self, source: RequestSource, target_pct: float = 0.0) -> WindowSequenceState:
        """Convenience: close rear row first, then front row."""
        return await self.orchestrate(WindowSequenceCommand(
            source=source, mode=WindowSequenceMode.CASCADE_CLOSE,
            stages=(WindowSequenceStage(group=WindowGroup.ROW_2_REAR, target_pct=target_pct),
                    WindowSequenceStage(group=WindowGroup.ROW_1_FRONT, target_pct=target_pct))))

    async def sync_all(self, source: RequestSource, target_pct: float) -> WindowSequenceState:
        """Convenience: move every zone to the same target in one stage."""
        return await self.orchestrate(WindowSequenceCommand(
            source=source, mode=WindowSequenceMode.SYNC,
            stages=(WindowSequenceStage(group=WindowGroup.ALL, target_pct=target_pct),)))

    def abort(self) -> None:
        """Signal the running orchestration to stop after the current stage."""
        self._aborted = True
