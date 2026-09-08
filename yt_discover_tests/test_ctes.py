"""Tests for non-recursive yt-sql common table expressions."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from yt_media_tools.dates import DateContext
from yt_media_tools.optimizer import optimise_query
from yt_media_tools.planner import plan_limit_termination, required_query_fields
from yt_media_tools.query import (
    QuerySyntaxError,
    apply_query,
    format_query,
    parse_query,
    query_single_physical_source,
    resolve_query,
)
from yt_media_tools.schema import QuerySchema


CONTEXT = DateContext(now=datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc))


def records() -> list[dict]:
    return [
        {"id": "a", "title": "Mars", "duration": 600, "view_count": 10, "uploader": "α"},
        {"id": "b", "title": "Moon", "duration": 1200, "view_count": 20, "uploader": "α"},
        {"id": "c", "title": "MARS mission", "duration": 1800, "view_count": 30, "uploader": "β"},
        {"id": "d", "title": "Cafe\u0301 Mars", "duration": 4200, "view_count": 40, "uploader": "β"},
    ]


def resolve(source: str):
    rows = records()
    return rows, resolve_query(parse_query(source), QuerySchema(rows), CONTEXT)


def test_single_cte_projects_a_logical_relation() -> None:
    rows, query = resolve(
        "WITH short AS (SELECT id, title, duration / 60 AS minutes FROM @fixture WHERE duration < 1h) "
        "SELECT id, minutes FROM short ORDER BY minutes DESC"
    )
    assert apply_query(rows, query) == [
        {"id": "c", "title": "MARS mission", "minutes": 30.0},
        {"id": "b", "title": "Moon", "minutes": 20.0},
        {"id": "a", "title": "Mars", "minutes": 10.0},
    ]


def test_chained_ctes_use_prior_logical_schema_case_insensitively() -> None:
    rows, query = resolve(
        "WITH Base AS (SELECT id, title, duration / 60 AS minutes FROM @fixture), "
        "mars AS (SELECT id, minutes FROM base WHERE title ILIKE '%mars%') "
        "SELECT id, minutes FROM MARS ORDER BY minutes DESC"
    )
    assert [(row["id"], row["minutes"]) for row in apply_query(rows, query)] == [
        ("d", 70.0),
        ("c", 30.0),
        ("a", 10.0),
    ]


def test_aggregate_cte_exports_aggregate_aliases() -> None:
    rows, query = resolve(
        "WITH grouped AS (SELECT uploader, COUNT(*) AS n, SUM(view_count) AS views FROM @fixture GROUP BY uploader) "
        "SELECT uploader, n, views FROM grouped WHERE n >= 2 ORDER BY views DESC"
    )
    assert [(row["uploader"], row["n"], row["views"]) for row in apply_query(rows, query)] == [
        ("β", 2, 70),
        ("α", 2, 30),
    ]


def test_cte_optimizer_is_differential_and_idempotent() -> None:
    rows, query = resolve(
        "WITH x AS (SELECT id, view_count + (1 + 1) AS score FROM @fixture WHERE NOT (view_count < 20)) "
        "SELECT id, score FROM x ORDER BY score DESC"
    )
    first = optimise_query(query)
    second = optimise_query(first.query)
    assert apply_query(rows, query) == apply_query(rows, first.query)
    assert second.query == first.query
    assert any(item.rule.startswith("cte-x-") for item in first.decisions)


def test_required_fields_follow_physical_cte_input_not_logical_outer_names() -> None:
    query = parse_query(
        "WITH x AS (SELECT id, duration / 60 AS minutes FROM @fixture WHERE view_count > 10) "
        "SELECT id, minutes FROM x ORDER BY minutes"
    )
    assert required_query_fields(query) == {"id", "duration", "view_count"}


def test_query_single_physical_source_resolves_through_cte_chain() -> None:
    query = parse_query("WITH a AS (SELECT id FROM @fixture), b AS (SELECT id FROM a) SELECT id FROM b")
    assert query_single_physical_source(query) == "@fixture"


def test_multiple_physical_sources_are_deferred_to_union_phase() -> None:
    query = parse_query("WITH a AS (SELECT id FROM @one), b AS (SELECT id FROM @two) SELECT id FROM a")
    with pytest.raises(QuerySyntaxError, match="only one physical source"):
        resolve_query(query, QuerySchema(records()), CONTEXT)


@pytest.mark.parametrize(
    ("source", "message"),
    (
        ("WITH RECURSIVE a AS (SELECT id FROM @fixture) SELECT id FROM a", "Recursive CTEs are not supported"),
        ("WITH a AS (SELECT id FROM a) SELECT id FROM a", "Recursive reference to CTE"),
        ("WITH a AS (SELECT id FROM b), b AS (SELECT id FROM @fixture) SELECT id FROM a", "cannot reference later CTE"),
        (
            "WITH a AS (WITH b AS (SELECT id FROM @fixture) SELECT id FROM b) SELECT id FROM a",
            "Nested WITH clauses are not supported",
        ),
        ("WITH a AS SELECT id FROM @fixture SELECT id FROM a", "Expected '(' before CTE query"),
    ),
)
def test_invalid_cte_forms_are_rejected(source: str, message: str) -> None:
    with pytest.raises(QuerySyntaxError, match=message):
        resolve_query(parse_query(source), QuerySchema(records()), CONTEXT)


def test_cte_format_round_trip_preserves_structure() -> None:
    source = "WITH x AS (SELECT id, title FROM @fixture WHERE title ILIKE '%mars%') SELECT id FROM x LIMIT 2"
    parsed = parse_query(source)
    formatted = format_query(parsed)
    reparsed = parse_query(formatted)
    assert reparsed.ctes[0].name == "x"
    assert reparsed.from_source == "x"
    assert reparsed.limit == 2


def test_select_star_from_cte_expands_only_exported_columns_in_projection_order() -> None:
    rows, query = resolve("WITH x AS (SELECT title, id FROM @fixture) SELECT * FROM x")
    assert [term.output_name for term in query.select] == ["title", "id"]
    assert list(apply_query(rows, query)[0])[:2] == ["title", "id"]


def test_cte_does_not_expose_unprojected_physical_fields() -> None:
    with pytest.raises(QuerySyntaxError, match="Unknown field 'duration'"):
        resolve("WITH x AS (SELECT id, title FROM @fixture) SELECT duration FROM x")


def test_cte_limit_disables_early_acquisition_termination() -> None:
    query = parse_query("WITH x AS (SELECT id FROM @fixture WHERE view_count > 10) SELECT id FROM x LIMIT 1")
    plan = plan_limit_termination(query)
    assert not plan.eligible
    assert "CTE materialisation" in plan.reason
