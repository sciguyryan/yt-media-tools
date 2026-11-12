"""Unicode code-point construction coverage for yt-sql CHAR()."""

from __future__ import annotations

from datetime import datetime

import pytest

from yt_discover_tests.conformance.generate_dataset import GENERATED_AT
from yt_discover_tests.conformance.test_records import cached_records
from yt_media_tools.dates import DateContext
from yt_media_tools.metadata import normalise_record
from yt_media_tools.optimizer import optimise_query
from yt_media_tools.query import QuerySyntaxError, apply_query, evaluate_scalar_expression, parse_query, resolve_query
from yt_media_tools.schema import QuerySchema


def _records() -> list[dict[str, object]]:
    records = []
    for source_index, raw in enumerate(cached_records("small"), start=1):
        record = normalise_record(dict(raw))
        record["source_index"] = source_index
        records.append(record)
    return records


def _resolve(query: str):
    records = _records()
    parsed = parse_query(query)
    resolved = resolve_query(
        parsed,
        QuerySchema(records),
        DateContext(date_order="dmy", now=datetime.fromisoformat(GENERATED_AT)),
    )
    return records, resolved


def _project(query: str) -> object:
    records, resolved = _resolve(query)
    row = apply_query(records, resolved)[0]
    return evaluate_scalar_expression(resolved.select[0].expression, row)


def test_char_concatenates_multiple_codepoints_without_normalising() -> None:
    assert _project("SELECT CHAR(101, 769) AS value FROM @yt_sql_fixture LIMIT 1") == "e\u0301"
    assert _project("SELECT LENGTH(CHAR(101, 769)) AS value FROM @yt_sql_fixture LIMIT 1") == 2
    assert _project("SELECT CHAR(233) AS value FROM @yt_sql_fixture LIMIT 1") != _project(
        "SELECT CHAR(101, 769) AS value FROM @yt_sql_fixture LIMIT 1"
    )


@pytest.mark.parametrize(
    ("query", "message"),
    (
        ("SELECT CHAR() FROM @yt_sql_fixture", "CHAR requires at least one argument"),
        ("SELECT CHAR('A') FROM @yt_sql_fixture", "CHAR requires integer code-point values"),
        ("SELECT CHAR(65.5) FROM @yt_sql_fixture", "CHAR requires integer code-point values"),
        ("SELECT CHAR(-1) FROM @yt_sql_fixture", "Unicode scalar values"),
        ("SELECT CHAR(55296) FROM @yt_sql_fixture", "Unicode scalar values"),
        ("SELECT CHAR(57343) FROM @yt_sql_fixture", "Unicode scalar values"),
        ("SELECT CHAR(1114112) FROM @yt_sql_fixture", "Unicode scalar values"),
        ("SELECT CHAR(1114111 + 1) FROM @yt_sql_fixture", "Unicode scalar values"),
    ),
)
def test_char_rejects_invalid_constant_arguments(query: str, message: str) -> None:
    with pytest.raises(QuerySyntaxError, match=message):
        _resolve(query)


def test_char_constant_folding_is_observationally_equivalent() -> None:
    records, resolved = _resolve(
        "SELECT CHAR(65, 946, 128512) AS value FROM @yt_sql_fixture ORDER BY CHAR(66 - 1) LIMIT 1"
    )
    result = optimise_query(resolved)
    assert apply_query(records, result.query) == apply_query(records, resolved)
    assert result.query.select[0].field == "'Aβ😀'"
    assert result.query.order_by[0].field == "'A'"
    assert any(decision.rule == "fold-constant-function" for decision in result.decisions)
