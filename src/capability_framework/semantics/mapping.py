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
capability_framework.semantics.mapping
======================================
The capability catalog: one YAML file per capability, declaring what it does and
which COVESA standard elements it is grounded in.

A catalog entry names VSS **templates** (``"{instance}.Position"``) rather than
repeating a path per zone. The instance dimension comes from a named VSS branch
(e.g. ``Vehicle.Cabin.Door.Row1.DriverSide.Window``), so adding a row or a third
row is a data change, not a code change.

Optional ``vdm`` references let a capability anchor to the Vehicle Data Model.
Nothing here is trusted: ``capability_framework.checker`` resolves every
template, datatype, unit, range, and VDM reference against the pinned pins.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Mapping

import yaml

__all__ = [
    "CatalogError",
    "CapabilitySpec",
    "Operation",
    "SignalRef",
    "VdmRef",
    "load_capability",
    "load_catalog",
]


class CatalogError(ValueError):
    """Raised when a catalog entry is structurally unusable."""


@dataclass(frozen=True)
class VdmRef:
    """A pointer into the pinned VDM, e.g. ``Window.position``."""

    type_name: str
    field_name: str | None = None
    intent: str = "read"

    @property
    def label(self) -> str:
        return f"{self.type_name}.{self.field_name}" if self.field_name else self.type_name


@dataclass(frozen=True)
class SignalRef:
    """A capability's use of one VSS signal family."""

    id: str
    role: str
    template: str
    unit: str | None = None
    datatype: str | None = None
    vdm: VdmRef | None = None
    applies_to: tuple[str, ...] = ()

    def expand(self, instance: str) -> str:
        return self.template.replace("{instance}", instance)


@dataclass(frozen=True)
class Operation:
    """A northbound operation as declared in the catalog."""

    name: str
    description: str = ""
    command_type: str = "None"
    response_type: str = "None"
    is_async: bool = False
    requires_arbitration: bool = False
    transport: str = "http"
    preconditions: tuple[str, ...] = ()
    signals: tuple[str, ...] = ()
    verified_by: tuple[str, ...] = ()
    vdm: tuple[VdmRef, ...] = ()


@dataclass(frozen=True)
class CapabilitySpec:
    """One parsed catalog entry."""

    name: str
    display_name: str
    description: str
    domain: str
    api_version: str
    asil_tier: str
    state_topic: str
    contract: str
    source_path: Path
    capability_id: str = ""
    docs: str | None = None
    instances: Mapping[str, str] = field(default_factory=dict)
    signals: tuple[SignalRef, ...] = ()
    operations: tuple[Operation, ...] = ()
    vdm: Mapping[str, Any] = field(default_factory=dict)
    southbound_dependencies: tuple[str, ...] = ()
    requirements: tuple[Mapping[str, Any], ...] = ()

    # ── derived views ────────────────────────────────────────────────────

    def signal(self, signal_id: str) -> SignalRef | None:
        return next((s for s in self.signals if s.id == signal_id), None)

    def operation(self, name: str) -> Operation | None:
        return next((o for o in self.operations if o.name == name), None)

    def expanded_signals(self) -> Iterator[tuple[str, str, SignalRef]]:
        """Yield ``(instance, path, signal)`` for every concrete mapping."""
        for signal in self.signals:
            instances = (
                {k: self.instances[k] for k in signal.applies_to}
                if signal.applies_to
                else dict(self.instances)
            )
            for instance_name, base in instances.items():
                yield instance_name, signal.expand(base), signal

    def instance_tag_map(self) -> Mapping[str, Mapping[str, str]]:
        vdm = self.vdm or {}
        tag = vdm.get("instance_tag") or {}
        return tag.get("map") or {}

    def vdm_refs(self) -> Iterator[tuple[str, VdmRef]]:
        """Yield ``(context, ref)`` for every VDM reference in the entry."""
        for signal in self.signals:
            if signal.vdm:
                yield f"signal:{signal.id}", signal.vdm
        for op in self.operations:
            for ref in op.vdm:
                yield f"operation:{op.name}", ref
        tag_type = (self.vdm or {}).get("instance_tag", {}).get("type")
        if tag_type:
            yield "vdm.instance_tag", VdmRef(type_name=tag_type)


# ── loading ──────────────────────────────────────────────────────────────

_REQUIRED = ("capability", "display_name", "domain", "api_version", "asil_tier")


