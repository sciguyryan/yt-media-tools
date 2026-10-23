"""Portable multi-source topology integrity and adversarial cases."""

from __future__ import annotations
import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "yt-sql/datasets/heterogeneous-sources-v1.json"
spec = importlib.util.spec_from_file_location("topology_validator", ROOT / "yt-sql/validate_portable_topology.py")
assert spec and spec.loader
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def fixture() -> dict:
    return json.loads(PATH.read_text(encoding="utf-8"))


def test_topology_valid_and_cross_source_duplicates() -> None:
    validator.validate_file(PATH)
    data = fixture()
    assert len(data["sources"]) == 3
    assert data["record_count"] == 6
    assert [record["id"] for record in data["records"]].count("shared-id") == 2
    assert any("\u0301" in record["title"] for record in data["records"])


def test_topology_export_current() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "yt-sql/export_portable_topology.py"), "--check"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "change", ["duplicate_index", "wrong_membership", "duplicate_within_source", "digest", "unassigned", "surrogate"]
)
def test_invalid_topology_rejected(change: str) -> None:
    data = copy.deepcopy(fixture())
    if change == "duplicate_index":
        data["sources"][1]["record_indices"].append(0)
    elif change == "wrong_membership":
        data["records"][0]["_yt_sql_source"] = "@twitch_archive"
    elif change == "duplicate_within_source":
        data["records"][1]["id"] = data["records"][0]["id"]
    elif change == "digest":
        data["record_digest_sha256"] = "0" * 64
    elif change == "unassigned":
        data["sources"][0]["record_indices"].remove(0)
    elif change == "surrogate":
        data["records"][0]["title"] = "\ud800"
    with pytest.raises(ValueError):
        validator.validate(data)
