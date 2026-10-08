"""Language-only contract for the deferred final-result POSITION expression."""

import pytest

from yt_media_tools.query_formatter import format_query
from yt_media_tools.query_model import QuerySemanticError, QuerySyntaxError, ScalarFunction
from yt_media_tools.query_parser import parse_query
from yt_media_tools.query_resolver import resolve_query
from yt_media_tools.schema import QuerySchema


def test_position_projection_parses_and_canonicalises():
    query = parse_query("SELECT POSITION() AS position, id FROM @fixture ORDER BY id LIMIT 3 OFFSET 2")
    assert isinstance(query.select[0].expression, ScalarFunction)
    assert query.select[0].expression.name == "POSITION"
    canonical = format_query(query)
    assert "POSITION()" in canonical
    assert format_query(parse_query(canonical)) == canonical
    resolved = resolve_query(query, QuerySchema([{"id": "a"}]))
    assert resolved.select[0].kind == "integer"


@pytest.mark.parametrize("expression", ["POSITION(1)", "POSITION(id)", "POSITION(1, 2)"])
def test_position_requires_zero_arguments(expression):
    with pytest.raises(QuerySyntaxError, match="POSITION requires no arguments"):
        parse_query(f"SELECT {expression} FROM @fixture")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id FROM @fixture WHERE POSITION() > 0",
        "SELECT id FROM @fixture ORDER BY POSITION()",
        "SELECT POSITION() + 1 FROM @fixture",
        "SELECT COALESCE(POSITION(), 1) FROM @fixture",
        "SELECT id FROM @fixture GROUP BY POSITION()",
    ],
)
def test_position_is_rejected_outside_standalone_projection(sql):
    query = parse_query(sql)
    with pytest.raises((QuerySemanticError, QuerySyntaxError), match="POSITION"):
        resolve_query(query, QuerySchema([{"id": "a"}]))


def test_position_numbers_after_ordering_before_offset_and_limit():
    from yt_media_tools.query_evaluator import apply_query

    records = [{"id": "c"}, {"id": "a"}, {"id": "d"}, {"id": "b"}]
    sql = "SELECT POSITION() AS position, id FROM @fixture ORDER BY id ASC LIMIT 2 OFFSET 1"
    resolved = resolve_query(parse_query(sql), QuerySchema(records))
    result = apply_query(records, resolved)
    assert [(row["position"], row["id"]) for row in result] == [(2, "b"), (3, "c")]
    assert all("position" not in row for row in records)


def test_position_is_deferred_until_after_distinct():
    from yt_media_tools.query_evaluator import apply_query

    records = [{"title": "a"}, {"title": "a"}, {"title": "b"}]
    sql = "SELECT DISTINCT POSITION() AS position, title FROM @fixture ORDER BY title ASC"
    resolved = resolve_query(parse_query(sql), QuerySchema(records))
    result = apply_query(records, resolved)
    assert [(row["position"], row["title"]) for row in result] == [(1, "a"), (2, "b")]


def test_position_numbers_aggregate_result():
    from yt_media_tools.query_evaluator import apply_query

    records = [{"title": "b"}, {"title": "a"}, {"title": "b"}]
    sql = "SELECT POSITION() AS position, title, COUNT(*) AS total FROM @fixture GROUP BY title ORDER BY title ASC"
    resolved = resolve_query(parse_query(sql), QuerySchema(records))
    result = apply_query(records, resolved)
    assert [(row["position"], row["total"]) for row in result] == [(1, 1), (2, 2)]


def test_position_alias_cannot_order_the_result():
    query = parse_query("SELECT POSITION() AS position, id FROM @fixture ORDER BY position")
    with pytest.raises(QuerySemanticError, match="ORDER BY cannot depend"):
        resolve_query(query, QuerySchema([{"id": "a"}]))
