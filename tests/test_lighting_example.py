"""Tests for the interior lighting capability: in-process API, HTTP routes, VSS projection."""

from __future__ import annotations

import asyncio

import pytest

from capability_framework.app import build_stack, create_app
from capability_framework.capabilities.base import RequestSource
from capability_framework.capabilities.lighting import (
    LightingInhibitReason,
    LightingManager,
    LightingState,
    LightingStatus,
    LightingZone,
    SetInteriorLightCommand,
)
from capability_framework.capabilities.lighting.vss import project_state
from capability_framework.events import EventBus, Topics
from capability_framework.southbound import ActuatorError, LightingActuatorPort, LightOutput
from capability_framework.vehicle_state import OtaState, PowerState

DRIVER_FRONT = "Vehicle.Cabin.Light.AmbientLight.Row1.DriverSide"
PASSENGER_REAR = "Vehicle.Cabin.Light.AmbientLight.Row2.PassengerSide"


def _set(zone=LightingZone.DRIVER_FRONT, intensity=60.0, color=None,
         source=RequestSource.OEM_AUTOMATION) -> SetInteriorLightCommand:
    return SetInteriorLightCommand(source=source, zone=zone, intensity_pct=intensity, color=color)


def _publish_vehicle_state(stack, **changes) -> None:
    for name, value in changes.items():
        setattr(stack.vehicle_state, name, value)
    asyncio.run(stack.vehicle_state.publish())


# ── Capability northbound API (in-process) ────────────────────────────────

def test_set_interior_light_via_northbound_api() -> None:
    stack = build_stack()
    state = asyncio.run(stack.lighting.setInteriorLight(
        _set(zone=LightingZone.PASSENGER_FRONT, intensity=75.0, color="#3366ff")))
    assert state.status is LightingStatus.ON
    assert state.intensity_pct == pytest.approx(75.0)
    assert state.color == "#3366FF"
    assert state.reason is None
    assert stack.bus.last(Topics.LIGHTING_STATE) is state

    read = asyncio.run(stack.lighting.getInteriorLightState(LightingZone.PASSENGER_FRONT))
    assert (read.intensity_pct, read.color) == (75.0, "#3366FF")


def test_zero_intensity_switches_the_light_off() -> None:
    stack = build_stack()
    asyncio.run(stack.lighting.setInteriorLight(_set(intensity=80.0, color="#FF0000")))
    state = asyncio.run(stack.lighting.setInteriorLight(_set(intensity=0.0)))
    assert state.status is LightingStatus.OFF
    assert state.intensity_pct == 0.0
    assert state.color == "#FF0000"  # color is kept when not commanded


def test_lighting_precondition_inhibits_when_power_off() -> None:
    stack = build_stack()
    _publish_vehicle_state(stack, power_state=PowerState.OFF)
    state = asyncio.run(stack.lighting.setInteriorLight(_set(source=RequestSource.DRIVER)))
    assert state.status is LightingStatus.INHIBITED
    assert state.reason is LightingInhibitReason.POWER_OFF
    assert state.intensity_pct == 0.0  # the light did not change


def test_lighting_is_allowed_in_accessory_but_not_during_ota() -> None:
    stack = build_stack()
    _publish_vehicle_state(stack, power_state=PowerState.ACC)
    assert asyncio.run(stack.lighting.setInteriorLight(_set())).status is LightingStatus.ON

    _publish_vehicle_state(stack, ota_state=OtaState.APPLYING)
    state = asyncio.run(stack.lighting.setInteriorLight(_set()))
    assert state.reason is LightingInhibitReason.OTA_IN_PROGRESS


def test_lighting_inhibits_on_undervoltage() -> None:
    stack = build_stack()
    _publish_vehicle_state(stack, supply_voltage_v=11.5)
    assert asyncio.run(stack.lighting.setInteriorLight(_set())).status is LightingStatus.ON

    _publish_vehicle_state(stack, supply_voltage_v=10.9)
    state = asyncio.run(stack.lighting.setInteriorLight(_set(intensity=20.0)))
    assert state.status is LightingStatus.INHIBITED
    assert state.reason is LightingInhibitReason.UNDERVOLTAGE


