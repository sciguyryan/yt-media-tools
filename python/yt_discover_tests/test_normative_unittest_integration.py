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
