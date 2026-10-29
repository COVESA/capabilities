"""The capability rule checker must pass for every catalog entry."""

from __future__ import annotations

from pathlib import Path

import pytest

from capability_framework.checker import CheckContext, run_checks
from capability_framework.checker.cli import main
from capability_framework.semantics import CatalogError, load_capability

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "third_party" / "generated"


@pytest.fixture(scope="module")
def context() -> CheckContext:
    return CheckContext.from_paths(
        catalog_dir=ROOT / "catalog" / "capabilities",
        contracts_dir=ROOT / "contracts",
        repo_root=ROOT,
        vss_json=GENERATED / "vss.json",
        vdm_graphql=GENERATED / "vdm.graphql",
    )


def test_every_catalog_entry_passes_strict(context: CheckContext) -> None:
    result = run_checks(context)
    assert result.ok, [f"{f.rule_id} {f.location}: {f.message}" for f in result.errors]
    assert not result.warnings, [f"{f.rule_id} {f.location}: {f.message}" for f in result.warnings]


def test_report_is_deterministic(context: CheckContext) -> None:
    first = [f.to_dict() for f in run_checks(context).findings]
    second = [f.to_dict() for f in run_checks(context).findings]
    assert first == second


def test_cli_exits_zero_when_clean() -> None:
    assert main(["--no-color", "--strict"]) == 0


