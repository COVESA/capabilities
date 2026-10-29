# ADR 0003 — Generated standards artifacts are checked in

- **Status:** Accepted
- **Date:** 2026-10-29

## Context

Two options for turning the pinned standards into something the code can read:

1. **Build at install/test time** from the submodules using `vss-tools` and the
   S2DM tooling.
2. **Generate once, check in**, and verify hashes.

`vss-tools` drags in a heavy dependency tree (pandas, rdflib, graphene) and the VDM
toolchain is still moving. Making the runtime depend on either would mean the
runnable example cannot start without a standards build.

## Decision

Generate the artifacts, **check them in** under `third_party/generated/`, and record
their SHA-256 in the lock file:

- `vss.json` — exported by `vspec` from the pinned submodule
- `vdm.graphql` — composed from the pinned VDM SDL

`capability-check`, the runtime VSS view, and the test suite read the checked-in
files. Regeneration is a deliberate, verifiable step (`make vendor`), and CI fails
if regeneration produces different bytes.

## Consequences

- **Good:** `pip install` + run works with Flask alone; no standards toolchain needed.
- **Good:** a standards bump produces a diffable artifact change.
- **Good:** the exported `vss.json` is byte-identical to the official v6.1 release,
  which makes "we generated it ourselves" checkable.
- **Cost:** artifacts must be regenerated (and reviewed) when a pin moves — enforced
  by `tests/test_standards_pins.py`.
