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
capability_framework.semantics.graph
====================================
A typed knowledge graph over the catalog, the northbound contract, the pinned VSS,
and the pinned VDM.

The graph answers the question the repo could not answer before: *what does this
capability actually mean, and in which standard is it grounded?* Every edge is
derived from a checked artifact, so the picture cannot disagree with the code.

Nodes and edges are sorted by id, so a snapshot diff is reviewable and two builds
of the same inputs are byte-identical.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

import yaml

from .mapping import CapabilitySpec, load_catalog
from .vdm import VdmSchema
from .vss import VssCatalog

__all__ = ["Graph", "GraphEdge", "GraphNode", "build_graph"]

#: Layer ordering used by the UI. Mechanical order, not importance.
LAYERS = ("capability", "contract", "vss", "vdm", "safety")


@dataclass(frozen=True)
class GraphNode:
    id: str
    type: str
    label: str
    layer: str
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "label": self.label,
            "layer": self.layer,
            "attributes": dict(self.attributes),
        }

    def sort_key(self) -> str:
        return self.id


@dataclass(frozen=True)
class GraphEdge:
    source: str
    relation: str
    target: str

    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "relation": self.relation, "target": self.target}

    def sort_key(self) -> tuple[str, str, str]:
        return (self.source, self.relation, self.target)


class Graph:
    """An immutable, deterministically ordered graph."""

    def __init__(self, nodes: Iterable[GraphNode], edges: Iterable[GraphEdge],
                 meta: Mapping[str, Any] | None = None) -> None:
        self._nodes = {node.id: node for node in nodes}
        self._edges = tuple(sorted(set(edges), key=GraphEdge.sort_key))
        self._meta = dict(meta or {})
        self._out: dict[str, list[GraphEdge]] = defaultdict(list)
        self._in: dict[str, list[GraphEdge]] = defaultdict(list)
        for edge in self._edges:
            self._out[edge.source].append(edge)
            self._in[edge.target].append(edge)

    # ── access ───────────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._nodes)

    def __contains__(self, node_id: object) -> bool:
        return node_id in self._nodes

    def node(self, node_id: str) -> GraphNode | None:
        return self._nodes.get(node_id)

    @property
    def nodes(self) -> tuple[GraphNode, ...]:
        return tuple(sorted(self._nodes.values(), key=GraphNode.sort_key))

    @property
    def edges(self) -> tuple[GraphEdge, ...]:
        return self._edges

    def neighbours(self, node_id: str) -> list[tuple[str, GraphEdge]]:
        """Every adjacent node and the edge joining them, in both directions."""
        out = [(edge.target, edge) for edge in self._out.get(node_id, ())]
        incoming = [(edge.source, edge) for edge in self._in.get(node_id, ())]
        return sorted(out + incoming, key=lambda item: (item[0], item[1].relation))

    # ── queries ──────────────────────────────────────────────────────────

    def by_layer(self, layer: str) -> list[GraphNode]:
        return [node for node in self.nodes if node.layer == layer]

    def by_type(self, node_type: str) -> list[GraphNode]:
        return [node for node in self.nodes if node.type == node_type]

    def count_by(self, key: str) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for node in self._nodes.values():
            counts[str(getattr(node, key))] += 1
        return dict(sorted(counts.items()))

    def search(self, text: str, *, limit: int = 30) -> list[GraphNode]:
        needle = text.lower()
        hits = [
            node for node in self._nodes.values()
            if needle in node.id.lower() or needle in node.label.lower()
        ]
        hits.sort(key=lambda node: (node.layer, len(node.id), node.id))
        return hits[:limit]

    def subgraph(self, root: str, *, depth: int = 1) -> "Graph":
        """The neighbourhood of *root* out to *depth* hops, in both directions."""
        if root not in self._nodes:
            return Graph((), (), {"root": root, "missing": True})
        seen = {root}
        queue: deque[tuple[str, int]] = deque([(root, 0)])
        while queue:
            current, level = queue.popleft()
            if level >= depth:
                continue
            for neighbour, _ in self.neighbours(current):
                if neighbour not in seen:
                    seen.add(neighbour)
                    queue.append((neighbour, level + 1))
        nodes = [self._nodes[node_id] for node_id in seen]
        edges = [edge for edge in self._edges if edge.source in seen and edge.target in seen]
        return Graph(nodes, edges, {**self._meta, "root": root, "depth": depth})

    # ── output ───────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "meta": {
                **self._meta,
                "nodes": len(self._nodes),
                "edges": len(self._edges),
                "layers": list(LAYERS),
            },
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self._edges],
        }


