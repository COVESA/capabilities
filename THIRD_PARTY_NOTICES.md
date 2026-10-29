# Third-party notices

This repository vendors two COVESA standards as git submodules and checks in
artifacts generated from them. Neither is part of the Apache-2.0 licensed
`capability-framework` source; they remain under their own terms.

## COVESA Vehicle Signal Specification (VSS)

- Repository: <https://github.com/COVESA/vehicle_signal_specification>
- Pinned: tag `v6.1`, commit `2817646d1808fc7c470c0432fc7f4ed685e5c9e3`
- License: **Mozilla Public License 2.0 (MPL-2.0)** — confirmed from the
  `LICENSE` file at the pinned ref
- Location: `third_party/vss/` (submodule)
- Generated: `third_party/generated/vss.json`, produced by `vss-tools` from the
  pinned sources. The output is byte-identical to the official `vss.json` release
  artifact for v6.1.

MPL-2.0 is file-level copyleft. The generated JSON is data derived from the
specification; keeping the submodule and the generated artifact unmodified and
attributed here is the intended usage.

## COVESA Vehicle Data Model (VDM)

- Repository: <https://github.com/COVESA/vdm>
- Pinned: commit `36bc93936eab097647b52eea377a3374bcf926f5` (no releases exist)
- License: **UNRESOLVED.** No `LICENSE` file was found in the repository root at
  the pinned commit.
- Location: `third_party/vdm/` (submodule)
- Generated: `third_party/generated/vdm.graphql` (concatenated SDL)

**Action required before redistribution:** confirm VDM licensing with COVESA.
Until then, treat the VDM pin as a review gate: it is used for validation and
visualization in this reference project, and is not relicensed by inclusion.

## Tooling used for generation (not vendored)

- `vss-tools` 6.1.0 — MPL-2.0, installed into the dev environment only. Its
  license does not affect this project's source code.

## QUDT units

VSS and VDM derive unit definitions from the QUDT reference model
(<https://qudt.org>), © QUDT.org, licensed CC BY 4.0. Unit names and symbols
appear in the generated artifacts via the pinned sources and are attributed here.
