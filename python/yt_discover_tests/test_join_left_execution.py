"""JOIN Phase 7 part 2 executable LEFT JOIN coverage for issue #62."""

from yt_media_tools.query import apply_query, parse_query, resolve_query
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


def test_left_join_preserves_unmatched_left_rows_with_null_extended_right_fields() -> None:
    records, query = _resolve("SELECT l.id, l.title, r.tag FROM @left AS l LEFT JOIN @right AS r ON l.id = r.id")
    assert _project(apply_query(records, query), query) == [
        ["a", "Alpha", None],
        ["b", "Beta", "first"],
        ["b", "Beta", "second"],
        [None, "Null left", None],
    ]


def test_left_outer_join_spelling_executes_identically() -> None:
    records, query = _resolve("SELECT l.id, r.tag FROM @left AS l LEFT OUTER JOIN @right AS r ON l.id = r.id")
    assert _project(apply_query(records, query), query) == [["a", None], ["b", "first"], ["b", "second"], [None, None]]


def test_left_join_empty_right_relation_preserves_every_left_row_once() -> None:
    records = [row for row in _records() if row["_yt_sql_source"] == "@left"]
    right_schema = QuerySchema.from_field_infos(QuerySchema(_records()[3:]).available_fields())
    schemas = {("@left", None): QuerySchema(records), ("@right", None): right_schema}
    query = resolve_query(
        parse_query("SELECT l.title, r.tag FROM @left AS l LEFT JOIN @right AS r ON l.id = r.id"),
        QuerySchema(records),
        source_schemas=schemas,
    )
    assert _project(apply_query(records, query), query) == [["Alpha", None], ["Beta", None], ["Null left", None]]


def test_left_join_where_on_null_extended_right_field_observes_sql_null() -> None:
    records, query = _resolve("SELECT l.title FROM @left AS l LEFT JOIN @right AS r ON l.id = r.id WHERE r.tag IS NULL")
    assert _project(apply_query(records, query), query) == [["Alpha"], ["Null left"]]


def test_left_join_where_can_select_only_matched_right_rows() -> None:
    records, query = _resolve(
        "SELECT l.title, r.tag FROM @left AS l LEFT JOIN @right AS r ON l.id = r.id "
        "WHERE r.tag IS NOT NULL ORDER BY r.tag ASC"
    )
    assert _project(apply_query(records, query), query) == [["Beta", "first"], ["Beta", "second"]]


def test_left_join_qualified_wildcard_null_extends_dynamic_right_fields() -> None:
    records, query = _resolve("SELECT r.* FROM @left AS l LEFT JOIN @right AS r ON l.id = r.id")
    rows = apply_query(records, query)
    names = [term.output_name for term in query.select]
    tag_index = names.index("tag")
    projected = _project(rows, query)
    assert [row[tag_index] for row in projected] == [None, "first", "second", None]


def test_left_join_against_cte_preserves_unmatched_rows() -> None:
    text = (
        "WITH picked AS (SELECT id, tag FROM @right WHERE tag = 'second') "
        "SELECT l.title, p.tag FROM @left AS l LEFT JOIN picked AS p ON l.id = p.id"
    )
    records = _records()
    left = [row for row in records if row["_yt_sql_source"] == "@left"]
    right = [row for row in records if row["_yt_sql_source"] == "@right"]
    schemas = {("@left", None): QuerySchema(left), ("@right", None): QuerySchema(right)}
    query = resolve_query(parse_query(text), QuerySchema(records), source_schemas=schemas)
    assert _project(apply_query(records, query), query) == [["Alpha", None], ["Beta", "second"], ["Null left", None]]


def test_left_join_with_cte_backed_primary_relation_preserves_unmatched_rows() -> None:
    text = (
        "WITH primary_rows AS (SELECT id, title FROM @left WHERE title != 'Null left') "
        "SELECT p.title, r.tag FROM primary_rows AS p LEFT JOIN @right AS r ON p.id = r.id"
    )
    records = _records()
    left = [row for row in records if row["_yt_sql_source"] == "@left"]
    right = [row for row in records if row["_yt_sql_source"] == "@right"]
    schemas = {("@left", None): QuerySchema(left), ("@right", None): QuerySchema(right)}
    query = resolve_query(parse_query(text), QuerySchema(records), source_schemas=schemas)
    assert _project(apply_query(records, query), query) == [["Alpha", None], ["Beta", "first"], ["Beta", "second"]]


def test_left_join_empty_primary_relation_produces_no_rows() -> None:
    records = [row for row in _records() if row["_yt_sql_source"] == "@right"]
    left_schema = QuerySchema.from_field_infos(QuerySchema(_records()[:3]).available_fields())
    schemas = {("@left", None): left_schema, ("@right", None): QuerySchema(records)}
    query = resolve_query(
        parse_query("SELECT l.title, r.tag FROM @left AS l LEFT JOIN @right AS r ON l.id = r.id"),
        QuerySchema(records),
        source_schemas=schemas,
    )
    assert apply_query(records, query) == []
