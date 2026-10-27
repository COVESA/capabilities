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
capability_framework.capabilities.window.manager
================================================
WindowManager owns the ``moveWindow()`` public interface.

Internal execution order for every ``moveWindow()`` call:
  1. ARBITRATION     — first-in-wins priority queue; higher-priority source pre-empts.
  2. PRECONDITION    — checks vehicle state (power, OTA).
  3. SAFETY CASE     — validates position range, voltage, thermal state.
  4. ACTUATOR CALL   — delegates to the southbound ``WindowActuatorPort``.
  5. STATE PUBLISH   — emits ``WindowState`` on the event bus.

Pinch detection: if the actuator reports a pinch event during closing, the
window auto-reverses to the last safe position and publishes ``PINCHED`` with
``PINCH_DETECTED``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Protocol

from ...events import EventBus, Topics
from ...southbound import ActuatorError, ActuatorProfile, WindowActuatorPort
from ...vehicle_state import OtaState, PowerState, VehicleState
from ..base import (
    PRIORITY as _PRIORITY,
    ActuatorOutcome,
    Capability,
    CapabilityDescriptor,
    NorthboundOperation,
    SystemModel,
)
from .types import (
    API_VERSION,
    MoveWindowCommand,
    WindowInhibitReason,
    WindowState,
    WindowStatus,
    WindowZone,
)

log = logging.getLogger(__name__)

_UNDERVOLTAGE_V = 12.0


class WindowPlantModel(SystemModel, Protocol):
    """What WindowManager needs from an injected window plant model."""

    def compute_move_kpis(self, target_mm: float, from_mm: float | None = None) -> Any: ...

    def for_profile(self, profile: ActuatorProfile) -> "WindowPlantModel": ...


