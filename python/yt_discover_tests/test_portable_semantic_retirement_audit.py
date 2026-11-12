"""Guard the Phase 6.1 discovery inventory against silent source drift."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_retirement_audit_is_current() -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "yt-sql/build_semantic_retirement_audit.py"), "--check"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def test_retirement_audit_does_not_certify_unreviewed_replacements() -> None:
    audit = json.loads((ROOT / "yt-sql/SEMANTIC-RETIREMENT-AUDIT.json").read_text(encoding="utf-8"))
    assert audit["status"] == "discovery_only_no_semantic_replacements_certified"
    assert audit["counts"]["language_elements"] == len(audit["language_obligations"])
    assert audit["counts"]["legacy_test_files"] == len(audit["legacy_tests"])
    assert audit["counts"]["normative_manifests"] == len(audit["normative_cases"])
    assert all(entry["migration_status"] == "not_certified" for entry in audit["language_obligations"])
    assert all(entry["retirement_decision"] == "retain_pending_assertion_level_review" for entry in audit["legacy_tests"])
    assert audit["counts"]["test_functions"] == sum(len(entry["tests"]) for entry in audit["legacy_tests"])
    assert audit["counts"]["assertion_sites"] == sum(
        len(test["assertion_sites"]) for entry in audit["legacy_tests"] for test in entry["tests"]
    )
