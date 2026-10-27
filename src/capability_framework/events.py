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
capability_framework.events
===========================
Async pub/sub event bus shared by capabilities and callers.

Usage
-----
    bus = EventBus()

    async def on_state(payload):
        ...

    bus.subscribe(Topics.WINDOW_STATE, on_state)
    await bus.publish(Topics.WINDOW_STATE, payload)
    last = bus.last(Topics.WINDOW_STATE)   # None if never published
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Awaitable, Callable

__all__ = ["EventBus", "Subscriber", "Topics", "bus"]

log = logging.getLogger(__name__)

# Type alias for async subscriber callbacks.
Subscriber = Callable[[Any], Awaitable[None]]


class EventBus:
    """
    Lightweight async pub/sub bus.

    - Topics are plain strings (convention: snake_case matching the payload type).
    - Subscribers are async callables, invoked concurrently via ``asyncio.gather``.
    - The last published value per topic is cached for synchronous polling via ``last()``.
    - A subscriber that raises is logged, not propagated: one bad subscriber cannot
      break the publisher or its peers.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Subscriber]] = defaultdict(list)
        self._last: dict[str, Any] = {}

    # ── Subscription ──────────────────────────────────────────────────────

    def subscribe(self, topic: str, callback: Subscriber) -> None:
        """Register *callback* to receive every payload published on *topic*."""
        self._subscribers[topic].append(callback)

    def unsubscribe(self, topic: str, callback: Subscriber) -> None:
        """Remove a previously registered callback. Silent if not present."""
        try:
            self._subscribers[topic].remove(callback)
        except ValueError:
            pass

    # ── Publishing ────────────────────────────────────────────────────────

    async def publish(self, topic: str, payload: Any) -> None:
        """Cache *payload* as the latest value for *topic*, then notify subscribers."""
        self._last[topic] = payload
        subscribers = list(self._subscribers[topic])  # snapshot
        if not subscribers:
            return
        await asyncio.gather(*(self._safe_call(cb, payload) for cb in subscribers))

    # ── Polling ───────────────────────────────────────────────────────────

    def last(self, topic: str) -> Any | None:
        """Return the most-recently published payload for *topic*, or None."""
        return self._last.get(topic)

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    async def _safe_call(cb: Subscriber, payload: Any) -> None:
        try:
            await cb(payload)
        except Exception:  # noqa: BLE001
            log.exception("EventBus: unhandled exception in subscriber %s", cb)


# Module-level singleton shared by the whole process.
bus: EventBus = EventBus()


class Topics:
    """String constants for bus topics — avoids magic strings."""
    VEHICLE_STATE = "vehicle_state"
    WINDOW_STATE = "window_state"
