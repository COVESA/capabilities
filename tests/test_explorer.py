"""Tests for the interactive explorer: the stepable boundary view and playground."""

from __future__ import annotations

import pytest

from capability_framework.app import create_app


@pytest.fixture
def client():
    app = create_app(role="oem_automation")
    app.config["TESTING"] = True
    return app.test_client()


# ── Catalog ──────────────────────────────────────────────────────────────

def test_catalog_ui_renders_with_boundary_tab(client) -> None:
    html = client.get("/vehicle/catalog/").get_data(as_text=True)
    assert "data-dtab=\"boundary\"" in html
    assert "startBoundaryAnim" in html


def test_catalog_data_exposes_descriptor_and_operations(client) -> None:
    body = client.get("/vehicle/catalog/data").get_json()
    entry = body["window"]
    assert entry["descriptor"]["display_name"] == "Window Movement Control"
    assert any(op["name"] == "moveWindow" for op in entry["operations"])


def test_catalog_packages_lists_the_window_package(client) -> None:
    packages = client.get("/vehicle/catalog/packages").get_json()["packages"]
    caps = [c["name"] for pkg in packages for c in pkg["capabilities"]]
    assert "window" in caps


# ── Navigation between the tools ─────────────────────────────────────────

TOOL_LINKS = (
    "/vehicle/catalog/",
    "/vehicle/api-explorer/",
    "/vehicle/signals/",
    "/vehicle/graph/",
)


@pytest.mark.parametrize("page", TOOL_LINKS)
def test_every_tool_page_links_to_every_tool(client, page: str) -> None:
    """The landing page and the other tools form one navigable set."""
    html = client.get(page).get_data(as_text=True)
    for link in TOOL_LINKS:
        assert f'href="{link}"' in html, f"{page} does not link to {link}"


@pytest.mark.parametrize("page", TOOL_LINKS)
def test_every_tool_page_reachable(client, page: str) -> None:
    assert client.get(page).status_code == 200


def test_root_serves_the_catalog_landing_page(client) -> None:
    """Running the app lands on a page that can reach the other tools."""
    resp = client.get("/")
    assert resp.status_code in (301, 302, 308)
    assert "/vehicle/catalog/" in resp.headers["Location"]


def test_vss_signals_page_renders_the_live_signals(client) -> None:
    html = client.get("/vehicle/signals/").get_data(as_text=True)
    assert "/vehicle/vss" in html
    assert "Position" in html or "signals" in html


# ── Stepable boundary diagram ────────────────────────────────────────────

def test_boundary_diagram_is_svg_with_steppable_groups(client) -> None:
    resp = client.get("/vehicle/capability-diagram/window/boundary")
    assert resp.status_code == 200
    assert resp.mimetype == "image/svg+xml"
    svg = resp.get_data(as_text=True)
    # The client lights .bd-step groups as the request is replayed.
    assert 'class="bd-step"' in svg
    for node in ("bd-feature", "bd-nb", "bd-mgr", "bd-sb", "bd-plant"):
        assert f'id="{node}"' in svg


def test_boundary_diagram_does_not_double_prefix_asil(client) -> None:
    svg = client.get("/vehicle/capability-diagram/window/boundary").get_data(as_text=True)
    assert "ASIL B" in svg
    assert "ASIL ASIL" not in svg


def test_deployment_topology_is_out_of_scope(client) -> None:
    # Deployment/ECU topology is a downstream extension, not part of the base.
    for kind in ("deployment1", "deployment2", "deployment3"):
        assert client.get(f"/vehicle/capability-diagram/window/{kind}").status_code == 404


def test_unknown_diagram_kind_is_404(client) -> None:
    assert client.get("/vehicle/capability-diagram/window/nonsense").status_code == 404


# ── Lighting in the explorer ─────────────────────────────────────────────

def test_catalog_lists_the_lighting_capability(client) -> None:
    body = client.get("/vehicle/catalog/data").get_json()
    entry = body["lighting"]
    assert entry["descriptor"]["display_name"] == "Interior Lighting Control"
    assert entry["contract"] == "contracts/lighting-api.yaml"
    assert entry["state_topic"] == "lighting_state"
    assert entry["operations"][0]["name"] == "setInteriorLight"
    assert entry["operations"][0]["command_type"] == "SetInteriorLightCommand"

    packages = client.get("/vehicle/catalog/packages").get_json()["packages"]
    lighting = next(pkg for pkg in packages if pkg["name"] == "lighting")
    assert lighting["capabilities"][0]["navigation_path"] == "vehicle.body.lighting.lighting"


