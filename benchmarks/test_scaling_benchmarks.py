"""Opt-in scaling benchmarks for AST depth and deterministic dataset size."""

from __future__ import annotations

import pytest

from yt_discover_tests.conformance.generate_dataset import DATASET_SEED, build_records
from yt_media_tools.query import apply_query, parse_query, resolve_query
from yt_media_tools.query_properties import analyse_query
from yt_media_tools.schema import QuerySchema

AST_DEPTHS = (8, 32, 128)
DATASET_SIZES = (100, 1_000, 10_000)


def _deep_predicate(depth: int) -> str:
    terms = [f"view_count >= {index}" for index in range(depth)]
    return "SELECT id WHERE " + " AND ".join(terms)


@pytest.mark.scale
@pytest.mark.benchmark(group="analysis-scaling")
@pytest.mark.parametrize("depth", AST_DEPTHS)
def test_analysis_ast_depth(benchmark, depth: int, benchmark_schema, benchmark_dates) -> None:
    """Measure analysis growth as expression-tree depth increases."""
    resolved = resolve_query(parse_query(_deep_predicate(depth)), benchmark_schema, benchmark_dates)
    benchmark.extra_info["benchmark_id"] = f"analysis.ast_depth.{depth}"
    result = benchmark(analyse_query, resolved)
    assert result.required_fields


@pytest.mark.scale
@pytest.mark.benchmark(group="offline-scaling")
@pytest.mark.parametrize("size", DATASET_SIZES)
def test_offline_dataset_scaling(benchmark, size: int, benchmark_dates) -> None:
    """Measure local execution growth over deterministic dataset sizes."""
    records = build_records(size, seed=DATASET_SEED)
    schema = QuerySchema(records)
    resolved = resolve_query(
        parse_query("SELECT id WHERE view_count >= 1000 ORDER BY view_count DESC LIMIT 100"), schema, benchmark_dates
    )
    benchmark.extra_info["benchmark_id"] = f"end_to_end.offline.{size}"
    result = benchmark(apply_query, records, resolved)
    assert isinstance(result, list)