def load_capability(path: str | Path) -> CapabilitySpec:
    """Parse and structurally validate one catalog YAML file."""
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - malformed yaml
        raise CatalogError(f"{path}: invalid YAML: {exc}") from exc

    missing = [key for key in _REQUIRED if not raw.get(key)]
    if missing:
        raise CatalogError(f"{path}: missing required keys: {', '.join(missing)}")

    if not isinstance(raw.get("operations"), list) or not raw["operations"]:
        raise CatalogError(f"{path}: 'operations' must be a non-empty list")

    vss = raw.get("vss") or {}
    signals = tuple(_signal_ref(entry, path) for entry in (vss.get("signals") or ()))
    known = {signal.id for signal in signals}
    operations = tuple(_operation(entry, known, path) for entry in raw["operations"])

    return CapabilitySpec(
        name=str(raw["capability"]),
        display_name=str(raw["display_name"]),
        description=str(raw.get("description") or "").strip(),
        domain=str(raw["domain"]),
        api_version=str(raw["api_version"]),
        asil_tier=str(raw["asil_tier"]),
        state_topic=str(raw.get("state_topic") or ""),
        contract=str(raw.get("contract") or ""),
        source_path=path,
        capability_id=str(raw.get("id") or ""),
        docs=raw.get("docs"),
        instances={str(k): str(v) for k, v in (vss.get("instances") or {}).items()},
        signals=signals,
        operations=operations,
        vdm=raw.get("vdm") or {},
        southbound_dependencies=tuple(raw.get("southbound_dependencies") or ()),
        requirements=tuple(raw.get("requirements") or ()),
    )


def load_catalog(directory: str | Path) -> dict[str, CapabilitySpec]:
    """Load every ``*.yaml`` capability entry in *directory*, keyed by name."""
    directory = Path(directory)
    if not directory.is_dir():
        raise CatalogError(f"{directory} is not a directory")
    catalog: dict[str, CapabilitySpec] = {}
    for path in sorted(directory.glob("*.yaml")):
        spec = load_capability(path)
        if spec.name in catalog:
            raise CatalogError(f"duplicate capability {spec.name!r} in {path}")
        catalog[spec.name] = spec
    if not catalog:
        raise CatalogError(f"no capability entries found in {directory}")
    return catalog


def _signal_ref(entry: Mapping[str, Any], path: Path) -> SignalRef:
    signal_id = entry.get("id")
    template = entry.get("template")
    if not signal_id or not template:
        raise CatalogError(f"{path}: every vss.signal needs an 'id' and a 'template'")
    vdm_raw = entry.get("vdm")
    vdm = None
    if vdm_raw:
        vdm = VdmRef(
            type_name=str(vdm_raw["type"]),
            field_name=vdm_raw.get("field"),
            intent=str(vdm_raw.get("intent") or "read"),
        )
    return SignalRef(
        id=str(signal_id),
        role=str(entry.get("role") or "state"),
        template=str(template),
        unit=entry.get("unit"),
        datatype=entry.get("datatype"),
        vdm=vdm,
        applies_to=tuple(entry.get("applies_to") or ()),
    )


def _operation(entry: Mapping[str, Any], known: set[str], path: Path) -> Operation:
    name = entry.get("name")
    if not name:
        raise CatalogError(f"{path}: every operation needs a 'name'")
    signals = tuple(entry.get("signals") or ())
    unknown = [s for s in signals if s not in known]
    if unknown:
        raise CatalogError(
            f"{path}: operation {name!r} references undeclared signal(s): {', '.join(unknown)}"
        )
    return Operation(
        name=str(name),
        description=str(entry.get("description") or "").strip(),
        command_type=str(entry.get("command_type") or "None"),
        response_type=str(entry.get("response_type") or "None"),
        is_async=bool(entry.get("is_async")),
        requires_arbitration=bool(entry.get("requires_arbitration")),
        transport=str(entry.get("transport") or "http"),
        preconditions=tuple(entry.get("preconditions") or ()),
        signals=signals,
        verified_by=tuple(entry.get("verified_by") or ()),
        vdm=tuple(
            VdmRef(
                type_name=str(ref["type"]),
                field_name=ref.get("field"),
                intent=str(ref.get("intent") or "read"),
            )
            for ref in (entry.get("vdm") or ())
        ),
    )
