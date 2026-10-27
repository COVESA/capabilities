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

from flask import Flask, redirect, send_from_directory, url_for

from .bindings import WindowSimulatorPort
from .capabilities.window import (
    API_VERSION,
    MoveWindowCommand,
    WindowCapabilityOrchestrator,
    WindowManager,
    WindowZone,
)
from .capabilities.base import RequestSource
from .events import EventBus, Topics
from .explorer import create_blueprint as explorer_blueprint
from .models import WindowMotorModel, WindowMotorParams
from .northbound import create_blueprint as capabilities_blueprint
from .vehicle_state import DriveState, OtaState, PowerState, VehicleState

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "contracts"
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
class Stack:
    """Every runtime object of the example, wired on one bus and one binding."""
    bus: EventBus
    vehicle_state: VehicleStateStub
    power: PowerManagerStub
    window: WindowManager
    window_orchestrator: WindowCapabilityOrchestrator


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


def create_app(*, role: str = "oem_automation") -> Flask:
    """Build the Flask app: the runnable example."""
    stack = build_stack(role=role)

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
