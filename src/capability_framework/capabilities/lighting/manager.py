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
capability_framework.capabilities.lighting.manager
==================================================
LightingManager owns the ``setInteriorLight()`` public interface — the lighting
counterpart of the window capability's ``moveWindow()``.

Internal execution order for every ``setInteriorLight()`` call:
  1. ARBITRATION     — first-in-wins priority queue; higher-priority source pre-empts.
  2. PRECONDITION    — checks vehicle state (power, OTA).
  3. SAFETY CASE     — validates supply voltage, intensity range and color format.
  4. ACTUATOR CALL   — delegates to the southbound ``LightingActuatorPort``.
  5. STATE PUBLISH   — emits ``LightingState`` on the event bus.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ...events import EventBus, Topics
from ...semantics.vss_paths import LIGHTING_INTENSITY
from ...southbound import ActuatorError, LightingActuatorPort, LightOutput
from ...vehicle_state import OtaState, PowerState, VehicleState
from ..base import (
    PRIORITY as _PRIORITY,
    ActuatorOutcome,
    Capability,
    CapabilityDescriptor,
    NorthboundOperation,
)
from .types import (
    API_VERSION,
    COLOR_PATTERN,
    LightingInhibitReason,
    LightingState,
    LightingStatus,
    LightingZone,
    SetInteriorLightCommand,
)

log = logging.getLogger(__name__)

# Ambient lighting draws little current, so it is allowed below the window's
# 12.0 V floor; below this it is shed to protect the battery.
_UNDERVOLTAGE_V = 11.0

_ADDRESSABLE_ZONES = (
    LightingZone.DRIVER_FRONT,
    LightingZone.PASSENGER_FRONT,
    LightingZone.DRIVER_REAR,
    LightingZone.PASSENGER_REAR,
)


def _status_for(intensity_pct: float | None) -> LightingStatus:
    return LightingStatus.ON if intensity_pct else LightingStatus.OFF


