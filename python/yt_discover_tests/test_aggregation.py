"""Tests for grouped and ungrouped yt-sql aggregation semantics."""

from __future__ import annotations

from datetime import datetime, timezone


from yt_media_tools.dates import DateContext
from yt_media_tools.optimizer import optimise_query
from yt_media_tools.planner import plan_limit_termination, required_query_fields
from yt_media_tools.query import apply_query, parse_query, resolve_query
from yt_media_tools.schema import QuerySchema


CONTEXT = DateContext(now=datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc))


def resolve(source: str, records: list[dict]):
    return resolve_query(parse_query(source), QuerySchema(records), CONTEXT)


def rows() -> list[dict]:
    return [
        {"id": "a", "uploader": "é", "view_count": 10, "duration": 20, "title": "β"},
        {"id": "b", "uploader": "é", "view_count": None, "duration": 40, "title": "α"},
        {"id": "c", "uploader": "e\u0301", "view_count": 30, "duration": 50, "title": "é"},
        {"id": "d", "uploader": None, "view_count": 40, "duration": None, "title": None},
        {"id": "e", "uploader": None, "view_count": 50, "duration": 10, "title": "Ω"},
    ]


def test_group_by_is_unicode_normalisation_sensitive_and_nulls_group_together() -> None:
    records = rows()
    query = resolve(
        "SELECT uploader, COUNT(*) AS n FROM @fixture GROUP BY uploader ORDER BY n DESC",
        records,
    )
    selected = apply_query(records, query)
    assert [(row["uploader"], row["n"]) for row in selected] == [("é", 2), (None, 2), ("e\u0301", 1)]


def test_group_order_without_order_by_is_first_source_occurrence() -> None:
    records = rows()
    query = resolve("SELECT uploader, COUNT(*) AS n FROM @fixture GROUP BY uploader", records)
    selected = apply_query(records, query)
    assert [row["uploader"] for row in selected] == ["é", "e\u0301", None]


def test_optimizer_is_idempotent_and_preserves_aggregate_results() -> None:
    records = rows()
    query = resolve(
        "SELECT uploader, SUM(1 + 2) FILTER (WHERE duration >= 10s AND duration >= 20s) AS score "
        "FROM @fixture GROUP BY uploader HAVING COUNT(*) >= 1 ORDER BY score DESC",
        records,
    )
    first = optimise_query(query)
    second = optimise_query(first.query)
    assert second.query == first.query
    assert apply_query(records, first.query) == apply_query(records, query)


def test_aggregate_fields_are_included_in_planning_and_limit_cannot_terminate_early() -> None:
    records = rows()
    query = resolve(
        "SELECT uploader, AVG(view_count) FILTER (WHERE duration < 1h) AS mean FROM @fixture "
        "GROUP BY uploader HAVING COUNT(title) > 0 LIMIT 1",
        records,
    )
    assert {"uploader", "view_count", "duration", "title"} <= required_query_fields(query)
    plan = plan_limit_termination(query)
    assert not plan.eligible
    assert "aggregation requires complete input groups" in plan.reason
