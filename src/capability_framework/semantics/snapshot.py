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
capability_framework.semantics.snapshot
=======================================
A live, VSS-shaped view of what the capabilities are doing.

Capabilities publish domain state on the event bus (``WindowState``). This module
projects those events onto VSS signal paths and keeps the latest value per
signal, quantized to the datatype and range the pinned standard declares.

Nothing is invented: a path that does not exist in the pinned VSS is refused, so
this doubles as a runtime check that the catalog's mapping is real.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .mapping import CapabilitySpec
from .units import quantize
from .vss import VssCatalog

__all__ = ["Projector", "VssSnapshot", "UnknownSignal"]

log = logging.getLogger(__name__)

#: Turns a capability event into ``{vss_path: value}``.
Projector = Callable[[Any], Mapping[str, Any]]


class UnknownSignal(KeyError):
    """Raised when a projection targets a path the pinned VSS does not define."""


@dataclass
class VssSnapshot:
    """The latest value of every VSS signal the attached capabilities project."""

    catalog: VssCatalog
    spec: CapabilitySpec
    version: str | None = None
    _values: dict[str, Any] = field(default_factory=dict, repr=False)
    _updated: dict[str, datetime] = field(default_factory=dict, repr=False)
    _extra_specs: list[CapabilitySpec] = field(default_factory=list, repr=False)

    def attach(self, spec: CapabilitySpec) -> None:
        """Record another capability whose projections share this snapshot."""
        if spec.name != self.spec.name and all(s.name != spec.name for s in self._extra_specs):
            self._extra_specs.append(spec)

    # ── writing ──────────────────────────────────────────────────────────

    def set(self, path: str, value: Any) -> Any:
        """Quantize and record *value* for *path*, validating the path first."""
        signal = self.catalog.get(path)
        if signal is None:
            raise UnknownSignal(f"{path!r} is not a signal in the pinned VSS")
        quantized = quantize(value, signal)
        self._values[path] = quantized
        self._updated[path] = datetime.now(timezone.utc)
        return quantized

    def update(self, values: Mapping[str, Any]) -> dict[str, Any]:
        """Record every mapping entry; returns what was actually stored."""
        return {path: self.set(path, value) for path, value in values.items()}

    # ── reading ──────────────────────────────────────────────────────────

    def value(self, path: str) -> Any | None:
        return self._values.get(path)

    def signal_view(self, path: str) -> dict[str, Any] | None:
        signal = self.catalog.get(path)
        if signal is None:
            return None
        updated = self._updated.get(path)
        return {
            "path": path,
            "value": self._values.get(path),
            "datatype": signal.datatype,
            "unit": signal.unit,
            "type": signal.type,
            "min": signal.minimum,
            "max": signal.maximum,
            "updated_at": updated.isoformat() if updated else None,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "standard": "vss",
            "version": self.version,
            "capability": self.spec.name,
            "api_version": self.spec.api_version,
            "capabilities": {
                spec.name: spec.api_version for spec in (self.spec, *self._extra_specs)
            },
            "signals": {
                path: self.signal_view(path) for path in sorted(self._values)
            },
        }

    # ── event bus wiring ─────────────────────────────────────────────────

    def handler(self, projector: Projector) -> Callable[[Any], Awaitable[None]]:
        """Build an async subscriber that projects events into this snapshot."""

        async def on_event(payload: Any) -> None:
            try:
                values = projector(payload)
            except Exception:  # noqa: BLE001 - a projection bug must not break publishing
                log.exception("%s: projection failed", self.spec.name)
                return
            self.update(values)

        return on_event