class LightingManager(Capability[SetInteriorLightCommand, LightingState]):
    """
    Manages interior lighting requests with arbitration, vehicle-state gating,
    input validation, and actuator dispatch.

    Northbound API:
      - setInteriorLight(SetInteriorLightCommand) → LightingState
      - releaseInteriorLight(request_id) → None
      - can_execute(SetInteriorLightCommand) → LightingState
      - getInteriorLightState(zone) → LightingState

    Southbound dependencies:
      - LightingActuatorPort.set_ambient_light(zone, intensity_pct, color) → LightOutput
      - LightingActuatorPort.get_ambient_light(zone) → LightOutput
    """

    def __init__(self, actuator: LightingActuatorPort, event_bus: EventBus | None = None) -> None:
        super().__init__(actuator, event_bus)

    # ── Capability descriptor ─────────────────────────────────────────────

    @property
    def descriptor(self) -> CapabilityDescriptor:
        return CapabilityDescriptor(
            name="lighting",
            display_name="Interior Lighting Control",
            description=(
                "Controls the cabin's ambient lights per zone: on/off, intensity "
                "(0-100%), and RGB color. Supports per-zone operation "
                "(driver/passenger, front/rear) with arbitration and vehicle "
                "state preconditions."
            ),
            api_version=API_VERSION,
            domain="body",
            asil_tier="QM",
            northbound_operations=(
                "setInteriorLight", "releaseInteriorLight", "can_execute", "getInteriorLightState",
            ),
            southbound_dependencies=("set_ambient_light", "get_ambient_light"),
            system_model_params=self.get_transfer_function_params(),
        )

    @property
    def northbound_api(self) -> list[NorthboundOperation]:
        intensity_paths = tuple(LIGHTING_INTENSITY[zone.value] for zone in _ADDRESSABLE_ZONES)
        return [
            NorthboundOperation(
                name="setInteriorLight",
                description="Set a single lighting zone's intensity (0%=off, 100%=full) and optional color",
                command_type="SetInteriorLightCommand",
                response_type="LightingState",
                is_async=True,
                requires_arbitration=True,
                vss_paths=intensity_paths,
            ),
            NorthboundOperation(
                name="releaseInteriorLight",
                description="Release the lighting lock for a given request_id",
                command_type="str",
                response_type="None",
                is_async=False,
                requires_arbitration=False,
            ),
            NorthboundOperation(
                name="can_execute",
                description="Pre-flight check: runs the full pipeline with no side effects",
                command_type="SetInteriorLightCommand",
                response_type="LightingState",
                is_async=False,
                requires_arbitration=False,
            ),
            NorthboundOperation(
                name="getInteriorLightState",
                description="Read the current state for a zone (on/off, intensity, color)",
                command_type="LightingZone",
                response_type="LightingState",
                is_async=False,
                requires_arbitration=False,
                vss_paths=intensity_paths,
            ),
        ]

    @property
    def state_topic(self) -> str:
        return Topics.LIGHTING_STATE

    # ── Public interface (northbound API) ─────────────────────────────────

    async def setInteriorLight(self, command: SetInteriorLightCommand) -> LightingState:
        """Primary northbound operation: arbitration → precondition → safety → actuator → publish."""
        async with self._lock:
            # ── 1. ARBITRATION ────────────────────────────────────────────
            arb_reason = self._arbitrate(command)
            if arb_reason:
                return await self._publish(await self._rejected_state(arb_reason, command))

            self._open_release(command.request_id)
            self._active_request = command
            log.info("LightingManager: ARBITRATION WON  source=%s  zone=%s  id=%s",
                     command.source.name, command.zone.value, command.request_id)
            try:
                # ── 2. PRECONDITION CHECK ─────────────────────────────────
                vs: VehicleState | None = self._bus.last(Topics.VEHICLE_STATE)
                inhibit = self._check_preconditions(vs)
                if inhibit:
                    return await self._publish(await self._inhibited_state(inhibit, command))

                # ── 3. SAFETY CASE ────────────────────────────────────────
                fault = self._safety_case(command, vs)
                if fault:
                    return await self._publish(await self._inhibited_state(fault, command))

                # ── 4. ACTUATOR DISPATCH ──────────────────────────────────
                zone = command.zone.value
                try:
                    run = await self._run_actuator(command.request_id, self._dispatch(command),
                                                   command.timeout_s)
                except ActuatorError as exc:
                    log.warning("LightingManager: actuator error — %s", exc)
                    held = await self._held(zone, lambda: self._actuator.get_ambient_light(zone))
                    output: LightOutput | None = held.value
                    state = LightingState(
                        status=LightingStatus.INHIBITED,
                        intensity_pct=output.intensity_pct if output else None,
                        color=output.color if output else None,
                        zone=command.zone, reason=LightingInhibitReason.ACTUATOR_FAULT,
                        message=str(exc), winning_source=command.source,
                        request_id=command.request_id, api_version=API_VERSION,
                    )
                    return await self._publish(state)

                if run.outcome is not ActuatorOutcome.COMPLETED:
                    return await self._publish(await self._interrupted_state(run.outcome, command))

                output = run.result
                self._confirm(zone, output)

                # ── 5. PUBLISH STATE ──────────────────────────────────────
                return await self._publish(
                    await self._build_state(command, output, _status_for(output.intensity_pct).value)
                )
            finally:
                self._active_request = None
                self._close_release(command.request_id)

    async def releaseInteriorLight(self, request_id: str) -> None:
        """Release the lighting lock for request_id; an in-flight command holds the current output."""
        active = self._active_request
        if active is None or active.request_id != request_id:
            return
        log.info("LightingManager: explicit release  id=%s", request_id)
        self._signal_release(request_id)
        self._active_request = None

    async def can_execute(self, command: SetInteriorLightCommand) -> LightingState:
        """Pre-flight check: arbitration + precondition + safety, with NO side effects."""
        arb_reason = self._arbitrate(command, dry_run=True)
        if arb_reason:
            return await self._rejected_state(arb_reason, command)

        vs = self._bus.last(Topics.VEHICLE_STATE)
        problem = self._check_preconditions(vs) or self._safety_case(command, vs)
        if problem:
            return await self._inhibited_state(problem, command)

        output = await self._actuator.get_ambient_light(command.zone.value)
        return LightingState(
            status=_status_for(output.intensity_pct), intensity_pct=output.intensity_pct,
            color=output.color, zone=command.zone, reason=None,
            message="can_execute: all checks passed", winning_source=command.source,
            request_id=command.request_id, api_version=API_VERSION,
        )

    async def getInteriorLightState(self, zone: LightingZone) -> LightingState:
        """Read the zone's current output. A read never takes the arbitration lock."""
        output = await self._actuator.get_ambient_light(zone.value)
        return LightingState(
            status=_status_for(output.intensity_pct), intensity_pct=output.intensity_pct,
            color=output.color, zone=zone, api_version=API_VERSION,
        )

    # ── Phase implementations ─────────────────────────────────────────────

    def _arbitrate(self, command: SetInteriorLightCommand, *, dry_run: bool = False) -> str | None:
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

        return f"lighting_busy: active request from {active.source.name} (id={active.request_id})"

    def _check_preconditions(self, vs: VehicleState | None) -> str | None:
        """Phase 2: vehicle-state precondition check. Lighting is allowed in ACC as well as ON."""
        if vs is None:
            return None  # fail-open for simulation
        if vs.power_state == PowerState.OFF:
            return LightingInhibitReason.POWER_OFF.value
        if vs.ota_state in (OtaState.DOWNLOADING, OtaState.APPLYING):
            return LightingInhibitReason.OTA_IN_PROGRESS.value
        return None

    def _safety_case(self, command: SetInteriorLightCommand, vs: VehicleState | None) -> str | None:
        """Phase 3: domain-specific validation."""
        if vs is not None and vs.supply_voltage_v < _UNDERVOLTAGE_V:
            return LightingInhibitReason.UNDERVOLTAGE.value
        if not (0.0 <= command.intensity_pct <= 100.0):
            return LightingInhibitReason.OUT_OF_RANGE.value
        if command.color is not None and not COLOR_PATTERN.fullmatch(command.color):
            return LightingInhibitReason.INVALID_COLOR.value
        return None

    async def _dispatch(self, command: SetInteriorLightCommand) -> LightOutput:
        """Phase 4: actuator dispatch."""
        color = command.color.upper() if command.color else None
        return await self._actuator.set_ambient_light(command.zone.value, command.intensity_pct, color)

    async def _build_state(self, command: SetInteriorLightCommand, dispatch_result: LightOutput,
                           status: str) -> LightingState:
        """Phase 5: build state for publish."""
        color = dispatch_result.color
        if command.zone is LightingZone.ALL:
            # Intensity is uniform across ALL, but the zones may keep different
            # colors; only a commanded color is known to hold for every zone.
            color = command.color.upper() if command.color else None
        return LightingState(
            status=LightingStatus(status), intensity_pct=dispatch_result.intensity_pct,
            color=color, zone=command.zone,
            winning_source=command.source, request_id=command.request_id, api_version=API_VERSION,
        )

    # ── Helper methods ────────────────────────────────────────────────────

    async def _publish(self, state: LightingState) -> LightingState:
        await self._bus.publish(Topics.LIGHTING_STATE, state)
        return state

    async def _rejected_state(self, reason: str, command: SetInteriorLightCommand) -> LightingState:
        output = await self._actuator.get_ambient_light(command.zone.value)
        return LightingState(
            status=LightingStatus.REJECTED, intensity_pct=output.intensity_pct, color=output.color,
            zone=command.zone, reason=LightingInhibitReason.LIGHTING_BUSY, message=reason,
            winning_source=(self._active_request.source if self._active_request else None),
            request_id=command.request_id, api_version=API_VERSION,
        )

    async def _inhibited_state(self, reason: str, command: SetInteriorLightCommand) -> LightingState:
        output = await self._actuator.get_ambient_light(command.zone.value)
        return LightingState(
            status=LightingStatus.INHIBITED, intensity_pct=output.intensity_pct, color=output.color,
            zone=command.zone, reason=LightingInhibitReason(reason), message=reason,
            winning_source=command.source, request_id=command.request_id, api_version=API_VERSION,
        )

    async def _interrupted_state(self, outcome: ActuatorOutcome,
                                 command: SetInteriorLightCommand) -> LightingState:
        """Safe state: the light holds its current output; an unknown output is an ACTUATOR_FAULT."""
        zone = command.zone.value
        held = await self._held(zone, lambda: self._actuator.get_ambient_light(zone))
        output: LightOutput | None = held.value
        if output is None:
            status, reason = LightingStatus.INHIBITED, LightingInhibitReason.ACTUATOR_FAULT
            message = f"{outcome.value}: {held.message}"
        else:
            status, message = _status_for(output.intensity_pct), held.message
            reason = (LightingInhibitReason.RELEASED if outcome is ActuatorOutcome.RELEASED
                      else LightingInhibitReason.TIMEOUT)
        return LightingState(
            status=status, intensity_pct=output.intensity_pct if output else None,
            color=output.color if output else None, zone=command.zone, reason=reason,
            message=message, winning_source=command.source,
            request_id=command.request_id, api_version=API_VERSION,
        )
