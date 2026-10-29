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
capability_framework.semantics.vdm
==================================
A read-only view over the pinned COVESA Vehicle Data Model.

VDM is authored with S2DM as GraphQL SDL; SDL here is a *schema description*,
not a running GraphQL endpoint. The composed document
(``third_party/generated/vdm.graphql``) is parsed once and indexed, so a
capability can point at a VDM type/field and have that reference verified.

VDM's ``spec/vss`` projection is what makes the two standards joinable: its
types carry ``@vspec(fqn: "Vehicle....")`` annotations, so a capability can map
one behaviour to both a VSS signal and a VDM field and prove they agree.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from graphql import GraphQLEnumType, GraphQLObjectType, GraphQLSchema, build_schema

__all__ = ["VdmField", "VdmSchema", "VdmType"]

_NUMERIC = re.compile(r"^-?\d+(\.\d+)?$")


@dataclass(frozen=True)
class VdmField:
    """A field of a VDM type, with any VSS annotation it carries."""

    name: str
    type_name: str
    returns: str
    args: tuple[str, ...] = ()
    vspec_fqn: str | None = None
    vspec_element: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    description: str | None = None

    @property
    def vss_path(self) -> str | None:
        """The VSS path this field projects onto, if it declares one."""
        return self.vspec_fqn


@dataclass(frozen=True)
class VdmType:
    """A VDM object type or enum."""

    name: str
    kind: str
    vspec_fqn: str | None = None
    vspec_element: str | None = None
    description: str | None = None
    is_instance_tag: bool = False
    fields: tuple[VdmField, ...] = ()
    values: tuple[str, ...] = ()

    def field(self, name: str) -> VdmField | None:
        return next((f for f in self.fields if f.name == name), None)


class VdmSchema:
    """An indexed, read-only view of the composed VDM SDL document."""

    def __init__(self, schema: GraphQLSchema) -> None:
        self._schema = schema
        self._types: dict[str, VdmType] = {}
        self._by_fqn: dict[str, list[tuple[str, str | None]]] = {}
        for name, graphql_type in schema.type_map.items():
            if name.startswith("__"):
                continue
            vdm_type = _to_vdm_type(graphql_type)
            if vdm_type is None:
                continue
            self._types[name] = vdm_type
            if vdm_type.vspec_fqn:
                self._by_fqn.setdefault(vdm_type.vspec_fqn, []).append((name, None))
            for field in vdm_type.fields:
                if field.vspec_fqn:
                    self._by_fqn.setdefault(field.vspec_fqn, []).append((name, field.name))

    # ── construction ─────────────────────────────────────────────────────

    @classmethod
    def from_sdl_file(cls, path: str | Path) -> "VdmSchema":
        return cls(build_schema(Path(path).read_text(encoding="utf-8")))

    @classmethod
    def from_sdl(cls, sdl: str) -> "VdmSchema":
        return cls(build_schema(sdl))

    # ── queries ──────────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._types)

    def __contains__(self, name: object) -> bool:
        return name in self._types

    def __iter__(self) -> Iterator[VdmType]:
        return iter(self._types.values())

    def get(self, name: str) -> VdmType | None:
        return self._types.get(name)

    def has_type(self, name: str) -> bool:
        return name in self._types

    def fields(self, type_name: str) -> tuple[VdmField, ...]:
        vdm_type = self._types.get(type_name)
        return vdm_type.fields if vdm_type else ()

    def field(self, type_name: str, field_name: str) -> VdmField | None:
        vdm_type = self._types.get(type_name)
        return vdm_type.field(field_name) if vdm_type else None

    def enum_values(self, type_name: str) -> tuple[str, ...]:
        vdm_type = self._types.get(type_name)
        return vdm_type.values if vdm_type else ()

    @property
    def instance_dimension_segments(self) -> frozenset[str]:
        """Original VSS segment names used as instance dimensions (Row1, DriverSide, ...).

        VDM projects VSS branches with their instance dimensions *collapsed*, and
        re-expresses them as ``@instanceTag`` enums. Any comparison between a
        concrete VSS path and a VDM ``@vspec(fqn:)`` must therefore drop these
        segments first.
        """
        if not hasattr(self, "_dimension_segments"):
            segments: set[str] = set()
            for name, graphql_type in self._schema.type_map.items():
                if not isinstance(graphql_type, GraphQLEnumType) or "_Dimension" not in name:
                    continue
                for value in graphql_type.values.values():
                    original = _arg(_directive(value.ast_node, "vspec"), "originalName")
                    segments.add(str(original or value.name))
            self._dimension_segments = frozenset(segments)
        return self._dimension_segments

    def normalize_vss_path(self, path: str) -> str:
        """Drop instance-dimension segments so a VSS path matches a VDM fqn."""
        segments = self.instance_dimension_segments
        return ".".join(part for part in path.split(".") if part not in segments)

    def lookup_vss_path(self, vss_path: str) -> list[tuple[str, str | None]]:
        """VDM (type, field) pairs annotated with *vss_path*. Field is None for a type."""
        return self._by_fqn.get(vss_path, [])

    def search(self, text: str, *, limit: int = 25) -> list[VdmType]:
        needle = text.lower()
        hits = [
            vdm_type
            for vdm_type in self._types.values()
            if needle in vdm_type.name.lower()
            or needle in (vdm_type.description or "").lower()
            or any(needle in f.name.lower() for f in vdm_type.fields)
        ]
        hits.sort(key=lambda vdm_type: vdm_type.name)
        return hits[:limit]

    def to_dict(self) -> dict[str, Any]:
        return {
            "types": [
                {
                    "name": t.name,
                    "kind": t.kind,
                    "vspec_fqn": t.vspec_fqn,
                    "is_instance_tag": t.is_instance_tag,
                    "fields": [
                        {"name": f.name, "returns": f.returns, "vspec_fqn": f.vspec_fqn}
                        for f in t.fields
                    ],
                    "values": list(t.values),
                }
                for t in sorted(self._types.values(), key=lambda t: t.name)
            ]
        }


