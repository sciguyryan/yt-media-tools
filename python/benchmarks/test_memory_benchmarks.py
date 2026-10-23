"""Opt-in Python allocation benchmarks kept separate from timing measurements."""

from __future__ import annotations

import gc
import tracemalloc

import pytest

from yt_media_tools.query import evaluate_scalar_expression, parse_query, resolve_query

PARSER_NESTING_DEPTHS = (1, 32)


@pytest.mark.memory
@pytest.mark.parametrize("pipeline_depth", [1, 2, 4, 8])
def test_collection_pipeline_peak_allocations(
    pipeline_depth: int, benchmark_schema, benchmark_dates, benchmark_records, record_property
) -> None:
    """Record peak traced allocation as composed collection pipelines deepen."""
    expression = "tags"
    for index in range(pipeline_depth):
        if index % 2 == 0:
            expression = f"FILTER({expression} AS tag{index} WHERE tag{index} IS NOT NULL)"
        else:
            expression = f"MAP({expression} AS tag{index} SELECT tag{index})"
    resolved = resolve_query(parse_query(f"SELECT {expression} AS result"), benchmark_schema, benchmark_dates)
    selected = resolved.select[0].expression
    assert selected is not None
    gc.collect()
    tracemalloc.start()
    try:
        values = [evaluate_scalar_expression(selected, record) for record in benchmark_records]
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    record_property("benchmark_id", f"memory.collection_pipeline.depth_{pipeline_depth}")
    record_property("peak_traced_bytes", peak)
    assert len(values) == len(benchmark_records)


def _record_parser_peak(parser, depth: int, record_property, name: str) -> None:
    source = f"SELECT {'(' * depth}id{')' * depth} FROM @fixture"
    parser(source)
    gc.collect()
    tracemalloc.start()
    try:
        result = parser(source)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    record_property("benchmark_id", f"memory.parser.{name}.nested.depth_{depth}")
    record_property("peak_traced_bytes", peak)
    assert result.source == source


@pytest.mark.memory
@pytest.mark.parametrize("depth", PARSER_NESTING_DEPTHS)
def test_parser_peak_allocations(depth: int, record_property) -> None:
    """Record reference parser allocations as scalar parentheses deepen."""
    _record_parser_peak(parse_query, depth, record_property, "reference")
