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
capability_framework.explorer.blueprint
=======================================
The two interactive views distilled from the reference explorer:

  * ``/vehicle/catalog/`` — the API catalog: the capability's northbound and
    southbound interface, and the *stepable* boundary diagram
    (``?cap=window&tab=boundary``) that replays a request through the five
    pipeline phases.
  * ``/vehicle/api-explorer/`` — the API spec plus the *playground*, which
    drives the real :class:`WindowMotorModel` physics over ``simulate``.

Everything else the catalog UI shows is data-driven from the injected window
capability's descriptor and plant model, so this module never hard-codes the
capability's operations. The composition root owns the wiring.

Deployment topology (which ECU or zone controller hosts the capability) is out
of scope: that is a downstream concern a binding layer extends, not part of the
capability's own boundary.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from flask import Blueprint, Response, jsonify, redirect, render_template, request, url_for

from ..capabilities.window import WindowManager
from ..models import WindowMotorModel
from .bond_graph import window_motor_bond_graph
from .capability_diagram import (
    build_capability_arch_model,
    capability_architecture_svg,
    capability_boundary_svg,
)
_CONTRACT_ARTIFACT = re.compile(r"contracts/([a-z0-9]+(?:-[a-z0-9]+)*-api\.yaml)")


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def create_blueprint(
    *,
    window: WindowManager,
    motor_factory: Callable[[], WindowMotorModel] | None = None,
    contracts_dir: Path | None = None,
    url_prefix: str = "/vehicle",
    name: str = "explorer",
) -> Blueprint:
    """
    Build the explorer blueprint around the injected window capability.

    ``window`` supplies the descriptor, the northbound operations and the
    southbound dependencies. ``motor_factory`` supplies a fresh physics model per
    request (defaults to the deployed ``WindowMotorModel``); ``contracts_dir`` is
    where the capability's API contract is read from for the catalog's contract
    tab.
    """
    bp = Blueprint(name, __name__, url_prefix=url_prefix, template_folder="templates")

    def make_motor() -> WindowMotorModel:
        if motor_factory is not None:
            return motor_factory()
        model = window.system_model
        if isinstance(model, WindowMotorModel):
            return model.for_profile(window.deployment_profile) if window.deployment_profile else model
        return WindowMotorModel()

    def build_catalog_dict() -> dict[str, dict[str, Any]]:
        """The flat catalog entry the UI and the diagrams both read from."""
        desc = window.descriptor
        operations = [
            {
                "name": op.name,
                "description": op.description,
                "command_type": op.command_type,
                "response_type": op.response_type,
                "is_async": op.is_async,
                "requires_arbitration": op.requires_arbitration,
                "vss_paths": list(op.vss_paths),
            }
            for op in window.northbound_api
        ]
        return {
            "window": {
                "descriptor": {
                    "name": desc.name,
                    "display_name": desc.display_name,
                    "description": desc.description,
                    "domain": desc.domain,
                    "asil_tier": desc.asil_tier,
                    "api_version": desc.api_version,
                    "northbound_operations": list(desc.northbound_operations),
                    "southbound_dependencies": list(desc.southbound_dependencies),
                },
                "operations": operations,
                "state_topic": _enum_value(window.state_topic),
                "system_model": desc.system_model_params,
                "navigation_path": f"vehicle.body.window.{desc.name}",
                "contract": "contracts/window-api.yaml",
            }
        }

    def build_packages_view() -> list[dict[str, Any]]:
        desc = window.descriptor
        return [{
            "name": "window",
            "display_name": "Windows",
            "icon": "🪟",
            "description": "Power window movement capabilities.",
            "path": "vehicle.body.window",
            "capabilities": [{
                "name": "window",
                "display_name": desc.display_name,
                "asil_tier": desc.asil_tier,
                "navigation_path": f"vehicle.body.window.{desc.name}",
                "generic": False,
            }],
        }]

    def catalog_entry(capability: str) -> dict[str, Any] | None:
        return build_catalog_dict().get(capability)

    # ── Catalog ──────────────────────────────────────────────────────────

    @bp.route("/catalog/")
    def catalog_ui():
        return render_template("capability_catalog.html")

    @bp.route("/catalog/data")
    def catalog_data():
        return jsonify(build_catalog_dict())

    @bp.route("/catalog/packages")
    def catalog_packages():
        return jsonify({"packages": build_packages_view()})

    @bp.route("/catalog/artifact/<path:filepath>")
    def catalog_artifact(filepath: str):
        contract = _CONTRACT_ARTIFACT.fullmatch(filepath)
        if contract and contracts_dir is not None:
            path = contracts_dir / contract.group(1)
            if path.is_file():
                return jsonify({"path": filepath, "content": path.read_text(encoding="utf-8")})
        return jsonify({"error": "File not found"}), 404

    # ── Capability diagrams ──────────────────────────────────────────────

    @bp.route("/capability-diagram/<capability>/<kind>")
    def capability_diagram(capability: str, kind: str):
        cap = catalog_entry(capability)
        if cap is None:
            return jsonify({"error": f"Unknown capability '{capability}'."}), 404
        if kind == "boundary":
            svg = capability_boundary_svg(cap)
        elif kind == "architecture":
            svg = capability_architecture_svg(cap)
        else:
            return jsonify({"error": f"Unknown diagram kind '{kind}'."}), 404
        return Response(svg, mimetype="image/svg+xml")

    @bp.route("/capability-arch/<capability>/data")
    def capability_arch_data(capability: str):
        cap = catalog_entry(capability)
        if cap is None:
            return jsonify({"error": f"Unknown capability '{capability}'."}), 404
        return jsonify(build_capability_arch_model(cap))

    # ── Model views ──────────────────────────────────────────────────────

    @bp.route("/transfer-function/<capability>")
    def transfer_function_data(capability: str):
        if capability != "window":
            return jsonify({"error": f"No transfer function model for '{capability}'"}), 404
        model = make_motor()
        kpis = model.compute_move_kpis(target_mm=300.0, from_mm=0.0, time_limit_s=10.0)
        trajectory = model.simulate_move(target_mm=300.0, from_mm=0.0, dt=0.01, time_limit_s=10.0)
        return jsonify({
            "params": model.get_params(),
            "kpis": kpis.summary(),
            "trajectory": [
                {
                    "time_s": round(s.time_s, 4),
                    "position": round(s.position, 2),
                    "velocity": round(s.velocity, 2),
                    "force": round(s.force_or_torque, 2),
                    "temperature_c": round(s.temperature_c, 2),
                    "is_stalled": s.is_stalled,
                    "is_at_limit": s.is_at_limit,
                }
                for s in trajectory[::5]
            ],
        })

    @bp.route("/transfer-function/<capability>/kpis")
    def transfer_function_kpis(capability: str):
        if capability != "window":
            return jsonify({"error": f"No KPI model for '{capability}'."}), 404
        from_mm = float(request.args.get("from_mm", 0.0))
        target_mm = float(request.args.get("target_mm", 300.0))
        load_n = float(request.args.get("load_n", 50.0))
        velocity_mms = float(request.args.get("velocity_mms", 30.0))
        supply_v = float(request.args.get("supply_voltage_v", 12.0))
        model = make_motor()
        kpis = model.compute_move_kpis(target_mm=target_mm, from_mm=from_mm, time_limit_s=12.0)
        op = model.current_from_operating_point(
            force_n=load_n, velocity_mms=velocity_mms, supply_voltage_v=supply_v
        )
        return jsonify({**kpis.summary(), "operating_point": op})

    @bp.route("/transfer-function/<capability>/bond-graph")
    def transfer_function_bond_graph(capability: str):
        if capability != "window":
            return jsonify({"error": f"No BOND graph for '{capability}'."}), 404
        svg = window_motor_bond_graph(make_motor().get_params())
        return Response(svg, mimetype="image/svg+xml")

    @bp.route("/deployment-profile/<capability>")
    def deployment_profile(capability: str):
        if capability != "window":
            return jsonify({"error": f"No deployment profile for '{capability}'."}), 404
        profile = window.deployment_profile
        agnostic = window.agnostic_kpis or {}
        deployment = window.deployment_kpis or {}
        deltas = {
            key: round(deployment[key] - agnostic[key], 4)
            for key in ("move_latency_s", "peak_current_a", "rms_current_a",
                        "energy_wh", "avg_velocity_mms")
            if agnostic.get(key) is not None and deployment.get(key) is not None
        }
        return jsonify({
            "capability": capability,
            "boundary": "southbound",
            "profile": profile.summary() if profile else {},
            "kpis_agnostic": agnostic,
            "kpis_deployment": deployment,
            "kpis_delta": deltas,
        })

    # ── API Explorer / playground ────────────────────────────────────────

    @bp.route("/api-explorer/")
    def api_explorer_ui():
        return render_template("api_explorer.html")

    @bp.route("/api-explorer/simulate", methods=["POST"])
    def api_explorer_simulate():
        """Physics simulation of one window move for the playground."""
        data = request.get_json() or {}
        capability = data.get("capability", "window")
        if capability != "window":
            return jsonify({"error": f"No physics model for '{capability}'"}), 404

        target_mm = max(0.0, min(300.0, float(data.get("target_mm", 150.0))))
        from_mm = max(0.0, min(300.0, float(data.get("from_mm", 0.0))))

        model = make_motor()
        trajectory = model.simulate_move(target_mm=target_mm, from_mm=from_mm, dt=0.001, time_limit_s=8.0)
        kpis = make_motor().compute_move_kpis(target_mm=target_mm, from_mm=from_mm, time_limit_s=8.0)

        # Subsample to ~200 points for response compactness.
        step = max(1, -(-len(trajectory) // 200))
        points = [
            {
                "time_s": round(s.time_s, 3),
                "position": round(s.position, 2),
                "velocity": round(s.velocity, 3),
                "force": round(s.force_or_torque, 2),
                "is_at_limit": s.is_at_limit,
            }
            for s in trajectory[::step]
        ]

        rising = target_mm > from_mm
        direction = {
            "axis": "vertical",
            "label": "Closing (raising)" if rising else "Opening (lowering)",
            "sense": "up" if rising else "down",
            "gravity": "opposes motion (load)" if rising else "assists motion",
        }

        return jsonify({
            "capability": capability,
            "from_mm": from_mm,
            "target_mm": target_mm,
            "direction": direction,
            "params": model.get_params(),
            "kpis": kpis.summary(),
            "trajectory": points,
            "duration_s": round(trajectory[-1].time_s, 3) if trajectory else 0,
            "final_position_mm": round(trajectory[-1].position, 2) if trajectory else from_mm,
        })

    @bp.route("/")
    def dashboard():
        return redirect(url_for(".catalog_ui"))

    return bp


__all__ = ["create_blueprint"]
