"""Compound-query grouping, branch scope and outer-result semantics."""

from __future__ import annotations

import pytest

from yt_media_tools.dates import DateContext
from yt_media_tools.query_evaluator import apply_query
from yt_media_tools.query_formatter import format_query
from yt_media_tools.query_model import QuerySyntaxError
from yt_media_tools.query_parser import parse_query
from yt_media_tools.query_resolver import resolve_query
from yt_media_tools.query_semantics import query_physical_source_requests, semantic_key
from yt_media_tools.schema import QuerySchema


def _records() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for source, prefix in (("@a", "a"), ("@b", "b")):
        for index, upload_date in ((1, "20240101"), (3, "20240301"), (2, "20240201")):
            rows.append(
                {
                    "id": f"{prefix}{index}",
                    "upload_date": upload_date,
                    "_yt_sql_source": source,
                    "_yt_sql_source_facet": None,
                }
            )
    return rows


def _resolve(source: str):
    records = _records()
    return records, resolve_query(parse_query(source), QuerySchema(records), DateContext())


def test_parenthesised_union_branches_retain_local_order_and_limit() -> None:
    source = (
        "(SELECT id FROM @a ORDER BY upload_date DESC LIMIT 2) "
        "UNION ALL "
        "(SELECT id FROM @b ORDER BY upload_date DESC LIMIT 2) "
        "ORDER BY id ASC"
    )
    records, query = _resolve(source)
    assert apply_query(records, query) == [{"id": "a2"}, {"id": "a3"}, {"id": "b2"}, {"id": "b3"}]


def test_outer_limit_applies_after_grouped_branch_limits() -> None:
    source = (
        "(SELECT id FROM @a ORDER BY upload_date DESC LIMIT 2) "
        "UNION ALL "
        "(SELECT id FROM @b ORDER BY upload_date DESC LIMIT 2) "
        "ORDER BY id ASC LIMIT 3 OFFSET 1"
    )
    records, query = _resolve(source)
    assert apply_query(records, query) == [{"id": "a3"}, {"id": "b2"}, {"id": "b3"}]


def test_grouped_branch_supports_standalone_offset_before_outer_slicing() -> None:
    source = (
        "(SELECT id FROM @a ORDER BY upload_date ASC OFFSET 1) "
        "UNION ALL (SELECT id FROM @b ORDER BY upload_date ASC LIMIT 1) "
        "ORDER BY id ASC LIMIT 2 OFFSET 1"
    )
    records, query = _resolve(source)
    assert apply_query(records, query) == [{"id": "a3"}, {"id": "b1"}]
    assert format_query(parse_query(format_query(query))) == format_query(query)


def test_parenthesised_compound_branch_nests_without_flattening() -> None:
    source = "SELECT id FROM @a UNION ALL (SELECT id FROM @b UNION SELECT id FROM @a LIMIT 2) ORDER BY id ASC"
    query = parse_query(source)
    assert query.set_operations[0].grouped
    assert query.set_operations[0].query.set_operations
    assert format_query(query) == source


def test_grouped_left_primary_is_structurally_distinct_and_round_trips() -> None:
    source = "(SELECT id FROM @a ORDER BY upload_date DESC LIMIT 2) UNION ALL SELECT id FROM @b ORDER BY id ASC"
    query = parse_query(source)
    assert query.left_query is not None
    assert format_query(query) == source
    assert semantic_key(parse_query(format_query(query))) == semantic_key(query)


def test_grouped_sources_remain_visible_to_physical_acquisition() -> None:
    query = parse_query("(SELECT id FROM @a LIMIT 1) UNION ALL (SELECT id FROM @b LIMIT 1)")
    assert query_physical_source_requests(query) == (("@a", None), ("@b", None))


def test_unparenthesised_branch_local_modifier_remains_invalid() -> None:
    with pytest.raises(QuerySyntaxError, match="Unexpected token 'UNION'"):
        parse_query("SELECT id FROM @a ORDER BY id LIMIT 2 UNION ALL SELECT id FROM @b")


def test_empty_parenthesised_query_is_rejected() -> None:
    with pytest.raises(QuerySyntaxError, match="Parenthesised query cannot be empty"):
        parse_query("() UNION ALL SELECT id FROM @b")


def test_parentheses_change_mixed_union_multiplicity() -> None:
    records = [{"id": "same", "_yt_sql_source": source, "_yt_sql_source_facet": None} for source in ("@a", "@b", "@c")]
    schema = QuerySchema(records)
    dates = DateContext()

    left_grouped = resolve_query(
        parse_query("(SELECT id FROM @a UNION ALL SELECT id FROM @b) UNION SELECT id FROM @c"),
        schema,
        dates,
    )
    right_grouped = resolve_query(
        parse_query("SELECT id FROM @a UNION ALL (SELECT id FROM @b UNION SELECT id FROM @c)"),
        schema,
        dates,
    )

    assert apply_query(records, left_grouped) == [{"id": "same"}]
    assert apply_query(records, right_grouped) == [{"id": "same"}, {"id": "same"}]


def test_leading_cte_scopes_over_grouped_compound_expression() -> None:
    source = "WITH a AS (SELECT id FROM @a) (SELECT id FROM a LIMIT 1) UNION ALL (SELECT id FROM @b LIMIT 1)"
    query = parse_query(source)
    assert len(query.ctes) == 1
    assert query.left_query is not None
    assert format_query(query) == source
