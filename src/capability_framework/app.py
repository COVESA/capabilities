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
capability_framework.app
========================
Composition root and runnable example application.

Builds the window capability on the simulator binding, injects the physics
model, and mounts the northbound HTTP adapters. This is the only module that
knows the binding and the models.

Run::

    python -m capability_framework.app            # http://127.0.0.1:8770
    python -m capability_framework.app --port 9000 --role passenger_app

Power management and vehicle-state are intentionally **stubs** here: this
repository shows the capability, its northbound and southbound interfaces, and
the motor model — not the platform services around them.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, send_from_directory, url_for

from .bindings import WindowSimulatorPort
from .capabilities.window import (
    API_VERSION,
    MoveWindowCommand,
    WindowCapabilityOrchestrator,
    WindowManager,
    WindowZone,
)
from .capabilities.window.vss import WindowVssProjector
from .capabilities.base import RequestSource
from .events import EventBus, Topics
from .explorer import create_blueprint as explorer_blueprint
from .models import WindowMotorModel, WindowMotorParams
from .northbound import create_blueprint as capabilities_blueprint
from .semantics import VssCatalog, VssSnapshot, load_capability
from .vehicle_state import DriveState, OtaState, PowerState, VehicleState

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = REPO_ROOT / "contracts"
CATALOG_DIR = REPO_ROOT / "catalog" / "capabilities"
GENERATED_DIR = REPO_ROOT / "third_party" / "generated"
STANDARDS_LOCK = REPO_ROOT / "third_party" / "standards.lock.json"
DEFAULT_PORT = 8770


# ── Platform stand-ins (NOT the focus of this example) ──────────────────────
#
# A real vehicle supplies vehicle state from a determinator and authorizes power
# from a central manager. Both are reduced here to the smallest thing that lets
# the window capability run, because they are platform concerns, not the window
# capability itself. They publish on the same event-bus topic the capability
# reads in its precondition phase, so the wiring is faithful even though the
# source is a stub.


@dataclass
class VehicleStateStub:
    """Minimal vehicle-state source: publishes a VehicleState the capability gates on."""

    bus: EventBus
    power_state: PowerState = PowerState.ON
    drive_state: DriveState = DriveState.PARKED
    ota_state: OtaState = OtaState.IDLE
    supply_voltage_v: float = 12.6

    def snapshot(self) -> VehicleState:
        return VehicleState(
            power_state=self.power_state,
            drive_state=self.drive_state,
            ota_state=self.ota_state,
            supply_voltage_v=self.supply_voltage_v,
        )

    async def publish(self) -> None:
        await self.bus.publish(Topics.VEHICLE_STATE, self.snapshot())


@dataclass
class PowerManagerStub:
    """
    Minimal power authorization stand-in.

    A real central power manager grants a budget before an actuator moves and can
    refuse under low battery or shedding. Here it always grants, but it records
    the requests so the example shows where the seam is.
    """
    grants: list[float] = field(default_factory=list)
    budget_w: float = 400.0

    def request_power(self, budget_w: float) -> float:
        self.grants.append(budget_w)
        return min(budget_w, self.budget_w)

    def release_power(self) -> None:
        return None


@dataclass
class VssRuntime:
    """The live VSS view: the pinned catalog plus the capability's projected signals."""

    bus: EventBus
    snapshot: VssSnapshot
    projector: WindowVssProjector
    catalog: VssCatalog

    def refresh(self) -> None:
        """Project the latest capability state, in case it predates the subscription."""
        state = self.bus.last(Topics.WINDOW_STATE)
        if state is not None:
            self.snapshot.update(self.projector(state))


@dataclass
class Stack:
    """Every runtime object of the example, wired on one bus and one binding."""
    bus: EventBus
    vehicle_state: VehicleStateStub
    power: PowerManagerStub
    window: WindowManager
    window_orchestrator: WindowCapabilityOrchestrator
    vss: "VssRuntime | None" = None


def build_stack(*, role: str = "oem_automation") -> Stack:
    """Compose the example: bus → stub state → binding + model → window capability."""
    bus = EventBus()
    vehicle_state = VehicleStateStub(bus=bus)
    power = PowerManagerStub()

    # The southbound binding owns the physics model; the capability is injected
    # with the same model so it can introspect parameters and predict KPIs.
    model = WindowMotorModel(WindowMotorParams())
    binding = WindowSimulatorPort(model=model)

    window = WindowManager(actuator=binding, event_bus=bus, motor_model=model)
    window_orchestrator = WindowCapabilityOrchestrator(window, event_bus=bus)

    # Publish the initial vehicle state so the capability's precondition phase has
    # something to read on first use.
    asyncio.run(vehicle_state.publish())

    # Bind the capability to the deployment physics (southbound handshake).
    asyncio.run(window.bind_deployment())

    return Stack(bus=bus, vehicle_state=vehicle_state, power=power,
                 window=window, window_orchestrator=window_orchestrator)


def build_vss_runtime(stack: Stack) -> VssRuntime | None:
    """
    Attach a VSS view to the stack, or return None when the pins are not vendored.

    The runtime needs the pinned ``vss.json`` and the window catalog entry. Both are
    checked-in artifacts, so a normal checkout always has them; an installed wheel
    without them degrades to "no VSS endpoint" instead of failing to boot.
    """
    vss_json = GENERATED_DIR / "vss.json"
    entry = CATALOG_DIR / "window.yaml"
    if not vss_json.is_file() or not entry.is_file():
        log.warning("VSS runtime disabled: run ./scripts/vendor_standards.sh")
        return None

    catalog = VssCatalog.from_json(vss_json)
    spec = load_capability(entry)
    version = None
    if STANDARDS_LOCK.is_file():
        import json

        version = json.loads(STANDARDS_LOCK.read_text(encoding="utf-8"))["standards"]["vss"][
            "version_label"
        ]

    snapshot = VssSnapshot(catalog=catalog, spec=spec, version=version)
    projector = WindowVssProjector()
    stack.bus.subscribe(Topics.WINDOW_STATE, snapshot.handler(projector))

    runtime = VssRuntime(bus=stack.bus, snapshot=snapshot, projector=projector, catalog=catalog)
    runtime.refresh()
    return runtime