# ── construction ─────────────────────────────────────────────────────────

def build_graph(
    *,
    catalog: Mapping[str, CapabilitySpec] | str | Path,
    vss: VssCatalog,
    vdm: VdmSchema,
    contracts_dir: str | Path,
    vss_version: str | None = None,
) -> Graph:
    """Build the graph from checked artifacts."""
    specs = load_catalog(catalog) if isinstance(catalog, (str, Path)) else dict(catalog)
    contracts = Path(contracts_dir)

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    # VDM fields that project a VSS signal, keyed by normalized VSS path.
    vdm_by_signal: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for vdm_type in vdm:
        for vdm_field in vdm_type.fields:
            if vdm_field.vspec_fqn:
                vdm_by_signal[vdm.normalize_vss_path(vdm_field.vspec_fqn)].append(
                    (vdm_type.name, vdm_field.name)
                )

    for name in sorted(specs):
        spec = specs[name]
        cap_id = f"cap:{name}"
        nodes.append(GraphNode(
            id=cap_id, type="Capability", label=spec.display_name, layer="capability",
            attributes={
                "domain": spec.domain,
                "api_version": spec.api_version,
                "asil_tier": spec.asil_tier,
                "state_topic": spec.state_topic,
                "capability_id": spec.capability_id,
                "source": str(spec.source_path.name),
            },
        ))

        # Operations + their signals
        for operation in spec.operations:
            op_id = f"op:{name}.{operation.name}"
            nodes.append(GraphNode(
                id=op_id, type="Operation", label=operation.name, layer="capability",
                attributes={
                    "transport": operation.transport,
                    "is_async": operation.is_async,
                    "arbitrated": operation.requires_arbitration,
                    "command": operation.command_type,
                    "response": operation.response_type,
                },
            ))
            edges.append(GraphEdge(cap_id, "PROVIDES", op_id))

            for signal_id in operation.signals:
                signal = spec.signal(signal_id)
                if signal is None:
                    continue
                role = signal.role
                for instance, path, expanded in spec.expanded_signals():
                    if expanded.id != signal_id:
                        continue
                    signal_node = _signal_node(path, vss, nodes)
                    relation = "COMMANDS" if role == "command" else "OBSERVES"
                    edges.append(GraphEdge(op_id, relation, signal_node.id))
                    if role == "command":
                        edges.append(GraphEdge(cap_id, "COMMANDS", signal_node.id))
                    for type_name, field_name in vdm_by_signal.get(
                        vdm.normalize_vss_path(path), ()
                    ):
                        field_id = f"vdm:{type_name}.{field_name}"
                        _vdm_field_node(field_id, type_name, field_name, vdm, nodes)
                        edges.append(GraphEdge(signal_node.id, "PROJECTS_TO", field_id))

        # Southbound dependencies
        for dependency in spec.southbound_dependencies:
            port_id = f"port:{name}.{dependency}"
            nodes.append(GraphNode(
                id=port_id, type="SouthboundPort", label=dependency, layer="capability",
            ))
            edges.append(GraphEdge(cap_id, "REQUIRES", port_id))

        # Contract + schemas
        if spec.contract:
            contract_id = f"contract:{Path(spec.contract).stem}"
            contract_path = contracts / Path(spec.contract).name
            schemas = _contract_schemas(contract_path)
            nodes.append(GraphNode(
                id=contract_id, type="Contract", label=Path(spec.contract).name,
                layer="contract",
                attributes={"schemas": len(schemas), "api_version": spec.api_version},
            ))
            edges.append(GraphEdge(cap_id, "HAS_CONTRACT", contract_id))
            for schema_name in schemas:
                schema_id = f"schema:{schema_name}"
                nodes.append(GraphNode(
                    id=schema_id, type="Schema", label=schema_name, layer="contract",
                ))
                edges.append(GraphEdge(contract_id, "HAS_SCHEMA", schema_id))

        # Requirements + verification
        for requirement in spec.requirements:
            req_id = f"req:{requirement.get('id')}"
            nodes.append(GraphNode(
                id=req_id, type="Requirement", label=str(requirement.get("id")), layer="safety",
                attributes={"statement": " ".join(str(requirement.get("statement", "")).split())},
            ))
            edges.append(GraphEdge(cap_id, "HAS_REQUIREMENT", req_id))
            for test_name in requirement.get("verified_by") or ():
                test_id = f"test:{test_name}"
                nodes.append(GraphNode(
                    id=test_id, type="TestCase", label=test_name, layer="safety",
                ))
                edges.append(GraphEdge(req_id, "VERIFIED_BY", test_id))

        for operation in spec.operations:
            for test_name in operation.verified_by:
                test_id = f"test:{test_name}"
                nodes.append(GraphNode(
                    id=test_id, type="TestCase", label=test_name, layer="safety",
                ))
                edges.append(GraphEdge(f"op:{name}.{operation.name}", "VERIFIED_BY", test_id))

        # VDM anchors declared by the capability
        for _context, ref in spec.vdm_refs():
            if not vdm.has_type(ref.type_name):
                continue
            if ref.field_name:
                field_id = f"vdm:{ref.type_name}.{ref.field_name}"
                _vdm_field_node(field_id, ref.type_name, ref.field_name, vdm, nodes)
                edges.append(GraphEdge(cap_id, "ANCHORS", field_id))
            else:
                type_id = f"vdm:{ref.type_name}"
                vdm_type = vdm.get(ref.type_name)
                nodes.append(GraphNode(
                    id=type_id, type="VdmType", label=ref.type_name, layer="vdm",
                    attributes={"vspec_fqn": vdm_type.vspec_fqn if vdm_type else None},
                ))
                edges.append(GraphEdge(cap_id, "ANCHORS", type_id))

    return Graph(nodes, edges, {
        "standards": {"vss": vss_version, "vdm": "pinned"},
        "capabilities": sorted(specs),
    })


