"""JOIN Phase 6 executable INNER JOIN coverage."""

import pytest

from yt_media_tools.query import QuerySemanticError, apply_query, parse_query, resolve_query
from yt_media_tools.query_evaluator import canonical_record_value
from yt_media_tools.schema import QuerySchema


def _records() -> list[dict[str, object]]:
    return [
        {"id": "a", "title": "Alpha", "_yt_sql_source": "@left", "_yt_sql_source_facet": None},
        {"id": "b", "title": "Beta", "_yt_sql_source": "@left", "_yt_sql_source_facet": None},
        {"id": None, "title": "Null left", "_yt_sql_source": "@left", "_yt_sql_source_facet": None},
        {"id": "b", "tag": "first", "_yt_sql_source": "@right", "_yt_sql_source_facet": None},
        {"id": "b", "tag": "second", "_yt_sql_source": "@right", "_yt_sql_source_facet": None},
        {"id": None, "tag": "null", "_yt_sql_source": "@right", "_yt_sql_source_facet": None},
    ]


def _resolve(text: str):
    records = _records()
    left_records = [row for row in records if row["_yt_sql_source"] == "@left"]
    right_records = [row for row in records if row["_yt_sql_source"] == "@right"]
    schemas = {("@left", None): QuerySchema(left_records), ("@right", None): QuerySchema(right_records)}
    return records, resolve_query(parse_query(text), QuerySchema(records), source_schemas=schemas)


def _project(records, query):
    return [[canonical_record_value(record, term) for term in query.select] for record in records]


def test_inner_join_multiplies_duplicate_true_matches() -> None:
    records, query = _resolve("SELECT l.id, r.tag FROM @left AS l INNER JOIN @right AS r ON l.id = r.id")
    assert _project(apply_query(records, query), query) == [["b", "first"], ["b", "second"]]


def test_join_keyword_executes_as_inner_join() -> None:
    records, query = _resolve("SELECT l.title, r.tag FROM @left AS l JOIN @right AS r ON l.id = r.id")
    assert _project(apply_query(records, query), query) == [["Beta", "first"], ["Beta", "second"]]


def test_inner_join_does_not_match_unknown_null_comparison() -> None:
    records, query = _resolve("SELECT l.title, r.tag FROM @left AS l JOIN @right AS r ON l.id = r.id")
    assert [row for row in _project(apply_query(records, query), query) if row[0] == "Null left"] == []


def test_inner_join_right_fields_participate_in_where_order_and_limit() -> None:
    records, query = _resolve(
        "SELECT l.id, r.tag FROM @left AS l JOIN @right AS r ON l.id = r.id "
        "WHERE r.tag != 'first' ORDER BY r.tag DESC LIMIT 1"
    )
    assert _project(apply_query(records, query), query) == [["b", "second"]]


def test_inner_join_qualified_wildcard_exposes_right_relation() -> None:
    records, query = _resolve("SELECT r.* FROM @left AS l JOIN @right AS r ON l.id = r.id")
    rows = apply_query(records, query)
    output_names = [term.output_name for term in query.select]
    assert "id" in output_names
    assert "tag" in output_names
    id_index = output_names.index("id")
    tag_index = output_names.index("tag")
    projected = _project(rows, query)
    assert [[row[id_index], row[tag_index]] for row in projected] == [["b", "first"], ["b", "second"]]


def test_left_join_preserves_inner_matches_and_unmatched_left_rows() -> None:
    records, query = _resolve("SELECT l.id FROM @left AS l LEFT JOIN @right AS r ON l.id = r.id")
    assert _project(apply_query(records, query), query) == [["a"], ["b"], ["b"], [None]]


def test_multi_way_inner_join_remains_behind_execution_guard() -> None:
    records = _records()
    schemas = {
        ("@left", None): QuerySchema([row for row in records if row["_yt_sql_source"] == "@left"]),
        ("@right", None): QuerySchema([row for row in records if row["_yt_sql_source"] == "@right"]),
        ("@third", None): QuerySchema([{"id": "b"}]),
    }
    text = "SELECT l.id FROM @left AS l JOIN @right AS r ON l.id = r.id JOIN @third AS t ON r.id = t.id"
    with pytest.raises(QuerySemanticError, match="Multi-way JOIN execution is not implemented yet"):
        resolve_query(parse_query(text), QuerySchema(records), source_schemas=schemas)