def _directive(node: Any, name: str) -> Any:
    for item in getattr(node, "directives", ()) or ():
        if item.name.value == name:
            return item
    return None


def _arg(directive: Any, name: str) -> Any:
    if directive is None:
        return None
    for arg in directive.arguments:
        if arg.name.value == name:
            value = getattr(arg.value, "value", None)
            # graphql-core keeps IntValue/FloatValue as strings; @range needs numbers.
            if isinstance(value, str) and _NUMERIC.match(value):
                return float(value) if "." in value else int(value)
            return value
    return None


def _to_vdm_type(graphql_type: Any) -> VdmType | None:
    if isinstance(graphql_type, GraphQLObjectType):
        annotation = _directive(graphql_type.ast_node, "vspec")
        fields = tuple(
            VdmField(
                name=name,
                type_name=graphql_type.name,
                returns=str(field.type),
                args=tuple(field.args),
                vspec_fqn=_arg(_directive(field.ast_node, "vspec"), "fqn"),
                vspec_element=_arg(_directive(field.ast_node, "vspec"), "element"),
                minimum=_arg(_directive(field.ast_node, "range"), "min"),
                maximum=_arg(_directive(field.ast_node, "range"), "max"),
                description=field.description,
            )
            for name, field in graphql_type.fields.items()
        )
        return VdmType(
            name=graphql_type.name,
            kind="object",
            vspec_fqn=_arg(annotation, "fqn"),
            vspec_element=_arg(annotation, "element"),
            description=graphql_type.description,
            is_instance_tag=_directive(graphql_type.ast_node, "instanceTag") is not None,
            fields=fields,
        )
    if isinstance(graphql_type, GraphQLEnumType):
        annotation = _directive(graphql_type.ast_node, "vspec")
        return VdmType(
            name=graphql_type.name,
            kind="enum",
            vspec_fqn=_arg(annotation, "fqn"),
            vspec_element=_arg(annotation, "element"),
            description=graphql_type.description,
            values=tuple(graphql_type.values),
        )
    return None
