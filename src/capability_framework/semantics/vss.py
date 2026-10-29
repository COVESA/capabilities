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
capability_framework.semantics.vss
==================================
An index over the pinned COVESA Vehicle Signal Specification.

The index is built from the generated ``third_party/generated/vss.json`` artifact
(exported by ``vspec`` from the pinned submodule), never from the ``.vspec``
sources at runtime. That keeps capability code fast and dependency-light while
still being provably tied to a specific, hashed VSS release.

Paths use VSS dot notation and no ``children`` segment:
``Vehicle.Cabin.Door.Row1.DriverSide.Window.Position``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Mapping

__all__ = ["VssCatalog", "VssPathError", "VssSignal"]

_CHILDREN = "children"


class VssPathError(KeyError):
    """Raised when a signal path does not exist in the pinned VSS."""


def _flatten_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


@dataclass(frozen=True)
class VssSignal:
    """One node of the VSS tree: a branch, or a leaf that carries a value."""

    path: str
    type: str = ""
    datatype: str | None = None
    unit: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    allowed: tuple[Any, ...] = ()
    default: Any = None
    description: str | None = None
    comment: str | None = None
    deprecated: bool = False

    @property
    def is_branch(self) -> bool:
        return self.datatype is None

    @property
    def is_actuator(self) -> bool:
        """An actuator is the only signal kind a capability may command."""
        return self.type == "actuator"

    @property
    def is_sensor(self) -> bool:
        return self.type == "sensor"

    def accepts(self, value: float) -> bool:
        """True if *value* is inside the declared VSS range."""
        if self.minimum is not None and value < self.minimum:
            return False
        if self.maximum is not None and value > self.maximum:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "type": self.type,
            "datatype": self.datatype,
            "unit": self.unit,
            "min": self.minimum,
            "max": self.maximum,
            "allowed": list(self.allowed),
            "description": self.description,
            "deprecated": self.deprecated,
        }


class VssCatalog:
    """Read-only index of every signal in a pinned VSS release."""

    def __init__(self, signals: Mapping[str, VssSignal]) -> None:
        self._signals: dict[str, VssSignal] = dict(signals)

    # ── construction ─────────────────────────────────────────────────────

    @classmethod
    def from_json(cls, path: str | Path) -> "VssCatalog":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    @classmethod
    def from_dict(cls, tree: Mapping[str, Any]) -> "VssCatalog":
        signals: dict[str, VssSignal] = {}
        for root, node in tree.items():
            if isinstance(node, dict):
                _walk(root, node, signals)
        return cls(signals)

    # ── queries ──────────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._signals)

    def __contains__(self, path: object) -> bool:
        return path in self._signals

    def __iter__(self) -> Iterator[VssSignal]:
        return iter(self._signals.values())

    def get(self, path: str) -> VssSignal | None:
        return self._signals.get(path)

    def require(self, path: str) -> VssSignal:
        try:
            return self._signals[path]
        except KeyError:
            raise VssPathError(f"{path!r} is not a signal in the pinned VSS") from None

    def children(self, path: str) -> list[VssSignal]:
        prefix = path + "."
        depth = path.count(".") + 1
        return [
            signal
            for candidate, signal in self._signals.items()
            if candidate.startswith(prefix) and candidate.count(".") == depth
        ]

    def search(self, text: str, *, limit: int = 25) -> list[VssSignal]:
        """Match signals containing every whitespace-separated token, in any order."""
        tokens = [token for token in text.lower().split() if token]
        hits = [
            signal
            for path, signal in self._signals.items()
            if all(
                token in path.lower() or token in (signal.description or "").lower()
                for token in tokens
            )
        ]
        hits.sort(key=lambda signal: (len(signal.path), signal.path))
        return hits[:limit]

    def subtree(self, path: str) -> list[VssSignal]:
        prefix = path + "."
        matches = [s for p, s in self._signals.items() if p == path or p.startswith(prefix)]
        return sorted(matches, key=lambda signal: signal.path)

    def expand(self, template: str, instance: str) -> str:
        """Expand a catalog template such as ``"{instance}.Position"``."""
        return template.replace("{instance}", instance)


def _walk(path: str, node: Mapping[str, Any], out: dict[str, VssSignal]) -> None:
    children = node.get(_CHILDREN) or {}
    out[path] = VssSignal(
        path=path,
        type=str(node.get("type") or ""),
        datatype=node.get("datatype"),
        unit=node.get("unit"),
        minimum=_flatten_number(node.get("min")),
        maximum=_flatten_number(node.get("max")),
        allowed=tuple(node.get("allowed") or ()),
        default=node.get("default"),
        description=node.get("description"),
        comment=node.get("comment"),
        deprecated=bool(node.get("deprecation")),
    )
    for name, child in children.items():
        if isinstance(child, dict):
            _walk(f"{path}.{name}", child, out)
