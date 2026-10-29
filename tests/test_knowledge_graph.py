"""The knowledge graph is derived from checked artifacts and is deterministic."""

from __future__ import annotations

from pathlib import Path

import pytest

from capability_framework.semantics import VssCatalog, load_catalog
from capability_framework.semantics.graph import build_graph
from capability_framework.semantics.vdm import VdmSchema

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "third_party" / "generated"


@pytest.fixture(scope="module")
def graph():
    return build_graph(
        catalog=load_catalog(ROOT / "catalog" / "capabilities"),
        vss=VssCatalog.from_json(GENERATED / "vss.json"),
        vdm=VdmSchema.from_sdl_file(GENERATED / "vdm.graphql"),
        contracts_dir=ROOT / "contracts",
        vss_version="6.1",
    )


def test_graph_contains_every_layer(graph) -> None:
    assert set(graph.count_by("layer")) == {"capability", "contract", "vss", "vdm", "safety"}


def test_capability_is_connected_to_its_operations(graph) -> None:
    neighbours = {target for target, edge in graph.neighbours("cap:window")
                  if edge.relation == "PROVIDES"}
    assert "op:window.moveWindow" in neighbours
    assert "op:window.getWindowState" in neighbours


def test_operations_are_grounded_in_vss(graph) -> None:
    commands = {target for target, edge in graph.neighbours("op:window.moveWindow")
                if edge.relation == "COMMANDS"}
    # One template expands to every VSS instance, so the command reaches all four doors.
    assert commands == {
        f"vss:Vehicle.Cabin.Door.{row}.{side}.Window.Switch"
        for row in ("Row1", "Row2")
        for side in ("DriverSide", "PassengerSide")
    }


def test_vss_signals_project_onto_vdm_fields(graph) -> None:
    targets = {target for target, edge in graph.neighbours(
        "vss:Vehicle.Cabin.Door.Row1.DriverSide.Window.Position")
        if edge.relation == "PROJECTS_TO"}
    assert targets == {"vdm:Window.position"}


def test_signal_nodes_carry_standard_metadata(graph) -> None:
    node = graph.node("vss:Vehicle.Cabin.Door.Row1.DriverSide.Window.Position")
    assert node is not None
    assert node.attributes["datatype"] == "uint8"
    assert node.attributes["unit"] == "percent"
    assert node.attributes["max"] == 100.0


def test_requirements_are_traceable_to_tests(graph) -> None:
    tests = {target for target, edge in graph.neighbours("req:REQ-WIN-002")
             if edge.relation == "VERIFIED_BY"}
    assert tests == {"test:test_pinch_triggers_auto_reverse"}


def test_subgraph_is_bounded_by_depth(graph) -> None:
    one = graph.subgraph("cap:window", depth=1)
    two = graph.subgraph("cap:window", depth=2)
    assert len(one) < len(two) <= len(graph)
    assert "cap:window" in one


def test_subgraph_of_unknown_node_is_empty_but_marked(graph) -> None:
    sub = graph.subgraph("cap:does_not_exist")
    assert len(sub) == 0
    assert sub.to_dict()["meta"]["missing"] is True


def test_serialization_is_deterministic(graph) -> None:
    again = build_graph(
        catalog=load_catalog(ROOT / "catalog" / "capabilities"),
        vss=VssCatalog.from_json(GENERATED / "vss.json"),
        vdm=VdmSchema.from_sdl_file(GENERATED / "vdm.graphql"),
        contracts_dir=ROOT / "contracts",
        vss_version="6.1",
    )
    assert graph.to_dict() == again.to_dict()


def test_every_edge_endpoint_exists(graph) -> None:
    for edge in graph.edges:
        assert edge.source in graph, edge
        assert edge.target in graph, edge


def test_graph_endpoints() -> None:
    from capability_framework.app import create_app

    app = create_app(role="oem_automation")
    client = app.test_client()

    assert client.get("/vehicle/graph/").status_code == 200
    model = client.get("/vehicle/graph/model.json").get_json()
    assert model["meta"]["nodes"] > 0
    assert any(node["type"] == "Capability" for node in model["nodes"])

    sub = client.get("/vehicle/graph/node/cap:window").get_json()
    assert len(sub["nodes"]) > 1

    found = client.get("/vehicle/graph/search?q=Window.Position").get_json()
    assert found["results"]
