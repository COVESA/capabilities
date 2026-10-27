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
capability_framework.models.window_motor
========================================
4-stage BOND graph model for the automotive power window system.

BOND graph chain:
  SE(volt) → Motor [I,R] → Actuator GY/TF → Linkage [R, worm] → Window Mass [I,R,C,SE]

Position convention:
  0 mm = fully open (lower hard stop)
  300 mm = fully closed (door frame stop)
  Positive voltage → closes the window
  Gravity assists opening, opposes closing
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .base import MoveKPIs, PhysicalState, TransferFunctionModel


@dataclass
class WindowMotorParams:
    """
    Calibrated parameters for the 4-stage power window BOND graph model.

    Stage 1 — DC Motor:  Ke=0.5, Kt=0.5, L=5mH, R=2Ω, J=0.003, B=0.002
    Stage 2 — Actuator:  gain=0.01 m/rad, J=0.0005 kg·m²
    Stage 3 — Linkage:   lead_angle=4°, μ=0.10, damping=0.01 Ns/mm
    Stage 4 — Window:    m=6.5 kg, seal_damp=3600 Ns/m, hard stops at 0/300 mm
    """
    # Stage 1: Motor
    Ke: float = 0.5
    Kt: float = 0.5
    inductance_h: float = 0.005
    resistance_ohm: float = 2.0
    J_motor: float = 0.003
    B_motor: float = 0.002
    supply_voltage_v: float = 12.0
    current_peak_a: float = 25.0

    # Stage 2: Actuator
    actuator_gain_m_rad: float = 0.01
    J_actuator: float = 0.0005
    constant_load_torque_nm: float = 0.0

    # Stage 3: Worm screw linkage
    linkage_damping: float = 0.01        # Ns/mm
    lead_angle_deg: float = 4.0
    friction_coefficient: float = 0.10

    # Stage 4: Window mass
    window_mass_kg: float = 6.5
    seal_damping_ns_m: float = 3600.0
    gravity_m_s2: float = 9.81
    max_position_m: float = 0.3          # 300 mm = fully closed
    min_position_m: float = 0.0          # 0 mm = fully open
    frame_stiffness_n_m: float = 15000.0
    linkage_stiffness_n_m: float = 30000.0

    # Pinch detection
    pinch_force_threshold_n: float = 100.0
    auto_reverse_on_pinch: bool = True
    reverse_duration_s: float = 0.5

    @classmethod
    def from_profile(cls, profile: Any) -> "WindowMotorParams":
        """Build params from a southbound ``ActuatorProfile`` (duck-typed)."""
        return cls(
            Ke=profile.motor_ke,
            Kt=profile.motor_kt,
            resistance_ohm=profile.resistance_ohm,
            inductance_h=profile.inductance_h,
            supply_voltage_v=profile.supply_voltage_v,
            current_peak_a=profile.current_limit_a,
            actuator_gain_m_rad=profile.geometry_gain_m_rad,
            friction_coefficient=profile.friction_coefficient,
            window_mass_kg=profile.load_mass_kg,
            seal_damping_ns_m=profile.seal_damping_ns_m,
            min_position_m=profile.travel_min_mm / 1000.0,
            max_position_m=profile.travel_max_mm / 1000.0,
            pinch_force_threshold_n=profile.pinch_force_threshold_n,
        )


