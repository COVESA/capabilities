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
capability_framework.checker.engine
====================================
Wires the pinned standards to the catalog and runs every rule, producing a
deterministic report.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import yaml

from ..semantics import CapabilitySpec, VdmSchema, VssCatalog, load_catalog
from .rules import (
    Finding,
    Severity,
    boundary_rules,
    catalog_rules,
    contract_rules,
    safety_rules,
    test_rules,
    vdm_rules,
    vss_rules,
)

__all__ = [
    "BaselineEntry",
    "CheckContext",
    "CheckReport",
    "apply_baseline",
    "load_baseline",
    "report",
    "run_checks",
]


@dataclass
class CheckContext:
    """Everything the rules need, resolved once."""

    catalog_dir: Path
    contracts_dir: Path
    repo_root: Path
    vss: VssCatalog
    vdm: VdmSchema
    tests_dir: Path | None = None
    baseline: tuple["BaselineEntry", ...] = ()

    @classmethod
    def from_paths(
        cls,
        *,
        catalog_dir: str | Path,
        contracts_dir: str | Path,
        repo_root: str | Path,
        vss_json: str | Path,
        vdm_graphql: str | Path,
        tests_dir: str | Path | None = None,
        baseline_path: str | Path | None = None,
    ) -> "CheckContext":
        root = Path(repo_root)
        return cls(
            catalog_dir=Path(catalog_dir),
            contracts_dir=Path(contracts_dir),
            repo_root=root,
            vss=VssCatalog.from_json(vss_json),
            vdm=VdmSchema.from_sdl_file(vdm_graphql),
            tests_dir=Path(tests_dir) if tests_dir else root / "tests",
            baseline=load_baseline(baseline_path) if baseline_path else (),
        )


# ── baseline ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BaselineEntry:
    """A time-boxed exemption for one rule on one capability."""

    rule: str
    capability: str
    reason: str
    owner: str
    expires: date
    location: str | None = None

    def matches(self, finding: Finding) -> bool:
        if finding.rule_id != self.rule or finding.capability != self.capability:
            return False
        return self.location is None or finding.location == self.location


_REQUIRED_BASELINE_KEYS = ("rule", "capability", "reason", "owner", "expires")


def load_baseline(path: str | Path | None) -> tuple[BaselineEntry, ...]:
    """Parse ``baseline.yaml``; every entry must justify itself and expire."""
    if path is None:
        return ()
    path = Path(path)
    if not path.is_file():
        return ()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries: list[BaselineEntry] = []
    for index, item in enumerate(raw.get("entries") or ()):
        missing = [key for key in _REQUIRED_BASELINE_KEYS if not item.get(key)]
        if missing:
            raise ValueError(f"{path}: entry {index} missing {', '.join(missing)}")
        expires = item["expires"]
        entries.append(
            BaselineEntry(
                rule=str(item["rule"]),
                capability=str(item["capability"]),
                reason=str(item["reason"]),
                owner=str(item["owner"]),
                expires=expires if isinstance(expires, date) else date.fromisoformat(str(expires)),
                location=item.get("location"),
            )
        )
    return tuple(entries)


def apply_baseline(
    findings: Iterable[Finding],
    entries: Iterable[BaselineEntry],
    *,
    today: date | None = None,
) -> list[Finding]:
    """Drop suppressed findings; an expired exemption reports itself instead."""
    today = today or date.today()
    entries = list(entries)
    kept: list[Finding] = []
    for finding in findings:
        matching = [entry for entry in entries if entry.matches(finding)]
        if any(entry.expires >= today for entry in matching):
            continue
        kept.append(finding)
        for entry in matching:
            if entry.expires < today:
                kept.append(
                    Finding(
                        rule_id="CAP-900",
                        severity=Severity.ERROR,
                        capability=finding.capability,
                        location=finding.location,
                        message=(
                            f"baseline exemption for {finding.rule_id} expired on "
                            f"{entry.expires.isoformat()} (owner: {entry.owner})"
                        ),
                        hint=f"fix the finding or renew the exemption: {entry.reason}",
                    )
                )
    return kept


