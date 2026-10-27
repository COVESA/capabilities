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
capability_framework.northbound.http
====================================
Northbound HTTP adapter for the window capability — the same API surface used in
the reference deployment: command routes plus an SSE stream of capability state.

The composition root injects the capability and the event bus; this module never
builds or binds hardware. Flask (synchronous) serves each request on its own
thread, while the capability is shared and its asyncio locks assume one event
loop. So every route runs its call on one long-lived event loop (``_shared_loop()``),
never ``asyncio.run()`` per request.

A caller's *role* decides the request source (the capability never trusts a
self-asserted source); a role that may not command capabilities is refused.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import queue
import threading
import uuid
from collections.abc import Callable
from datetime import datetime

from flask import Blueprint, Response, abort, jsonify, make_response, request, stream_with_context

from ..capabilities.base import RequestSource
from ..capabilities.window import (
    MoveWindowCommand,
    WindowCapabilityOrchestrator,
    WindowInhibitReason,
    WindowManager,
    WindowSequenceMode,
    WindowState,
    WindowZone,
)
from ..events import EventBus, Topics
from ..vehicle_state import VehicleState, vehicle_state_to_dict

__all__ = ["HTTP_ROLE_TO_SOURCE", "create_blueprint"]

#: Verified role → the source every command it issues carries. No role maps to SAFETY.
HTTP_ROLE_TO_SOURCE: dict[str, RequestSource] = {
    "passenger_app": RequestSource.APP,
    "driver_input": RequestSource.DRIVER,
    "oem_automation": RequestSource.OEM_AUTOMATION,
}

_SOURCE_NOTE = (
    "the request source is set by the northbound adapter from the caller's verified role; "
    "it is not part of the payload"
)

# A call that has not answered within call_timeout_s is cancelled; once the
# capability has stopped, the request is answered 504. Grace for the cleanup.
_CANCEL_GRACE_S = 2.0

_default_loop: asyncio.AbstractEventLoop | None = None
_default_loop_pid: int | None = None
_default_loop_guard = threading.Lock()


def _shared_loop() -> asyncio.AbstractEventLoop:
    """The process-wide capability event loop, created once per process."""
    global _default_loop, _default_loop_pid
    with _default_loop_guard:
        if _default_loop is None or _default_loop_pid != os.getpid():
            loop = asyncio.new_event_loop()
            threading.Thread(target=loop.run_forever, name="capability-loop", daemon=True).start()
            _default_loop, _default_loop_pid = loop, os.getpid()
        return _default_loop


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def _response_fields(state: WindowState) -> dict:
    """The shared fields every capability response carries."""
    return {
        "reason": _enum_value(state.reason),
        "message": state.message,
        "retry_after_s": state.retry_after_s,
        "winning_source": state.winning_source.name if state.winning_source else None,
        "request_id": state.request_id,
        "api_version": state.api_version,
    }


def _window_to_dict(st: WindowState) -> dict:
    return {"status": _enum_value(st.status), "position_pct": st.position_pct,
            "zone": _enum_value(st.zone), **_response_fields(st)}


