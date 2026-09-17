"""JOIN Phase 5 executable SEMI and ANTI join coverage."""

import pytest

from yt_media_tools.query import (
    QuerySemanticError,
    apply_query,
    parse_query,
    query_physical_source_requests,
    resolve_query,
)
from yt_media_tools.schema import QuerySchema


def _records() -> list[dict[str, object]]:
    return [
        {"id": "a", "title": "Alpha", "_yt_sql_source": "@left", "_yt_sql_source_facet": None},
        {"id": "b", "title": "Beta", "_yt_sql_source": "@left", "_yt_sql_source_facet": None},
        {"id": None, "title": "Null left", "_yt_sql_source": "@left", "_yt_sql_source_facet": None},
        {"id": "b", "_yt_sql_source": "@right", "_yt_sql_source_facet": None},
        {"id": "b", "_yt_sql_source": "@right", "_yt_sql_source_facet": None},
        {"id": None, "_yt_sql_source": "@right", "_yt_sql_source_facet": None},
    ]


def _resolve(text: str):
    records = _records()
    left_records = [row for row in records if row["_yt_sql_source"] == "@left"]
    right_records = [row for row in records if row["_yt_sql_source"] == "@right"]
    schemas = {("@left", None): QuerySchema(left_records), ("@right", None): QuerySchema(right_records)}
    return records, resolve_query(parse_query(text), QuerySchema(records), source_schemas=schemas)


def test_join_sources_participate_in_physical_acquisition_requests() -> None:
    query = parse_query("SELECT l.id FROM @left AS l SEMI JOIN @right AS r ON l.id = r.id")
    assert query_physical_source_requests(query) == (("@left", None), ("@right", None))


def test_semi_join_returns_each_matching_left_row_once() -> None:
    records, query = _resolve("SELECT l.id FROM @left AS l SEMI JOIN @right AS r ON l.id = r.id")
    assert [row["id"] for row in apply_query(records, query)] == ["b"]


def test_anti_join_returns_only_left_rows_without_true_match() -> None:
    records, query = _resolve("SELECT l.id FROM @left AS l ANTI JOIN @right AS r ON l.id = r.id")
    assert [row["id"] for row in apply_query(records, query)] == ["a", None]


def test_existence_join_preserves_left_side_where_and_projection() -> None:
    records, query = _resolve(
        "SELECT l.title FROM @left AS l ANTI JOIN @right AS r ON l.id = r.id WHERE l.title != 'Null left'"
    )
    assert [row["title"] for row in apply_query(records, query)] == ["Alpha"]


def test_semi_join_does_not_expose_right_relation_projection() -> None:
    with pytest.raises(QuerySemanticError, match="SEMI JOIN does not expose fields from relation 'r'"):
        _resolve("SELECT r.id FROM @left AS l SEMI JOIN @right AS r ON l.id = r.id")


def test_inner_join_remains_behind_execution_guard() -> None:
    with pytest.raises(QuerySemanticError, match="JOIN execution is not implemented yet"):
        _resolve("SELECT l.id FROM @left AS l INNER JOIN @right AS r ON l.id = r.id")


def test_left_join_remains_behind_execution_guard() -> None:
    with pytest.raises(QuerySemanticError, match="JOIN execution is not implemented yet"):
        _resolve("SELECT l.id FROM @left AS l LEFT JOIN @right AS r ON l.id = r.id")
