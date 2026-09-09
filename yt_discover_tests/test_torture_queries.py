"""Deliberately pathological yt-sql parser and composition torture tests."""

from __future__ import annotations

from datetime import datetime, timezone
import re

import pytest

from yt_discover_tests.conformance.generate_dataset import PROFILE_SIZES, build_records
from yt_discover_tests.test_cross_facet_composition import SOURCE, SHORTS, VIDEOS, _records as cross_facet_records
from yt_media_tools.dates import DateContext
from yt_media_tools.metadata import normalise_record
from yt_media_tools.optimizer import optimise_query
from yt_media_tools.query import QuerySyntaxError, apply_query, format_query, parse_query, resolve_query
from yt_media_tools.schema import QuerySchema


CONTEXT = DateContext(date_order="dmy", now=datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc))


def _fixture_records() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, raw in enumerate(build_records(PROFILE_SIZES["small"]), start=1):
        record = normalise_record(raw)
        record["source_index"] = index
        record["_yt_sql_source"] = "@yt_sql_fixture"
        rows.append(record)
    return rows


def _resolve_fixture(text: str):
    rows = _fixture_records()
    schema = QuerySchema(rows)
    query = resolve_query(
        parse_query(text),
        schema,
        CONTEXT,
        source_schemas={("@yt_sql_fixture", None): schema},
    )
    return rows, query


def _resolve_cross_facet(text: str):
    rows = cross_facet_records()
    schemas = {
        (SOURCE, VIDEOS): QuerySchema([row for row in rows if row["_yt_sql_source_facet"] == VIDEOS]),
        (SOURCE, SHORTS): QuerySchema([row for row in rows if row["_yt_sql_source_facet"] == SHORTS]),
    }
    query = resolve_query(parse_query(text), QuerySchema(rows), CONTEXT, source_schemas=schemas)
    return rows, query


def test_hostile_whitespace_and_deep_parentheses_round_trip() -> None:
    source = (
        "\n\tSELECT\t id ,\n"
        "CASE WHEN (((title ILIKE '%mars%') AND (NOT ((duration IS NULL))))) "
        "THEN GREATEST(COALESCE(view_count, 0), 0x10) ELSE 0b1 END AS score\n"
        "FROM\t@yt_sql_fixture\n"
        "WHERE (((availability IN ('public','private','public')) AND "
        "((duration BETWEEN 0s AND 1d))) OR ((title LIKE 'Caf%') AND (view_count IS NOT NULL)))\n"
        "ORDER\tBY score DESC , id ASC LIMIT 12 OFFSET 2\n"
    )
    first = parse_query(source)
    canonical = format_query(first)
    second = parse_query(canonical)
    assert format_query(second) == canonical


def test_dense_scalar_boolean_query_is_optimiser_differential_and_idempotent() -> None:
    rows, query = _resolve_fixture(
        "SELECT id, CASE WHEN title ILIKE '%mars%' AND NOT (duration IS NULL) "
        "THEN GREATEST(COALESCE(view_count, 0), 0x10) ELSE 0b1 END AS score "
        "FROM @yt_sql_fixture "
        "WHERE ((availability IN ('public', 'private', 'public') AND duration BETWEEN 0s AND 1d) "
        "OR (title LIKE 'Caf%' AND view_count IS NOT NULL)) "
        "ORDER BY score DESC, id ASC LIMIT 12 OFFSET 2"
    )
    first = optimise_query(query)
    second = optimise_query(first.query)
    assert apply_query(rows, query) == apply_query(rows, first.query)
    assert second.query == first.query


def test_chained_cte_aggregate_torture_query() -> None:
    rows, query = _resolve_fixture(
        "WITH filtered AS ("
        "SELECT id, title, uploader, duration, view_count FROM @yt_sql_fixture "
        "WHERE (title ILIKE '%mars%' OR title CONTAINS 'Unicode') AND duration IS NOT NULL"
        "), grouped AS ("
        "SELECT uploader, COUNT(*) AS n, SUM(duration) AS total, AVG(view_count) AS avg_views "
        "FROM filtered GROUP BY uploader HAVING COUNT(*) >= 1"
        ") SELECT uploader, n, total, avg_views FROM grouped ORDER BY n DESC, uploader LIMIT 10"
    )
    result = apply_query(rows, query)
    assert result == [
        {
            "uploader": "Conformance Fixture",
            "n": 10,
            "total": 104729,
            "avg_views": 1214321.5,
        }
    ]


