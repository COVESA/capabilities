# ADR 0001 — Pin VSS and VDM as git submodules

- **Status:** Accepted
- **Date:** 2026-10-29

## Context

The catalog claims alignment with two COVESA standards: the Vehicle Signal
Specification (VSS) and the Vehicle Data Model (VDM). Path strings in a descriptor
cannot prove that claim, and external drift silently invalidates it. We need
provenance (which standard release?), reproducibility (same artifacts everywhere),
and an auditable upgrade path.

## Decision

Vendor both standards as **git submodules**, pinned to an exact ref and commit:

| Standard | Ref | Why that pin |
|---|---|---|
| VSS | tag `v6.1` | a released, stable catalog; matches the pinned `vss-tools` |
| VDM | commit SHA | the project publishes no GitHub releases yet |

`third_party/standards.lock.json` records the ref, commit, license, and the SHA-256
of every generated artifact. `scripts/vendor_standards.sh` regenerates and verifies.
Tests fail if a submodule HEAD or artifact hash drifts from the lock file.

## Consequences

- **Good:** provenance is exact; upgrades are reviewable diffs; builds are offline.
- **Good:** the local VSS export is byte-identical to the official release artifact,
  so generation is verifiable rather than trusted.
- **Cost:** clones must initialize submodules (`bootstrap.sh` does this).
- **Cost:** VDM has no releases and no license file; the pin is a review gate, not a
  legal clearance — see `THIRD_PARTY_NOTICES.md`.
