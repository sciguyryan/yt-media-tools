"""Contract tests for the portable unittest adapter and deterministic sharding."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
MODULE = PROJECT / "python" / "yt_discover_tests" / "test_normative_ysql_unittest.py"


def _adapter():
    spec = importlib.util.spec_from_file_location("normative_unittest_contract", MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_shards_cover_all_cases_once() -> None:
    adapter = _adapter()
    all_ids = [case_id for case_id, _ in adapter.selected_cases()]
    partitions = [adapter.selected_cases(shard_index=i, shard_count=4) for i in range(4)]
    assert sorted(case_id for partition in partitions for case_id, _ in partition) == all_ids
    assert max(len(partition) for partition in partitions) - min(len(partition) for partition in partitions) <= 1


def test_invalid_shards_fail_closed() -> None:
    adapter = _adapter()
    with pytest.raises(ValueError, match="shard index"):
        adapter.selected_cases(shard_index=2, shard_count=2)
    with pytest.raises(ValueError, match="shard index"):
        adapter.selected_cases(shard_count=0)


def test_individual_case_is_selectable() -> None:
    adapter = _adapter()
    case_class = adapter.build_case_class()
    method = "test_smoke_source_order_limit"
    assert hasattr(case_class, method)
    test = case_class(method)
    result = test.defaultTestResult()
    test.run(result)
    assert result.wasSuccessful()
    assert result.testsRun == 1


def test_incomplete_declared_case_is_a_failing_unittest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing expectation fails its own case, not unittest discovery."""
    import json

    adapter = _adapter()
    directory = tmp_path / "cases" / "scalar" / "incomplete"
    directory.mkdir(parents=True)
    (directory / "test.json").write_text(
        json.dumps(
            {
                "version": 1,
                "id": "scalar.incomplete",
                "datasets": ["python-v6-small"],
                "query": "query.ysql",
                "expected": "expected.json",
                "order": "ordered",
            }
        ),
        encoding="utf-8",
    )
    (directory / "query.ysql").write_text("SELECT 1", encoding="utf-8")
    import shutil

    (tmp_path / "datasets").mkdir()
    shutil.copyfile(
        PROJECT / "yt-sql" / "datasets" / "python-v6-small.json", tmp_path / "datasets" / "python-v6-small.json"
    )
    monkeypatch.setattr(adapter, "CORPUS", tmp_path)
    cases = adapter.selected_cases()
    assert cases == [("scalar.incomplete", directory)]
    suite = adapter.build_case_class()
    result = suite("test_scalar_incomplete").defaultTestResult()
    suite("test_scalar_incomplete").run(result)
    assert result.testsRun == 1
    assert len(result.errors) == 1
    assert "expected.json" in result.errors[0][1]


def test_malformed_manifest_remains_discoverable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _adapter()
    directory = tmp_path / "cases" / "invalid"
    directory.mkdir(parents=True)
    (directory / "test.json").write_text("{bad json", encoding="utf-8")
    monkeypatch.setattr(adapter, "CORPUS", tmp_path)
    assert adapter.selected_cases() == [("invalid.invalid", directory)]
    suite = adapter.build_case_class()
    test = suite("test_invalid_invalid")
    result = test.defaultTestResult()
    test.run(result)
    assert result.testsRun == 1 and len(result.errors) == 1


def test_duplicate_ids_fail_as_individual_cases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json
    import shutil

    adapter = _adapter()
    (tmp_path / "datasets").mkdir()
    shutil.copyfile(
        PROJECT / "yt-sql" / "datasets" / "python-v6-small.json", tmp_path / "datasets" / "python-v6-small.json"
    )
    for name in ("first", "second"):
        directory = tmp_path / "cases" / name
        directory.mkdir(parents=True)
        (directory / "test.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "id": "scalar.duplicate",
                    "datasets": ["python-v6-small"],
                    "query": "query.ysql",
                    "expected": "expected.json",
                    "order": "ordered",
                }
            ),
            encoding="utf-8",
        )
        (directory / "query.ysql").write_text("SELECT 1", encoding="utf-8")
        (directory / "expected.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "outcome": "rows",
                    "columns": ["1"],
                    "rows": [[1]],
                }
            ),
            encoding="utf-8",
        )
    monkeypatch.setattr(adapter, "CORPUS", tmp_path)
    suite = adapter.build_case_class()
    result = (
        __import__("unittest").defaultTestLoader.loadTestsFromTestCase(suite).run(__import__("unittest").TestResult())
    )
    assert result.testsRun == 2
    assert len(result.failures) == 2
    assert all("duplicate case ID" in failure for _, failure in result.failures)