class WindowMotorModel(TransferFunctionModel):
    """Physics-based power window model using a 4-stage BOND graph."""

    def __init__(self, params: WindowMotorParams | None = None) -> None:
        self._p = params or WindowMotorParams()
        self._motor_current: float = 0.0
        self._v_r: float = 0.0
        self._gear_ang_vel: float = 0.0
        self._position_m: float = 0.0
        self._velocity_m_s: float = 0.0
        self._linkage_force_prev: float = 0.0
        self._pinch_detected: bool = False
        self._reversing: bool = False
        self._reverse_remaining_s: float = 0.0
        self._reverse_direction_sign: float = 1.0
        self._time_s: float = 0.0

    @property
    def name(self) -> str:
        return "Power Window BOND Graph Model (4-stage)"

    def for_profile(self, profile: Any) -> "WindowMotorModel":
        """Return a new model parameterised by a southbound ``ActuatorProfile``."""
        return WindowMotorModel(WindowMotorParams.from_profile(profile))

    @property
    def pinch_detected(self) -> bool:
        return self._pinch_detected

    @property
    def is_reversing(self) -> bool:
        """True while an anti-pinch reversal is driving the window back open."""
        return self._reversing

    def reset(self) -> None:
        self._motor_current = 0.0
        self._v_r = 0.0
        self._gear_ang_vel = 0.0
        self._position_m = 0.0
        self._velocity_m_s = 0.0
        self._linkage_force_prev = 0.0
        self._pinch_detected = False
        self._reversing = False
        self._reverse_remaining_s = 0.0
        self._reverse_direction_sign = 1.0
        self._time_s = 0.0

    def get_state(self) -> PhysicalState:
        p = self._p
        actuator_force = p.Kt * self._motor_current / max(p.actuator_gain_m_rad, 1e-9)
        return PhysicalState(
            time_s=self._time_s,
            position=self._position_m * 1000.0,
            velocity=self._velocity_m_s * 1000.0,
            acceleration=0.0,
            force_or_torque=actuator_force,
            temperature_c=25.0,
            current_a=abs(self._motor_current),
            is_stalled=self._pinch_detected,
            is_at_limit=(self._position_m <= p.min_position_m or self._position_m >= p.max_position_m),
        )

    def get_params(self) -> dict[str, Any]:
        p = self._p
        return {
            "model_name": self.name,
            "Ke": p.Ke, "Kt": p.Kt, "R": p.resistance_ohm, "L": p.inductance_h,
            "J_motor": p.J_motor, "B_motor": p.B_motor,
            "actuator_gain_m_rad": p.actuator_gain_m_rad,
            "lead_angle_deg": p.lead_angle_deg,
            "friction_coefficient": p.friction_coefficient,
            "self_locking": self._is_self_locking(),
            "window_mass_kg": p.window_mass_kg,
            "seal_damping_Ns_m": p.seal_damping_ns_m,
            "max_position_mm": p.max_position_m * 1000.0,
            "pinch_force_threshold_N": p.pinch_force_threshold_n,
        }

    def _is_self_locking(self) -> bool:
        p = self._p
        friction_angle_deg = math.degrees(math.atan(p.friction_coefficient))
        return p.lead_angle_deg < friction_angle_deg

    def step(self, dt: float, command: Any) -> PhysicalState:
        """
        Advance the model by *dt* seconds.

        command dict: ``{"voltage": float, "obstruction_force": float}``.
        Positive voltage closes the window; positive obstruction_force opposes closing.
        """
        p = self._p
        volt = float(command.get("voltage", 0.0)) if isinstance(command, dict) else 0.0
        obstruction_force = float(command.get("obstruction_force", 0.0)) if isinstance(command, dict) else 0.0

        # An anti-pinch reversal overrides the caller's command for a bounded time.
        if self._reversing:
            volt = -self._reverse_direction_sign * p.supply_voltage_v
            self._reverse_remaining_s -= dt
            if self._reverse_remaining_s <= 0.0:
                self._reversing = False
                self._reverse_remaining_s = 0.0

        n_sub = max(1, int(math.ceil(dt / 0.001)))
        dt_sub = dt / n_sub

        for _ in range(n_sub):
            # Stage 1: Motor
            back_emf = p.Ke * self._gear_ang_vel
            di_dt = (volt - back_emf - self._v_r) / max(p.inductance_h, 1e-9)
            self._motor_current += di_dt * dt_sub
            self._motor_current = max(-p.current_peak_a, min(p.current_peak_a, self._motor_current))
            self._v_r = self._motor_current * p.resistance_ohm
            torque = p.Kt * self._motor_current

            # Stage 2: Actuator
            load_torque_reflected = self._linkage_force_prev * p.actuator_gain_m_rad
            net_torque = torque - load_torque_reflected - p.constant_load_torque_nm - p.B_motor * self._gear_ang_vel
            self._gear_ang_vel += (net_torque / max(p.J_actuator, 1e-9)) * dt_sub

            # Stage 3: Worm screw linkage
            actuator_force = torque / max(p.actuator_gain_m_rad, 1e-9)
            linkage_force = actuator_force - p.linkage_damping * self._velocity_m_s * 1000.0

            # Stage 4: Window mass
            pos = self._position_m
            overshoot = pos - p.max_position_m
            f_frame = -p.frame_stiffness_n_m * overshoot if overshoot > 0.0 else 0.0
            undershoot = p.min_position_m - pos
            f_stop = p.linkage_stiffness_n_m * undershoot if undershoot > 0.0 else 0.0
            f_friction = -p.seal_damping_ns_m * self._velocity_m_s
            f_gravity = -p.window_mass_kg * p.gravity_m_s2

            # obstruction_force opposes closure, so it is subtracted.
            net_force = linkage_force + f_frame + f_stop + f_friction + f_gravity - obstruction_force
            new_vel = self._velocity_m_s + (net_force / max(p.window_mass_kg, 1e-9)) * dt_sub
            new_pos = pos + new_vel * dt_sub

            if self._is_self_locking() and abs(volt) < 0.1:
                new_vel = 0.0
                new_pos = pos

            # Detect a pinch only while the drive is attempting closure, and never
            # while a reversal is already running.
            if (volt > 1e-9 and not self._reversing
                    and abs(obstruction_force) + abs(f_frame) > p.pinch_force_threshold_n):
                if not self._pinch_detected:
                    self._pinch_detected = True
                    if p.auto_reverse_on_pinch:
                        # A pinch is a closing obstruction, so the reversal always
                        # drives toward opening.
                        self._reversing = True
                        self._reverse_remaining_s = p.reverse_duration_s
                        self._reverse_direction_sign = 1.0
                new_vel = 0.0
                new_pos = pos
                self._gear_ang_vel = 0.0
                self._motor_current = 0.0

            self._velocity_m_s = max(-10.0, min(10.0, new_vel))
            self._position_m = max(p.min_position_m, min(p.max_position_m, new_pos))

            if new_pos <= p.min_position_m or new_pos >= p.max_position_m:
                self._velocity_m_s = 0.0
                self._gear_ang_vel = 0.0

            self._linkage_force_prev = linkage_force

        self._time_s += dt
        return self.get_state()

    def simulate_move(
        self,
        target_mm: float,
        from_mm: float | None = None,
        time_limit_s: float = 10.0,
        dt: float = 0.001,
    ) -> list[PhysicalState]:
        """Run a full move and return the trajectory."""
        self._reset_to(from_mm)
        p = self._p
        target_m = target_mm / 1000.0
        trajectory: list[PhysicalState] = [self.get_state()]
        elapsed = 0.0

        while elapsed < time_limit_s:
            error_m = target_m - self._position_m
            if abs(error_m) < 0.001 and abs(self._velocity_m_s) < 0.002:
                break
            # Bang-bang drive with a 1 mm deadband: a real window is driven until it
            # reaches the commanded position, then the worm screw self-locks.
            voltage = math.copysign(p.supply_voltage_v, error_m) if abs(error_m) > 0.001 else 0.0
            state = self.step(dt, {"voltage": voltage})
            trajectory.append(state)
            elapsed += dt
            if state.is_at_limit or (state.is_stalled and not self.is_reversing):
                break

        return trajectory

    def compute_move_kpis(
        self,
        target_mm: float,
        from_mm: float | None = None,
        time_limit_s: float = 10.0,
        dt: float = 0.001,
        settle_tol_mm: float = 1.0,
        settle_vel_mms: float = 1.0,
    ) -> MoveKPIs:
        """
        Run a full simulated window move and return motor KPIs.

        The primary KPI is ``move_latency_s`` — time from command to the window
        settling within ``settle_tol_mm`` of ``target_mm``.
        """
        from_pos = from_mm if from_mm is not None else self._p.min_position_m * 1000.0
        travel = abs(target_mm - from_pos)

        self._reset_to(from_mm)
        p = self._p
        target_m = target_mm / 1000.0
        elapsed = 0.0
        currents: list[float] = [abs(self._motor_current)]
        states: list[PhysicalState] = [self.get_state()]

        while elapsed < time_limit_s:
            error_m = target_m - self._position_m
            if abs(error_m) < settle_tol_mm / 1000.0 and abs(self._velocity_m_s * 1000.0) < settle_vel_mms:
                break
            voltage = (math.copysign(p.supply_voltage_v, error_m)
                       if abs(error_m) > settle_tol_mm / 1000.0 else 0.0)
            state = self.step(dt, {"voltage": voltage})
            states.append(state)
            currents.append(abs(self._motor_current))
            elapsed += dt
            if state.is_at_limit or (state.is_stalled and not self.is_reversing):
                break

        latency = self._latency(states, target_mm, settle_tol_mm, settle_vel_mms)
        n = max(len(currents), 1)
        return MoveKPIs(
            move_latency_s=latency,
            peak_current_a=round(max(currents), 4),
            rms_current_a=round(math.sqrt(sum(c ** 2 for c in currents) / n), 4),
            avg_current_a=round(sum(currents) / n, 4),
            peak_force_n=round(max(abs(s.force_or_torque) for s in states), 2),
            avg_velocity_mms=round(sum(abs(s.velocity) for s in states) / len(states), 2),
            energy_wh=round(sum(p.supply_voltage_v * currents[i] * dt
                                for i in range(1, len(currents))) / 3600.0, 6),
            total_travel_mm=travel,
            supply_voltage_v=p.supply_voltage_v,
        )

    def current_from_operating_point(
        self,
        force_n: float,
        velocity_mms: float,
        supply_voltage_v: float | None = None,
    ) -> dict[str, float]:
        """
        Back-calculate window-motor current from a known load operating point.

        Steady-state relationships:
          Torque   T  = F · actuator_gain_m_rad
          Current  I  = T / Kt
          ω_gear      = v_window / actuator_gain
          Back EMF Vb = Ke · ω_gear
          V_required  = R · I + Vb
        """
        p = self._p
        v_supply = supply_voltage_v if supply_voltage_v is not None else p.supply_voltage_v
        torque_nm = force_n * p.actuator_gain_m_rad
        i_a = torque_nm / max(p.Kt, 1e-9)
        omega = (velocity_mms / 1000.0) / max(p.actuator_gain_m_rad, 1e-9)
        back_emf = p.Ke * omega
        v_required = p.resistance_ohm * i_a + back_emf
        p_mech = force_n * (velocity_mms / 1000.0)
        p_elec = v_required * i_a
        eff_pct = (p_mech / max(p_elec, 1e-9)) * 100.0
        return {
            "current_a": round(i_a, 4),
            "back_emf_v": round(back_emf, 4),
            "required_voltage_v": round(v_required, 4),
            "mechanical_power_w": round(p_mech, 4),
            "electrical_power_w": round(p_elec, 4),
            "efficiency_pct": round(min(eff_pct, 100.0), 2),
            "supply_voltage_v": round(v_supply, 2),
        }

    # ── Private ───────────────────────────────────────────────────────────

    def _reset_to(self, from_mm: float | None) -> None:
        if from_mm is None:
            return
        self._position_m = from_mm / 1000.0
        self._velocity_m_s = 0.0
        self._gear_ang_vel = 0.0
        self._motor_current = 0.0
        self._v_r = 0.0
        self._linkage_force_prev = 0.0
        self._pinch_detected = False
        self._reversing = False
        self._reverse_remaining_s = 0.0
        self._time_s = 0.0

    @staticmethod
    def _latency(states: list[PhysicalState], target_mm: float,
                 settle_tol_mm: float, settle_vel_mms: float,
                 settle_window_s: float = 0.1) -> float:
        """Time to settle within tolerance, else the elapsed time at the end."""
        settle_time = states[-1].time_s
        settle_start: float | None = None
        for st in states:
            if abs(st.position - target_mm) < settle_tol_mm and abs(st.velocity) < settle_vel_mms:
                if settle_start is None:
                    settle_start = st.time_s
                elif (st.time_s - settle_start) >= settle_window_s:
                    settle_time = settle_start
            else:
                settle_start = None
        if settle_time == states[-1].time_s and settle_start is not None:
            settle_time = settle_start
        return settle_time
