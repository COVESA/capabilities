# Capability rules

`capability-check` proves a capability catalog entry against the pinned COVESA
standards and its own northbound contract. It is meant to run before review, in
CI, and in a pre-commit hook — the point is that a capability cannot be added by
asserting that it is grounded.

```bash
make check                                        # text report, strict
capability-check --format json                    # machine-readable
capability-check --format junit > report.xml      # CI consumption
capability-check --only window                    # one capability
capability-check --baseline path/to/baseline.yaml # exemptions
```

Exit codes: `0` clean, `1` findings (warnings too, under `--strict`), `2` usage
or missing artifacts.

## Severity

- **error** — the catalog contradicts a pinned standard or its contract. Fix it.
- **warning** — a gap that will become an error. `--strict` fails on these.

## Families

### CAP-0xx — catalog structure

| Rule | Checks |
|---|---|
| CAP-010 | `api_version` is SemVer |
| CAP-011 | `domain` is in the taxonomy |
| CAP-012 | `asil_tier` is a valid tier |
| CAP-013 | a contract is declared and the file exists |
| CAP-014 | the docs file exists *(warning)* |
| CAP-015 | the capability id is a `urn:capability:` URI *(warning)* |
| CAP-016 | a `state_topic` is declared *(warning)* |
| CAP-017 | operation names are unique |

### CAP-1xx — contract agreement

| Rule | Checks |
|---|---|
| CAP-020 | the contract is valid YAML |
| CAP-021 | `info.version` equals the catalog `api_version` |
| CAP-022 | every HTTP operation has an `operationId` in the contract |
| CAP-023 | a contract `operationId` has no catalog operation *(warning)* |
| CAP-024 | the contract is an OpenAPI document |

Operations with `transport: in-process` are Python-level APIs and are exempt from
CAP-022/023. Declaring the transport is how the catalog tells the truth about
what is actually reachable over HTTP.

### CAP-2xx — VSS grounding

| Rule | Checks |
|---|---|
| CAP-030 / 031 | instances and signals are declared |
| CAP-032 | every instance base is a branch in the pinned VSS |
| CAP-033 | every expanded template path exists in the pinned VSS |
| CAP-034 | declared datatype matches the standard |
| CAP-035 | declared unit matches the standard |
| CAP-036 | a `command`-role signal is a VSS `actuator` |
| CAP-037 | a `state`-role signal is not a branch |
| CAP-038 | the signal is not deprecated *(warning)* |
| CAP-039 | a declared signal is referenced by an operation *(warning)* |

### CAP-3xx — VDM grounding

| Rule | Checks |
|---|---|
| CAP-340 / 341 | the referenced VDM type / field exists |
| CAP-342 | the VDM field's `@vspec(fqn)` agrees with the VSS mapping, after instance-dimension normalization |
| CAP-343 | declared VDM types exist |
| CAP-344 – 348 | instance-tag type, `@instanceTag` annotation, dimensions, and enum values |
| CAP-349 | every VSS instance has a VDM instance-tag mapping *(warning)* |

**Normalization matters.** VDM projects VSS branches with instance dimensions
collapsed: `Window.position` maps to `Vehicle.Cabin.Door.Window.Position`, while
the concrete window in `Row1.DriverSide` is
`Vehicle.Cabin.Door.Row1.DriverSide.Window.Position`. CAP-342 removes the
dimension segments (from VDM's own `Door_InstanceTag_Dimension*` enums) before
comparing, so the abstract and concrete views are reconciled rather than fudged.

### CAP-4xx — the boundary

| Rule | Checks |
|---|---|
| CAP-410 | the northbound contract contains no bus id, transport name, or ECU/supplier reference |
| CAP-411 | a capability that commands hardware names a southbound dependency |
| CAP-412 | southbound dependencies are snake_case operation names |
| CAP-413 | instance names do not embed numeric hardware slots *(warning)* |

Transport and ECU names are matched **case-sensitively**: lowercase "can" is
ordinary English (`/window/can-execute`), and a rule that flags prose is a rule
people switch off.

### CAP-5xx — safety and requirements

| Rule | Checks |
|---|---|
| CAP-510 | a non-QM capability declares requirements |
| CAP-511 | requirement ids match `REQ-<AREA>-<NNN>` and are unique |
| CAP-512 | each requirement has a statement |
| CAP-513 | each requirement names a verifying test *(warning)* |
| CAP-514 | an operation that commands hardware declares arbitration or preconditions *(warning)* |

### CAP-6xx — verification coverage

| Rule | Checks |
|---|---|
| CAP-610 | an exposed operation declares `verified_by` *(warning)* |
| CAP-611 | every `verified_by` on an operation names an existing test |
| CAP-612 | every requirement's `verified_by` names an existing test |
| CAP-620 | the test directory was found *(warning)* |

Test names are resolved by scanning `tests/**/test_*.py` for `def test_*`, so a
renamed test breaks the trace instead of quietly orphaning a requirement.

### CAP-900 — expired exemption

A baseline entry past its `expires` date no longer suppresses the finding and is
itself reported as an error.

## Baselines

`src/capability_framework/checker/baseline.yaml` holds exemptions. Every entry
requires `rule`, `capability`, `reason`, `owner`, and `expires`; anything less is
rejected when the file is loaded.

```yaml
entries:
  - rule: CAP-610
    capability: window
    location: operations.getWindowSystemModel
    reason: introspection test lands with the explorer rewrite
    owner: body-domain
    expires: 2026-12-31
```

## Adding a rule

1. Add the function to `checker/rules.py` returning `Finding`s.
2. Use the next free id in the correct family.
3. Call it from `run_checks` in `checker/engine.py`.
4. Add a positive test and a negative test in `tests/test_capability_rules.py`.
5. Add a row to the table above.