def test_lighting_boundary_diagram_renders_the_lighting_capability(client) -> None:
    resp = client.get("/vehicle/capability-diagram/lighting/boundary")
    assert resp.status_code == 200
    assert resp.mimetype == "image/svg+xml"
    svg = resp.get_data(as_text=True)
    for node in ("bd-feature", "bd-nb", "bd-mgr", "bd-phase-4", "bd-sb", "bd-plant", "bd-eb", "bd-resp"):
        assert f'id="{node}"' in svg
    assert "LIGHTING CAPABILITY MANAGER" in svg
    assert "SetInteriorLightCommand" in svg
    assert "LightingState" in svg
    assert "Topics.LIGHTING_STATE" in svg
    assert "set_ambient_light, get_ambient_light" in svg
    assert "Ambient RGB LED Driver" in svg
    # QM is not an ASIL level, and the window's motor feedback does not apply.
    assert "QM · v1.0.0" in svg
    assert "ASIL QM" not in svg
    assert "Hall pulses" not in svg
    assert "no plant model" in svg
    # Lighting has no orchestration operations, so no orchestrator is claimed.
    assert "LIGHTING DOMAIN CAPABILITY ORCHESTRATOR" not in svg
    assert "no domain orchestrator" in svg


def test_window_boundary_keeps_its_orchestrator_and_plant_labels(client) -> None:
    svg = client.get("/vehicle/capability-diagram/window/boundary").get_data(as_text=True)
    assert "WINDOW DOMAIN CAPABILITY ORCHESTRATOR" in svg
    assert "Hall pulses" in svg
    assert "see Transfer Function / BOND graph" in svg


def test_lighting_architecture_diagram_and_model(client) -> None:
    assert client.get("/vehicle/capability-diagram/lighting/architecture").status_code == 200
    assert client.get("/vehicle/capability-arch/lighting/data").status_code == 200


def test_lighting_contract_artifact_is_served(client) -> None:
    body = client.get("/vehicle/catalog/artifact/contracts/lighting-api.yaml").get_json()
    assert "operationId: setInteriorLight" in body["content"]


def test_lighting_has_no_physics_views(client) -> None:
    for path in ("/vehicle/transfer-function/lighting", "/vehicle/deployment-profile/lighting"):
        assert client.get(path).status_code == 404


# ── Model views ──────────────────────────────────────────────────────────

def test_transfer_function_returns_trajectory(client) -> None:
    body = client.get("/vehicle/transfer-function/window").get_json()
    assert len(body["trajectory"]) > 1
    assert body["kpis"]["total_travel_mm"] == 300.0


def test_bond_graph_is_svg(client) -> None:
    resp = client.get("/vehicle/transfer-function/window/bond-graph")
    assert resp.status_code == 200
    assert resp.mimetype == "image/svg+xml"
    assert "GY" in resp.get_data(as_text=True)


# ── Playground ───────────────────────────────────────────────────────────

def test_playground_ui_renders(client) -> None:
    html = client.get("/vehicle/api-explorer/").get_data(as_text=True)
    assert "btnSimulate" in html
    assert "api-explorer/simulate" in html


def test_simulate_runs_the_physics_model(client) -> None:
    resp = client.post("/vehicle/api-explorer/simulate",
                       json={"capability": "window", "from_mm": 0.0, "target_mm": 300.0})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["direction"]["sense"] == "up"
    assert body["final_position_mm"] == pytest.approx(300.0, abs=2.0)
    assert body["kpis"]["move_latency_s"] > 0
    assert 2 <= len(body["trajectory"]) <= 201


def test_simulate_lowering_reports_gravity_assists(client) -> None:
    body = client.post("/vehicle/api-explorer/simulate",
                       json={"capability": "window", "from_mm": 300.0, "target_mm": 0.0}).get_json()
    assert body["direction"]["sense"] == "down"
    assert "assists" in body["direction"]["gravity"]


def test_simulate_clamps_out_of_range_target(client) -> None:
    body = client.post("/vehicle/api-explorer/simulate",
                       json={"capability": "window", "target_mm": 999.0}).get_json()
    assert body["target_mm"] == 300.0


def test_simulate_rejects_unknown_capability(client) -> None:
    resp = client.post("/vehicle/api-explorer/simulate", json={"capability": "seating"})
    assert resp.status_code == 404
