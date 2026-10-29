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
capability_framework.checker.rules
==================================
Individual rules. Each rule is a pure function of the check context and returns
findings; none of them mutate state or touch the network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

import yaml

if TYPE_CHECKING:  # pragma: no cover
    from ..semantics import CapabilitySpec, VdmSchema, VssCatalog

__all__ = [
    "ASIL_TIERS",
    "DOMAINS",
    "Finding",
    "REQUIREMENT_ID",
    "Severity",
    "boundary_rules",
    "catalog_rules",
    "contract_rules",
    "safety_rules",
    "test_rules",
    "vdm_rules",
    "vss_rules",
]

DOMAINS = {
    "body", "chassis", "powertrain", "adas", "infotainment", "connectivity", "thermal",
}
ASIL_TIERS = {"QM", "ASIL_A", "ASIL_B", "ASIL_C", "ASIL_D"}
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: Severity
    capability: str
    location: str
    message: str
    hint: str | None = None

    def sort_key(self) -> tuple[str, str, str]:
        return (self.capability, self.rule_id, self.location)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule_id,
            "severity": self.severity.value,
            "capability": self.capability,
            "location": self.location,
            "message": self.message,
            "hint": self.hint,
        }


def _error(rule: str, spec: "CapabilitySpec", location: str, message: str, hint: str | None = None) -> Finding:
    return Finding(rule, Severity.ERROR, spec.name, location, message, hint)


def _warn(rule: str, spec: "CapabilitySpec", location: str, message: str, hint: str | None = None) -> Finding:
    return Finding(rule, Severity.WARNING, spec.name, location, message, hint)


# ── CAP-0xx: catalog structure ───────────────────────────────────────────

def catalog_rules(spec: "CapabilitySpec", *, contracts_dir: Path, repo_root: Path) -> list[Finding]:
    findings: list[Finding] = []
    where = spec.source_path.name

    if not SEMVER.match(spec.api_version):
        findings.append(
            _error("CAP-010", spec, where, f"api_version {spec.api_version!r} is not SemVer", "use MAJOR.MINOR.PATCH")
        )

    if spec.domain not in DOMAINS:
        findings.append(
            _error("CAP-011", spec, where, f"domain {spec.domain!r} is not in the taxonomy",
                   f"one of: {', '.join(sorted(DOMAINS))}")
        )

    if spec.asil_tier not in ASIL_TIERS:
        findings.append(
            _error("CAP-012", spec, where, f"asil_tier {spec.asil_tier!r} is not valid",
                   f"one of: {', '.join(sorted(ASIL_TIERS))}")
        )

    if not spec.contract:
        findings.append(_error("CAP-013", spec, where, "no northbound contract declared"))
    elif not (contracts_dir / Path(spec.contract).name).is_file():
        findings.append(
            _error("CAP-013", spec, spec.contract, "contract file does not exist", "add the OpenAPI contract")
        )

    if spec.docs and not (repo_root / spec.docs).is_file():
        findings.append(_warn("CAP-014", spec, spec.docs, "documentation file does not exist"))

    if not spec.capability_id.startswith("urn:capability:"):
        findings.append(
            _warn("CAP-015", spec, where, "capability id should be a urn:capability: URI")
        )

    if not spec.state_topic:
        findings.append(_warn("CAP-016", spec, where, "no state_topic declared; callers cannot subscribe"))

    names = [op.name for op in spec.operations]
    duplicates = {name for name in names if names.count(name) > 1}
    for name in sorted(duplicates):
        findings.append(_error("CAP-017", spec, f"operations.{name}", "operation declared more than once"))

    return findings


# ── CAP-1xx: contract agreement ──────────────────────────────────────────

