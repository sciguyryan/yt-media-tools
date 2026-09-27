"""Statistical benchmarks for the principal yt-sql query pipeline stages."""

from __future__ import annotations

import pytest

from yt_media_tools.optimizer import optimise_query
from yt_media_tools.query import apply_query, evaluate_scalar_expression, parse_query, resolve_query
from yt_media_tools.query_properties import analyse_query

SIMPLE_QUERY = "SELECT id WHERE view_count >= 1000"
COMPLEX_QUERY = (
    "SELECT id, title, COALESCE(view_count, 0) AS views "
    "WHERE (view_count >= 1000 AND title ILIKE '%video%') "
    "OR (duration >= 60s AND upload_date >= 2025-01-01) "
    "ORDER BY view_count DESC, title ASC LIMIT 100 OFFSET 5"
)
COLLECTION_QUERY = (
    "SELECT id, MAP(FILTER(tags AS tag WHERE tag IS NOT NULL) AS tag SELECT UPPER(tag)) AS normalised_tags "
    "WHERE ANY(tags AS tag WHERE tag = 'group-1')"
)


@pytest.mark.benchmark(group="parser")
@pytest.mark.parametrize(
    "source", [SIMPLE_QUERY, COMPLEX_QUERY, COLLECTION_QUERY], ids=["simple", "complex", "collection"]
)
def test_parse_query(benchmark, source: str) -> None:
    """Measure parser cost independently of semantic resolution."""
    benchmark.extra_info["benchmark_id"] = f"parser.{source[:24]}"
    result = benchmark(parse_query, source)
    assert result.source == source


@pytest.mark.benchmark(group="resolution")
@pytest.mark.parametrize(
    "source", [SIMPLE_QUERY, COMPLEX_QUERY, COLLECTION_QUERY], ids=["simple", "complex", "collection"]
)
def test_resolve_query(benchmark, source: str, benchmark_schema, benchmark_dates) -> None:
    """Measure semantic resolution against a stable inferred schema."""
    parsed = parse_query(source)
    benchmark.extra_info["benchmark_id"] = f"resolution.{source[:24]}"
    result = benchmark(resolve_query, parsed, benchmark_schema, benchmark_dates)
    assert result.select


@pytest.mark.benchmark(group="analysis")
def test_analyse_complex_query(benchmark, benchmark_schema, benchmark_dates) -> None:
    """Measure repeated semantic property derivation on a representative query."""
    resolved = resolve_query(parse_query(COMPLEX_QUERY), benchmark_schema, benchmark_dates)
    benchmark.extra_info["benchmark_id"] = "analysis.complex"
    result = benchmark(analyse_query, resolved)
    assert result.required_fields


@pytest.mark.benchmark(group="optimiser")
def test_optimise_complex_query(benchmark, benchmark_schema, benchmark_dates) -> None:
    """Measure optimiser cost after resolution."""
    resolved = resolve_query(parse_query(COMPLEX_QUERY), benchmark_schema, benchmark_dates)
    benchmark.extra_info["benchmark_id"] = "optimiser.complex"
    result = benchmark(optimise_query, resolved)
    assert result.query.select


@pytest.mark.benchmark(group="evaluation")
def test_evaluate_scalar_expression(benchmark, benchmark_schema, benchmark_dates, benchmark_records) -> None:
    """Measure a resolved scalar expression over a representative record set."""
    resolved = resolve_query(
        parse_query("SELECT COALESCE(view_count, 0) + 10 AS adjusted"), benchmark_schema, benchmark_dates
    )
    expression = resolved.select[0].expression
    assert expression is not None

    def evaluate_all() -> list[object]:
        return [evaluate_scalar_expression(expression, record) for record in benchmark_records]

    benchmark.extra_info["benchmark_id"] = "evaluation.scalar.medium"
    result = benchmark(evaluate_all)
    assert len(result) == len(benchmark_records)


@pytest.mark.benchmark(group="collection-evaluation")
def test_evaluate_collection_pipeline(benchmark, benchmark_schema, benchmark_dates, benchmark_records) -> None:
    """Measure composed FILTER and MAP evaluation over deterministic records."""
    resolved = resolve_query(parse_query(COLLECTION_QUERY), benchmark_schema, benchmark_dates)
    expression = resolved.select[1].expression
    assert expression is not None

    def evaluate_all() -> list[object]:
        return [evaluate_scalar_expression(expression, record) for record in benchmark_records]

    benchmark.extra_info["benchmark_id"] = "evaluation.collection.filter_map.medium"
    result = benchmark(evaluate_all)
    assert len(result) == len(benchmark_records)


@pytest.mark.benchmark(group="end-to-end-offline")
def test_apply_resolved_query(benchmark, benchmark_schema, benchmark_dates, benchmark_records) -> None:
    """Measure local query execution without remote acquisition or parser cost."""
    resolved = resolve_query(parse_query(COMPLEX_QUERY), benchmark_schema, benchmark_dates)
    benchmark.extra_info["benchmark_id"] = "end_to_end.offline.medium"
    result = benchmark(apply_query, benchmark_records, resolved)
    assert isinstance(result, list)


@pytest.mark.benchmark(group="formatting")
def test_format_complex_query(benchmark, benchmark_schema, benchmark_dates) -> None:
    """Measure canonical formatting of a resolved representative query."""
    from yt_media_tools.query import format_query

    resolved = resolve_query(parse_query(COMPLEX_QUERY), benchmark_schema, benchmark_dates)
    benchmark.extra_info["benchmark_id"] = "formatting.complex"
    result = benchmark(format_query, resolved)
    assert result.startswith("SELECT ")


@pytest.mark.benchmark(group="planning")
def test_plan_acquisition(benchmark, benchmark_dates) -> None:
    """Measure deterministic acquisition planning without remote work."""
    from yt_media_tools.planner import plan_acquisition

    parsed = parse_query(
        "FROM @example WHERE upload_date >= 2025-01-01 AND view_count >= 1000 ORDER BY upload_date DESC LIMIT 100"
    )
    benchmark.extra_info["benchmark_id"] = "planning.acquisition.bounded"
    result = benchmark(plan_acquisition, parsed, source_kind="channel", tab="videos", dates=benchmark_dates)
    assert result.mode
