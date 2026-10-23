"""Coverage for volatile and deterministically seeded RANDOM()."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from yt_media_tools.dates import DateContext
from yt_media_tools.optimizer import optimise_query
from yt_media_tools.query import QuerySyntaxError, apply_query, canonical_record_value, parse_query, resolve_query
from yt_media_tools.schema import QuerySchema


RECORDS = [
    {"id": "a", "title": "Alpha", "duration": 10},
    {"id": "b", "title": "Beta", "duration": 20},
    {"id": "c", "title": "Cymru 🏴\U000e0067\U000e0062\U000e0077\U000e006c\U000e0073\U000e007f", "duration": 30},
    {"id": "d", "title": "Delta", "duration": 40},
]


def _resolve(source: str):
    return resolve_query(
        parse_query(source),
        QuerySchema(RECORDS),
        DateContext(now=datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)),
    )


def test_random_projects_synthetic_number_column() -> None:
    query = _resolve("SELECT id, RANDOM() AS shuffle_key FROM @fixture ORDER BY shuffle_key")
    rows = apply_query([dict(row) for row in RECORDS], query)
    assert {row["id"] for row in rows} == {"a", "b", "c", "d"}
    values = [canonical_record_value(row, query.select[1]) for row in rows]
    assert all(0.0 <= value < 1.0 for value in values)
    assert values == sorted(values)


def test_random_alias_reuses_same_value_for_ordering() -> None:
    query = _resolve("SELECT id, RANDOM() AS r FROM @fixture ORDER BY r")
    rows = apply_query([dict(row) for row in RECORDS], query)
    values = [canonical_record_value(row, query.select[1]) for row in rows]
    assert values == sorted(values)


def test_unseeded_random_is_volatile_between_executions() -> None:
    query = _resolve("SELECT id, RANDOM() AS r FROM @fixture ORDER BY id")
    first = apply_query([dict(row) for row in RECORDS], query)
    first_values = [canonical_record_value(row, query.select[1]) for row in first]
    second = apply_query([dict(row) for row in RECORDS], query)
    second_values = [canonical_record_value(row, query.select[1]) for row in second]
    assert first_values != second_values


def test_seeded_random_is_reproducible_and_row_stable() -> None:
    query = _resolve("SELECT id, RANDOM(0xC0FFEE) AS r FROM @fixture ORDER BY id")
    first = apply_query([dict(row) for row in RECORDS], query)
    second = apply_query(list(reversed([dict(row) for row in RECORDS])), query)
    assert [row["id"] for row in first] == [row["id"] for row in second]
    first_values = [canonical_record_value(row, query.select[1]) for row in first]
    second_values = [canonical_record_value(row, query.select[1]) for row in second]
    assert first_values == second_values
    assert len(set(first_values)) == len(RECORDS)


def test_seeded_random_can_shuffle_reproducibly() -> None:
    query = _resolve("SELECT id FROM @fixture ORDER BY RANDOM(31415926) LIMIT 3")
    first = apply_query([dict(row) for row in RECORDS], query)
    second = apply_query(list(reversed([dict(row) for row in RECORDS])), query)
    assert first == second
    assert len(first) == 3


def test_random_survives_cte_and_union_projection() -> None:
    records = [
        {"id": "a", "_yt_sql_source": "@one"},
        {"id": "b", "_yt_sql_source": "@one"},
        {"id": "c", "_yt_sql_source": "@two"},
    ]
    parsed = parse_query(
        "WITH mixed AS (SELECT id FROM @one UNION ALL SELECT id FROM @two) "
        "SELECT id, RANDOM(42) AS r FROM mixed ORDER BY r"
    )
    schema = QuerySchema(records)
    resolved = resolve_query(parsed, schema, source_schemas={("@one", None): schema, ("@two", None): schema})
    rows = apply_query(records, resolved)
    assert [row["r"] for row in rows] == sorted(row["r"] for row in rows)
    assert {row["id"] for row in rows} == {"a", "b", "c"}


@pytest.mark.parametrize(
    "source",
    (
        "SELECT id FROM @fixture GROUP BY RANDOM()",
        "SELECT COUNT(*) FROM @fixture HAVING RANDOM() > 0.5",
    ),
)
def test_random_rejects_disallowed_aggregate_placements(source: str) -> None:
    with pytest.raises(QuerySyntaxError, match="RANDOM"):
        _resolve(source)


@pytest.mark.parametrize(
    "source",
    (
        "SELECT RANDOM(1, 2) FROM @fixture",
        "SELECT RANDOM('seed') FROM @fixture",
        "SELECT RANDOM(duration) FROM @fixture",
        "SELECT RANDOM(1.5) FROM @fixture",
    ),
)
def test_random_rejects_invalid_seed_forms(source: str) -> None:
    with pytest.raises(QuerySyntaxError, match="RANDOM"):
        _resolve(source)


def test_optimizer_never_constant_folds_random() -> None:
    query = _resolve("SELECT RANDOM(42) AS r FROM @fixture ORDER BY RANDOM(42)")
    result = optimise_query(query)
    assert "RANDOM(42)" in result.query.select[0].field
    assert "RANDOM(42)" in result.query.order_by[0].field
    assert not any(decision.rule == "fold-constant-function" for decision in result.decisions)
