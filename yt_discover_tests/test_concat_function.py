"""Text concatenation coverage for yt-sql CONCAT()."""

from __future__ import annotations

from datetime import datetime

import pytest

from yt_discover_tests.conformance.generate_dataset import GENERATED_AT, PROFILE_SIZES, build_records
from yt_media_tools.dates import DateContext
from yt_media_tools.metadata import normalise_record
from yt_media_tools.optimizer import optimise_query
from yt_media_tools.query import QuerySyntaxError, apply_query, canonical_record_value, parse_query, resolve_query
from yt_media_tools.schema import QuerySchema


def _records() -> list[dict[str, object]]:
    records = []
    for source_index, raw in enumerate(build_records(PROFILE_SIZES["small"]), start=1):
        record = normalise_record(dict(raw))
        record["source_index"] = source_index
        records.append(record)
    return records


def _resolve(query: str):
    records = _records()
    resolved = resolve_query(
        parse_query(query),
        QuerySchema(records),
        DateContext(date_order="dmy", now=datetime.fromisoformat(GENERATED_AT)),
    )
    return records, resolved


def _project(query: str) -> object:
    records, resolved = _resolve(query)
    row = apply_query(records, resolved)[0]
    return canonical_record_value(row, resolved.select[0])


def test_concat_joins_text_in_argument_order() -> None:
    assert _project("SELECT CONCAT('video', ' # ', 'title') AS value FROM @yt_sql_fixture LIMIT 1") == "video # title"
    assert _project("SELECT CONCAT('a', '', 'b', 'c') AS value FROM @yt_sql_fixture LIMIT 1") == "abc"


def test_concat_propagates_null() -> None:
    assert _project("SELECT CONCAT('a', NULL, 'b') AS value FROM @yt_sql_fixture LIMIT 1") is None


@pytest.mark.parametrize(
    ("query", "message"),
    (
        ("SELECT CONCAT('a') FROM @yt_sql_fixture", "CONCAT requires at least two arguments"),
        ("SELECT CONCAT() FROM @yt_sql_fixture", "CONCAT requires at least two arguments"),
        ("SELECT CONCAT('a', 1) FROM @yt_sql_fixture", "CONCAT requires text values"),
    ),
)
def test_concat_rejects_invalid_arity_or_types(query: str, message: str) -> None:
    with pytest.raises(QuerySyntaxError, match=message):
        _resolve(query)


def test_concat_supports_field_projection_and_ordering() -> None:
    records, resolved = _resolve(
        "SELECT CONCAT(id, ' # ', title) AS annotated FROM @yt_sql_fixture "
        "WHERE source_index <= 5 ORDER BY CONCAT(title, ' ', id), source_index"
    )
    selected = apply_query(records, resolved)
    assert selected
    assert all(" # " in canonical_record_value(row, resolved.select[0]) for row in selected)


def test_concat_constant_folds() -> None:
    records, resolved = _resolve("SELECT CONCAT('a', ' # ', 'b') AS value FROM @yt_sql_fixture LIMIT 1")
    optimised = optimise_query(resolved)
    assert apply_query(records, optimised.query) == apply_query(records, resolved)
    assert optimised.query.select[0].field == "'a # b'"
    assert any(decision.rule == "fold-constant-function" for decision in optimised.decisions)