def create_blueprint(
    *,
    window: WindowManager,
    window_orchestrator: WindowCapabilityOrchestrator,
    event_bus: EventBus,
    vehicle_state: Callable[[], VehicleState],
    role: str,
    loop: asyncio.AbstractEventLoop | None = None,
    call_timeout_s: float = 300.0,
    url_prefix: str = "/vehicle",
    name: str = "capabilities",
) -> Blueprint:
    """Build the window command blueprint around the injected capability."""
    source = HTTP_ROLE_TO_SOURCE.get(role)
    if source is None:
        raise PermissionError(f"role {role!r} may not command capabilities over HTTP")

    bp = Blueprint(name, __name__, url_prefix=url_prefix)

    def run(call):
        """Run a capability call on the capability loop; this request's thread waits for the answer."""
        finished = threading.Event()

        async def tracked():
            try:
                return await call
            finally:
                finished.set()

        future = asyncio.run_coroutine_threadsafe(tracked(), loop if loop is not None else _shared_loop())
        try:
            return future.result(timeout=call_timeout_s)
        except concurrent.futures.TimeoutError:
            if future.done():
                return future.result()
            future.cancel()
            note = ("it was cancelled and has stopped" if finished.wait(timeout=_CANCEL_GRACE_S)
                    else f"it was cancelled but had not confirmed it stopped after {_CANCEL_GRACE_S} s")
            abort(make_response(jsonify(
                {"error": f"the capability did not answer within {call_timeout_s} s; {note}"}), 504))

    def body() -> dict:
        d = request.get_json()
        if not isinstance(d, dict):
            abort(make_response(jsonify({"error": "the request body must be a JSON object"}), 400))
        if "source" in d:
            abort(make_response(jsonify({"error": _SOURCE_NOTE}), 400))
        return d

    # ── SSE fan-out ──────────────────────────────────────────────────────
    sse_clients: list[queue.Queue] = []
    sse_lock = threading.Lock()

    def push_sse(topic: str, payload: dict) -> None:
        data = json.dumps({"topic": topic, "payload": payload,
                           "ts": datetime.now().strftime("%H:%M:%S.%f")[:-3]})
        with sse_lock:
            dead = []
            for q in sse_clients:
                try:
                    q.put_nowait(data)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                sse_clients.remove(q)

    async def _on_window_state(payload) -> None:
        push_sse("WINDOW_STATE", _window_to_dict(payload))

    event_bus.subscribe(Topics.WINDOW_STATE, _on_window_state)

    @bp.route("/events")
    def sse_stream():
        """Server-Sent Events stream — the browser subscribes once and receives window events."""
        q: queue.Queue = queue.Queue(maxsize=100)
        with sse_lock:
            sse_clients.append(q)

        def generate():
            snapshot = {"topic": "VEHICLE_STATE", "payload": vehicle_state_to_dict(vehicle_state()),
                        "ts": datetime.now().strftime("%H:%M:%S.%f")[:-3]}
            yield f"data: {json.dumps(snapshot)}\n\n"
            try:
                while True:
                    try:
                        data = q.get(timeout=15.0)
                        yield f"data: {data}\n\n"
                    except queue.Empty:
                        yield ": keep-alive\n\n"
            finally:
                with sse_lock:
                    if q in sse_clients:
                        sse_clients.remove(q)

        return Response(stream_with_context(generate()), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ── Window ───────────────────────────────────────────────────────────

    @bp.route("/window/move", methods=["POST"])
    def window_move():
        d = body()
        cmd = MoveWindowCommand(
            source=source,
            zone=WindowZone(d.get("zone", "DRIVER_FRONT")),
            target_pct=float(d.get("target_pct", 0.0)),
            request_id=str(d.get("request_id") or uuid.uuid4()),
            timeout_s=float(d.get("timeout_s", 30.0)),
        )
        return jsonify(_window_to_dict(run(window.moveWindow(cmd))))

    @bp.route("/window/can-execute", methods=["POST"])
    def window_can_execute():
        d = body()
        cmd = MoveWindowCommand(
            source=source,
            zone=WindowZone(d.get("zone", "DRIVER_FRONT")),
            target_pct=float(d.get("target_pct", 0.0)),
        )
        return jsonify(_window_to_dict(run(window.can_execute(cmd))))

    @bp.route("/window/release", methods=["POST"])
    def window_release():
        d = body()
        run(window.releaseWindow(d.get("request_id", "")))
        return jsonify({"ok": True})

    @bp.route("/window/state")
    def window_state():
        zone = WindowZone(request.args.get("zone", "DRIVER_FRONT"))
        pos = run(_position(zone))
        return jsonify({
            "status": "STATIONARY",
            "position_pct": pos,
            "zone": zone.value,
            "winning_source": None,
            "request_id": None,
            "api_version": window.descriptor.api_version,
            "reason": None,
        })

    async def _position(zone: WindowZone) -> float:
        return await window._actuator.get_window_position(zone.value)

    @bp.route("/window/model")
    def window_model():
        """Introspect the physics model parameters the capability is validated against."""
        model = window.system_model
        return jsonify({
            "name": model.name if model else None,
            "parameters": model.get_params() if model else {},
            "agnostic_kpis": window.agnostic_kpis,
            "deployment_kpis": window.deployment_kpis,
        })

    @bp.route("/window/orchestrate", methods=["POST"])
    def window_orchestrate():
        """Window domain capability orchestrator: multi-zone staged sequences."""
        d = body()
        try:
            mode = WindowSequenceMode(d.get("mode", "CASCADE_OPEN"))
        except ValueError:
            return jsonify({"error": f"unknown mode: {d.get('mode')}"}), 400

        target_pct = float(d.get("target_pct", 100.0 if mode == WindowSequenceMode.CASCADE_OPEN else 0.0))

        if mode == WindowSequenceMode.CASCADE_OPEN:
            call = window_orchestrator.cascade_open(source=source, target_pct=target_pct)
        elif mode == WindowSequenceMode.CASCADE_CLOSE:
            call = window_orchestrator.cascade_close(source=source, target_pct=target_pct)
        elif mode == WindowSequenceMode.SYNC:
            call = window_orchestrator.sync_all(source=source, target_pct=target_pct)
        else:
            return jsonify({"error": f"unsupported mode {mode.value}"}), 400

        state = run(call)
        return jsonify({
            "status": state.status.value,
            "mode": mode.value,
            "active_stage_index": state.active_stage_index,
            "per_zone": {
                zone: {"status": s.status.value, "position_pct": s.position_pct,
                       "reason": _enum_value(s.reason)}
                for zone, s in state.per_zone.items()
            },
            "reason": state.reason,
            "request_id": state.request_id,
            "api_version": state.api_version,
        })

    @bp.route("/window/catalog")
    def window_catalog():
        """The capability's machine-readable descriptor (for the API catalog)."""
        desc = window.descriptor
        return jsonify({
            "name": desc.name,
            "display_name": desc.display_name,
            "description": desc.description,
            "api_version": desc.api_version,
            "domain": desc.domain,
            "asil_tier": desc.asil_tier,
            "northbound_operations": list(desc.northbound_operations),
            "southbound_dependencies": list(desc.southbound_dependencies),
        })

    return bp
