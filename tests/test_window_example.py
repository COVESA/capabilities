"""Tests for the runnable example: the physics model and the northbound API."""

from __future__ import annotations

import asyncio
import json

import pytest

from capability_framework.app import build_stack, create_app
from capability_framework.capabilities.base import RequestSource
from capability_framework.capabilities.window import (
    MoveWindowCommand,
    WindowInhibitReason,
    WindowStatus,
    WindowZone,
)
from capability_framework.models import WindowMotorModel, WindowMotorParams


# ── Physics model ────────────────────────────────────────────────────────

def test_full_stroke_move_reaches_the_target() -> None:
    model = WindowMotorModel()
    model.simulate_move(target_mm=300.0, from_mm=0.0)
    assert model.get_state().position == pytest.approx(300.0, abs=1.0)


def test_move_kpis_are_reported() -> None:
    kpis = WindowMotorModel().compute_move_kpis(target_mm=300.0, from_mm=0.0).summary()
    assert kpis["move_latency_s"] > 0
    assert kpis["peak_current_a"] > 0
    assert kpis["total_travel_mm"] == 300.0


def test_pinch_triggers_auto_reverse() -> None:
    model = WindowMotorModel()
    model.simulate_move(target_mm=0.0, from_mm=0.0)  # at open stop
    # Drive closing while an obstruction opposes it above the pinch threshold.
    model._pinch_detected = False  # noqa: SLF001
    for _ in range(2000):
        model.step(0.001, {"voltage": 12.0, "obstruction_force": 150.0})
        if model.pinch_detected:
            break
    assert model.pinch_detected
    assert model.is_reversing


def test_params_from_profile_roundtrip() -> None:
    from capability_framework.southbound import ActuatorProfile, ProfileSource
    profile = ActuatorProfile(
        capability="window", deployment_id="d", supply_voltage_v=13.0, current_limit_a=20.0,
        travel_min_mm=0.0, travel_max_mm=320.0, motor_ke=0.6, motor_kt=0.6,
        resistance_ohm=1.8, inductance_h=0.004, load_mass_kg=7.0,
        geometry_gain_m_rad=0.011, friction_coefficient=0.12, seal_damping_ns_m=3400.0,
        source=ProfileSource.DATASHEET,
    )
    params = WindowMotorParams.from_profile(profile)
    assert params.Ke == 0.6
    assert params.max_position_m == pytest.approx(0.32)


# ── Capability northbound API (in-process) ────────────────────────────────

def test_move_window_via_northbound_api() -> None:
    stack = build_stack()
    cmd = MoveWindowCommand(source=RequestSource.OEM_AUTOMATION,
                            zone=WindowZone.DRIVER_FRONT, target_pct=100.0)
    state = asyncio.run(stack.window.moveWindow(cmd))
    assert state.status is WindowStatus.MOVING
    assert state.position_pct == pytest.approx(100.0, abs=1.0)


def test_precondition_inhibits_when_power_off() -> None:
    stack = build_stack()
    from capability_framework.vehicle_state import PowerState
    stack.vehicle_state.power_state = PowerState.OFF
    asyncio.run(stack.vehicle_state.publish())
    cmd = MoveWindowCommand(source=RequestSource.DRIVER,
                            zone=WindowZone.DRIVER_FRONT, target_pct=50.0)
    state = asyncio.run(stack.window.moveWindow(cmd))
    assert state.status is WindowStatus.INHIBITED
    assert state.reason is WindowInhibitReason.POWER_OFF


# ── HTTP northbound API (the same surface the app exposes) ─────────────────

@pytest.fixture
def client():
    app = create_app(role="oem_automation")
    app.config["TESTING"] = True
    return app.test_client()


def test_http_move_route(client) -> None:
    resp = client.post("/vehicle/window/move",
                       json={"zone": "DRIVER_FRONT", "target_pct": 100.0})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "MOVING"
    assert body["position_pct"] == pytest.approx(100.0, abs=1.0)
    assert body["api_version"] == "2.0.0"


def test_http_rejects_self_asserted_source(client) -> None:
    resp = client.post("/vehicle/window/move",
                       json={"zone": "DRIVER_FRONT", "target_pct": 50.0, "source": "SAFETY"})
    assert resp.status_code == 400
    assert "verified role" in resp.get_json()["error"]


def test_http_catalog_descriptor(client) -> None:
    body = client.get("/vehicle/window/catalog").get_json()
    assert body["name"] == "window"
    assert "moveWindow" in body["northbound_operations"]
    assert "move_window" in body["southbound_dependencies"]


def test_http_orchestrate_cascade(client) -> None:
    resp = client.post("/vehicle/window/orchestrate", json={"mode": "CASCADE_OPEN", "target_pct": 100.0})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "COMPLETED"
    assert set(body["per_zone"]) == {"DRIVER_FRONT", "PASSENGER_FRONT", "DRIVER_REAR", "PASSENGER_REAR"}


def test_http_model_introspection(client) -> None:
    body = client.get("/vehicle/window/model").get_json()
    assert body["parameters"]["model_name"].startswith("Power Window")
    assert body["deployment_kpis"]["move_latency_s"] > 0