def test_cli_renders_json(capsys: pytest.CaptureFixture[str]) -> None:
    import json

    assert main(["--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert "window" in payload["capabilities"]


def test_unknown_vss_signal_is_rejected(tmp_path: Path) -> None:
    entry = tmp_path / "broken.yaml"
    entry.write_text(
        (ROOT / "catalog" / "capabilities" / "window.yaml").read_text(encoding="utf-8")
        .replace("{instance}.IsOpen", "{instance}.NotASignal"),
        encoding="utf-8",
    )
    spec = load_capability(entry)
    from capability_framework.checker.rules import Severity, vss_rules
    from capability_framework.semantics import VssCatalog

    findings = vss_rules(spec, vss=VssCatalog.from_json(GENERATED / "vss.json"))
    assert any(f.rule_id == "CAP-033" and f.severity is Severity.ERROR for f in findings)


def test_operation_referencing_an_undeclared_signal_is_rejected(tmp_path: Path) -> None:
    entry = tmp_path / "broken.yaml"
    entry.write_text(
        (ROOT / "catalog" / "capabilities" / "window.yaml").read_text(encoding="utf-8")
        .replace("      - window.is_open\n", "      - window.does_not_exist\n", 1),
        encoding="utf-8",
    )
    with pytest.raises(CatalogError, match="undeclared signal"):
        load_capability(entry)


# ── CAP-4xx / 5xx / 6xx behaviour ────────────────────────────────────

def _spec_from(tmp_path: Path, mutate) -> object:
    text = (ROOT / "catalog" / "capabilities" / "window.yaml").read_text(encoding="utf-8")
    entry = tmp_path / "window.yaml"
    entry.write_text(mutate(text), encoding="utf-8")
    return load_capability(entry)


def test_boundary_rule_flags_bus_identifiers(tmp_path: Path) -> None:
    from capability_framework.checker.rules import Severity, boundary_rules

    spec = _spec_from(tmp_path, lambda t: t)
    (tmp_path / "window-api.yaml").write_text(
        "openapi: '3.1.0'\ninfo:\n  version: '2.0.0'\npaths:\n  /x:\n    post:\n"
        "      operationId: moveWindow\n      description: reads CAN id 0x1A2\n",
        encoding="utf-8",
    )
    findings = boundary_rules(spec, contracts_dir=tmp_path)
    assert any(f.rule_id == "CAP-410" and f.severity is Severity.ERROR for f in findings)


def test_boundary_rule_does_not_flag_the_word_can(tmp_path: Path) -> None:
    """'can-execute' is prose, not a CAN bus reference."""
    from capability_framework.checker.rules import boundary_rules

    spec = _spec_from(tmp_path, lambda t: t)
    (tmp_path / "window-api.yaml").write_text(
        "openapi: '3.1.0'\ninfo:\n  version: '2.0.0'\npaths:\n  /capabilities/x/can-execute:\n"
        "    post:\n      operationId: canExecuteWindow\n      summary: can execute a move\n",
        encoding="utf-8",
    )
    assert not [f for f in boundary_rules(spec, contracts_dir=tmp_path) if f.rule_id == "CAP-410"]


def test_safety_rule_requires_requirements_for_asil(tmp_path: Path) -> None:
    from capability_framework.checker.rules import Severity, safety_rules

    spec = _spec_from(tmp_path, lambda t: t.replace("requirements:", "ignored:"))
    findings = safety_rules(spec)
    assert any(f.rule_id == "CAP-510" and f.severity is Severity.ERROR for f in findings)


def test_safety_rule_rejects_malformed_requirement_ids(tmp_path: Path) -> None:
    from capability_framework.checker.rules import safety_rules

    spec = _spec_from(tmp_path, lambda t: t.replace("REQ-WIN-001", "WIN-1"))
    assert any(f.rule_id == "CAP-511" for f in safety_rules(spec))


def test_test_rule_flags_a_missing_verification_test(tmp_path: Path) -> None:
    from capability_framework.checker.rules import Severity, test_rules

    spec = _spec_from(tmp_path, lambda t: t.replace(
        "test_http_move_route", "test_that_does_not_exist"))
    findings = test_rules(spec, tests_dir=ROOT / "tests")
    assert any(f.rule_id == "CAP-611" and f.severity is Severity.ERROR for f in findings)


def test_test_rule_flags_an_operation_without_verification(tmp_path: Path) -> None:
    from capability_framework.checker.rules import test_rules

    spec = _spec_from(tmp_path, lambda t: t.replace(
        "    verified_by: [test_http_get_window_state_reads_a_zone]\n", ""))
    assert any(f.rule_id == "CAP-610" for f in test_rules(spec, tests_dir=ROOT / "tests"))


# ── baselines ────────────────────────────────────────────────────────

def test_baseline_suppresses_a_live_finding() -> None:
    from datetime import date, timedelta

    from capability_framework.checker.engine import BaselineEntry, apply_baseline
    from capability_framework.checker.rules import Finding, Severity

    finding = Finding("CAP-610", Severity.WARNING, "window", "operations.x", "no test")
    entry = BaselineEntry("CAP-610", "window", "known", "body", date.today() + timedelta(days=1))
    assert apply_baseline([finding], [entry]) == []


def test_expired_baseline_reports_the_underlying_finding_and_itself() -> None:
    from datetime import date, timedelta

    from capability_framework.checker.engine import BaselineEntry, apply_baseline
    from capability_framework.checker.rules import Finding, Severity

    finding = Finding("CAP-610", Severity.WARNING, "window", "operations.x", "no test")
    entry = BaselineEntry("CAP-610", "window", "known", "body", date.today() - timedelta(days=1))
    kept = apply_baseline([finding], [entry])
    assert any(f.rule_id == "CAP-610" for f in kept)
    assert any(f.rule_id == "CAP-900" and f.severity is Severity.ERROR for f in kept)


def test_baseline_requires_justification(tmp_path: Path) -> None:
    from capability_framework.checker.engine import load_baseline

    path = tmp_path / "baseline.yaml"
    path.write_text("entries:\n  - rule: CAP-610\n    capability: window\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing"):
        load_baseline(path)


def test_junit_output_is_xml(context: CheckContext) -> None:
    import xml.etree.ElementTree as ET

    from capability_framework.checker.engine import report

    xml = report(run_checks(context), fmt="junit")
    suite = ET.fromstring(xml)
    assert suite.tag == "testsuite"
    assert int(suite.get("tests", "0")) >= 1