class _RecordingPort(LightingActuatorPort):
    """A port that records every command and can be made to fault or stall."""

    def __init__(self, *, fault: bool = False, stall_s: float = 0.0) -> None:
        self.calls: list[tuple[str, float, str | None]] = []
        self.output = LightOutput(0.0, "#FFFFFF")
        self.fault = fault
        self.stall_s = stall_s

    async def set_ambient_light(self, zone, intensity_pct, color=None):
        self.calls.append((zone, intensity_pct, color))
        if self.stall_s:
            await asyncio.sleep(self.stall_s)
        if self.fault:
            raise ActuatorError("LED driver open-circuit")
        self.output = LightOutput(intensity_pct, color or self.output.color)
        return self.output

    async def get_ambient_light(self, zone):
        return self.output


def test_lighting_safety_case_refuses_bad_input() -> None:
    port = _RecordingPort()
    lighting = LightingManager(actuator=port, event_bus=EventBus())
    for command, reason in (
        (_set(intensity=101.0), LightingInhibitReason.OUT_OF_RANGE),
        (_set(intensity=-1.0), LightingInhibitReason.OUT_OF_RANGE),
        (_set(color="red"), LightingInhibitReason.INVALID_COLOR),
        (_set(color="#12345"), LightingInhibitReason.INVALID_COLOR),
    ):
        state = asyncio.run(lighting.setInteriorLight(command))
        assert state.status is LightingStatus.INHIBITED
        assert state.reason is reason
    assert port.calls == []  # the actuator was never commanded


def test_lighting_actuator_fault_reports_the_held_output() -> None:
    port = _RecordingPort(fault=True)
    lighting = LightingManager(actuator=port, event_bus=EventBus())
    state = asyncio.run(lighting.setInteriorLight(_set(intensity=50.0)))
    assert state.status is LightingStatus.INHIBITED
    assert state.reason is LightingInhibitReason.ACTUATOR_FAULT
    assert state.intensity_pct == 0.0


def test_lighting_timeout_holds_the_current_output() -> None:
    port = _RecordingPort(stall_s=5.0)
    lighting = LightingManager(actuator=port, event_bus=EventBus())
    command = SetInteriorLightCommand(source=RequestSource.DRIVER, zone=LightingZone.DRIVER_FRONT,
                                      intensity_pct=50.0, timeout_s=0.05)
    state = asyncio.run(lighting.setInteriorLight(command))
    assert state.reason is LightingInhibitReason.TIMEOUT
    assert state.status is LightingStatus.OFF


def test_lighting_all_zone_sets_every_zone_and_keeps_their_colors() -> None:
    stack = build_stack()
    asyncio.run(stack.lighting.setInteriorLight(_set(zone=LightingZone.DRIVER_REAR, color="#00FF00")))
    state = asyncio.run(stack.lighting.setInteriorLight(_set(zone=LightingZone.ALL, intensity=30.0)))
    assert state.status is LightingStatus.ON
    assert state.color is None  # zones keep different colors
    for zone in (LightingZone.DRIVER_FRONT, LightingZone.DRIVER_REAR, LightingZone.PASSENGER_REAR):
        read = asyncio.run(stack.lighting.getInteriorLightState(zone))
        assert read.intensity_pct == 30.0
    assert asyncio.run(stack.lighting.getInteriorLightState(LightingZone.DRIVER_REAR)).color == "#00FF00"


# ── VSS projection ───────────────────────────────────────────────────────

def _state(zone=LightingZone.DRIVER_FRONT, intensity=42.0, color="#FFAA00") -> LightingState:
    return LightingState(status=LightingStatus.ON, intensity_pct=intensity, color=color, zone=zone)


def test_lighting_projection_splits_intensity_into_on_and_level() -> None:
    values = project_state(_state(intensity=42.0))
    assert values[f"{DRIVER_FRONT}.IsLightOn"] is True
    assert values[f"{DRIVER_FRONT}.Intensity"] == 42.0
    assert values[f"{DRIVER_FRONT}.Color"] == "#FFAA00"


def test_lighting_projection_reports_off_without_a_zero_intensity() -> None:
    values = project_state(_state(intensity=0.0))
    assert values[f"{DRIVER_FRONT}.IsLightOn"] is False
    assert f"{DRIVER_FRONT}.Intensity" not in values  # VSS Intensity is 1-100


def test_lighting_projection_clamps_dim_light_to_the_vss_minimum() -> None:
    assert project_state(_state(intensity=0.2))[f"{DRIVER_FRONT}.Intensity"] == 1.0


def test_lighting_projection_fans_out_all_and_ignores_unknown_output() -> None:
    values = project_state(_state(zone=LightingZone.ALL, color=None))
    assert sum(path.endswith(".IsLightOn") for path in values) == 4
    assert not any(path.endswith(".Color") for path in values)
    unknown = LightingState(status=LightingStatus.INHIBITED, intensity_pct=None, color=None,
                            zone=LightingZone.DRIVER_FRONT)
    assert project_state(unknown) == {}


