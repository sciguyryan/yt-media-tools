"""Tests for searched CASE scalar expressions and their optimiser integration."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from yt_media_tools.dates import DateContext
from yt_media_tools.optimizer import optimise_query
from yt_media_tools.planner import required_query_fields
from yt_media_tools.query import (
    QuerySyntaxError,
    apply_query,
    canonical_record_value,
    format_scalar_expression,
    parse_query,
    resolve_query,
)
from yt_media_tools.schema import QuerySchema

NOW = datetime(2026, 9, 8, 9, 0, tzinfo=timezone.utc)


def _resolve(source: str, records: list[dict]):
    return resolve_query(parse_query(source), QuerySchema(records), DateContext(now=NOW))


def _values(source: str, records: list[dict]) -> list[object]:
    query = _resolve(source, records)
    return [canonical_record_value(record, query.select[-1]) for record in records]


def test_searched_case_uses_first_true_branch() -> None:
    records = [
        {"id": "short", "duration": 300},
        {"id": "medium", "duration": 1800},
        {"id": "long", "duration": 7200},
    ]
    values = _values(
        "SELECT CASE WHEN duration < 10m THEN 'short' WHEN duration < 1h THEN 'medium' ELSE 'long' END AS bucket FROM @fixture",
        records,
    )
    assert values == ["short", "medium", "long"]


def test_case_when_unknown_falls_through() -> None:
    records = [{"id": "missing", "duration": None}]
    assert _values(
        "SELECT CASE WHEN duration < 10m THEN 'short' ELSE 'other' END AS bucket FROM @fixture", records
    ) == ["other"]


def test_case_without_else_returns_null() -> None:
    records = [{"id": "short", "duration": 60}, {"id": "long", "duration": 3600}, {"id": "missing"}]
    assert _values("SELECT CASE WHEN duration < 10m THEN 1 END AS bucket FROM @fixture", records) == [1, None, None]


def test_case_boolean_condition_accepts_bare_boolean_field() -> None:
    records = [{"id": "live", "is_live": True}, {"id": "not", "is_live": False}, {"id": "missing", "is_live": None}]
    assert _values("SELECT CASE WHEN is_live THEN 'live' ELSE 'other' END AS state FROM @fixture", records) == [
        "live",
        "other",
        "other",
    ]


def test_case_condition_supports_three_valued_boolean_logic() -> None:
    records = [
        {"id": "a", "view_count": None, "is_live": False},
        {"id": "b", "view_count": 50, "is_live": False},
        {"id": "c", "view_count": 50, "is_live": True},
    ]
    source = "SELECT CASE WHEN view_count >= 10 AND NOT is_live THEN 'match' ELSE 'other' END AS state FROM @fixture"
    assert _values(source, records) == ["other", "match", "other"]


def test_case_results_accept_nested_scalar_expressions() -> None:
    records = [{"id": "a", "view_count": 10, "title": "Example"}, {"id": "b", "view_count": None, "title": "Other"}]
    source = "SELECT CASE WHEN view_count IS NULL THEN LENGTH(LOWER(title)) ELSE (view_count + 2) * 3 END AS score FROM @fixture"
    assert _values(source, records) == [36, 5]


def test_case_can_be_nested() -> None:
    records = [{"id": "a", "duration": 60, "view_count": 1}, {"id": "b", "duration": 3600, "view_count": 20}]
    source = (
        "SELECT CASE WHEN duration < 10m THEN CASE WHEN view_count > 10 THEN 'popular-short' ELSE 'short' END "
        "ELSE 'long' END AS bucket FROM @fixture"
    )
    assert _values(source, records) == ["short", "long"]


def test_case_numeric_branch_types_are_compatible() -> None:
    records = [{"id": "a", "view_count": 1}, {"id": "b", "view_count": 2}]
    source = "SELECT CASE WHEN view_count = 1 THEN 1 ELSE view_count / 2 END AS value FROM @fixture"
    query = _resolve(source, records)
    assert query.select[0].kind == "number"
    assert [canonical_record_value(record, query.select[0]) for record in records] == [1, 1.0]


def test_case_null_branch_does_not_force_mixed_type() -> None:
    records = [{"id": "a", "view_count": 1}, {"id": "b", "view_count": 2}]
    query = _resolve("SELECT CASE WHEN view_count = 1 THEN NULL ELSE 'value' END AS x FROM @fixture", records)
    assert query.select[0].kind == "string"
    assert [canonical_record_value(record, query.select[0]) for record in records] == [None, "value"]


def test_case_all_null_results_are_valid() -> None:
    records = [{"id": "a", "view_count": 1}]
    query = _resolve("SELECT CASE WHEN view_count = 1 THEN NULL ELSE NULL END AS x FROM @fixture", records)
    assert query.select[0].kind is None
    assert canonical_record_value(records[0], query.select[0]) is None


def test_case_rejects_incompatible_known_result_types() -> None:
    records = [{"id": "a", "view_count": 1}]
    with pytest.raises(QuerySyntaxError, match="compatible types"):
        _resolve("SELECT CASE WHEN view_count = 1 THEN 'one' ELSE 2 END AS x FROM @fixture", records)


def test_case_can_order_rows_directly() -> None:
    records = [
        {"id": "a", "duration": 3600},
        {"id": "b", "duration": 60},
        {"id": "c", "duration": 1200},
    ]
    query = _resolve(
        "SELECT id FROM @fixture ORDER BY CASE WHEN duration < 10m THEN 1 WHEN duration < 1h THEN 2 ELSE 3 END ASC",
        records,
    )
    assert [record["id"] for record in apply_query(records, query)] == ["b", "c", "a"]


def test_case_projection_alias_can_be_ordered() -> None:
    records = [{"id": "a", "duration": 3600}, {"id": "b", "duration": 60}, {"id": "c", "duration": 1200}]
    source = (
        "SELECT id, CASE WHEN duration < 10m THEN 1 WHEN duration < 1h THEN 2 ELSE 3 END AS bucket "
        "FROM @fixture ORDER BY bucket DESC"
    )
    query = _resolve(source, records)
    assert [record["id"] for record in apply_query(records, query)] == ["a", "c", "b"]


def test_required_fields_include_case_conditions_and_results() -> None:
    query = parse_query(
        "SELECT CASE WHEN duration < 10m THEN view_count + LENGTH(title) ELSE source_index END AS score "
        "FROM @fixture ORDER BY CASE WHEN is_live THEN release_timestamp ELSE duration END"
    )
    assert required_query_fields(query) == {
        "duration",
        "view_count",
        "title",
        "source_index",
        "is_live",
        "release_timestamp",
    }


def test_case_formats_canonically() -> None:
    records = [{"id": "a", "duration": 60}]
    query = _resolve("SELECT CASE WHEN duration < 10m THEN 1 ELSE 2 END AS bucket FROM @fixture", records)
    assert format_scalar_expression(query.select[0].expression) == "CASE WHEN duration < 10m THEN 1 ELSE 2 END"


def test_case_when_predicate_is_optimised_and_semantics_preserved() -> None:
    records = [{"id": "null", "duration": None}, {"id": "low", "duration": 90}, {"id": "high", "duration": 180}]
    source = "SELECT CASE WHEN duration > 1m AND duration > 2m THEN 1 ELSE 0 END AS bucket FROM @fixture"
    original = _resolve(source, records)
    result = optimise_query(original)
    assert [(item.rule, item.before, item.after) for item in result.decisions] == [
        ("case-when-subsumed-and-predicate", "(duration > 1m AND duration > 2m)", "duration > 2m")
    ]
    assert [canonical_record_value(record, original.select[0]) for record in records] == [
        canonical_record_value(record, result.query.select[0]) for record in records
    ]


def test_case_optimiser_is_idempotent() -> None:
    records = [{"id": "a", "duration": 180}]
    query = _resolve("SELECT CASE WHEN duration > 1m AND duration > 2m THEN 1 ELSE 0 END AS x FROM @fixture", records)
    first = optimise_query(query)
    second = optimise_query(first.query)
    assert second.query == first.query
    assert second.decisions == ()


def test_case_can_return_temporal_field_with_null_fallback() -> None:
    records = [
        {"id": "a", "is_live": True, "upload_date": "20260901"},
        {"id": "b", "is_live": False, "upload_date": "20260902"},
    ]
    query = _resolve("SELECT CASE WHEN is_live THEN upload_date ELSE NULL END AS day FROM @fixture", records)
    assert query.select[0].kind == "date"
    values = [canonical_record_value(record, query.select[0]) for record in records]
    assert str(values[0]) == "2026-09-01"
    assert values[1] is None


def test_case_when_supports_between_in_text_and_temporal_predicates() -> None:
    records = [
        {
            "id": "a",
            "duration": 300,
            "title": "Mars briefing",
            "availability": "public",
            "upload_date": "20260901",
        },
        {
            "id": "b",
            "duration": 1200,
            "title": "Other",
            "availability": "private",
            "upload_date": None,
        },
    ]
    queries = [
        ("SELECT CASE WHEN duration BETWEEN 1m AND 10m THEN 1 ELSE 0 END AS x FROM @fixture", [1, 0]),
        ("SELECT CASE WHEN availability IN ('public', 'unlisted') THEN 1 ELSE 0 END AS x FROM @fixture", [1, 0]),
        ("SELECT CASE WHEN title CONTAINS 'mars' THEN 1 ELSE 0 END AS x FROM @fixture", [1, 0]),
        ("SELECT CASE WHEN upload_date < INFINITY() THEN 1 ELSE 0 END AS x FROM @fixture", [1, 0]),
    ]
    for source, expected in queries:
        assert _values(source, records) == expected


def test_case_branch_order_prevents_later_true_branch_from_winning() -> None:
    records = [{"id": "a", "duration": 60}]
    source = "SELECT CASE WHEN duration < 1h THEN 'first' WHEN duration < 10m THEN 'second' ELSE 'none' END AS x FROM @fixture"
    assert _values(source, records) == ["first"]


def test_case_result_may_be_boolean() -> None:
    records = [{"id": "a", "view_count": 1}, {"id": "b", "view_count": 2}]
    source = "SELECT CASE WHEN view_count = 1 THEN TRUE ELSE FALSE END AS x FROM @fixture"
    query = _resolve(source, records)
    assert query.select[0].kind == "boolean"
    assert [canonical_record_value(record, query.select[0]) for record in records] == [True, False]


def test_case_predicate_optimizer_runs_to_fixed_point() -> None:
    records = [{"id": "a", "duration": 180}, {"id": "b", "duration": None}]
    source = (
        "SELECT CASE WHEN NOT NOT (duration > 1m AND duration > 2m AND duration > 2m) "
        "THEN 1 ELSE 0 END AS x FROM @fixture"
    )
    original = _resolve(source, records)
    optimised = optimise_query(original)
    assert [canonical_record_value(record, original.select[0]) for record in records] == [
        canonical_record_value(record, optimised.query.select[0]) for record in records
    ]
    assert optimise_query(optimised.query).decisions == ()


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("SELECT CASE FROM @fixture", "CASE requires at least one WHEN|Only searched CASE"),
        ("SELECT CASE view_count WHEN 1 THEN 'x' END FROM @fixture", "Only searched CASE"),
        ("SELECT CASE WHEN THEN 1 END FROM @fixture", "requires a condition"),
        ("SELECT CASE WHEN view_count = 1 1 END FROM @fixture", "Expected THEN"),
        ("SELECT CASE WHEN view_count = 1 THEN END FROM @fixture", "requires a scalar result"),
        ("SELECT CASE WHEN view_count = 1 THEN 1 ELSE END FROM @fixture", "ELSE requires"),
        ("SELECT CASE WHEN view_count = 1 THEN 1 FROM @fixture", "Expected END"),
    ],
)
def test_malformed_case_is_rejected(source: str, message: str) -> None:
    with pytest.raises(QuerySyntaxError, match=message):
        parse_query(source)


def test_case_condition_unknown_field_is_rejected_during_resolution() -> None:
    records = [{"id": "a", "view_count": 1}]
    with pytest.raises(QuerySyntaxError, match="Unknown field"):
        _resolve("SELECT CASE WHEN nonexistent = 1 THEN 1 ELSE 0 END AS x FROM @fixture", records)


def test_case_result_structured_field_preserves_select_diagnostic() -> None:
    records = [{"id": "a", "view_count": 1, "_raw": {"formats": [{"format_id": "1"}]}}]
    with pytest.raises(QuerySyntaxError, match="Cannot SELECT structured"):
        _resolve("SELECT CASE WHEN view_count = 1 THEN raw.formats ELSE NULL END AS x FROM @fixture", records)