def contract_rules(spec: "CapabilitySpec", *, contracts_dir: Path) -> list[Finding]:
    findings: list[Finding] = []
    if not spec.contract:
        return findings

    path = contracts_dir / Path(spec.contract).name
    if not path.is_file():
        return findings

    try:
        contract = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return [_error("CAP-020", spec, spec.contract, f"contract is not valid YAML: {exc}")]

    info = contract.get("info") or {}
    if str(info.get("version")) != spec.api_version:
        findings.append(
            _error("CAP-021", spec, spec.contract,
                   f"contract version {info.get('version')!r} != catalog api_version {spec.api_version!r}")
        )

    operation_ids = {
        str(op.get("operationId"))
        for path_item in (contract.get("paths") or {}).values()
        if isinstance(path_item, dict)
        for op in path_item.values()
        if isinstance(op, dict) and op.get("operationId")
    }

    for op in spec.operations:
        if getattr(op, "transport", "http") != "http":
            continue
        if op.name not in operation_ids:
            findings.append(
                _error("CAP-022", spec, f"operations.{op.name}",
                       "no matching operationId in the contract",
                       "callers discover operations from the contract")
            )

    for operation_id in sorted(operation_ids):
        if operation_id not in {op.name for op in spec.operations}:
            findings.append(
                _warn("CAP-023", spec, f"contract.{operation_id}",
                      "contract exposes an operation the catalog does not declare")
            )

    if not contract.get("openapi"):
        findings.append(_error("CAP-024", spec, spec.contract, "not an OpenAPI document (no `openapi` key)"))

    return findings


# ── CAP-2xx: VSS grounding ───────────────────────────────────────────────

def vss_rules(spec: "CapabilitySpec", *, vss: "VssCatalog") -> list[Finding]:
    findings: list[Finding] = []

    if not spec.instances:
        findings.append(_error("CAP-030", spec, "vss.instances", "no VSS instances declared"))
    if not spec.signals:
        findings.append(_error("CAP-031", spec, "vss.signals", "no VSS signals declared"))

    for instance, base in spec.instances.items():
        if base not in vss:
            findings.append(
                _error("CAP-032", spec, f"vss.instances.{instance}",
                       f"{base!r} is not a branch in the pinned VSS",
                       "resolve the path against third_party/generated/vss.json")
            )

    for instance, path, signal in spec.expanded_signals():
        location = f"vss.signals.{signal.id}[{instance}]"
        resolved = vss.get(path)
        if resolved is None:
            findings.append(
                _error("CAP-033", spec, location,
                       f"{path!r} does not exist in the pinned VSS",
                       "the standard is the source of truth; fix the template or the instance base")
            )
            continue

        if signal.datatype and resolved.datatype != signal.datatype:
            findings.append(
                _error("CAP-034", spec, location,
                       f"declared datatype {signal.datatype!r} but VSS says {resolved.datatype!r}")
            )

        if signal.unit and resolved.unit != signal.unit:
            findings.append(
                _error("CAP-035", spec, location,
                       f"declared unit {signal.unit!r} but VSS says {resolved.unit!r}")
            )

        if signal.role == "command" and not resolved.is_actuator:
            findings.append(
                _error("CAP-036", spec, location,
                       f"role 'command' requires a VSS actuator, but {path} is {resolved.type or 'a branch'!r}")
            )

        if signal.role == "state" and resolved.is_branch:
            findings.append(_error("CAP-037", spec, location, f"{path!r} is a branch, not a signal"))

        if resolved.deprecated:
            findings.append(
                _warn("CAP-038", spec, location, f"{path!r} is deprecated in the pinned VSS",
                      "migrate before the next standards bump")
            )

    declared = {signal.id for signal in spec.signals}
    used = {signal_id for op in spec.operations for signal_id in op.signals}
    for signal_id in sorted(declared - used):
        findings.append(
            _warn("CAP-039", spec, f"vss.signals.{signal_id}",
                  "declared but no operation references it", "wire it into an operation or remove it")
        )

    return findings


# ── CAP-3xx: VDM grounding ───────────────────────────────────────────────

