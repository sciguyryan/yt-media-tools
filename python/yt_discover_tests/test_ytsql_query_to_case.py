"""Protect the boundary between Python observations and normative expectations."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ytsql_query_to_case.py"
SPEC = importlib.util.spec_from_file_location("ytsql_query_to_case", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_draft_is_explicitly_unverified(tmp_path: Path) -> None:
    query = ROOT / "yt-sql/cases/scalar/coalesce_null_chain/query.ysql"
    destination = tmp_path / "candidate"
    MODULE.draft(query, destination, case_id="draft.coalesce", dataset="python-v6-small", order="ordered")
    review = json.loads((destination / "REVIEW.json").read_text())
    expected = json.loads((destination / "expected.json").read_text())
    assert review["status"] == "unverified"
    assert "Python may contain defects" in review["warning"]
    assert expected["rows"] == [["fallback"]]
    assert json.loads((destination / "test.json").read_text())["id"] == "draft.coalesce"
    with pytest.raises(FileExistsError):
        MODULE.draft(query, destination, case_id="draft.coalesce", dataset="python-v6-small", order="ordered")


def test_never_write_unreviewed_case_into_normative_tree(tmp_path: Path) -> None:
    query = tmp_path / "query.ysql"
    query.write_text("SELECT 1 FROM @yt_sql_fixture LIMIT 1", encoding="utf-8")
    with pytest.raises(ValueError, match="outside"):
        MODULE.draft(
            query,
            ROOT / "yt-sql/cases/draft-candidate",
            case_id="draft.example",
            dataset="python-v6-small",
            order="ordered",
        )
    with pytest.raises(ValueError, match="dot-separated"):
        MODULE.draft(query, tmp_path / "output", case_id="Invalid Name", dataset="python-v6-small", order="ordered")


def test_discover_engine_datasets_and_generate_ready_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    available = MODULE.datasets()
    assert {
        "python-v6-small",
        "python-v6-normal",
        "heterogeneous-sources-v1",
        "heterogeneous-facets-v1",
    } <= available.keys()
    query = ROOT / "yt-sql/cases/scalar/coalesce_null_chain/query.ysql"
    destination = tmp_path / "draft"
    MODULE.draft(
        query,
        destination,
        case_id="scalar.coalesce_new_case",
        dataset="python-v6-normal",
        order="ordered",
        description="Review candidate",
        features=("scalar.coalesce",),
    )
    manifest = json.loads((destination / "test.json").read_text())
    assert manifest["datasets"] == ["python-v6-normal"]
    assert manifest["features"] == ["scalar.coalesce"]
    assert manifest["description"] == "Review candidate"
    assert (destination / "expected.json").exists()
    output = capsys.readouterr().out
    assert "cases/scalar/coalesce_new_case" in output
    assert "test.json" in output
    assert "No central case manifest edit is required" in output


def test_generator_rejects_unknown_dataset_before_creating_files(tmp_path: Path) -> None:
    query = ROOT / "yt-sql/cases/scalar/coalesce_null_chain/query.ysql"
    destination = tmp_path / "draft"
    with pytest.raises(ValueError, match="unknown or unsupported dataset"):
        MODULE.draft(query, destination, case_id="scalar.example", dataset="missing", order="ordered")
    assert not destination.exists()
