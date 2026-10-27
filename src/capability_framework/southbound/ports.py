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
capability_framework.southbound.ports
=====================================
Southbound interfaces: what a capability may ask of the hardware below it.

Per design there is one small ABC per capability family, so each capability
depends only on the operations it uses. All share ``ActuatorPortBase`` for the
deployment-physics handshake.

All methods are async so bindings can use network I/O without changing
capability code. Arguments are domain-language names and physical units only;
no bus ids, ECU ids or hardware detail (those never cross the boundary).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .profile import ActuatorProfile, MoveOutcome, ProfileSource

__all__ = [
    "ActuatorError",
    "ActuatorPortBase",
    "WindowActuatorPort",
]


class ActuatorError(RuntimeError):
    """Raised when an actuator rejects or cannot execute a command."""


class ActuatorPortBase(ABC):
    """
    Deployment-physics handshake shared by every southbound port.

    ``describe_actuator`` hands the binding's physics envelope up to the
    capability; ``report_move_outcome`` closes the loop so measured moves refine
    the profile (DATASHEET → CALIBRATED → IDENTIFIED). Neither carries hardware
    addressing.

    Abort contract (every port): when a capability cancels a call (timeout or
    explicit release), the binding must stop promptly and leave the output in its
    safe state (motion stopped, last setpoint held). A call that ignores
    cancellation is abandoned by the capability after a bounded wait.
    """

    async def describe_actuator(self, capability: str) -> ActuatorProfile:
        """
        Return the deployment ``ActuatorProfile`` for *capability*.

        Default: a generic datasheet profile. Concrete bindings override this
        with the real values measured or configured for their deployment.
        """
        return ActuatorProfile(
            capability=capability,
            deployment_id="generic-datasheet",
            supply_voltage_v=12.0,
            current_limit_a=25.0,
            travel_min_mm=0.0,
            travel_max_mm=300.0,
            motor_ke=0.5,
            motor_kt=0.5,
            resistance_ohm=2.0,
            inductance_h=0.005,
            load_mass_kg=6.5,
            geometry_gain_m_rad=0.01,
            friction_coefficient=0.10,
            seal_damping_ns_m=3600.0,
            source=ProfileSource.DATASHEET,
            confidence=0.5,
        )

    async def report_move_outcome(self, capability: str, outcome: MoveOutcome) -> ActuatorProfile:
        """
        Report a measured real move so the binding can refine its profile.

        Default: no-op returning the current (unchanged) profile.
        """
        return await self.describe_actuator(capability)


class WindowActuatorPort(ActuatorPortBase):
    """Power window actuation."""

    @abstractmethod
    async def move_window(self, zone: str, target_pct: float) -> float:
        """
        Command a window to a target position.

        Args:
            zone:       "DRIVER_FRONT" | "PASSENGER_FRONT" | "DRIVER_REAR" | "PASSENGER_REAR"
            target_pct: 0.0 (fully closed) to 100.0 (fully open)

        Returns:
            Resulting position as a percentage (0.0–100.0).

        Raises:
            ActuatorError: if the actuator rejects the command or a pinch is detected.
        """

    @abstractmethod
    async def get_window_position(self, zone: str) -> float:
        """Return the current position for *zone* as a percentage (0.0–100.0)."""