def vdm_rules(spec: "CapabilitySpec", *, vdm: "VdmSchema") -> list[Finding]:
    findings: list[Finding] = []

    for context, ref in spec.vdm_refs():
        location = f"vdm.{context}"
        vdm_type = vdm.get(ref.type_name)
        if vdm_type is None:
            findings.append(
                _error("CAP-340", spec, location, f"VDM type {ref.type_name!r} does not exist in the pinned VDM")
            )
            continue

        if ref.field_name:
            field = vdm_type.field(ref.field_name)
            if field is None:
                findings.append(
                    _error("CAP-341", spec, location,
                           f"VDM type {ref.type_name!r} has no field {ref.field_name!r}")
                )
                continue

            # Fidelity: when the VDM field projects a VSS signal, the capability's
            # VSS mapping for the same behaviour must point at that same signal.
            if field.vspec_fqn:
                signal = next(
                    (s for s in spec.signals if s.id == context.split(":", 1)[-1]),
                    None,
                )
                if signal is not None:
                    expanded = {path for _, path, sig in spec.expanded_signals() if sig.id == signal.id}
                    normalized = {vdm.normalize_vss_path(path) for path in expanded}
                    if field.vspec_fqn not in normalized:
                        findings.append(
                            _error("CAP-342", spec, location,
                                   f"VDM field projects {field.vspec_fqn!r}, but the catalog maps "
                                   f"{sorted(expanded)}",
                                   "VSS and VDM must describe the same signal for the same behaviour")
                        )

    types = (spec.vdm or {}).get("types") or ()
    for type_name in types:
        if not vdm.has_type(str(type_name)):
            findings.append(_error("CAP-343", spec, f"vdm.types.{type_name}",
                                   f"VDM type {type_name!r} does not exist"))

    tag = (spec.vdm or {}).get("instance_tag") or {}
    if tag:
        tag_type = vdm.get(str(tag.get("type")))
        if tag_type is None:
            findings.append(_error("CAP-344", spec, "vdm.instance_tag",
                                   f"instance tag type {tag.get('type')!r} does not exist"))
        else:
            if not tag_type.is_instance_tag:
                findings.append(
                    _error("CAP-345", spec, "vdm.instance_tag",
                           f"VDM type {tag_type.name!r} is not annotated @instanceTag")
                )
            for dimension in tag.get("dimensions") or ():
                field = tag_type.field(str(dimension))
                if field is None:
                    findings.append(
                        _error("CAP-346", spec, f"vdm.instance_tag.dimensions.{dimension}",
                               f"{tag_type.name!r} has no field {dimension!r}")
                    )
                    continue
                allowed = set(vdm.enum_values(field.returns))
                for zone, mapping in (tag.get("map") or {}).items():
                    value = mapping.get(str(dimension))
                    if value is None:
                        findings.append(
                            _error("CAP-347", spec, f"vdm.instance_tag.map.{zone}",
                                   f"missing {dimension!r}")
                        )
                    elif allowed and value not in allowed:
                        findings.append(
                            _error("CAP-348", spec, f"vdm.instance_tag.map.{zone}",
                                   f"{value!r} is not a value of {field.returns}",
                                   f"allowed: {', '.join(sorted(allowed))}")
                        )

            mapped = set((tag.get("map") or {}).keys())
            missing = sorted(set(spec.instances) - mapped)
            for zone in missing:
                findings.append(
                    _warn("CAP-349", spec, f"vdm.instance_tag.map.{zone}",
                          "VSS instance has no VDM instance tag mapping")
                )

    return findings


# ── CAP-4xx: the northbound/southbound boundary ──────────────────────────

#: Patterns that must never appear in a northbound contract: those are hardware
#: or transport details, which belong below the southbound boundary.
#:
#: Transport and ECU names are matched case-sensitively on purpose: lowercase
#: "can" is ordinary English ("can-execute"), and a rule that flags prose is a
#: rule people disable.
_HARDWARE_PATTERNS: tuple[tuple[str, str, int], ...] = (
    (r"\b0x[0-9A-Fa-f]{2,}\b", "a hex bus identifier", re.IGNORECASE),
    (r"\b(can_?id|lin_?id|flexray_?id|msg_?id)\b", "a bus message id", re.IGNORECASE),
    (r"\b(CAN|LIN|FlexRay|SOME/IP|DDS)\b", "a transport name", 0),
    (r"\b(ECU|ECUs|SUPPLIER)\b", "an ECU or supplier reference", 0),
)


