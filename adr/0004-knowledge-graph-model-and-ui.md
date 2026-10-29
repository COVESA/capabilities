# ADR 0004 — Knowledge graph model and text-first UI

- **Status:** Accepted
- **Date:** 2026-10-29

## Context

The catalog, the OpenAPI contract, VSS, and VDM each hold part of the answer to
"what does this capability do?". They were readable individually and unrelated in
practice. A diagram that is hand-drawn would go stale immediately, and a
JavaScript graph library would add a build step and an offline-hostile CDN for a
reference project whose main output is a JSON model.

## Decision

1. **The model is the product.** `semantics/graph.py` builds a typed graph from
   checked artifacts only: catalog entries, contract schemas, the pinned VSS index,
   the pinned VDM schema, requirements, and test names.
2. **Deterministic by construction.** Nodes sorted by id, edges by
   `(source, relation, target)`, duplicates removed. Two builds from the same inputs
   are byte-identical, so a graph export can be reviewed as a diff.
3. **Text-first UI.** `/vehicle/graph/` is a searchable, layer-grouped node list plus
   a neighbour table. It works with keyboard and screen readers and needs no layout
   engine. A canvas view is a later enhancement, not a dependency.
4. **Stdlib rendering.** A small `scripts/export_graph.py` emits JSON and a Mermaid
   flowchart per capability for docs — no third-party graph library.

## Consequences

- **Good:** the graph cannot disagree with the code; it is derived from the same
  artifacts the checker validates.
- **Good:** offline, accessible, reviewable, and cheap to test (determinism is
  asserted, not assumed).
- **Cost:** no force-directed layout, so very large catalogs will need the search
  and depth limit rather than a "zoom out". That is acceptable: the graph's job is
  drill-down, not overview art.
- **Revisit:** if a visual canvas is added, vendor the library and keep the text
  view as the accessible baseline.