def _signal_node(path: str, vss: VssCatalog, nodes: list[GraphNode]) -> GraphNode:
    node_id = f"vss:{path}"
    if any(node.id == node_id for node in nodes):
        return GraphNode(id=node_id, type="VssSignal", label=path, layer="vss")
    signal = vss.get(path)
    node = GraphNode(
        id=node_id, type="VssSignal", label=path.rsplit(".", 1)[-1], layer="vss",
        attributes={
            "path": path,
            "datatype": signal.datatype if signal else None,
            "unit": signal.unit if signal else None,
            "signal_type": signal.type if signal else None,
            "min": signal.minimum if signal else None,
            "max": signal.maximum if signal else None,
        },
    )
    nodes.append(node)
    return node


def _vdm_field_node(
    field_id: str, type_name: str, field_name: str, vdm: VdmSchema, nodes: list[GraphNode]
) -> None:
    if any(node.id == field_id for node in nodes):
        return
    vdm_field = vdm.field(type_name, field_name)
    nodes.append(GraphNode(
        id=field_id, type="VdmField", label=f"{type_name}.{field_name}", layer="vdm",
        attributes={
            "returns": vdm_field.returns if vdm_field else None,
            "vspec_fqn": vdm_field.vspec_fqn if vdm_field else None,
        },
    ))


def _contract_schemas(contract_path: Path) -> list[str]:
    if not contract_path.is_file():
        return []
    try:
        document = yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return []
    return sorted((document.get("components") or {}).get("schemas") or {})
