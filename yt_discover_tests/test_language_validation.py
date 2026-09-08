"""Negative and boundary validation for the currently supported yt-sql grammar."""

from __future__ import annotations

from datetime import datetime, timezone
import re

import pytest

from yt_discover_tests.conformance.generate_dataset import PROFILE_SIZES, build_records
from yt_media_tools.dates import DateContext
from yt_media_tools.metadata import normalise_record
from yt_media_tools.query import QuerySyntaxError, parse_query, resolve_query
from yt_media_tools.schema import QuerySchema


def _dataset_schema() -> QuerySchema:
    records = []
    for index, raw in enumerate(build_records(PROFILE_SIZES["small"]), start=1):
        record = normalise_record(raw)
        record["source_index"] = index
        records.append(record)
    return QuerySchema(records)


def _resolve(text: str) -> None:
    resolve_query(
        parse_query(text),
        _dataset_schema(),
        DateContext(date_order="dmy", now=datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)),
    )


@pytest.mark.parametrize(
    ("query", "message"),
    (
        ("SELECT", "Expected a scalar field"),
        (
            "SELECT id, FROM @yt_sql_fixture",
            "Expected WHERE, GROUP BY, HAVING, ORDER BY, LIMIT, OFFSET, or end of query",
        ),
        ("SELECT MAGIC(title) FROM @yt_sql_fixture", "Unsupported scalar function"),
        ("SELECT LOWER(title, id) FROM @yt_sql_fixture", "LOWER requires exactly one argument"),
        ("SELECT UPPER() FROM @yt_sql_fixture", "UPPER requires exactly one argument"),
        ("SELECT LENGTH(title, id) FROM @yt_sql_fixture", "LENGTH requires exactly one argument"),
        ("SELECT COALESCE(title) FROM @yt_sql_fixture", "COALESCE requires at least two arguments"),
        ("FROM", "Expected a channel/playlist identifier"),
        ("FROM https://example.invalid/x", "Unexpected character"),
        ("SELECT id FROM @yt_sql_fixture OF", "OF requires a collection/facet name"),
        ("SELECT id FROM @yt_sql_fixture OF 'videos'", "OF requires a collection/facet name"),
        ("SELECT id FROM @yt_sql_fixture WHERE", "WHERE requires an expression"),
        ("SELECT id FROM @yt_sql_fixture ORDER", "Expected BY after ORDER"),
        (
            "SELECT id FROM @yt_sql_fixture ORDER BY",
            "Expected a scalar field, literal, function, or parenthesised expression",
        ),
        ("SELECT id FROM @yt_sql_fixture LIMIT 0", "LIMIT must be greater than zero"),
        ("SELECT id FROM @yt_sql_fixture LIMIT -1", "LIMIT requires a positive integer"),
        ("SELECT id FROM @yt_sql_fixture LIMIT 1.5", "LIMIT requires a positive integer"),
        ("SELECT id FROM @yt_sql_fixture OFFSET -1", "OFFSET requires a non-negative integer"),
        ("SELECT id FROM @yt_sql_fixture OFFSET 1.5", "OFFSET requires a non-negative integer"),
        ("SELECT id FROM @yt_sql_fixture WHERE (view_count = 1", "Expected ')'"),
        ("SELECT id FROM @yt_sql_fixture WHERE duration BETWEEN 1m 2m", "Expected AND"),
        ("SELECT id FROM @yt_sql_fixture WHERE availability IN ()", "IN requires at least one value"),
        ("SELECT id FROM @yt_sql_fixture WHERE availability IN ('public'", "Expected ')' after IN values"),
        ("SELECT id FROM @yt_sql_fixture WHERE is_live IS MAYBE", "Expected NULL, TRUE, or FALSE after IS"),
        ("SELECT id FROM @yt_sql_fixture WHERE title DOES CONTAIN 'Mars'", "Expected NOT after DOES"),
        ("SELECT id FROM @yt_sql_fixture WHERE title DOES NOT EQUAL 'Mars'", "Expected CONTAIN, MATCH, LIKE, or ILIKE"),
        ("SELECT id FROM @yt_sql_fixture WHERE title NOT = 'Mars'", "NOT must be followed"),
        ("SELECT id FROM @yt_sql_fixture WHERE title MATCHES '[unterminated'", "Invalid regular expression"),
        ("SELECT id FROM @yt_sql_fixture WHERE title = 'unterminated", "Unexpected character"),
    ),
)
def test_parser_rejects_malformed_supported_syntax(query: str, message: str) -> None:
    with pytest.raises(QuerySyntaxError, match=re.escape(message)):
        parse_query(query)


@pytest.mark.parametrize(
    ("query", "message"),
    (
        ("SELECT id FROM @yt_sql_fixture WHERE view_count = NULL", "Use IS NULL or IS NOT NULL"),
        ("SELECT id FROM @yt_sql_fixture WHERE duraton < 1h", "Unknown field 'duraton'"),
        ("SELECT id FROM @yt_sql_fixture WHERE raw.formats = 1", "Unknown field 'raw.formats'"),
        ("SELECT id FROM @yt_sql_fixture WHERE view_count CONTAINS '1'", "CONTAINS requires a text field"),
        ("SELECT id FROM @yt_sql_fixture WHERE is_live = maybe", "requires TRUE or FALSE"),
        ("SELECT id FROM @yt_sql_fixture WHERE fixture_group = 1.5", "requires an integer"),
        ("SELECT id FROM @yt_sql_fixture WHERE duration = 1200", "A duration needs a unit"),
        ("SELECT id FROM @yt_sql_fixture WHERE duration = 1:60", "Duration seconds must be below 60"),
        ("SELECT id FROM @yt_sql_fixture WHERE duration = 1:60:00", "Duration minutes and seconds must be below 60"),
        ("SELECT id FROM @yt_sql_fixture WHERE duration = 1nonesuch", "Unknown duration unit"),
        ("SELECT id FROM @yt_sql_fixture WHERE duration = 1 month", "cannot be used for a duration"),
        ("SELECT id FROM @yt_sql_fixture WHERE upload_date = 2026-02-30", "Invalid date"),
        ("SELECT id FROM @yt_sql_fixture WHERE upload_date = NOW()", "NOW() produces a timestamp"),
        ("SELECT id FROM @yt_sql_fixture WHERE release_timestamp = TODAY()", "TODAY() produces a date"),
        ("SELECT id FROM @yt_sql_fixture WHERE upload_date = TODAY()-1h", "does not support sub-day unit"),
        ("SELECT id FROM @yt_sql_fixture WHERE upload_date = TODAY()-1.5month", "requires a whole number of months"),
        (
            "SELECT id FROM @yt_sql_fixture WHERE release_timestamp = not-a-timestamp",
            "Could not understand the timestamp",
        ),
        ("SELECT title, id AS title FROM @yt_sql_fixture", "Duplicate SELECT output name"),
        ("SELECT LOWER(view_count) FROM @yt_sql_fixture", "LOWER requires a text field"),
    ),
)
def test_semantic_resolution_rejects_invalid_values_against_dataset(query: str, message: str) -> None:
    with pytest.raises(QuerySyntaxError, match=re.escape(message)):
        _resolve(query)
