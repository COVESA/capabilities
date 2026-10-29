# ADR 0002 — The catalog YAML is the source of truth

- **Status:** Accepted
- **Date:** 2026-10-29

## Context

Capability metadata currently lives in three places that can disagree: Python
`CapabilityDescriptor` objects, `docs/api-catalog.yaml`, and the explorer's
hard-coded window view. Standards mappings were only strings inside those.

## Decision

`catalog/capabilities/<name>.yaml` is canonical. Everything else is derived or
validated:

| Artifact | Relationship |
|---|---|
| `docs/api-catalog.yaml` | generated/exported from the registry |
| runtime descriptor | built from the entry |
| `capability_framework.semantics.vss_paths` | generated from the entry + pinned VSS |
| `capability-check` | validates the entry against contracts and standards |

The entry uses **templates** (`"{instance}.Position"`) plus an `instances` map
rather than repeating a path per zone. Adding a third row or a fourth door is a
data change.

## Consequences

- **Good:** the reviewable artifact is data, not code.
- **Good:** a path typo cannot be introduced by a developer "just writing the
  string" — it is expanded and resolved against the standard.
- **Cost:** the Python descriptor must be kept derived (a later phase generates it);
  until then the checker catches divergence in names and operations.
