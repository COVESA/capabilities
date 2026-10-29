"""The semantics layer resolves the window capability's VSS and VDM grounding."""

from __future__ import annotations

from pathlib import Path

import pytest

from capability_framework.semantics import (
    VdmSchema,
    VssCatalog,
    VssPathError,
    load_capability,
)

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "third_party" / "generated"
WINDOW_ENTRY = ROOT / "catalog" / "capabilities" / "window.yaml"

ZONE = "Vehicle.Cabin.Door.Row1.DriverSide.Window"


@pytest.fixture(scope="module")
def vss() -> VssCatalog:
    return VssCatalog.from_json(GENERATED / "vss.json")


@pytest.fixture(scope="module")
def vdm() -> VdmSchema:
    return VdmSchema.from_sdl_file(GENERATED / "vdm.graphql")


@pytest.fixture(scope="module")
def window():
    return load_capability(WINDOW_ENTRY)


# ── VSS ──────────────────────────────────────────────────────────────

def test_window_position_signal_is_a_uint8_percentage(vss: VssCatalog) -> None:
    signal = vss.require(f"{ZONE}.Position")
    assert signal.datatype == "uint8"
    assert signal.unit == "percent"
    assert signal.is_actuator
    assert (signal.minimum, signal.maximum) == (0.0, 100.0)


def test_unknown_path_raises(vss: VssCatalog) -> None:
    with pytest.raises(VssPathError):
        vss.require("Vehicle.Cabin.Door.Row1.DriverSide.Window.Nope")


def test_range_check_follows_the_standard(vss: VssCatalog) -> None:
    signal = vss.require(f"{ZONE}.Position")
    assert signal.accepts(0) and signal.accepts(100)
    assert not signal.accepts(-1) and not signal.accepts(101)


def test_children_and_search(vss: VssCatalog) -> None:
    children = {s.path.rsplit(".", 1)[-1] for s in vss.children(ZONE)}
    assert {"Position", "IsOpen", "Switch"} <= children
    assert any("Window.Position" in s.path for s in vss.search("window position"))


def test_all_four_door_instances_exist(vss: VssCatalog) -> None:
    for row in ("Row1", "Row2"):
        for side in ("DriverSide", "PassengerSide"):
            assert f"Vehicle.Cabin.Door.{row}.{side}.Window.Position" in vss


# ── VDM ──────────────────────────────────────────────────────────────

def test_vdm_projects_window_with_a_range(vdm: VdmSchema) -> None:
    window_type = vdm.get("Window")
    assert window_type is not None
    assert window_type.vspec_fqn == "Vehicle.Cabin.Door.Window"
    field = window_type.field("position")
    assert field is not None
    assert field.returns == "UInt8"
    assert (field.minimum, field.maximum) == (0.0, 100.0)
    assert field.vspec_fqn == "Vehicle.Cabin.Door.Window.Position"


def test_vdm_door_instance_tag_dimensions(vdm: VdmSchema) -> None:
    tag = vdm.get("Door_InstanceTag")
    assert tag is not None and tag.is_instance_tag
    assert vdm.enum_values("Door_InstanceTag_Dimension1") == ("ROW1", "ROW2")
    assert vdm.enum_values("Door_InstanceTag_Dimension2") == ("DRIVER_SIDE", "PASSENGER_SIDE")


def test_instance_dimensions_are_normalized(vdm: VdmSchema) -> None:
    assert vdm.normalize_vss_path(f"{ZONE}.Position") == "Vehicle.Cabin.Door.Window.Position"


def test_vdm_lookup_by_vss_path(vdm: VdmSchema) -> None:
    assert ("Window", "position") in vdm.lookup_vss_path("Vehicle.Cabin.Door.Window.Position")


# ── catalog entry ────────────────────────────────────────────────────

def test_catalog_entry_expands_to_four_zones(window) -> None:
    paths = {path for _, path, signal in window.expanded_signals() if signal.id == "window.position"}
    assert len(paths) == 4
    assert f"{ZONE}.Position" in paths


def test_catalog_entry_declares_the_public_operations(window) -> None:
    names = {op.name for op in window.operations}
    assert {"moveWindow", "getWindowState", "canExecuteWindow"} <= names


def test_command_role_maps_to_the_vss_switch(window) -> None:
    switch = window.signal("window.switch")
    assert switch is not None and switch.role == "command"
    assert switch.expand(ZONE) == f"{ZONE}.Switch"