def boundary_rules(spec: "CapabilitySpec", *, contracts_dir: Path) -> list[Finding]:
    """Hardware detail must not leak above the southbound boundary."""
    findings: list[Finding] = []
    import re as _re

    if spec.contract:
        path = contracts_dir / Path(spec.contract).name
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            for pattern, label, flags in _HARDWARE_PATTERNS:
                match = _re.search(pattern, text, flags)
                if match:
                    findings.append(
                        _error("CAP-410", spec, spec.contract,
                               f"northbound contract contains {label}: {match.group(0)!r}",
                               "hardware addressing belongs in the southbound binding")
                    )

    commands = [s for s in spec.signals if s.role == "command"]
    if commands and not spec.southbound_dependencies:
        findings.append(
            _error("CAP-411", spec, "southbound_dependencies",
                   f"{len(commands)} command signal(s) declared but no southbound dependency",
                   "a capability that commands hardware must name the port it commands")
        )

    for dependency in spec.southbound_dependencies:
        if not _re.fullmatch(r"[a-z][a-z0-9_]*", dependency):
            findings.append(
                _error("CAP-412", spec, f"southbound_dependencies.{dependency}",
                       "southbound dependency is not a snake_case operation name")
            )

    for instance, base in spec.instances.items():
        if any(char.isdigit() for char in instance):
            findings.append(
                _warn("CAP-413", spec, f"vss.instances.{instance}",
                      "instance name embeds a numeric index; positions are VSS's job",
                      "name instances by role (DRIVER_FRONT), not by hardware slot")
            )

    return findings


# ── CAP-5xx: safety and requirements ─────────────────────────────────────

REQUIREMENT_ID = re.compile(r"^REQ-[A-Z0-9]+-\d{3}$")


def safety_rules(spec: "CapabilitySpec") -> list[Finding]:
    """A safety-relevant capability must state, and trace, its requirements."""
    findings: list[Finding] = []
    requirements = getattr(spec, "requirements", ()) or ()

    if spec.asil_tier != "QM":
        if not requirements:
            findings.append(
                _error("CAP-510", spec, "requirements",
                       f"{spec.asil_tier} capability declares no requirements",
                       "add REQ-* statements with a verifying test each")
            )

    seen: set[str] = set()
    for index, requirement in enumerate(requirements):
        identifier = str(requirement.get("id") or "")
        location = f"requirements[{index}]"
        if not REQUIREMENT_ID.match(identifier):
            findings.append(
                _error("CAP-511", spec, location,
                       f"requirement id {identifier!r} does not match REQ-<AREA>-<NNN>")
            )
        elif identifier in seen:
            findings.append(_error("CAP-511", spec, location, f"duplicate requirement id {identifier}"))
        seen.add(identifier)

        if not requirement.get("statement"):
            findings.append(_error("CAP-512", spec, location, "requirement has no statement"))
        if requirement.get("verified_by") is None:
            findings.append(
                _warn("CAP-513", spec, location,
                      "requirement has no verified_by test reference")
            )

    for operation in spec.operations:
        commands = [
            signal_id for signal_id in operation.signals
            if (spec.signal(signal_id) and spec.signal(signal_id).role == "command")
        ]
        if commands and not operation.requires_arbitration and not operation.preconditions:
            findings.append(
                _warn("CAP-514", spec, f"operations.{operation.name}",
                      "operation commands hardware but declares neither arbitration "
                      "nor preconditions")
            )

    return findings


# ── CAP-6xx: verification coverage ───────────────────────────────────────

def test_rules(spec: "CapabilitySpec", *, tests_dir: Path) -> list[Finding]:
    """Every exposed operation and every requirement must point at a real test."""
    findings: list[Finding] = []
    sources = _test_sources(tests_dir)

    if not sources:
        findings.append(_warn("CAP-620", spec, str(tests_dir), "no tests found"))

    for operation in spec.operations:
        if getattr(operation, "transport", "http") != "http":
            continue
        if not operation.verified_by:
            findings.append(
                _warn("CAP-610", spec, f"operations.{operation.name}",
                      "exposed operation declares no verified_by test")
            )
            continue
        for name in operation.verified_by:
            if name not in sources:
                findings.append(
                    _error("CAP-611", spec, f"operations.{operation.name}",
                           f"verified_by test {name!r} does not exist")
                )

    for requirement in getattr(spec, "requirements", ()) or ():
        for name in requirement.get("verified_by") or ():
            if name not in sources:
                findings.append(
                    _error("CAP-612", spec, f"requirements.{requirement.get('id')}",
                           f"verified_by test {name!r} does not exist")
                )

    return findings


def _test_sources(tests_dir: Path) -> set[str]:
    """Every ``def test_*`` name defined in *tests_dir*."""
    import re as _re

    names: set[str] = set()
    if not tests_dir.is_dir():
        return names
    for path in tests_dir.rglob("test_*.py"):
        names.update(_re.findall(r"^def (test_[A-Za-z0-9_]+)", path.read_text(encoding="utf-8"), _re.MULTILINE))
    return names
