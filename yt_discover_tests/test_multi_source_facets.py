"""Multi-facet OF syntax and lowering contract."""

from __future__ import annotations

import pytest

from yt_media_tools.query_formatter import format_query
from yt_media_tools.query_model import QuerySyntaxError
from yt_media_tools.query_parser import parse_query


def test_multi_facet_of_lowers_to_ordered_union_all_branches() -> None:
    query = parse_query("SELECT id FROM @example OF videos, live")
    assert query.from_facet == "videos"
    assert [(operation.query.from_facet, operation.all) for operation in query.set_operations] == [("live", True)]
    assert format_query(query) == ("SELECT id FROM @example OF videos UNION ALL SELECT id FROM @example OF live")


def test_multi_facet_of_repeats_branch_semantics_and_keeps_result_modifiers_outer() -> None:
    query = parse_query(
        "SELECT id, title FROM @example OF videos, live "
        "WHERE title ILIKE '%welcome%' ORDER BY upload_date ASC LIMIT 40 OFFSET 2"
    )
    assert format_query(query) == (
        "SELECT id, title FROM @example OF videos WHERE title ILIKE '%welcome%' "
        "UNION ALL SELECT id, title FROM @example OF live WHERE title ILIKE '%welcome%' "
        "ORDER BY upload_date ASC LIMIT 40 OFFSET 2"
    )


def test_multi_facet_of_composes_before_explicit_union_branches() -> None:
    query = parse_query("SELECT id FROM @example OF videos, live UNION ALL SELECT id FROM @other OF shorts")
    assert [
        (operation.query.from_source, operation.query.from_facet, operation.all) for operation in query.set_operations
    ] == [
        ("@example", "live", True),
        ("@other", "shorts", True),
    ]


def test_multi_facet_of_preserves_primary_relation_alias_on_each_branch() -> None:
    query = parse_query("SELECT e.id FROM @example OF videos, live AS e")
    assert query.from_alias == "e"
    assert query.set_operations[0].query.from_alias == "e"


def test_multi_facet_of_rejects_duplicate_facets() -> None:
    with pytest.raises(QuerySyntaxError, match="Duplicate facet 'videos' in OF list"):
        parse_query("SELECT id FROM @example OF videos, videos")


def test_multi_facet_of_is_not_accepted_for_join_relation() -> None:
    with pytest.raises(
        QuerySyntaxError,
        match="Multiple OF facets are supported only for the primary FROM relation",
    ):
        parse_query("SELECT l.id FROM @left OF videos AS l INNER JOIN @right OF videos, live AS r ON l.id = r.id")