def test_sadness_query_crosses_facets_ctes_unicode_random_and_aggregation() -> None:
    rows, query = _resolve_cross_facet(
        "WITH media AS ("
        "SELECT id, title, duration, "
        "CASE WHEN title ILIKE '%form%' THEN duration + 0x10 ELSE COALESCE(duration, 0) END AS score "
        "FROM @whatdamath OF videos WHERE duration NOT BETWEEN 0s AND 1m OR title LIKE 'Cymru%' "
        "UNION ALL "
        "SELECT id, title, duration, "
        "CASE WHEN title ILIKE '%form%' THEN duration + 0b10 ELSE COALESCE(duration, 0) END AS score "
        "FROM @whatdamath OF shorts WHERE duration BETWEEN 0s AND 1m"
        "), seeded AS ("
        "SELECT id, title, score, RANDOM(31415926) AS r FROM media"
        ") SELECT "
        "CASE WHEN title LIKE 'Cymru%' THEN 'cymru' WHEN title LIKE 'AMV%' THEN 'unicode' ELSE 'other' END AS bucket, "
        "COUNT(*) AS n, SUM(score) AS total FROM seeded "
        "GROUP BY CASE WHEN title LIKE 'Cymru%' THEN 'cymru' WHEN title LIKE 'AMV%' THEN 'unicode' ELSE 'other' END "
        "HAVING COUNT(*) >= 1 ORDER BY n DESC, bucket"
    )
    expected = [
        {"bucket": "other", "n": 2, "total": 663},
        {"bucket": "cymru", "n": 1, "total": 300},
        {"bucket": "unicode", "n": 1, "total": 30},
    ]
    assert apply_query(rows, query) == expected
    optimised = optimise_query(query)
    assert apply_query(rows, optimised.query) == expected
    assert optimise_query(optimised.query).query == optimised.query


@pytest.mark.parametrize(
    ("source", "message"),
    (
        ("SELECT id FROM @yt_sql_fixture WHERE (((((((title = 'x'))))))", "Expected ')'"),
        ("SELECT id FROM @yt_sql_fixture WHERE title IN ('a',, 'b')", "Expected a value."),
        ("SELECT id FROM @yt_sql_fixture WHERE title BETWEEN 'a' OR 'b'", "Expected AND"),
        ("SELECT id FROM @yt_sql_fixture WHERE NOT NOT", "Expected a field name"),
        ("SELECT id FROM @yt_sql_fixture GROUP title", "Expected BY after GROUP."),
        (
            "SELECT id FROM @yt_sql_fixture GROUP BY title HAVING",
            "Expected a scalar field, literal, function, or parenthesised expression",
        ),
        ("SELECT id FROM @yt_sql_fixture ORDER BY id DESC ASC", "Unexpected token 'ASC'."),
        ("SELECT id FROM @yt_sql_fixture LIMIT 1 OFFSET 1 OFFSET 2", "Unexpected token"),
        ("WITH a AS () SELECT id FROM a", "CTE query cannot be empty."),
        ("WITH a AS (SELECT id FROM @yt_sql_fixture), SELECT id FROM a", "Expected AS after CTE name."),
        ("SELECT id FROM @yt_sql_fixture UNION", "UNION requires a SELECT query on both sides"),
        ("SELECT id FROM @yt_sql_fixture UNION ALL ORDER BY id", "UNION requires a SELECT query on both sides"),
        ("SELECT CASE WHEN title = 'x' THEN 1 FROM @yt_sql_fixture", "Expected END to close CASE expression"),
        ("SELECT CASE ELSE 1 END FROM @yt_sql_fixture", "Only searched CASE is supported"),
        ("SELECT COUNT(*) FILTER (WHERE) FROM @yt_sql_fixture", "Expected a field name."),
        ("SELECT RANDOM(1, 2) FROM @yt_sql_fixture", "RANDOM accepts zero or one seed argument"),
        (
            "SELECT id FROM @yt_sql_fixture -- comment",
            "Expected WHERE, GROUP BY, HAVING, ORDER BY, LIMIT, OFFSET, or end of query",
        ),
        ("SELECT CHAR(0x110000) FROM @yt_sql_fixture", "CHAR code points must be Unicode scalar values"),
    ),
)
def test_malformed_torture_inputs_fail_deterministically(source: str, message: str) -> None:
    with pytest.raises(QuerySyntaxError, match=re.escape(message)):
        _resolve_fixture(source)
