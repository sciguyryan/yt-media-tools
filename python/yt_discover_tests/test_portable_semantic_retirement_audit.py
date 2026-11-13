"""Guard the Phase 6.1 discovery inventory against silent source drift."""

from __future__ import annotations

import ast
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
    assert all(
        entry["retirement_decision"] == "retain_pending_assertion_level_review" for entry in audit["legacy_tests"]
    )
    assert audit["counts"]["test_functions"] == sum(len(entry["tests"]) for entry in audit["legacy_tests"])
    assert audit["counts"]["assertion_sites"] == sum(
        len(test["assertion_sites"]) for entry in audit["legacy_tests"] for test in entry["tests"]
    )


def test_reviewed_retirements_have_explicit_portable_evidence() -> None:
    """Do not silently lose approved replacement cases after retiring legacy tests."""
    audit = json.loads((ROOT / "yt-sql/SEMANTIC-RETIREMENT-AUDIT.json").read_text(encoding="utf-8"))
    ledger = json.loads((ROOT / "yt-sql/REVIEWED-RETIREMENTS.json").read_text(encoding="utf-8"))
    available = {entry["id"] for entry in audit["normative_cases"]}
    assert audit["reviewed_retirements"] == ledger["retirements"]
    assert ledger["retirements"]
    for retirement in ledger["retirements"]:
        assert retirement["assertions"] > 0
        assert retirement["case_ids"]
        assert set(retirement["case_ids"]) <= available
        source = (ROOT / retirement["source"]).read_text(encoding="utf-8")
        tree = ast.parse(source)
        names = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        assert retirement["test"] not in names


def test_reviewed_modules_account_for_every_remaining_test() -> None:
    """A reviewed module must not silently retain unclassified portable tests."""
    ledger = json.loads((ROOT / "yt-sql/REVIEWED-RETIREMENTS.json").read_text(encoding="utf-8"))
    # The reviewed set grows as migration increments account for more modules;
    # the originally reviewed modules must never silently drop their accounting.
    reviewed = {entry["source"] for entry in ledger["module_reviews"]}
    assert reviewed >= {
        "python/yt_discover_tests/test_char_function.py",
        "python/yt_discover_tests/test_concat_function.py",
    }
    for review in ledger["module_reviews"]:
        tree = ast.parse((ROOT / review["source"]).read_text(encoding="utf-8"))
        remaining = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
        }
        retained = {item["test"] for item in review["retained"]}
        assert review["status"] == "portable_assertions_migrated"
        assert remaining == retained
        assert all(item["reason"] for item in review["retained"])
