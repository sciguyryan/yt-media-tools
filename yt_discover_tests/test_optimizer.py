"""Differential tests for the yt-sql semantics-preserving optimiser."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from yt_media_tools.dates import DateContext
from yt_media_tools.optimizer import optimise_query
from yt_media_tools.query import (
    Literal,
    apply_query,
    evaluate,
    evaluate_scalar_expression,
    format_query,
    format_scalar_expression,
    parse_query,
    resolve_query,
)
from yt_media_tools.schema import QuerySchema

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


def _resolved(source: str, records: list[dict[str, object]]):
    return resolve_query(parse_query(source), QuerySchema(records), DateContext(now=NOW))


def _assert_equivalent(source: str, records: list[dict[str, object]]) -> None:
    original = _resolved(source, records)
    optimised = optimise_query(original).query
    assert [evaluate(original.predicate, record) for record in records] == [
        evaluate(optimised.predicate, record) for record in records
    ]
    assert apply_query(records, original) == apply_query(records, optimised)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("WHERE NOT NOT view_count >= 10", "WHERE view_count >= 10"),
        ("WHERE NOT view_count >= 10", "WHERE view_count < 10"),
        ("WHERE NOT view_count = 10", "WHERE view_count != 10"),
        ("WHERE NOT view_count BETWEEN 10 AND 20", "WHERE view_count NOT BETWEEN 10 AND 20"),
        ("WHERE NOT view_count IN (10, 20)", "WHERE view_count NOT IN (10, 20)"),
        ("WHERE NOT title CONTAINS 'x'", "WHERE title NOT CONTAINS 'x'"),
        ("WHERE NOT title LIKE 'x%'", "WHERE title NOT LIKE 'x%'"),
        ("WHERE NOT title ILIKE 'x%'", "WHERE title NOT ILIKE 'x%'"),
        ("WHERE NOT title IS NULL", "WHERE title IS NOT NULL"),
        ("WHERE view_count BETWEEN 10 AND 10", "WHERE view_count = 10"),
    ],
)
def test_normalisation_rewrites_to_simpler_equivalent_forms(source: str, expected: str) -> None:
    records = [{"id": "a", "view_count": 10, "title": "x"}]
    result = optimise_query(_resolved(source, records))
    assert format_query(result.query) == f"SELECT id {expected}"
    assert result.changed is True


def test_duplicate_predicates_are_removed_without_changing_unknown() -> None:
    records = [{"id": "missing"}, {"id": "low", "view_count": 5}, {"id": "high", "view_count": 50}]
    source = "WHERE view_count >= 10 AND view_count >= 10"
    result = optimise_query(_resolved(source, records))
    assert format_query(result.query) == "SELECT id WHERE view_count >= 10"
    _assert_equivalent(source, records)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("WHERE view_count >= 10 AND view_count >= 20", "WHERE view_count >= 20"),
        ("WHERE view_count > 10 AND view_count >= 10", "WHERE view_count > 10"),
        ("WHERE view_count <= 20 AND view_count < 20", "WHERE view_count < 20"),
        ("WHERE view_count >= 10 OR view_count >= 20", "WHERE view_count >= 10"),
        ("WHERE view_count > 10 OR view_count >= 10", "WHERE view_count >= 10"),
        ("WHERE view_count <= 20 OR view_count < 20", "WHERE view_count <= 20"),
        ("WHERE view_count = 20 AND view_count >= 10", "WHERE view_count = 20"),
        ("WHERE view_count = 20 OR view_count >= 10", "WHERE view_count >= 10"),
    ],
)
def test_bound_subsumption(source: str, expected: str) -> None:
    records = [
        {"id": "null", "view_count": None},
        {"id": "low", "view_count": 5},
        {"id": "edge", "view_count": 10},
        {"id": "middle", "view_count": 15},
        {"id": "high", "view_count": 20},
        {"id": "higher", "view_count": 25},
    ]
    result = optimise_query(_resolved(source, records))
    assert format_query(result.query) == f"SELECT id {expected}"
    _assert_equivalent(source, records)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("WHERE view_count IN (10, 10, 20)", "WHERE view_count IN (10, 20)"),
        ("WHERE view_count IN (10)", "WHERE view_count = 10"),
        ("WHERE view_count NOT IN (10)", "WHERE view_count != 10"),
        ("WHERE view_count IN (10, 20) AND view_count IN (10, 20, 30)", "WHERE view_count IN (10, 20)"),
        ("WHERE view_count IN (10, 20) OR view_count IN (10, 20, 30)", "WHERE view_count IN (10, 20, 30)"),
        ("WHERE view_count = 20 AND view_count IN (10, 20, 30)", "WHERE view_count = 20"),
        ("WHERE view_count = 20 OR view_count IN (10, 20, 30)", "WHERE view_count IN (10, 20, 30)"),
    ],
)
def test_membership_normalisation_and_subsumption(source: str, expected: str) -> None:
    records = [
        {"id": "null", "view_count": None},
        {"id": "ten", "view_count": 10},
        {"id": "twenty", "view_count": 20},
        {"id": "thirty", "view_count": 30},
        {"id": "other", "view_count": 99},
    ]
    result = optimise_query(_resolved(source, records))
    assert format_query(result.query) == f"SELECT id {expected}"
    _assert_equivalent(source, records)


def test_membership_subsumption_is_conservative_for_negated_lists() -> None:
    records = [{"id": "null", "view_count": None}, {"id": "ten", "view_count": 10}]
    query = _resolved("WHERE view_count NOT IN (10, 20) AND view_count NOT IN (10, 20, 30)", records)
    result = optimise_query(query)
    assert result.query.predicate == query.predicate
    assert apply_query(records, result.query) == apply_query(records, query)


def test_incompatible_equality_and_bound_are_not_folded_to_false() -> None:
    records = [{"id": "null", "view_count": None}, {"id": "five", "view_count": 5}]
    query = _resolved("WHERE view_count = 5 AND view_count > 10", records)
    result = optimise_query(query)
    assert result.query.predicate == query.predicate
    assert evaluate(query.predicate, records[0]) is None
    assert evaluate(result.query.predicate, records[0]) is None


@pytest.mark.parametrize(
    "source",
    [
        "WHERE view_count >= 10 AND view_count >= 20 AND view_count < 100",
        "WHERE view_count < 10 OR view_count <= 20 OR view_count <= 30",
        "WHERE NOT NOT (view_count >= 10 AND view_count >= 20)",
        "WHERE title IS NULL OR title IS NULL",
        "WHERE title CONTAINS 'science' AND title CONTAINS 'science'",
        "WHERE title LIKE 'science%' AND title LIKE 'science%'",
        "WHERE title ILIKE '%science%' OR title ILIKE '%science%'",
        "WHERE upload_date >= 2024-01-01 AND upload_date >= 2025-01-01",
        "WHERE release_timestamp >= 2024-01-01T00:00:00Z AND release_timestamp >= 2025-01-01T00:00:00Z",
        "WHERE upload_date > -INFINITY() AND upload_date >= 2024-01-01",
    ],
)
def test_optimised_and_unoptimised_execution_are_identical(source: str) -> None:
    records = [
        {"id": "nulls", "view_count": None, "title": None, "upload_date": None, "release_timestamp": None},
        {
            "id": "old",
            "view_count": 5,
            "title": "Old science",
            "upload_date": "20240101",
            "release_timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp(),
        },
        {
            "id": "middle",
            "view_count": 20,
            "title": "Science feature",
            "upload_date": "20250101",
            "release_timestamp": datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp(),
        },
        {
            "id": "new",
            "view_count": 120,
            "title": "New release",
            "upload_date": "20260101",
            "release_timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp(),
        },
    ]
    _assert_equivalent(source, records)


def test_optimiser_is_idempotent() -> None:
    records = [{"id": "a", "view_count": 20}, {"id": "b", "view_count": None}]
    first = optimise_query(_resolved("WHERE view_count >= 10 AND view_count >= 20 AND view_count >= 20", records))
    second = optimise_query(first.query)
    assert second.query == first.query
    assert second.decisions == ()


def test_query_shape_outside_predicate_is_untouched() -> None:
    records = [{"id": "a", "view_count": 20}, {"id": "b", "view_count": 10}]
    query = _resolved(
        "SELECT DISTINCT id FROM @example WHERE view_count >= 10 AND view_count >= 20 "
        "ORDER BY view_count DESC LIMIT 3 OFFSET 1",
        records,
    )
    result = optimise_query(query)
    assert result.query.select == query.select
    assert result.query.from_source == query.from_source
    assert result.query.order_by == query.order_by
    assert result.query.distinct == query.distinct
    assert result.query.limit == query.limit
    assert result.query.offset == query.offset


def test_decision_log_is_deterministic_and_human_readable() -> None:
    records = [{"id": "a", "view_count": 20}]
    result = optimise_query(_resolved("WHERE view_count >= 10 AND view_count >= 20", records))
    assert [(item.rule, item.before, item.after) for item in result.decisions] == [
        ("subsumed-and-predicate", "(view_count >= 10 AND view_count >= 20)", "view_count >= 20")
    ]


def test_constant_arithmetic_is_fully_folded() -> None:
    records = [{"id": "a"}]
    query = _resolved("SELECT 19 * 2 * 100 * 0 AS answer FROM @example", records)
    result = optimise_query(query)
    expression = result.query.select[0].expression
    assert isinstance(expression, Literal)
    assert expression.value == 0
    assert format_scalar_expression(expression) == "0"
    assert [item.rule for item in result.decisions] == [
        "fold-constant-arithmetic",
        "fold-constant-arithmetic",
        "fold-constant-arithmetic",
    ]
    assert apply_query(records, query) == apply_query(records, result.query)


@pytest.mark.parametrize(
    "source",
    [
        "SELECT -(-5) AS value FROM @example",
        "SELECT 1 + 2 * 3 AS value FROM @example",
        "SELECT (1 + 2) * 3 AS value FROM @example",
        "SELECT 7 / 2 AS value FROM @example",
        "SELECT 7 % 3 AS value FROM @example",
        "SELECT 1 / 0 AS value FROM @example",
        "SELECT 1 % 0 AS value FROM @example",
        "SELECT NULL * 0 AS value FROM @example",
        "SELECT LOWER('ABC') AS value FROM @example",
        "SELECT UPPER('abc') AS value FROM @example",
        "SELECT LENGTH('abc') AS value FROM @example",
        "SELECT COALESCE(NULL, NULL, 17) AS value FROM @example",
        "SELECT COALESCE(NULL, 'it''s fine') AS value FROM @example",
        "SELECT (2 + 3) * (4 - 1) / 5 AS value FROM @example",
    ],
)
def test_constant_folding_preserves_scalar_results(source: str) -> None:
    records = [{"id": "a"}, {"id": "b"}]
    original = _resolved(source, records)
    optimised = optimise_query(original).query
    for record in records:
        before = evaluate_scalar_expression(original.select[0].expression, record)
        after = evaluate_scalar_expression(optimised.select[0].expression, record)
        assert after == before
    assert apply_query(records, optimised) == apply_query(records, original)


def test_constant_folding_is_recursive_inside_case_results() -> None:
    records = [{"id": "a", "view_count": 20}, {"id": "b", "view_count": 2}]
    source = "SELECT CASE WHEN view_count >= 10 THEN 2 * 3 ELSE 9 - 4 END AS bucket FROM @example"
    original = _resolved(source, records)
    result = optimise_query(original)
    assert "THEN 6" in result.query.select[0].field
    assert "ELSE 5" in result.query.select[0].field
    assert apply_query(records, result.query) == apply_query(records, original)


def test_symbolic_zero_multiplication_is_not_folded() -> None:
    records = [{"id": "missing", "view_count": None}, {"id": "known", "view_count": 9}]
    query = _resolved("SELECT view_count * 0 AS value FROM @example", records)
    result = optimise_query(query)
    assert result.query.select[0].expression == query.select[0].expression
    assert result.decisions == ()
    assert apply_query(records, result.query) == apply_query(records, query)


def test_scalar_constant_folding_is_idempotent() -> None:
    records = [{"id": "a"}]
    first = optimise_query(_resolved("SELECT (1 + 2) * 3, LOWER('ABC') FROM @example", records))
    second = optimise_query(first.query)
    assert second.query == first.query
    assert second.decisions == ()
