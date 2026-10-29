"""The capability's state, expressed as pinned VSS signals at runtime."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from capability_framework.capabilities.window.types import WindowState, WindowStatus, WindowZone
from capability_framework.capabilities.window.vss import WindowVssProjector, project_state
from capability_framework.semantics import (
    OutOfRange,
    UnitMismatch,
    UnknownSignal,
    VssCatalog,
    VssSnapshot,
    load_capability,
    quantize,
    quantize_percent,
)

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "third_party" / "generated"

DRIVER_POSITION = "Vehicle.Cabin.Door.Row1.DriverSide.Window.Position"
DRIVER_IS_OPEN = "Vehicle.Cabin.Door.Row1.DriverSide.Window.IsOpen"
DRIVER_SWITCH = "Vehicle.Cabin.Door.Row1.DriverSide.Window.Switch"


@pytest.fixture(scope="module")
def catalog() -> VssCatalog:
    return VssCatalog.from_json(GENERATED / "vss.json")


@pytest.fixture(scope="module")
def spec():
    return load_capability(ROOT / "catalog" / "capabilities" / "window.yaml")


def _state(zone=WindowZone.DRIVER_FRONT, position=42.0, status=WindowStatus.STATIONARY) -> WindowState:
    return WindowState(status=status, position_pct=position, zone=zone)


# ── quantization ─────────────────────────────────────────────────────

def test_float_percent_quantizes_to_the_vss_integer(catalog: VssCatalog) -> None:
    signal = catalog.require(DRIVER_POSITION)
    assert quantize_percent(50.4, signal) == 50
    assert quantize_percent(50.5, signal) == 51
    assert quantize_percent(0.0, signal) == 0
    assert quantize_percent(100.0, signal) == 100


def test_out_of_range_is_refused_not_silently_clamped(catalog: VssCatalog) -> None:
    signal = catalog.require(DRIVER_POSITION)
    with pytest.raises(OutOfRange):
        quantize_percent(140.0, signal)
    with pytest.raises(OutOfRange):
        quantize_percent(-1.0, signal)


def test_unit_mismatch_is_refused(catalog: VssCatalog) -> None:
    signal = catalog.require(DRIVER_POSITION)
    with pytest.raises(UnitMismatch):
        quantize_percent(50.0, signal, percent_unit="ratio")


def test_booleans_and_generic_quantization(catalog: VssCatalog) -> None:
    assert quantize(1, catalog.require(DRIVER_IS_OPEN)) is True
    assert quantize(0, catalog.require(DRIVER_IS_OPEN)) is False


# ── snapshot ─────────────────────────────────────────────────────────

def test_snapshot_refuses_signals_outside_the_standard(catalog: VssCatalog, spec) -> None:
    snapshot = VssSnapshot(catalog=catalog, spec=spec)
    with pytest.raises(UnknownSignal):
        snapshot.set("Vehicle.Cabin.Door.Row1.DriverSide.Window.NotReal", 1)


def test_snapshot_records_quantized_values(catalog: VssCatalog, spec) -> None:
    snapshot = VssSnapshot(catalog=catalog, spec=spec, version="6.1")
    snapshot.update({DRIVER_POSITION: 63.7})
    view = snapshot.to_dict()
    assert view["standard"] == "vss"
    assert view["version"] == "6.1"
    assert view["signals"][DRIVER_POSITION]["value"] == 64
    assert view["signals"][DRIVER_POSITION]["datatype"] == "uint8"


# ── projection ───────────────────────────────────────────────────────

def test_projection_maps_position_and_open_state() -> None:
    values = project_state(_state(position=0.0))
    assert values[DRIVER_POSITION] == 0.0
    assert values[DRIVER_IS_OPEN] is False

    values = project_state(_state(position=30.0))
    assert values[DRIVER_IS_OPEN] is True


def test_projection_derives_switch_from_direction() -> None:
    assert project_state(_state(position=40.0), previous_pct=10.0)[DRIVER_SWITCH] == "OPEN"
    assert project_state(_state(position=10.0), previous_pct=40.0)[DRIVER_SWITCH] == "CLOSE"
    assert project_state(_state(position=10.0), previous_pct=10.1)[DRIVER_SWITCH] == "INACTIVE"


def test_projection_treats_a_pinch_as_reversal() -> None:
    values = project_state(
        _state(position=55.0, status=WindowStatus.PINCHED), previous_pct=60.0
    )
    assert values[DRIVER_SWITCH] == "OPEN"


def test_projection_ignores_unknown_position_and_the_all_zone() -> None:
    unknown = WindowState(status=WindowStatus.INHIBITED, position_pct=None,
                          zone=WindowZone.DRIVER_FRONT)
    assert project_state(unknown) == {}
    assert project_state(_state(zone=WindowZone.ALL)) == {}


def test_projector_remembers_the_previous_position() -> None:
    projector = WindowVssProjector()
    projector(_state(position=5.0))
    moving = projector(_state(position=60.0))
    assert moving[DRIVER_SWITCH] == "OPEN"


# ── generated constants ──────────────────────────────────────────────

def test_generated_vss_paths_are_current() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gen_vss_paths.py"), "--check"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr


# ── app endpoints ────────────────────────────────────────────────────

@pytest.fixture
def client():
    from capability_framework.app import create_app

    app = create_app(role="oem_automation")
    app.config["TESTING"] = True
    return app.test_client()


def test_vss_endpoint_reports_the_moved_zone(client) -> None:
    client.post("/vehicle/window/move", json={"zone": "DRIVER_FRONT", "target_pct": 100.0})
    body = client.get("/vehicle/vss").get_json()
    assert body["standard"] == "vss"
    assert body["version"] == "6.1"
    assert body["signals"][DRIVER_POSITION]["value"] == 100
    assert body["signals"][DRIVER_IS_OPEN]["value"] is True


def test_vss_single_signal_endpoint(client) -> None:
    client.post("/vehicle/window/move", json={"zone": "PASSENGER_REAR", "target_pct": 40.0})
    path = "Vehicle.Cabin.Door.Row2.PassengerSide.Window.Position"
    body = client.get(f"/vehicle/vss/{path}").get_json()
    assert body["value"] == 40
    assert body["datatype"] == "uint8"


def test_vss_unknown_signal_is_404(client) -> None:
    assert client.get("/vehicle/vss/Vehicle.Cabin.Nope").status_code == 404


def test_vss_reports_mainstream_signal_metadata(client) -> None:
    client.post("/vehicle/window/move", json={"zone": "DRIVER_FRONT", "target_pct": 25.0})
    body = client.get("/vehicle/vss").get_json()
    signal = body["signals"][DRIVER_POSITION]
    assert signal["min"] == 0 and signal["max"] == 100
    assert signal["unit"] == "percent"
    assert json.loads(json.dumps(signal))["value"] == 25
