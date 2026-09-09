"""DISTINCT, OFFSET, scalar projection and LIMIT interaction semantics."""

from __future__ import annotations

import pytest

from yt_media_tools.dates import DateContext
from yt_media_tools.output import project_record
from yt_media_tools.planner import plan_limit_termination, required_query_fields
from yt_media_tools.query import QuerySyntaxError, apply_query, parse_query, resolve_query
from yt_media_tools.schema import QuerySchema


def resolve(text: str, records: list[dict]):
    return resolve_query(parse_query(text), QuerySchema(records), DateContext(date_order="ymd"))


def test_distinct_deduplicates_selected_projection_after_ordering() -> None:
    records = [
        {"id": "a", "title": "same", "view_count": 1},
        {"id": "b", "title": "same", "view_count": 2},
        {"id": "c", "title": "other", "view_count": 3},
    ]
    query = resolve("SELECT DISTINCT title FROM @x ORDER BY view_count DESC", records)
    selected = apply_query(records, query)
    assert [record["id"] for record in selected] == ["c", "b"]


def test_offset_applies_before_limit() -> None:
    records = [{"id": str(i), "source_index": i} for i in range(1, 6)]
    query = resolve("SELECT id FROM @x ORDER BY source_index ASC LIMIT 2 OFFSET 2", records)
    assert [record["id"] for record in apply_query(records, query)] == ["3", "4"]


def test_offset_accepts_zero_and_rejects_negative_like_syntax() -> None:
    assert parse_query("SELECT id FROM @x OFFSET 0").offset == 0
    with pytest.raises(QuerySyntaxError, match="OFFSET requires"):
        parse_query("SELECT id FROM @x OFFSET -1")


def test_scalar_functions_projection_and_order_alias() -> None:
    records = [{"id": "a", "title": "Zulu"}, {"id": "b", "title": "alpha"}, {"id": "c", "title": None}]
    query = resolve("SELECT LOWER(title) AS folded FROM @x ORDER BY folded ASC", records)
    selected = apply_query(records, query)
    assert [project_record(record, query.select)["folded"] for record in selected] == ["alpha", "zulu", None]


def test_length_and_coalesce() -> None:
    records = [{"id": "a", "title": "abc"}, {"id": "b", "title": None}]
    q1 = resolve("SELECT LENGTH(title) AS n FROM @x", records)
    assert [project_record(r, q1.select)["n"] for r in records] == [3, None]
    q2 = resolve("SELECT COALESCE(title, 'untitled') AS title FROM @x", records)
    assert [project_record(r, q2.select)["title"] for r in records] == ["abc", "untitled"]


def test_scalar_function_required_fields_are_underlying_fields() -> None:
    query = parse_query("SELECT LOWER(title) AS t, LENGTH(description) AS n FROM @x")
    assert required_query_fields(query) == {"title", "description"}


def test_limit_termination_disabled_by_distinct_but_allows_offset() -> None:
    assert not plan_limit_termination(parse_query("SELECT DISTINCT id FROM @x LIMIT 2")).eligible
    offset = plan_limit_termination(parse_query("SELECT id FROM @x LIMIT 2 OFFSET 1"))
    assert offset.eligible
    assert "3 authoritative match(es)" in offset.reason
