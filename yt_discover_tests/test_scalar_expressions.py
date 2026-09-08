"""Tests for first-class scalar expressions in yt-sql projections and ordering."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from yt_media_tools.dates import DateContext
from yt_media_tools.planner import required_query_fields
from yt_media_tools.query import QuerySyntaxError, apply_query, canonical_record_value, parse_query, resolve_query
from yt_media_tools.schema import QuerySchema


def _resolve(source: str, records: list[dict]):
    return resolve_query(
        parse_query(source),
        QuerySchema(records),
        DateContext(now=datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)),
    )


def test_arithmetic_precedence_and_parentheses() -> None:
    records = [{"id": "a", "view_count": 10}]
    query = _resolve(
        "SELECT view_count + 2 * 3 AS natural, (view_count + 2) * 3 AS grouped FROM @fixture",
        records,
    )
    assert canonical_record_value(records[0], query.select[0]) == 16
    assert canonical_record_value(records[0], query.select[1]) == 36


def test_duration_can_be_projected_as_minutes() -> None:
    records = [{"id": "a", "duration": 150}]
    query = _resolve("SELECT duration / 60 AS minutes FROM @fixture", records)
    assert canonical_record_value(records[0], query.select[0]) == 2.5


def test_unary_arithmetic_is_recursive() -> None:
    records = [{"id": "a", "view_count": 25}]
    query = _resolve("SELECT -(-view_count) AS restored FROM @fixture", records)
    assert canonical_record_value(records[0], query.select[0]) == 25


def test_nested_scalar_functions_accept_expressions() -> None:
    records = [{"id": "a", "title": "Example", "view_count": 9}]
    query = _resolve(
        "SELECT LENGTH(LOWER(title)) AS chars, COALESCE(view_count + 1, 0) AS adjusted FROM @fixture",
        records,
    )
    assert canonical_record_value(records[0], query.select[0]) == 7
    assert canonical_record_value(records[0], query.select[1]) == 10


def test_null_propagates_through_arithmetic() -> None:
    records = [{"id": "a", "duration": None}]
    query = _resolve("SELECT duration / 60 AS minutes FROM @fixture", records)
    assert canonical_record_value(records[0], query.select[0]) is None


@pytest.mark.parametrize("operator", ("/", "%"))
def test_zero_divisor_returns_null(operator: str) -> None:
    records = [{"id": "a", "view_count": 10}]
    query = _resolve(f"SELECT view_count {operator} 0 AS value FROM @fixture", records)
    assert canonical_record_value(records[0], query.select[0]) is None


def test_order_by_scalar_expression() -> None:
    records = [
        {"id": "a", "duration": 120},
        {"id": "b", "duration": 60},
        {"id": "c", "duration": None},
    ]
    query = _resolve("SELECT id FROM @fixture ORDER BY duration / 60 DESC", records)
    assert [record["id"] for record in apply_query(records, query)] == ["a", "b", "c"]


def test_order_by_projection_alias_resolves_to_expression() -> None:
    records = [
        {"id": "a", "view_count": 10},
        {"id": "b", "view_count": 30},
        {"id": "c", "view_count": 20},
    ]
    query = _resolve("SELECT id, view_count * 2 AS score FROM @fixture ORDER BY score DESC", records)
    assert [record["id"] for record in apply_query(records, query)] == ["b", "c", "a"]


def test_order_by_expression_can_reference_projection_alias() -> None:
    records = [
        {"id": "a", "view_count": 10},
        {"id": "b", "view_count": 30},
        {"id": "c", "view_count": 20},
    ]
    query = _resolve("SELECT id, view_count * 2 AS score FROM @fixture ORDER BY score + 1 DESC", records)
    assert [record["id"] for record in apply_query(records, query)] == ["b", "c", "a"]


def test_required_fields_walk_nested_scalar_expression() -> None:
    query = parse_query(
        "SELECT COALESCE(view_count + LENGTH(title), 0) AS score FROM @fixture ORDER BY duration / 60 DESC"
    )
    assert required_query_fields(query) == {"view_count", "title", "duration"}


@pytest.mark.parametrize(
    "source",
    (
        "SELECT title + 1 FROM @fixture",
        "SELECT 1 + title FROM @fixture",
        "SELECT -title FROM @fixture",
    ),
)
def test_arithmetic_rejects_known_non_numeric_fields(source: str) -> None:
    records = [{"id": "a", "title": "Example"}]
    with pytest.raises(QuerySyntaxError, match="numeric"):
        _resolve(source, records)
