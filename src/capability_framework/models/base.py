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
capability_framework.models.base
================================
Base classes shared by the physics models, plus the move-KPI computation.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PhysicalState:
    """Snapshot of a physical system's state at a point in time."""
    time_s: float
    position: float            # domain units (mm, degrees, %)
    velocity: float = 0.0      # domain units per second
    acceleration: float = 0.0
    force_or_torque: float = 0.0
    temperature_c: float = 25.0
    is_stalled: bool = False
    is_at_limit: bool = False
    # Actual winding current, in amperes, when the model tracks its electrical
    # state. Not interchangeable with force_or_torque: it is what makes the
    # current and energy KPIs meaningful at stall, where the rotor is stationary
    # but the winding carries its maximum current.
    current_a: float | None = None


class TransferFunctionModel(ABC):
    """Abstract physics-based transfer-function model (Newton's laws, motor equations, …)."""

    @abstractmethod
    def step(self, dt: float, command: Any) -> PhysicalState:
        """Advance the simulation by dt seconds. Returns the new physical state."""

    @abstractmethod
    def reset(self) -> None:
        """Reset the model to initial conditions."""

    @abstractmethod
    def get_params(self) -> dict[str, Any]:
        """Return all model parameters as a dictionary."""

    @abstractmethod
    def get_state(self) -> PhysicalState:
        """Return the current physical state."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable model name."""


@dataclass(frozen=True)
class MoveKPIs:
    """
    Key performance indicators derived from a simulated motor move.

    Definitions
    -----------
    move_latency_s    Time from command to steady state (the primary KPI).
    peak_current_a    Maximum instantaneous current during the move.
    rms_current_a     Root-mean-square current (proportional to I²R heating).
    avg_current_a     Mean current (proportional to charge drawn).
    peak_force_n      Peak mechanical output force during the move.
    avg_velocity_mms  Mean speed during the active phase.
    energy_wh         Total electrical energy consumed.
    total_travel_mm   Commanded travel distance.
    supply_voltage_v  Nominal supply voltage used in the simulation.
    """
    move_latency_s: float
    peak_current_a: float
    rms_current_a: float
    avg_current_a: float
    peak_force_n: float
    avg_velocity_mms: float
    energy_wh: float
    total_travel_mm: float
    supply_voltage_v: float

    def summary(self) -> dict[str, float]:
        """Return all KPIs as a flat dict (suitable for logging / JSON export)."""
        return {
            "move_latency_s": round(self.move_latency_s, 3),
            "peak_current_a": round(self.peak_current_a, 3),
            "rms_current_a": round(self.rms_current_a, 3),
            "avg_current_a": round(self.avg_current_a, 3),
            "peak_force_n": round(self.peak_force_n, 2),
            "avg_velocity_mms": round(self.avg_velocity_mms, 2),
            "energy_wh": round(self.energy_wh, 6),
            "total_travel_mm": round(self.total_travel_mm, 1),
            "supply_voltage_v": round(self.supply_voltage_v, 1),
        }
