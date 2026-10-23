"""Portable facet topology invariants and deliberately invalid variants."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "yt-sql/datasets/heterogeneous-facets-v1.json"
spec = importlib.util.spec_from_file_location("facet_validator", ROOT / "yt-sql/validate_portable_facets.py")
assert spec and spec.loader
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def fixture() -> dict:
    return json.loads(PATH.read_text(encoding="utf-8"))


def test_facet_fixture_is_valid_and_contains_empty_relations() -> None:
    validator.validate_file(PATH)
    data = fixture()
    assert len(data["facets"]) == 6
    assert sum(not facet["record_indices"] for facet in data["facets"]) == 3
    assert (
        data["records"]
        == json.loads((ROOT / "yt-sql/datasets/heterogeneous-sources-v1.json").read_text(encoding="utf-8"))["records"]
    )


def test_facet_export_is_current() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "yt-sql/export_portable_facets.py"), "--check"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "change",
    [
        "duplicate_facet",
        "cross_source",
        "duplicate_index",
        "missing_record",
        "bad_digest",
        "invalid_unicode",
        "wrong_provenance",
    ],
)
def test_invalid_facets_rejected(change: str) -> None:
    data = copy.deepcopy(fixture())
    if change == "duplicate_facet":
        data["facets"].append(copy.deepcopy(data["facets"][0]))
    elif change == "cross_source":
        data["facets"][0]["record_indices"].append(4)
    elif change == "duplicate_index":
        data["facets"][0]["record_indices"].append(0)
    elif change == "missing_record":
        data["facets"][0]["record_indices"].remove(0)
    elif change == "bad_digest":
        data["record_digest_sha256"] = "0" * 64
    elif change == "invalid_unicode":
        data["records"][0]["title"] = "\ud800"
    elif change == "wrong_provenance":
        data["provenance"]["source_dataset"] = "other"
    with pytest.raises(ValueError):
        validator.validate(data)
