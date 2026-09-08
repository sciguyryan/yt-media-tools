"""Tests for grouped and ungrouped yt-sql aggregation semantics."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from yt_media_tools.dates import DateContext
from yt_media_tools.optimizer import optimise_query
from yt_media_tools.planner import plan_limit_termination, required_query_fields
from yt_media_tools.query import QuerySyntaxError, apply_query, parse_query, resolve_query
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


def test_ungrouped_count_star_and_count_expression() -> None:
    records = rows()
    query = resolve("SELECT COUNT(*) AS total, COUNT(view_count) AS known FROM @fixture", records)
    assert apply_query(records, query) == [{"_yt_sql_aggregate_result": True, "total": 5, "known": 4}]


def test_empty_ungrouped_aggregate_retains_single_row() -> None:
    records = rows()
    query = resolve(
        "SELECT COUNT(*) AS n, SUM(view_count) AS total, AVG(view_count) AS mean, "
        "MIN(title) AS first, MAX(title) AS last FROM @fixture WHERE id = 'missing'",
        records,
    )
    assert apply_query(records, query) == [
        {
            "_yt_sql_aggregate_result": True,
            "n": 0,
            "total": None,
            "mean": None,
            "first": None,
            "last": None,
        }
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


def test_sum_avg_ignore_null_and_min_max_use_exact_unicode_order() -> None:
    records = rows()
    query = resolve(
        "SELECT SUM(view_count) AS total, AVG(view_count) AS mean, MIN(title) AS first, MAX(title) AS last "
        "FROM @fixture",
        records,
    )
    result = apply_query(records, query)[0]
    assert result["total"] == 130
    assert result["mean"] == 32.5
    assert result["first"] == min("β", "α", "é", "Ω")
    assert result["last"] == max("β", "α", "é", "Ω")


def test_filter_where_is_applied_per_aggregate_after_where() -> None:
    records = rows()
    query = resolve(
        "SELECT COUNT(*) AS all_rows, COUNT(*) FILTER (WHERE duration < 30s) AS short, "
        "SUM(view_count) FILTER (WHERE duration >= 40s) AS long_views FROM @fixture WHERE uploader IS NOT NULL",
        records,
    )
    assert apply_query(records, query)[0] == {
        "_yt_sql_aggregate_result": True,
        "all_rows": 3,
        "short": 1,
        "long_views": 30,
    }


def test_having_supports_direct_aggregates_aliases_boolean_logic_and_null_tests() -> None:
    records = rows()
    direct = resolve(
        "SELECT uploader, COUNT(*) AS n FROM @fixture GROUP BY uploader HAVING COUNT(*) > 1 ORDER BY uploader",
        records,
    )
    alias = resolve(
        "SELECT uploader, COUNT(*) AS n FROM @fixture GROUP BY uploader HAVING n > 1 AND NOT (SUM(view_count) IS NULL) ORDER BY uploader",
        records,
    )
    # Both forms retain the same two-row groups.
    assert {(r["uploader"], r["n"]) for r in apply_query(records, direct)} == {(None, 2), ("é", 2)}
    assert {(r["uploader"], r["n"]) for r in apply_query(records, alias)} == {(None, 2), ("é", 2)}


def test_aggregate_alias_can_order_groups() -> None:
    records = rows()
    query = resolve(
        "SELECT uploader, SUM(view_count) AS total FROM @fixture GROUP BY uploader ORDER BY total DESC",
        records,
    )
    assert [row["total"] for row in apply_query(records, query)] == [90, 30, 10]


def test_scalar_wrappers_can_contain_aggregates() -> None:
    records = rows()
    query = resolve("SELECT COALESCE(AVG(view_count), 0) + 1 AS adjusted FROM @fixture", records)
    assert apply_query(records, query)[0]["adjusted"] == 33.5


@pytest.mark.parametrize(
    "source, message",
    [
        ("SELECT id, COUNT(*) FROM @fixture", "must match a GROUP BY expression"),
        ("SELECT uploader, COUNT(*) FROM @fixture GROUP BY title", "must match a GROUP BY expression"),
        ("SELECT * FROM @fixture GROUP BY uploader", r"SELECT \* is not supported"),
        ("SELECT SUM(title) FROM @fixture", "SUM requires a numeric value"),
        ("SELECT AVG(title) FROM @fixture", "AVG requires a numeric value"),
        ("SELECT SUM(COUNT(*)) FROM @fixture", "Aggregate functions cannot be nested"),
        ("SELECT COUNT(*) FROM @fixture GROUP BY COUNT(*)", "GROUP BY expressions cannot contain aggregate"),
        ("SELECT id FROM @fixture HAVING id = 'a'", "HAVING requires GROUP BY or an aggregate"),
    ],
)
def test_invalid_aggregate_semantics_are_rejected(source: str, message: str) -> None:
    with pytest.raises(QuerySyntaxError, match=message):
        resolve(source, rows())


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
