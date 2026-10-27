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
capability_framework.southbound.profile
=======================================
Deployment Physics Profile — the hardware-agnostic physics envelope a concrete
actuator binding hands UP across the southbound boundary.

Above the southbound API a capability is hardware-agnostic: it reasons only in
typed physical quantities (volts, amps, millimetres, newtons, motor constants).
Below it a binding knows the actual microcontroller, motor, geometry and load.
The profile deliberately carries NO hardware addressing (bus ids, ECU ids,
service ids) — those never cross the boundary.

Two flows use it:

1. Bind-time handshake — ``describe_actuator()`` → ``ActuatorProfile``
2. Calibration feedback — ``report_move_outcome(MoveOutcome)`` refines the
   profile DATASHEET → CALIBRATED → IDENTIFIED.

Mapping a profile onto a specific plant model lives next to that model, so this
module stays a leaf.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

__all__ = ["ActuatorProfile", "MoveOutcome", "ProfileSource", "PROFILE_SOURCE_TRUST"]


class ProfileSource(str, Enum):
    """Provenance of a profile's parameters — increasing trust left→right."""
    DATASHEET = "datasheet"      # nominal values from the component datasheet
    CALIBRATED = "calibrated"    # adjusted at end-of-line / install calibration
    IDENTIFIED = "identified"    # system-identified from observed real moves


#: Total order over provenance, so trust can be compared and never regressed.
PROFILE_SOURCE_TRUST: dict["ProfileSource", int] = {
    ProfileSource.DATASHEET: 0,
    ProfileSource.CALIBRATED: 1,
    ProfileSource.IDENTIFIED: 2,
}


def _TRUST(source: "ProfileSource") -> int:
    return PROFILE_SOURCE_TRUST[source]


@dataclass(frozen=True)
class MoveOutcome:
    """A single measured real-world move reported by the binding for learning."""
    travel_mm: float
    measured_latency_s: float
    measured_peak_current_a: float | None   # None when the reporter cannot measure current
    rising: bool                            # True = against gravity (closing/raising)
    stalled: bool = False


@dataclass(frozen=True)
class ActuatorProfile:
    """
    The deployment physics envelope for one capability on one vehicle.

    All fields are hardware-agnostic physical quantities. A binding returns a
    populated profile from ``describe_actuator()``; the capability maps it into
    its plant model with that model's ``from_profile`` mapper.
    """
    capability: str
    deployment_id: str

    # ── Electrical envelope (driver-stage limits) ────────────────────────
    supply_voltage_v: float
    current_limit_a: float

    # ── Travel envelope (geometry) ───────────────────────────────────────
    travel_min_mm: float
    travel_max_mm: float

    # ── DC motor constants (the specific motor fitted) ───────────────────
    motor_ke: float           # back-EMF constant  [V·s/rad]
    motor_kt: float           # torque constant    [N·m/A]
    resistance_ohm: float
    inductance_h: float

    # ── Mechanical load (geometry + glass/seal for this door) ────────────
    load_mass_kg: float
    geometry_gain_m_rad: float
    friction_coefficient: float
    seal_damping_ns_m: float
    gravity_assists_open: bool = True

    # ── Safety limits derived for this deployment ────────────────────────
    pinch_force_threshold_n: float = 100.0

    # ── Provenance + learned measurements ────────────────────────────────
    source: ProfileSource = ProfileSource.DATASHEET
    confidence: float = 0.5
    samples: int = 0
    measured_latency_s: float | None = None
    measured_peak_current_a: float | None = None
    stall_count: int = 0
    min_operating_voltage_v: float = 12.0
    peak_current_samples: int = 0

    def refined_with(self, outcome: MoveOutcome) -> "ActuatorProfile":
        """
        Fold a measured move into the profile (the learning step).

        Returns a NEW frozen profile. Observables are blended by a running mean
        and provenance is promoted DATASHEET → CALIBRATED → IDENTIFIED as
        evidence accumulates. Learning is monotonic in trust: neither ``source``
        nor ``confidence`` can decrease.
        """
        n = self.samples
        new_n = n + 1

        def _blend(prev: float | None, new: float) -> float:
            if prev is None:
                return new
            return (prev * n + new) / new_n

        new_latency = _blend(self.measured_latency_s, outcome.measured_latency_s)
        peak_samples = self.peak_current_samples or (n if self.measured_peak_current_a is not None else 0)
        if outcome.measured_peak_current_a is None:
            new_peak_i = self.measured_peak_current_a
            new_peak_samples = peak_samples
        else:
            new_peak_i = (
                outcome.measured_peak_current_a
                if self.measured_peak_current_a is None
                else (self.measured_peak_current_a * peak_samples + outcome.measured_peak_current_a) / (peak_samples + 1)
            )
            new_peak_samples = peak_samples + 1
        new_stalls = self.stall_count + (1 if outcome.stalled else 0)

        if new_n >= 5:
            new_source = ProfileSource.IDENTIFIED
        elif new_n >= 1:
            new_source = max(self.source, ProfileSource.CALIBRATED, key=_TRUST)
        else:
            new_source = self.source

        new_conf = max(self.confidence, round(min(0.99, 0.5 + 0.1 * new_n), 3))

        return replace(
            self,
            samples=new_n,
            measured_latency_s=round(new_latency, 4),
            measured_peak_current_a=None if new_peak_i is None else round(new_peak_i, 4),
            peak_current_samples=new_peak_samples,
            stall_count=new_stalls,
            source=new_source,
            confidence=new_conf,
        )

    def summary(self) -> dict[str, Any]:
        """Flat dict for JSON export / catalog display."""
        return {
            "capability": self.capability,
            "deployment_id": self.deployment_id,
            "supply_voltage_v": self.supply_voltage_v,
            "current_limit_a": self.current_limit_a,
            "travel_min_mm": self.travel_min_mm,
            "travel_max_mm": self.travel_max_mm,
            "motor_ke": self.motor_ke,
            "motor_kt": self.motor_kt,
            "resistance_ohm": self.resistance_ohm,
            "inductance_h": self.inductance_h,
            "load_mass_kg": self.load_mass_kg,
            "geometry_gain_m_rad": self.geometry_gain_m_rad,
            "friction_coefficient": self.friction_coefficient,
            "seal_damping_ns_m": self.seal_damping_ns_m,
            "gravity_assists_open": self.gravity_assists_open,
            "pinch_force_threshold_n": self.pinch_force_threshold_n,
            "min_operating_voltage_v": self.min_operating_voltage_v,
            "source": self.source.value,
            "confidence": self.confidence,
            "samples": self.samples,
            "measured_latency_s": self.measured_latency_s,
            "measured_peak_current_a": self.measured_peak_current_a,
            "peak_current_samples": self.peak_current_samples,
            "stall_count": self.stall_count,
        }
