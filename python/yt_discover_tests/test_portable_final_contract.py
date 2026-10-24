"""Boundary checks shared by the corpus validator and observable comparator."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "yt-sql"))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"final_contract_{name}", ROOT / "yt-sql" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


compare = _load("compare_outcomes")
corpus = _load("validate_corpus")


@pytest.mark.parametrize("version", [True, 1.0, "1", None])
def test_observed_version_requires_integer_one(version: object) -> None:
    outcome = {"version": version, "outcome": "rows", "columns": [], "rows": []}
    with pytest.raises(compare.OutcomeError):
        compare.outcomes_match(outcome, outcome, order="ordered")


@pytest.mark.parametrize("columns", [["bad\ud800"], ["bad\udfff"]])
def test_observed_columns_reject_surrogates(columns: list[str]) -> None:
    outcome = {"version": 1, "outcome": "rows", "columns": columns, "rows": []}
    with pytest.raises(compare.OutcomeError):
        compare.outcomes_match(outcome, outcome, order="ordered")


def test_case_version_rejects_boolean(tmp_path: Path) -> None:
    case = tmp_path / "cases" / "example"
    case.mkdir(parents=True)
    (tmp_path / "datasets").mkdir()
    (tmp_path / "datasets" / "fixture.json").write_text('{"id":"fixture"}', encoding="utf-8")
    (case / "query.ysql").write_text("SELECT 1", encoding="utf-8")
    (case / "test.json").write_text(
        json.dumps(
            {
                "version": True,
                "id": "example",
                "datasets": ["fixture"],
                "query": "query.ysql",
                "expected": "expected.json",
                "order": "ordered",
            }
        ),
        encoding="utf-8",
    )
    (case / "expected.json").write_text('{"version":1,"outcome":"rows","columns":[],"rows":[]}', encoding="utf-8")
    with pytest.raises(corpus.CorpusError):
        corpus.validate_case(case, root=tmp_path)


def test_expected_version_rejects_boolean(tmp_path: Path) -> None:
    case = tmp_path / "cases" / "example"
    case.mkdir(parents=True)
    (tmp_path / "datasets").mkdir()
    (tmp_path / "datasets" / "fixture.json").write_text('{"id":"fixture"}', encoding="utf-8")
    (case / "query.ysql").write_text("SELECT 1", encoding="utf-8")
    (case / "test.json").write_text(
        '{"version":1,"id":"example","datasets":["fixture"],"query":"query.ysql","expected":"expected.json","order":"ordered"}',
        encoding="utf-8",
    )
    (case / "expected.json").write_text('{"version":true,"outcome":"rows","columns":[],"rows":[]}', encoding="utf-8")
    with pytest.raises(corpus.CorpusError):
        corpus.validate_case(case, root=tmp_path)