class WindowManager(Capability[MoveWindowCommand, WindowState]):
    """
    Manages window movement requests with arbitration, safety gating, pinch
    detection, and actuator dispatch.

    Northbound API:
      - moveWindow(MoveWindowCommand) → WindowState
      - releaseWindow(request_id) → None
      - can_execute(MoveWindowCommand) → WindowState

    Southbound dependencies:
      - WindowActuatorPort.move_window(zone, target_pct) → float
      - WindowActuatorPort.get_window_position(zone) → float
    """

    def __init__(
        self,
        actuator: WindowActuatorPort,
        event_bus: EventBus | None = None,
        motor_model: WindowPlantModel | None = None,
    ) -> None:
        super().__init__(actuator, event_bus)
        self._motor_model = motor_model
        self._profile = None
        self._agnostic_kpis: dict | None = None
        self._deployment_kpis: dict | None = None

    # ── Capability descriptor ─────────────────────────────────────────────

    @property
    def descriptor(self) -> CapabilityDescriptor:
        return CapabilityDescriptor(
            name="window",
            display_name="Window Movement Control",
            description=(
                "Controls vehicle power windows with position targeting, "
                "pinch detection, and auto-reverse safety. Supports per-zone "
                "operation (driver/passenger, front/rear) with arbitration "
                "and vehicle state preconditions."
            ),
            api_version=API_VERSION,
            domain="body",
            asil_tier="ASIL_B",
            northbound_operations=(
                "moveWindow", "releaseWindow", "can_execute",
                "cascade_open", "cascade_close", "sync_all", "orchestrate",
            ),
            southbound_dependencies=("move_window", "get_window_position"),
            system_model_params=self.get_transfer_function_params(),
        )

    @property
    def northbound_api(self) -> list[NorthboundOperation]:
        return [
            NorthboundOperation(
                name="moveWindow",
                description="Move a single window zone to target (0%=closed, 100%=open)",
                command_type="MoveWindowCommand",
                response_type="WindowState",
                is_async=True,
                requires_arbitration=True,
                vss_paths=(
                    "Vehicle.Cabin.Door.Row1.DriverSide.Window.Position",
                    "Vehicle.Cabin.Door.Row1.PassengerSide.Window.Position",
                    "Vehicle.Cabin.Door.Row2.DriverSide.Window.Position",
                    "Vehicle.Cabin.Door.Row2.PassengerSide.Window.Position",
                ),
            ),
            NorthboundOperation(
                name="releaseWindow",
                description="Release the per-zone window lock for a given request_id",
                command_type="str",
                response_type="None",
                is_async=False,
                requires_arbitration=False,
            ),
            NorthboundOperation(
                name="can_execute",
                description="Pre-flight check: runs the full pipeline with no side effects",
                command_type="MoveWindowCommand",
                response_type="WindowState",
                is_async=False,
                requires_arbitration=False,
            ),
            NorthboundOperation(
                name="cascade_open",
                description="Orchestration API: open front row first, then rear row (staggers inrush)",
                command_type="WindowSequenceCommand",
                response_type="WindowSequenceState",
                is_async=True,
                requires_arbitration=True,
            ),
            NorthboundOperation(
                name="cascade_close",
                description="Orchestration API: close rear row first, then front row",
                command_type="WindowSequenceCommand",
                response_type="WindowSequenceState",
                is_async=True,
                requires_arbitration=True,
            ),
            NorthboundOperation(
                name="sync_all",
                description="Orchestration API: synchronously move all four window zones to target",
                command_type="WindowSequenceCommand",
                response_type="WindowSequenceState",
                is_async=True,
                requires_arbitration=True,
            ),
            NorthboundOperation(
                name="orchestrate",
                description="Orchestration API: execute a staged multi-zone window sequence",
                command_type="WindowSequenceCommand",
                response_type="WindowSequenceState",
                is_async=True,
                requires_arbitration=True,
            ),
        ]

    @property
    def state_topic(self) -> str:
        return Topics.WINDOW_STATE

    @property
    def system_model(self) -> WindowPlantModel | None:
        return self._motor_model

    # ── Deployment physics binding (southbound boundary) ──────────────────

    @property
    def deployment_profile(self):
        """The bound ActuatorProfile, or None while still hardware-agnostic."""
        return self._profile

    @property
    def agnostic_kpis(self) -> dict | None:
        """KPIs predicted from datasheet params (before deployment binding)."""
        return self._agnostic_kpis

    @property
    def deployment_kpis(self) -> dict | None:
        """KPIs recomputed from the bound deployment profile."""
        return self._deployment_kpis

    async def bind_deployment(self, *, ref_target_mm: float = 300.0,
                              ref_from_mm: float = 0.0) -> None:
        """
        Meet the deployment physics at the southbound boundary.

        Asks the port to describe its actuator, re-parameterises the physics
        model from that profile, and recomputes the move KPIs. The capability's
        code does not change — only its physics model and derived limits.
        Idempotent. Without an injected model only the profile is recorded.
        """
        profile = await self._actuator.describe_actuator("window")
        self._profile = profile
        if self._motor_model is None:
            log.info("WindowManager: bound deployment '%s' (no system model injected)", profile.deployment_id)
            return

        if self._agnostic_kpis is None:
            self._agnostic_kpis = self._motor_model.compute_move_kpis(
                target_mm=ref_target_mm, from_mm=ref_from_mm,
            ).summary()

        self._motor_model = self._motor_model.for_profile(profile)
        self._deployment_kpis = self._motor_model.compute_move_kpis(
            target_mm=ref_target_mm, from_mm=ref_from_mm,
        ).summary()

        log.info(
            "WindowManager: bound deployment '%s' (source=%s conf=%.2f) — latency %.2fs→%.2fs",
            profile.deployment_id, profile.source.value, profile.confidence,
            self._agnostic_kpis["move_latency_s"], self._deployment_kpis["move_latency_s"],
        )

    # ── Public interface (northbound API) ─────────────────────────────────

    async def moveWindow(self, command: MoveWindowCommand) -> WindowState:
        """Primary northbound operation: arbitration → precondition → safety → actuator → publish."""
        async with self._lock:
            # ── 1. ARBITRATION ────────────────────────────────────────────
            arb_reason = self._arbitrate(command)
            if arb_reason:
                return await self._rejected_state(arb_reason, command)

            self._open_release(command.request_id)
            self._active_request = command
            log.info("WindowManager: ARBITRATION WON  source=%s  zone=%s  id=%s",
                     command.source.name, command.zone.value, command.request_id)
            try:
                # ── 2. PRECONDITION CHECK ─────────────────────────────────
                vs: VehicleState | None = self._bus.last(Topics.VEHICLE_STATE)
                inhibit = self._check_preconditions(vs)
                if inhibit:
                    return await self._inhibited_state(inhibit, command)

                # ── 3. SAFETY CASE ────────────────────────────────────────
                fault = self._safety_case(command, vs)
                if fault:
                    return await self._inhibited_state(fault, command)

                # ── 4. ACTUATOR DISPATCH ──────────────────────────────────
                try:
                    run = await self._run_actuator(
                        command.request_id,
                        self._actuator.move_window(command.zone.value, command.target_pct),
                        command.timeout_s,
                    )
                except ActuatorError as exc:
                    log.warning("WindowManager: actuator error — %s", exc)
                    held = await self._held(command.zone.value,
                                            lambda: self._actuator.get_window_position(command.zone.value))
                    new_pct = held.value
                    if "pinch" in str(exc).lower():
                        status, reason = WindowStatus.PINCHED, WindowInhibitReason.PINCH_DETECTED
                    else:
                        status, reason = WindowStatus.INHIBITED, WindowInhibitReason.THERMAL_PROTECTION
                else:
                    if run.outcome is not ActuatorOutcome.COMPLETED:
                        return await self._interrupted_state(run.outcome, command)
                    new_pct = run.result
                    self._confirm(command.zone.value, new_pct)
                    status, reason = WindowStatus.MOVING, None

                # ── 5. PUBLISH STATE ──────────────────────────────────────
                state = WindowState(
                    status=status,
                    position_pct=new_pct,
                    zone=command.zone,
                    reason=reason,
                    winning_source=command.source,
                    request_id=command.request_id,
                    api_version=API_VERSION,
                )
                await self._bus.publish(Topics.WINDOW_STATE, state)
                return state
            finally:
                self._active_request = None
                self._close_release(command.request_id)

    async def releaseWindow(self, request_id: str) -> None:
        """Release the window lock for request_id; an in-flight move stops at its current position."""
        active = self._active_request
        if active is None or active.request_id != request_id:
            return
        log.info("WindowManager: explicit release  id=%s", request_id)
        self._signal_release(request_id)
        self._active_request = None

    async def can_execute(self, command: MoveWindowCommand) -> WindowState:
        """Pre-flight check: arbitration + precondition + safety, with NO side effects."""
        arb_reason = self._arbitrate(command, dry_run=True)
        if arb_reason:
            pos = await self._actuator.get_window_position(command.zone.value)
            return WindowState(
                status=WindowStatus.REJECTED, position_pct=pos, zone=command.zone,
                reason=WindowInhibitReason.WINDOW_BUSY, message=arb_reason,
                winning_source=(self._active_request.source if self._active_request else None),
                request_id=command.request_id, api_version=API_VERSION,
            )

        vs = self._bus.last(Topics.VEHICLE_STATE)
        inhibit = self._check_preconditions(vs)
        if inhibit:
            pos = await self._actuator.get_window_position(command.zone.value)
            return WindowState(
                status=WindowStatus.INHIBITED, position_pct=pos, zone=command.zone,
                reason=WindowInhibitReason(inhibit) if inhibit in WindowInhibitReason.__members__ else WindowInhibitReason.POWER_OFF,
                message=inhibit, winning_source=command.source,
                request_id=command.request_id, api_version=API_VERSION,
            )

        fault = self._safety_case(command, vs)
        if fault:
            pos = await self._actuator.get_window_position(command.zone.value)
            return WindowState(
                status=WindowStatus.INHIBITED, position_pct=pos, zone=command.zone,
                reason=WindowInhibitReason(fault) if fault in WindowInhibitReason.__members__ else WindowInhibitReason.OUT_OF_RANGE,
                message=fault, winning_source=command.source,
                request_id=command.request_id, api_version=API_VERSION,
            )

        pos = await self._actuator.get_window_position(command.zone.value)
        return WindowState(
            status=WindowStatus.STATIONARY, position_pct=pos, zone=command.zone,
            reason=None, message="can_execute: all checks passed",
            winning_source=command.source, request_id=command.request_id, api_version=API_VERSION,
        )

    # ── Phase implementations ─────────────────────────────────────────────

    def _arbitrate(self, command: MoveWindowCommand, *, dry_run: bool = False) -> str | None:
        """Phase 1: first-in-wins with priority pre-emption."""
        active = self._active_request
        if active is None:
            return None

        elapsed = (datetime.now(timezone.utc) - active.timestamp.replace(tzinfo=timezone.utc)).total_seconds()
        if elapsed >= active.timeout_s:
            if not dry_run:
                self._active_request = None
            return None

        if _PRIORITY[command.source] > _PRIORITY[active.source]:
            if not dry_run:
                self._active_request = None
            return None

        return f"window_busy: active request from {active.source.name} (id={active.request_id})"

    def _check_preconditions(self, vs: VehicleState | None) -> str | None:
        """Phase 2: vehicle-state precondition check."""
        if vs is None:
            return None  # fail-open for simulation
        if vs.power_state == PowerState.OFF:
            return WindowInhibitReason.POWER_OFF.value
        if vs.ota_state in (OtaState.DOWNLOADING, OtaState.APPLYING):
            return WindowInhibitReason.OTA_IN_PROGRESS.value
        return None

    def _safety_case(self, command: MoveWindowCommand, vs: VehicleState | None) -> str | None:
        """Phase 3: domain-specific safety validation."""
        if vs is not None and vs.supply_voltage_v < _UNDERVOLTAGE_V:
            return WindowInhibitReason.UNDERVOLTAGE.value
        if not (0.0 <= command.target_pct <= 100.0):
            return WindowInhibitReason.OUT_OF_RANGE.value
        return None

    async def _dispatch(self, command: MoveWindowCommand) -> float:
        """Phase 4: actuator dispatch."""
        return await self._actuator.move_window(command.zone.value, command.target_pct)

    async def _build_state(self, command: MoveWindowCommand, dispatch_result: float, status: str) -> WindowState:
        """Phase 5: build state for publish."""
        return WindowState(
            status=WindowStatus(status), position_pct=dispatch_result, zone=command.zone,
            winning_source=command.source, request_id=command.request_id, api_version=API_VERSION,
        )

    # ── Helper methods ────────────────────────────────────────────────────

    async def _rejected_state(self, reason: str, command: MoveWindowCommand) -> WindowState:
        pos = await self._actuator.get_window_position(command.zone.value)
        state = WindowState(
            status=WindowStatus.REJECTED, position_pct=pos, zone=command.zone,
            reason=WindowInhibitReason.WINDOW_BUSY, message=reason,
            winning_source=(self._active_request.source if self._active_request else None),
            request_id=command.request_id, api_version=API_VERSION,
        )
        await self._bus.publish(Topics.WINDOW_STATE, state)
        return state

    async def _interrupted_state(self, outcome: ActuatorOutcome, command: MoveWindowCommand) -> WindowState:
        """Safe state: the window stops where it is; an unknown position is an ACTUATOR_FAULT."""
        zone = command.zone.value
        held = await self._held(zone, lambda: self._actuator.get_window_position(zone))
        if held.value is None:
            status, reason, message = WindowStatus.INHIBITED, WindowInhibitReason.ACTUATOR_FAULT, f"{outcome.value}: {held.message}"
        else:
            status, message = WindowStatus.STATIONARY, held.message
            reason = (WindowInhibitReason.RELEASED if outcome is ActuatorOutcome.RELEASED
                      else WindowInhibitReason.TIMEOUT)
        state = WindowState(
            status=status, position_pct=held.value, zone=command.zone, reason=reason,
            message=message, winning_source=command.source,
            request_id=command.request_id, api_version=API_VERSION,
        )
        await self._bus.publish(Topics.WINDOW_STATE, state)
        return state

    async def _inhibited_state(self, reason: str, command: MoveWindowCommand) -> WindowState:
        pos = await self._actuator.get_window_position(command.zone.value)
        try:
            typed_reason = WindowInhibitReason(reason)
        except ValueError:
            typed_reason = WindowInhibitReason.POWER_OFF
        state = WindowState(
            status=WindowStatus.INHIBITED, position_pct=pos, zone=command.zone,
            reason=typed_reason, message=reason, winning_source=command.source,
            request_id=command.request_id, api_version=API_VERSION,
        )
        await self._bus.publish(Topics.WINDOW_STATE, state)
        return state