def build_knowledge_graph():
    """Build the capability/VSS/VDM graph, or None when the pins are not vendored."""
    try:
        from .semantics.graph import build_graph
        from .semantics.vdm import VdmSchema
    except ImportError:
        log.warning("Knowledge graph disabled: install the 'standards' extra")
        return None

    vss_json = GENERATED_DIR / "vss.json"
    vdm_graphql = GENERATED_DIR / "vdm.graphql"
    if not vss_json.is_file() or not vdm_graphql.is_file() or not CATALOG_DIR.is_dir():
        log.warning("Knowledge graph disabled: run ./scripts/vendor_standards.sh")
        return None

    return build_graph(
        catalog=CATALOG_DIR,
        vss=VssCatalog.from_json(vss_json),
        vdm=VdmSchema.from_sdl_file(vdm_graphql),
        contracts_dir=CONTRACTS_DIR,
        vss_version=None,
    )


def create_app(*, role: str = "oem_automation") -> Flask:
    """Build the Flask app: the runnable example."""
    stack = build_stack(role=role)
    stack.vss = build_vss_runtime(stack)

    app = Flask(__name__, static_folder=None)
    app.config["STACK"] = stack

    bp = capabilities_blueprint(
        window=stack.window,
        window_orchestrator=stack.window_orchestrator,
        event_bus=stack.bus,
        vehicle_state=stack.vehicle_state.snapshot,
        role=role,
    )
    app.register_blueprint(bp)

    explorer = explorer_blueprint(
        window=stack.window,
        motor_factory=WindowMotorModel,
        contracts_dir=CONTRACTS_DIR,
    )
    app.register_blueprint(explorer)

    @app.route("/")
    def index():
        return redirect(url_for("explorer.catalog_ui"))

    @app.route("/<path:filename>")
    def static_files(filename: str):
        return send_from_directory(STATIC_DIR, filename)

    @app.route("/vehicle/state")
    def vehicle_state_view():
        from .vehicle_state import vehicle_state_to_dict
        return vehicle_state_to_dict(stack.vehicle_state.snapshot())

    # ── VSS view of the running capability ───────────────────────────────
    #
    # These routes serve the capability's own state, expressed as VSS signals
    # from the pinned standard. They are not a VISS server: there is no
    # subscription or access control, only a snapshot for inspection.

    @app.route("/vehicle/vss")
    def vss_view():
        runtime = stack.vss
        if runtime is None:
            return jsonify({"error": "VSS runtime disabled; run ./scripts/vendor_standards.sh"}), 503
        runtime.refresh()
        return jsonify(runtime.snapshot.to_dict())

    # ── Knowledge graph: capabilities, contracts, VSS, VDM ───────────────

    graph_cache: dict[str, object] = {}

    def knowledge_graph():
        if "graph" not in graph_cache:
            graph_cache["graph"] = build_knowledge_graph()
        return graph_cache["graph"]

    @app.route("/vehicle/graph/")
    def graph_ui():
        graph = knowledge_graph()
        if graph is None:
            return "Knowledge graph unavailable: run ./scripts/vendor_standards.sh", 503
        return render_template(
            "knowledge_graph.html",
            summary=graph.to_dict()["meta"],
            layer_counts=graph.count_by("layer"),
        )

    @app.route("/vehicle/graph/model.json")
    def graph_model():
        graph = knowledge_graph()
        if graph is None:
            return jsonify({"error": "knowledge graph unavailable"}), 503
        return jsonify(graph.to_dict())

    @app.route("/vehicle/graph/node/<path:node_id>")
    def graph_node(node_id: str):
        graph = knowledge_graph()
        if graph is None:
            return jsonify({"error": "knowledge graph unavailable"}), 503
        depth = max(1, min(3, int(request.args.get("depth", 1))))
        return jsonify(graph.subgraph(node_id, depth=depth).to_dict())

    @app.route("/vehicle/graph/search")
    def graph_search():
        graph = knowledge_graph()
        if graph is None:
            return jsonify({"error": "knowledge graph unavailable"}), 503
        query = request.args.get("q", "").strip()
        results = graph.search(query) if query else []
        return jsonify({"query": query, "results": [node.to_dict() for node in results]})

    @app.route("/vehicle/vss/<path:signal_path>")
    def vss_signal(signal_path: str):
        runtime = stack.vss
        if runtime is None:
            return jsonify({"error": "VSS runtime disabled; run ./scripts/vendor_standards.sh"}), 503
        runtime.refresh()
        view = runtime.snapshot.signal_view(signal_path)
        if view is None:
            return jsonify({"error": f"{signal_path!r} is not a signal in the pinned VSS"}), 404
        return jsonify(view)

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capability framework — window example")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--role", default="oem_automation",
                        choices=["passenger_app", "driver_input", "oem_automation"])
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    app = create_app(role=args.role)
    url = f"http://{args.host}:{args.port}/"
    print(f"Window capability example: {url}")
    print(f"  northbound API: {url}vehicle/window/move  (POST)")
    if not args.no_browser:
        import webbrowser
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    app.run(host=args.host, port=args.port, debug=False, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
