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
capability_framework.bindings.simulator
=======================================
In-process simulation binding for the window southbound port — the runnable
hardware stand-in.

``WindowSimulatorPort`` drives the injected ``WindowMotorModel`` (the 4-stage
BOND graph) for each move and reports the resulting position. No real ECU: the
binding is where the physics model plugs in, exactly as a real binding would
map the port onto a motor driver.

Only southbound types cross this boundary.
"""

from __future__ import annotations

import logging

from ..models.window_motor import WindowMotorModel, WindowMotorParams
from ..southbound import ActuatorError, ActuatorProfile, ProfileSource, WindowActuatorPort

__all__ = ["WindowSimulatorPort"]

log = logging.getLogger(__name__)

#: Travel of the modelled window, in millimetres (0 = full open, 300 = full closed).
TRAVEL_MM = 300.0


def _pct_to_mm(pct: float) -> float:
    """API position (0% closed … 100% open) → model position (300 mm closed … 0 mm open)."""
    return (100.0 - max(0.0, min(100.0, pct))) / 100.0 * TRAVEL_MM


def _mm_to_pct(mm: float) -> float:
    """Model position → API position (0% closed … 100% open)."""
    return (1.0 - max(0.0, min(TRAVEL_MM, mm)) / TRAVEL_MM) * 100.0


class WindowSimulatorPort(WindowActuatorPort):
    """In-process window actuator backed by the BOND-graph motor model."""

    def __init__(self, model: WindowMotorModel | None = None,
                 params: WindowMotorParams | None = None) -> None:
        self._model = model or WindowMotorModel(params)
        # Current position (%) per zone.
        self._zones: dict[str, float] = {
            "DRIVER_FRONT": 0.0,
            "PASSENGER_FRONT": 0.0,
            "DRIVER_REAR": 0.0,
            "PASSENGER_REAR": 0.0,
        }
        self._profile = self._build_profile()

    # ── Southbound API ───────────────────────────────────────────────────

    async def move_window(self, zone: str, target_pct: float) -> float:
        if zone == "ALL":
            for z in list(self._zones):
                await self.move_window(z, target_pct)
            return self._zones["DRIVER_FRONT"]

        target_pct = max(0.0, min(100.0, target_pct))
        from_pct = self._zones.get(zone, 0.0)

        # Drive the physics model from the current position to the target.
        self._model.simulate_move(
            target_mm=_pct_to_mm(target_pct),
            from_mm=_pct_to_mm(from_pct),
        )
        if self._model.pinch_detected:
            # The binding reports a pinch as a typed actuator error, as a real
            # binding would after applying its mitigation.
            self._zones[zone] = _mm_to_pct(self._model.get_state().position)
            raise ActuatorError(f"pinch detected moving {zone} toward {target_pct:.1f}%")

        self._zones[zone] = _mm_to_pct(self._model.get_state().position)
        log.debug("WindowSimulatorPort: %s → %.1f%% (model pos %.1f mm)",
                  zone, self._zones[zone], self._model.get_state().position)
        return self._zones[zone]

    async def get_window_position(self, zone: str) -> float:
        return self._zones.get(zone, 0.0)

    # ── Deployment profile ───────────────────────────────────────────────

    async def describe_actuator(self, capability: str) -> ActuatorProfile:
        return self._profile

    def _build_profile(self) -> ActuatorProfile:
        p = self._model._p  # noqa: SLF001 — the binding owns the model
        return ActuatorProfile(
            capability="window",
            deployment_id="simulated-window",
            supply_voltage_v=p.supply_voltage_v,
            current_limit_a=p.current_peak_a,
            travel_min_mm=0.0,
            travel_max_mm=TRAVEL_MM,
            motor_ke=p.Ke,
            motor_kt=p.Kt,
            resistance_ohm=p.resistance_ohm,
            inductance_h=p.inductance_h,
            load_mass_kg=p.window_mass_kg,
            geometry_gain_m_rad=p.actuator_gain_m_rad,
            friction_coefficient=p.friction_coefficient,
            seal_damping_ns_m=p.seal_damping_ns_m,
            pinch_force_threshold_n=p.pinch_force_threshold_n,
            source=ProfileSource.DATASHEET,
            confidence=0.5,
        )
