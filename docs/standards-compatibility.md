# Standards compatibility

Which framework version was validated against which standards.

| Framework | VSS | VSS commit | VDM commit | vss-tools | vss.json SHA-256 (first 12) |
|---|---|---|---|---|---|
| `0.1.0` (POC) | `v6.1` | `2817646d1808` | `36bc93936eab` | `6.1.0` | `bef9ad501b38` |

`third_party/standards.lock.json` is authoritative; this table is for humans.
A row is only added after `make standards` passes on a clean checkout.

## Version policy

| Artifact | Bump when |
|---|---|
| Framework minor | a capability is added, or a backward-compatible field appears |
| Framework major | a northbound API breaks, or a required mapping changes shape |
| Capability `api_version` major | request/response schema or behaviour breaks |
| Capability `api_version` minor | additive fields only |
| Standards pins | any minor framework release, provided `capability-check --strict` passes |

A standards bump that breaks a capability mapping is **not** a patch: it changes
what the capability means on the wire, so the capability's `api_version` moves too.

## Upgrade procedure

```bash
git submodule update --init --recursive
./scripts/bump_standards.sh v6.2                 # VSS only
./scripts/bump_standards.sh v6.2 36bc939         # VSS + VDM
```

The script updates the pins, regenerates artifacts, writes a `vspec diff` report
to `docs/upgrades/<date>-<ref>.md`, regenerates the VSS path constants, and runs
the rules and tests. It does not commit.

Review checklist:

- [ ] `git diff third_party/generated` shows only expected signal changes
- [ ] `docs/upgrades/*.md` has no *removed* signal we still map
- [ ] `capability-check --strict` is clean (or baselines are updated and justified)
- [ ] `gen_vss_paths.py --check` passes
- [ ] capability `api_version`s bumped where semantics changed
- [ ] `docs/standards-compatibility.md` row added

## Known constraints

- **VSS `Window.Position` is `uint8` percent.** The window API exposes a float.
  Quantization happens in `semantics.units`; out-of-range values raise rather than
  clamp silently.
- **VDM has no releases and no license file.** It is pinned by commit and treated
  as a review gate (see `THIRD_PARTY_NOTICES.md`).
- **VDM collapses instance dimensions.** `Window.position` projects
  `Vehicle.Cabin.Door.Window.Position`, not the `Row1.DriverSide` form. Comparisons
  normalize dimension segments first.
- **vss-tools pairing.** Use the version listed in the table; the VSS repo pins a
  compatible `vss-tools`, and newer/older versions may not read that catalog.
