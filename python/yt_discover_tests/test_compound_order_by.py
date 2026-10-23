"""Compound-result ORDER BY resolution and scope contract."""

import pytest

from yt_media_tools.query import QuerySyntaxError, apply_query, parse_query, query_physical_sources, resolve_query
from yt_media_tools.query_formatter import format_query
from yt_media_tools.schema import QuerySchema


def _records() -> list[dict[str, object]]:
    return [
        {"id": "a", "view_count": 10, "title": "Alpha", "_yt_sql_source": "@a"},
        {"id": "b", "view_count": 30, "title": "Beta", "_yt_sql_source": "@b"},
        {"id": "c", "view_count": 20, "title": "Gamma", "_yt_sql_source": "@b"},
    ]


def _resolve(text: str):
    records = _records()
    query = parse_query(text)
    source_schemas = {
        (source, None): QuerySchema([record for record in records if record.get("_yt_sql_source") == source])
        for source in query_physical_sources(query)
    }
    return records, resolve_query(query, QuerySchema(records), source_schemas=source_schemas)


def test_compound_order_by_exported_alias() -> None:
    records, query = _resolve(
        "SELECT id, view_count * 2 AS score FROM @a "
        "UNION ALL SELECT id, view_count * 2 AS ignored FROM @b "
        "ORDER BY score DESC"
    )
    assert [(row["id"], row["score"]) for row in apply_query(records, query)] == [
        ("b", 60),
        ("c", 40),
        ("a", 20),
    ]


def test_compound_order_by_expression_over_exported_alias() -> None:
    records, query = _resolve(
        "SELECT id, view_count * 2 AS score FROM @a "
        "UNION ALL SELECT id, view_count * 2 AS ignored FROM @b "
        "ORDER BY score + 1 DESC"
    )
    assert [row["id"] for row in apply_query(records, query)] == ["b", "c", "a"]


def test_compound_order_by_expression_over_exported_fields() -> None:
    records, query = _resolve(
        "SELECT id, title FROM @a UNION ALL SELECT id, title FROM @b ORDER BY LENGTH(title) DESC, id ASC"
    )
    assert [row["id"] for row in apply_query(records, query)] == ["a", "c", "b"]


def test_compound_order_by_cannot_reach_unexported_branch_field() -> None:
    with pytest.raises(QuerySyntaxError, match="Unknown field 'view_count'"):
        _resolve("SELECT id FROM @a UNION ALL SELECT id FROM @b ORDER BY view_count DESC")


@pytest.mark.parametrize(
    "text",
    [
        "SELECT id, title FROM @a ORDER BY 1",
        "SELECT id, title FROM @a UNION ALL SELECT id, title FROM @b ORDER BY 1",
        "(SELECT id, title FROM @a UNION ALL SELECT id, title FROM @b) ORDER BY 2 DESC",
    ],
)
def test_order_by_ordinals_are_rejected(text: str) -> None:
    with pytest.raises(QuerySyntaxError, match="ORDER BY ordinals are not supported"):
        _resolve(text)


def test_order_by_constant_expression_remains_a_scalar_expression() -> None:
    records, query = _resolve("SELECT id FROM @a UNION ALL SELECT id FROM @b ORDER BY 0x20 - 0b1")
    assert [row["id"] for row in apply_query(records, query)] == ["a", "b", "c"]


def test_compound_order_by_canonical_round_trip_preserves_expression() -> None:
    source = (
        "SELECT id, view_count * 2 AS score FROM @a "
        "UNION ALL SELECT id, view_count * 2 AS ignored FROM @b "
        "ORDER BY score + 1 DESC"
    )
    parsed = parse_query(source)
    canonical = format_query(parsed)
    assert canonical == (
        "SELECT id, view_count * 2 AS score\n"
        "FROM @a\n"
        "UNION ALL\n"
        "SELECT id, view_count * 2 AS ignored FROM @b\n"
        "ORDER BY score + 1 DESC"
    )
    assert format_query(parse_query(canonical)) == canonical
