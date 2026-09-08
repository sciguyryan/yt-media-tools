"""Unicode code-point construction coverage for yt-sql CHAR()."""

from __future__ import annotations

from datetime import datetime

import pytest

from yt_discover_tests.conformance.generate_dataset import GENERATED_AT, PROFILE_SIZES, build_records
from yt_media_tools.dates import DateContext
from yt_media_tools.metadata import normalise_record
from yt_media_tools.optimizer import optimise_query
from yt_media_tools.query import QuerySyntaxError, apply_query, evaluate_scalar_expression, parse_query, resolve_query
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


def test_char_constructs_unicode_scalar_values() -> None:
    assert _project("SELECT CHAR(65) AS value FROM @yt_sql_fixture LIMIT 1") == "A"
    assert _project("SELECT CHAR(233) AS value FROM @yt_sql_fixture LIMIT 1") == "é"
    assert _project("SELECT CHAR(128512) AS value FROM @yt_sql_fixture LIMIT 1") == "😀"
    assert _project("SELECT CHAR(66376) AS value FROM @yt_sql_fixture LIMIT 1") == "𐍈"


def test_char_concatenates_multiple_codepoints_without_normalising() -> None:
    assert _project("SELECT CHAR(101, 769) AS value FROM @yt_sql_fixture LIMIT 1") == "e\u0301"
    assert _project("SELECT LENGTH(CHAR(101, 769)) AS value FROM @yt_sql_fixture LIMIT 1") == 2
    assert _project("SELECT CHAR(233) AS value FROM @yt_sql_fixture LIMIT 1") != _project(
        "SELECT CHAR(101, 769) AS value FROM @yt_sql_fixture LIMIT 1"
    )


def test_char_accepts_integer_valued_scalar_expressions() -> None:
    assert _project("SELECT CHAR(60 + 5, 32, (70 - 4)) AS value FROM @yt_sql_fixture LIMIT 1") == "A B"


def test_char_null_propagates() -> None:
    assert _project("SELECT CHAR(NULL) AS value FROM @yt_sql_fixture LIMIT 1") is None
    assert _project("SELECT CHAR(65, NULL, 66) AS value FROM @yt_sql_fixture LIMIT 1") is None


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


def test_char_can_construct_pattern_text_for_existing_text_functions() -> None:
    assert _project("SELECT LOWER(CHAR(931)) AS value FROM @yt_sql_fixture LIMIT 1") == "σ"
    assert _project("SELECT UPPER(CHAR(223)) AS value FROM @yt_sql_fixture LIMIT 1") == "SS"