@dataclass(frozen=True)
class CheckReport:
    findings: tuple[Finding, ...]
    capabilities: tuple[str, ...]

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.WARNING]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "capabilities": list(self.capabilities),
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "findings": [f.to_dict() for f in self.findings],
        }


def run_checks(
    context: CheckContext,
    *,
    only: Iterable[str] | None = None,
    spec: CapabilitySpec | None = None,
) -> CheckReport:
    """Run every rule over the catalog (or a single already-loaded spec)."""
    specs = [spec] if spec is not None else list(load_catalog(context.catalog_dir).values())
    if only:
        wanted = {name.lower() for name in only}
        specs = [s for s in specs if s.name.lower() in wanted]

    findings: list[Finding] = []
    for capability in specs:
        findings.extend(catalog_rules(capability, contracts_dir=context.contracts_dir,
                                      repo_root=context.repo_root))
        findings.extend(contract_rules(capability, contracts_dir=context.contracts_dir))
        findings.extend(vss_rules(capability, vss=context.vss))
        findings.extend(vdm_rules(capability, vdm=context.vdm))
        findings.extend(boundary_rules(capability, contracts_dir=context.contracts_dir))
        findings.extend(safety_rules(capability))
        if context.tests_dir is not None:
            findings.extend(test_rules(capability, tests_dir=context.tests_dir))

    findings = apply_baseline(findings, context.baseline)
    findings.sort(key=Finding.sort_key)
    return CheckReport(tuple(findings), tuple(s.name for s in specs))


def report(result: CheckReport, *, fmt: str = "text", use_color: bool = True) -> str:
    """Render a report as text, JSON, or JUnit XML."""
    if fmt == "json":
        import json

        return json.dumps(result.to_dict(), indent=2)
    if fmt == "junit":
        return _junit(result)

    bold = "\033[1m" if use_color else ""
    red = "\033[31m" if use_color else ""
    yellow = "\033[33m" if use_color else ""
    green = "\033[32m" if use_color else ""
    dim = "\033[2m" if use_color else ""
    reset = "\033[0m" if use_color else ""

    lines: list[str] = []
    current = None
    for finding in result.findings:
        if finding.capability != current:
            current = finding.capability
            lines.append(f"\n{bold}{current}{reset}")
        colour = red if finding.severity is Severity.ERROR else yellow
        source = "" if finding.severity is Severity.ERROR else " (warning)"
        lines.append(f"  {colour}{finding.rule_id}{reset} {dim}{finding.location}{reset}: {finding.message}{source}")
        if finding.hint:
            lines.append(f"      {dim}hint: {finding.hint}{reset}")

    status = f"{green}ok{reset}" if result.ok else f"{red}failed{reset}"
    lines.append(
        f"\n{status}: {len(result.capabilities)} capability(ies), "
        f"{len(result.errors)} error(s), {len(result.warnings)} warning(s)"
    )
    return "\n".join(lines)


def _junit(result: CheckReport) -> str:
    """One test case per capability; error findings become failures."""
    from xml.sax.saxutils import escape, quoteattr

    by_capability: dict[str, list[Finding]] = {name: [] for name in result.capabilities}
    for finding in result.findings:
        by_capability.setdefault(finding.capability, []).append(finding)

    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<testsuite name="capability-rules" tests="{len(by_capability)}" '
        f'failures="{len(result.errors)}" errors="0">',
    ]
    for capability, findings in by_capability.items():
        errors = [f for f in findings if f.severity is Severity.ERROR]
        out.append(f'  <testcase classname="capability_rules" name={quoteattr(capability)}>')
        if errors:
            detail = "\n".join(f"{f.rule_id} {f.location}: {f.message}" for f in errors)
            out.append(
                f'    <failure message={quoteattr(f"{len(errors)} finding(s)")}>'
                f"{escape(detail)}</failure>"
            )
        for warning in (f for f in findings if f.severity is Severity.WARNING):
            out.append(
                f"    <system-out>{escape(f'warning {warning.rule_id} {warning.location}: {warning.message}')}</system-out>"
            )
        out.append("  </testcase>")
    out.append("</testsuite>")
    return "\n".join(out)
