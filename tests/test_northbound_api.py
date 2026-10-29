"""Coverage for every exposed northbound operation."""

from __future__ import annotations

import pytest


@pytest.fixture
def client():
    from capability_framework.app import create_app

    app = create_app(role="oem_automation")
    app.config["TESTING"] = True
    return app.test_client()


def test_http_get_window_state_reads_a_zone(client) -> None:
    client.post("/vehicle/window/move", json={"zone": "DRIVER_REAR", "target_pct": 60.0})
    body = client.get("/vehicle/window/state?zone=DRIVER_REAR").get_json()
    assert body["zone"] == "DRIVER_REAR"
    assert body["position_pct"] == pytest.approx(60.0, abs=1.0)


def test_http_can_execute_has_no_side_effects(client) -> None:
    body = client.post(
        "/vehicle/window/can-execute",
        json={"zone": "PASSENGER_FRONT", "target_pct": 10.0},
    ).get_json()
    assert body["status"] in {"STATIONARY", "MOVING", "INHIBITED"}
    # A pre-flight check must not have moved the window.
    after = client.get("/vehicle/window/state?zone=PASSENGER_FRONT").get_json()
    assert after["position_pct"] == pytest.approx(0.0, abs=1.0)


def test_http_release_window_after_move(client) -> None:
    move = client.post(
        "/vehicle/window/move",
        json={"zone": "DRIVER_FRONT", "target_pct": 45.0, "request_id": "11111111-1111-4111-8111-111111111111"},
    ).get_json()
    resp = client.post(
        "/vehicle/window/release",
        json={"request_id": move["request_id"]},
    )
    assert resp.status_code in {200, 409}
