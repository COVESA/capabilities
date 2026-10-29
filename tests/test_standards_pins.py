"""The pinned standards are present, hashed, and parseable."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "third_party" / "standards.lock.json"


@pytest.fixture(scope="module")
def lock() -> dict:
    return json.loads(LOCK.read_text(encoding="utf-8"))


def test_lock_file_records_both_standards(lock: dict) -> None:
    assert set(lock["standards"]) == {"vss", "vdm"}
    for std, entry in lock["standards"].items():
        assert entry["commit"], f"{std} has no pinned commit"
        assert entry["repo"].startswith("https://github.com/COVESA/")


def test_submodule_head_matches_the_lock_file(lock: dict) -> None:
    for std, entry in lock["standards"].items():
        path = ROOT / entry["path"]
        if not (path / ".git").exists():
            pytest.skip(f"{std} submodule not initialized; run ./scripts/vendor_standards.sh")
        head = subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
        assert head == entry["commit"], f"{std} drifted from the lock file"


def test_generated_artifacts_match_recorded_hashes(lock: dict) -> None:
    for std, entry in lock["standards"].items():
        for name, meta in entry["artifacts"].items():
            artifact = ROOT / meta["path"]
            assert artifact.is_file(), f"missing {artifact}"
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
            assert digest == meta["sha256"], (
                f"{name} does not match the lock file; rerun ./scripts/vendor_standards.sh"
            )


def test_vss_version_label_matches_the_pin(lock: dict) -> None:
    vss_json = ROOT / "third_party" / "generated" / "vss.json"
    tree = json.loads(vss_json.read_text(encoding="utf-8"))
    version = tree["Vehicle"]["children"]["VersionVSS"]["children"]
    label = f"{version['Major']['default']}.{version['Minor']['default']}"
    assert label == lock["standards"]["vss"]["version_label"]
