"""Conformance tests for total TRUE/FALSE/UNKNOWN truth-value inspection."""

from __future__ import annotations

from datetime import datetime, timezone

from yt_media_tools.dates import DateContext
from yt_media_tools.optimizer import optimise_query
from yt_media_tools.query import apply_query, format_expression, parse_query, resolve_query
from yt_media_tools.schema import QuerySchema

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
RECORDS = [
    {"id": "f", "is_live": False, "value": 1},
    {"id": "n", "is_live": None, "value": None},
    {"id": "t", "is_live": True, "value": 2},
]


def _resolve(source: str, records: list[dict] = RECORDS):
    return resolve_query(parse_query(source), QuerySchema(records), DateContext(now=NOW))


def _ids(predicate: str) -> list[str]:
    query = _resolve(f"SELECT id FROM @fixture WHERE {predicate} ORDER BY id ASC")
    return [record["id"] for record in apply_query(RECORDS, query)]


def test_boolean_field_truth_inspection_is_total() -> None:
    assert _ids("is_live IS TRUE") == ["t"]
    assert _ids("is_live IS NOT TRUE") == ["f", "n"]
    assert _ids("is_live IS FALSE") == ["f"]
    assert _ids("is_live IS NOT FALSE") == ["n", "t"]
    assert _ids("is_live IS UNKNOWN") == ["n"]
    assert _ids("is_live IS NOT UNKNOWN") == ["f", "t"]


def test_arbitrary_predicate_truth_inspection_observes_three_valued_result() -> None:
    assert _ids("(value = 2) IS TRUE") == ["t"]
    assert _ids("(value = 2) IS FALSE") == ["f"]
    assert _ids("(value = 2) IS UNKNOWN") == ["n"]
    assert _ids("(value = 2) IS NOT UNKNOWN") == ["f", "t"]


def test_compound_predicate_truth_inspection_preserves_boolean_semantics() -> None:
    assert _ids("(value = 2 OR is_live = FALSE) IS TRUE") == ["f", "t"]
    assert _ids("(value = 2 OR is_live = FALSE) IS UNKNOWN") == ["n"]


def test_truth_inspection_formats_canonically() -> None:
    field = _resolve("SELECT id FROM @fixture WHERE is_live IS UNKNOWN").predicate
    predicate = _resolve("SELECT id FROM @fixture WHERE (value = 2) IS NOT FALSE").predicate
    assert format_expression(field) == "is_live IS UNKNOWN"
    assert format_expression(predicate) == "(value = 2) IS NOT FALSE"


def test_truth_inspection_is_available_in_having() -> None:
    records = [{"id": "a", "uploader": "one"}, {"id": "b", "uploader": "one"}, {"id": "c", "uploader": "two"}]
    query = _resolve(
        "SELECT uploader, COUNT(*) AS n FROM @fixture GROUP BY uploader "
        "HAVING (COUNT(*) = 2) IS TRUE ORDER BY uploader ASC",
        records,
    )
    assert [record["uploader"] for record in apply_query(records, query)] == ["one"]


def test_constant_truth_inspection_can_be_optimised() -> None:
    query = _resolve("SELECT id FROM @fixture WHERE (NULL = TRUE) IS UNKNOWN")
    optimised = optimise_query(query).query
    assert apply_query(RECORDS, optimised) == RECORDS


def test_truth_inspection_composes_with_join_predicates() -> None:
    records = [
        {"id": None, "title": "left-null", "_yt_sql_source": "@left", "_yt_sql_source_facet": None},
        {"id": "x", "title": "left-x", "_yt_sql_source": "@left", "_yt_sql_source_facet": None},
        {"id": None, "tag": "right-null", "_yt_sql_source": "@right", "_yt_sql_source_facet": None},
        {"id": "x", "tag": "right-x", "_yt_sql_source": "@right", "_yt_sql_source_facet": None},
    ]
    schemas = {
        ("@left", None): QuerySchema([row for row in records if row["_yt_sql_source"] == "@left"]),
        ("@right", None): QuerySchema([row for row in records if row["_yt_sql_source"] == "@right"]),
    }
    query = resolve_query(
        parse_query("SELECT l.title FROM @left AS l JOIN @right AS r ON (l.id = r.id) IS TRUE ORDER BY l.title ASC"),
        QuerySchema(records),
        DateContext(now=NOW),
        source_schemas=schemas,
    )
    assert [record["title"] for record in apply_query(records, query)] == ["left-x"]
