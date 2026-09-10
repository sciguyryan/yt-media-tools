"""Architectural regression tests for separated yt-sql resolution and evaluation."""

from __future__ import annotations

import yt_media_tools.query as query_facade
import yt_media_tools.query_evaluator as evaluator
import yt_media_tools.query_resolver as resolver
import yt_media_tools.query_semantics as semantics
from yt_media_tools.dates import DateContext
from yt_media_tools.query import QuerySyntaxError, parse_query
from yt_media_tools.schema import QuerySchema


def test_query_facade_preserves_resolver_and_evaluator_exports() -> None:
    assert query_facade.resolve_query is resolver.resolve_query
    assert query_facade.apply_query is evaluator.apply_query
    assert query_facade.evaluate is evaluator.evaluate
    assert query_facade.evaluate_scalar_expression is evaluator.evaluate_scalar_expression
    assert query_facade.canonical_record_value is evaluator.canonical_record_value
    assert query_facade.like_matches is evaluator.like_matches


def test_query_facade_preserves_physical_source_inspection_exports() -> None:
    assert query_facade.query_physical_source_requests is semantics.query_physical_source_requests
    assert query_facade.query_physical_sources is semantics.query_physical_sources
    assert query_facade.query_single_physical_source is semantics.query_single_physical_source


def test_resolver_rejects_invalid_scalar_types_without_evaluating_rows() -> None:
    parsed = parse_query("SELECT id WHERE duration CONTAINS 'x'")
    schema = QuerySchema([{"id": "a", "duration": 60}])
    try:
        resolver.resolve_query(parsed, schema, DateContext())
    except QuerySyntaxError as exc:
        assert "CONTAINS requires a text field" in str(exc)
    else:
        raise AssertionError("resolver unexpectedly accepted a text predicate on duration")


def test_evaluator_consumes_an_already_resolved_query() -> None:
    records = [
        {"id": "a", "title": "Mars", "view_count": 20},
        {"id": "b", "title": "Venus", "view_count": 5},
    ]
    parsed = parse_query("SELECT id WHERE view_count >= 10 ORDER BY id")
    resolved = resolver.resolve_query(parsed, QuerySchema(records), DateContext())
    assert evaluator.apply_query(records, resolved) == [records[0]]
