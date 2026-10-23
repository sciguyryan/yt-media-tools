"""Static checks for the shared YT-SQL Phase 1 inventory."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_portable_coverage_inventory_is_current() -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "yt-sql/build_coverage_inventory.py"), "--check"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def test_portable_coverage_inventory_baseline_is_coherent() -> None:
    inventory = json.loads((ROOT / "yt-sql/COVERAGE-INVENTORY.json").read_text(encoding="utf-8"))
    features = set(inventory["registered_features"])
    cases = {case["id"] for case in inventory["existing_cases"]}
    assert inventory["status"] == "baseline_inventory_not_certified_completeness"
    assert len(features) == len(inventory["registered_features"])
    assert len(cases) == len(inventory["existing_cases"])
    assert not inventory["unregistered_existing_case_tags"]
    assert all(set(ids) <= cases for ids in inventory["feature_to_existing_cases"].values())
    assert inventory["parser_functions"]["scalar"]
    assert inventory["parser_functions"]["aggregate"]


def test_existing_test_inventory_matches_coverage_inventory() -> None:
    coverage = json.loads((ROOT / "yt-sql/COVERAGE-INVENTORY.json").read_text(encoding="utf-8"))
    existing = json.loads((ROOT / "yt-sql/EXISTING-TEST-INVENTORY.json").read_text(encoding="utf-8"))
    assert existing["existing_python_cases"] == len(coverage["existing_cases"])
    assert set(existing["existing_case_ids"]) == {case["id"] for case in coverage["existing_cases"]}
    assert existing["language_features"] == coverage["registered_features"]
    assert existing["language_feature_count"] == len(coverage["registered_features"])
    assert existing["python_test_files"]
