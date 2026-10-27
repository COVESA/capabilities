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
capability_framework.capabilities.base
======================================
Base class for all capabilities.

A capability is a first-class object with:

- a defined **northbound** API (commands offered to requestors),
- a defined **southbound** API (hardware dependencies via an actuator port),
- a five-phase internal pipeline
  (Arbitrate → Precondition → Safety → Actuator → Publish), and
- a system model describing physical constraints.

Capabilities are hardware-agnostic: the southbound interface absorbs hardware
differences, so the northbound API stays stable across deployments.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Hashable
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from types import MappingProxyType
from typing import Any, Generic, Mapping, Protocol, TypeVar

from ..events import EventBus, bus as _default_bus
from ..southbound import ActuatorError, ActuatorPortBase

__all__ = [
    "PRIORITY",
    "ActuatorOutcome",
    "ActuatorRun",
    "Capability",
    "CapabilityDescriptor",
    "HeldValue",
    "NorthboundOperation",
    "Priority",
    "RequestSource",
    "SystemModel",
    "TCommand",
    "TState",
]

log = logging.getLogger(__name__)

TCommand = TypeVar("TCommand")
TState = TypeVar("TState")


class Priority(IntEnum):
    """Named priority tiers: arbitration compares these, never raw source values."""
    APP = 1
    USER = 2
    SYSTEM = 3
    SAFETY = 4


class RequestSource(IntEnum):
    """Who issued a command. Set by the northbound adapter from a verified role."""
    APP = 1              # background app / comfort preset
    DRIVER = 2           # direct driver input
    OEM_AUTOMATION = 3   # entry/exit sequence, welcome mode
    SAFETY = 4           # collision, emergency stop, OTA gate


#: Named priority tiers. Arbitration compares these, never raw RequestSource values.
PRIORITY: Mapping[RequestSource, Priority] = MappingProxyType({
    RequestSource.APP: Priority.APP,
    RequestSource.DRIVER: Priority.USER,
    RequestSource.OEM_AUTOMATION: Priority.SYSTEM,
    RequestSource.SAFETY: Priority.SAFETY,
})


class SystemModel(Protocol):
    """An injected plant model. Plant-model packages satisfy this structurally."""

    def get_params(self) -> dict[str, Any]: ...


class ActuatorOutcome(str, Enum):
    """How phase 4 ended. Anything but COMPLETED means the capability must enter its safe state."""
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"    # the lock holder released the request while the call was in flight
    TIMED_OUT = "TIMED_OUT"  # the call outlived the command's timeout


@dataclass(frozen=True)
class ActuatorRun:
    outcome: ActuatorOutcome
    result: Any = None


@dataclass(frozen=True)
class HeldValue:
    """What the actuator holds after an interrupted command. ``value`` is None when unknown."""
    value: Any
    message: str | None = None


@dataclass(frozen=True)
class CapabilityDescriptor:
    """Machine-readable descriptor for a capability, used by the API catalog for discovery."""
    name: str
    display_name: str
    description: str
    api_version: str
    domain: str
    asil_tier: str = "QM"
    northbound_operations: tuple[str, ...] = ()
    southbound_dependencies: tuple[str, ...] = ()
    system_model_params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NorthboundOperation:
    """Describes a single northbound API operation."""
    name: str
    description: str
    command_type: str
    response_type: str
    is_async: bool = True
    requires_arbitration: bool = True
    vss_paths: tuple[str, ...] = ()   # COVESA VSS signal paths this op affects