# ── HTTP northbound API ───────────────────────────────────────────────────

@pytest.fixture
def client():
    app = create_app(role="oem_automation")
    app.config["TESTING"] = True
    return app.test_client()


def test_http_set_interior_light_route(client) -> None:
    resp = client.post("/vehicle/lighting/set",
                       json={"zone": "DRIVER_FRONT", "intensity_pct": 65.0, "color": "#112233"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ON"
    assert body["intensity_pct"] == 65.0
    assert body["color"] == "#112233"
    assert body["api_version"] == "1.0.0"
    assert body["winning_source"] == "OEM_AUTOMATION"


def test_http_set_interior_light_maps_bad_input_to_422_and_400(client) -> None:
    out_of_range = client.post("/vehicle/lighting/set", json={"zone": "DRIVER_FRONT", "intensity_pct": 140})
    assert out_of_range.status_code == 422
    assert out_of_range.get_json()["reason"] == "OUT_OF_RANGE"

    bad_color = client.post("/vehicle/lighting/set",
                            json={"zone": "DRIVER_FRONT", "intensity_pct": 10, "color": "blue"})
    assert bad_color.status_code == 422
    assert bad_color.get_json()["reason"] == "INVALID_COLOR"

    assert client.post("/vehicle/lighting/set", json={"zone": "TRUNK", "intensity_pct": 10}).status_code == 400
    assert client.post("/vehicle/lighting/set", json={"zone": "DRIVER_FRONT"}).status_code == 400


def test_http_lighting_rejects_self_asserted_source(client) -> None:
    resp = client.post("/vehicle/lighting/set",
                       json={"zone": "DRIVER_FRONT", "intensity_pct": 50.0, "source": "SAFETY"})
    assert resp.status_code == 400
    assert "verified role" in resp.get_json()["error"]


def test_http_can_execute_interior_light_has_no_side_effects(client) -> None:
    body = client.post("/vehicle/lighting/can-execute",
                       json={"zone": "PASSENGER_FRONT", "intensity_pct": 90.0}).get_json()
    assert body["status"] == "OFF"
    assert body["message"] == "can_execute: all checks passed"
    after = client.get("/vehicle/lighting/state?zone=PASSENGER_FRONT").get_json()
    assert after["intensity_pct"] == 0.0


def test_http_get_interior_light_state_reads_a_zone(client) -> None:
    client.post("/vehicle/lighting/set",
                json={"zone": "DRIVER_REAR", "intensity_pct": 35.0, "color": "#ABCDEF"})
    body = client.get("/vehicle/lighting/state?zone=DRIVER_REAR").get_json()
    assert body["zone"] == "DRIVER_REAR"
    assert body["status"] == "ON"
    assert body["intensity_pct"] == 35.0
    assert body["color"] == "#ABCDEF"


def test_http_release_interior_light(client) -> None:
    request_id = "22222222-2222-4222-8222-222222222222"
    client.post("/vehicle/lighting/set",
                json={"zone": "DRIVER_FRONT", "intensity_pct": 45.0, "request_id": request_id})
    resp = client.post("/vehicle/lighting/release", json={"request_id": request_id})
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}


def test_http_lighting_catalog_descriptor(client) -> None:
    body = client.get("/vehicle/lighting/catalog").get_json()
    assert body["name"] == "lighting"
    assert body["asil_tier"] == "QM"
    assert "setInteriorLight" in body["northbound_operations"]
    assert body["southbound_dependencies"] == ["set_ambient_light", "get_ambient_light"]


def test_lighting_vss_endpoint_reports_the_set_zone(client) -> None:
    client.post("/vehicle/lighting/set",
                json={"zone": "PASSENGER_REAR", "intensity_pct": 63.7, "color": "#00FF7F"})
    body = client.get("/vehicle/vss").get_json()
    assert body["capabilities"] == {"window": "2.0.0", "lighting": "1.0.0"}
    signals = body["signals"]
    assert signals[f"{PASSENGER_REAR}.IsLightOn"]["value"] is True
    assert signals[f"{PASSENGER_REAR}.Intensity"]["value"] == 64
    assert signals[f"{PASSENGER_REAR}.Intensity"]["datatype"] == "uint8"
    assert signals[f"{PASSENGER_REAR}.Color"]["value"] == "#00FF7F"

    single = client.get(f"/vehicle/vss/{PASSENGER_REAR}.Intensity").get_json()
    assert single["value"] == 64
