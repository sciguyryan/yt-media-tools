"""Conformance tests for NULL-safe comparison operators."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from yt_media_tools.dates import DateContext
from yt_media_tools.optimizer import optimise_query
from yt_media_tools.query import (
    QuerySemanticError,
    QuerySyntaxError,
    ScalarComparison,
    apply_query,
    canonical_record_value,
    format_expression,
    parse_query,
    resolve_query,
)
from yt_media_tools.schema import QuerySchema

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


def _resolve(source: str, records: list[dict]):
    return resolve_query(parse_query(source), QuerySchema(records), DateContext(now=NOW))


def _ids(predicate: str, records: list[dict]) -> list[str]:
    query = _resolve(f"SELECT id FROM @fixture WHERE {predicate} ORDER BY id ASC", records)
    return [record["id"] for record in apply_query(records, query)]


RECORDS = [
    {"id": "a", "title": None, "description": None},
    {"id": "b", "title": None, "description": "x"},
    {"id": "c", "title": "x", "description": None},
    {"id": "d", "title": "x", "description": "x"},
    {"id": "e", "title": "x", "description": "y"},
]


def test_is_distinct_from_has_total_null_safe_truth_table() -> None:
    assert _ids("title IS DISTINCT FROM description", RECORDS) == ["b", "c", "e"]


def test_is_not_distinct_from_has_total_null_safe_truth_table() -> None:
    assert _ids("title IS NOT DISTINCT FROM description", RECORDS) == ["a", "d"]


def test_null_safe_comparison_accepts_general_scalar_expressions() -> None:
    assert _ids("LOWER(title) IS NOT DISTINCT FROM LOWER(description)", RECORDS) == ["a", "d"]


def test_null_safe_comparison_accepts_null_literal() -> None:
    assert _ids("title IS NOT DISTINCT FROM NULL", RECORDS) == ["a", "b"]
    assert _ids("title IS DISTINCT FROM NULL", RECORDS) == ["c", "d", "e"]


def test_null_safe_comparison_formats_canonically() -> None:
    query = _resolve("SELECT id FROM @fixture WHERE LOWER(title) IS DISTINCT FROM description", RECORDS)
    assert isinstance(query.predicate, ScalarComparison)
    assert format_expression(query.predicate) == "LOWER(title) IS DISTINCT FROM description"


def test_null_safe_comparison_is_available_in_having() -> None:
    records = [{"id": "a", "uploader": "one"}, {"id": "b", "uploader": "one"}, {"id": "c", "uploader": "two"}]
    query = _resolve(
        "SELECT uploader, COUNT(*) AS n FROM @fixture GROUP BY uploader "
        "HAVING COUNT(*) IS NOT DISTINCT FROM 2 ORDER BY uploader ASC",
        records,
    )
    assert [record["uploader"] for record in apply_query(records, query)] == ["one"]


def test_null_safe_comparison_preserves_type_compatibility_rules() -> None:
    records = [{"id": "a", "title": "x", "view_count": 1}]
    with pytest.raises(QuerySemanticError, match="compatible types"):
        _resolve("SELECT id FROM @fixture WHERE title IS DISTINCT FROM view_count", records)


def test_constant_null_safe_comparison_can_be_optimised_without_three_valued_semantics() -> None:
    query = _resolve("SELECT id FROM @fixture WHERE NULL IS NOT DISTINCT FROM NULL", RECORDS)
    optimised = optimise_query(query).query
    assert apply_query(RECORDS, optimised) == RECORDS


def test_null_safe_comparison_composes_with_join_relation_fields() -> None:
    records = [
        {"id": None, "title": "left-null", "_yt_sql_source": "@left", "_yt_sql_source_facet": None},
        {"id": "x", "title": "left-x", "_yt_sql_source": "@left", "_yt_sql_source_facet": None},
        {"id": None, "tag": "right-null", "_yt_sql_source": "@right", "_yt_sql_source_facet": None},
        {"id": "x", "tag": "right-x", "_yt_sql_source": "@right", "_yt_sql_source_facet": None},
    ]
    schemas = {
        ("@left", None): QuerySchema([row for row in records if row["_yt_sql_source"] == "@left"]),
        ("@right", None): QuerySchema([row for row in records if row["_yt_sql_source"] == "@right"]),
    }
    query = resolve_query(
        parse_query(
            "SELECT l.title, r.tag FROM @left AS l JOIN @right AS r "
            "ON l.id IS NOT DISTINCT FROM r.id ORDER BY l.title ASC"
        ),
        QuerySchema(records),
        DateContext(now=NOW),
        source_schemas=schemas,
    )
    rows = apply_query(records, query)
    assert [[canonical_record_value(row, term) for term in query.select] for row in rows] == [
        ["left-null", "right-null"],
        ["left-x", "right-x"],
    ]


def test_is_distinct_from_requires_from_keyword() -> None:
    with pytest.raises(QuerySyntaxError, match="Expected FROM after IS DISTINCT"):
        parse_query("SELECT id FROM @fixture WHERE title IS DISTINCT description")
