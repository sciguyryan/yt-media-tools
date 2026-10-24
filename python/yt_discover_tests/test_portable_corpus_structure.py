"""Validate portable corpus layout independently of the YT-SQL engine."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "yt-sql"
CASES = sorted((CORPUS / "cases").rglob("test.json"))


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_corpus_has_cases() -> None:
    assert CASES


@pytest.mark.parametrize("manifest", CASES, ids=lambda p: str(p.relative_to(CORPUS)))
def test_case_resources_are_complete(manifest: Path) -> None:
    case = _read(manifest)
    assert case["version"] == 1
    assert case["query"] == "query.ysql"
    assert case["expected"] == "expected.json"
    assert case["order"] in {"ordered", "unordered"}
    assert case["datasets"]
    assert (manifest.parent / case["query"]).read_text(encoding="utf-8").strip()
    expected = _read(manifest.parent / case["expected"])
    assert expected["version"] == 1
    assert expected["outcome"] in {"rows", "error"}
    if expected["outcome"] == "rows":
        assert all(len(row) == len(expected["columns"]) for row in expected["rows"])
    else:
        assert expected["error"]["category"]
    for dataset in case["datasets"]:
        descriptor = _read(CORPUS / "datasets" / f"{dataset}.json")
        assert descriptor["id"] == dataset


def test_case_ids_unique() -> None:
    ids = [_read(path)["id"] for path in CASES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("implementation", ["python", "rust"])
def test_expectation_overrides_are_valid(implementation: str) -> None:
    manifest = _read(CORPUS / "expectations" / f"{implementation}.json")
    ids = {_read(path)["id"] for path in CASES}
    assert manifest["version"] == 1
    for case_id, override in manifest["expectations"].items():
        assert case_id in ids
        assert override["status"] == "xfail"
        assert override["reason"].strip()