class Capability(ABC, Generic[TCommand, TState]):
    """
    Abstract base class for all capabilities.

    Subclasses implement ``descriptor``, ``northbound_api``, ``state_topic`` and
    the five phase methods. Phase 4 should go through ``_run_actuator`` so the
    call is bounded by the command's timeout and can be interrupted by an
    explicit release.
    """

    # Upper bound on waiting for a cancelled actuator call to finish its cleanup.
    ABORT_TIMEOUT_S: float = 1.0
    # Upper bound on the safe-state read-back after an interruption.
    READBACK_TIMEOUT_S: float = 1.0

    def __init__(self, actuator: ActuatorPortBase, event_bus: EventBus | None = None) -> None:
        if actuator is None:
            raise TypeError(
                f"{type(self).__name__} needs an actuator port; inject one from the composition root"
            )
        self._actuator = actuator
        self._bus = event_bus or _default_bus
        self._active_request: Any | None = None
        self._lock = asyncio.Lock()
        # request_id → (loop running the command, its release event)
        self._release_signals: dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Event]] = {}
        self._released: set[str] = set()
        self._release_lock = threading.Lock()
        self._confirmed: dict[Hashable, Any] = {}

    # ── Descriptor & API surface ──────────────────────────────────────────

    @property
    @abstractmethod
    def descriptor(self) -> CapabilityDescriptor: ...

    @property
    @abstractmethod
    def northbound_api(self) -> list[NorthboundOperation]: ...

    @property
    @abstractmethod
    def state_topic(self) -> str: ...

    # ── Five-phase pipeline ───────────────────────────────────────────────

    @abstractmethod
    def _arbitrate(self, command: TCommand) -> str | None: ...

    @abstractmethod
    def _check_preconditions(self, vs: Any | None) -> str | None: ...

    @abstractmethod
    def _safety_case(self, command: TCommand, vs: Any | None) -> str | None: ...

    @abstractmethod
    async def _dispatch(self, command: TCommand) -> Any: ...

    @abstractmethod
    async def _build_state(self, command: TCommand, dispatch_result: Any, status: str) -> TState: ...

    @abstractmethod
    async def can_execute(self, command: TCommand) -> TState: ...

    # ── Phase 4 support: timeout, release and bounded abort ────────────────

    def _open_release(self, request_id: str) -> None:
        """Make *request_id* releasable. Pair with ``_close_release`` in a ``finally``."""
        entry = (asyncio.get_running_loop(), asyncio.Event())
        with self._release_lock:
            self._release_signals[request_id] = entry

    def _close_release(self, request_id: str) -> None:
        with self._release_lock:
            self._release_signals.pop(request_id, None)
            self._released.discard(request_id)

    def _is_released(self, request_id: str) -> bool:
        with self._release_lock:
            return request_id in self._released

    async def _run_actuator(self, request_id: str, call: Awaitable[Any], timeout_s: float) -> ActuatorRun:
        """
        Run the actuator call for *request_id*, bounded by *timeout_s* and
        interruptible by ``_signal_release``. On timeout or release the call is
        cancelled (see ``_abort``). A request released before phase 4 never
        starts the call. ``ActuatorError`` from the call propagates.
        """
        opened_here = request_id not in self._release_signals
        if opened_here:
            self._open_release(request_id)
        if self._is_released(request_id):
            if asyncio.iscoroutine(call):
                call.close()
            if opened_here:
                self._close_release(request_id)
            return ActuatorRun(ActuatorOutcome.RELEASED)
        released = self._release_signals[request_id][1]
        dispatch = asyncio.ensure_future(call)
        release_wait = asyncio.ensure_future(released.wait())
        try:
            done, _ = await asyncio.wait({dispatch, release_wait}, timeout=timeout_s,
                                         return_when=asyncio.FIRST_COMPLETED)
        finally:
            release_wait.cancel()
            if opened_here:
                self._close_release(request_id)
            if not dispatch.done():
                await self._abort(dispatch)
        if dispatch in done:
            return ActuatorRun(ActuatorOutcome.COMPLETED, dispatch.result())
        return ActuatorRun(ActuatorOutcome.RELEASED if released.is_set() else ActuatorOutcome.TIMED_OUT)

    async def _abort(self, dispatch: asyncio.Future) -> None:
        """Cancel the actuator call and wait at most ABORT_TIMEOUT_S for it to stop."""
        dispatch.cancel()
        await asyncio.wait({dispatch}, timeout=self.ABORT_TIMEOUT_S)
        if dispatch.done():
            if not dispatch.cancelled():
                dispatch.exception()  # retrieve so a late error is not reported as unhandled
            return
        log.error("%s: actuator call ignored cancellation for %.2f s; abandoning it",
                  type(self).__name__, self.ABORT_TIMEOUT_S)
        dispatch.add_done_callback(lambda fut: fut.cancelled() or fut.exception())

    def _signal_release(self, request_id: str) -> None:
        """
        Interrupt the in-flight actuator call of *request_id*, if there is one.
        Safe from any thread or event loop.
        """
        with self._release_lock:
            entry = self._release_signals.get(request_id)
            if entry is None:
                return
            self._released.add(request_id)
        loop, released = entry
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            released.set()
            return
        try:
            loop.call_soon_threadsafe(released.set)
        except RuntimeError:
            pass  # the owning loop already closed: the command has finished

    def _confirm(self, key: Hashable, value: Any) -> None:
        """Record *value* as what the actuator confirmed for *key*."""
        self._confirmed[key] = value

    async def _held(self, key: Hashable, read: Callable[[], Awaitable[Any]]) -> HeldValue:
        """
        The value the actuator holds for *key* after an interrupted command: the
        read-back, else the last confirmed value, else unknown (None). Never a
        requested or default value. The read-back is bounded by READBACK_TIMEOUT_S.
        """
        reading = asyncio.ensure_future(read())
        done, _ = await asyncio.wait({reading}, timeout=self.READBACK_TIMEOUT_S)
        if reading in done:
            try:
                value = reading.result()
            except ActuatorError as exc:
                return self._last_confirmed(key, f"read-back failed ({exc})")
            self._confirm(key, value)
            return HeldValue(value)
        await self._abort(reading)
        return self._last_confirmed(key, f"read-back exceeded {self.READBACK_TIMEOUT_S} s")

    def _last_confirmed(self, key: Hashable, problem: str) -> HeldValue:
        if key in self._confirmed:
            return HeldValue(self._confirmed[key], f"{problem}; reporting the last confirmed value")
        return HeldValue(None, f"{problem} and no value was ever confirmed; held value unknown")

    # ── Transfer-function model ───────────────────────────────────────────

    @property
    def system_model(self) -> Any | None:
        """The physics-based transfer-function model for this capability, or None."""
        return None

    def get_transfer_function_params(self) -> dict[str, Any]:
        """Return current transfer-function parameters for external consumers."""
        model = self.system_model
        if model is None:
            return {}
        return model.get_params()
