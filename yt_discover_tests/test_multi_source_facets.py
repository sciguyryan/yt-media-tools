"""Multi-facet OF syntax and lowering contract."""

from __future__ import annotations

import pytest

from yt_media_tools.dates import DateContext
from yt_media_tools.query_evaluator import apply_query
from yt_media_tools.query_formatter import format_query
from yt_media_tools.query_model import QuerySyntaxError
from yt_media_tools.query_parser import parse_query
from yt_media_tools.query_resolver import resolve_query
from yt_media_tools.schema import QuerySchema


def test_multi_facet_of_lowers_to_ordered_union_all_branches() -> None:
    query = parse_query("SELECT id FROM @example OF videos, live")
    assert query.from_facet == "videos"
    assert [(operation.query.from_facet, operation.all) for operation in query.set_operations] == [("live", True)]
    assert format_query(query) == "SELECT id FROM @example OF videos, live"


def test_multi_facet_of_repeats_branch_semantics_and_keeps_result_modifiers_outer() -> None:
    query = parse_query(
        "SELECT id, title FROM @example OF videos, live "
        "WHERE title ILIKE '%welcome%' ORDER BY upload_date ASC LIMIT 40 OFFSET 2"
    )
    assert format_query(query) == (
        "SELECT id, title FROM @example OF videos, live WHERE title ILIKE '%welcome%' "
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


def test_multi_facet_of_retains_source_field_ordering_outside_projection() -> None:
    source = (
        "SELECT CONCAT(id, ' # ', title) FROM @Insym OF videos, live "
        "WHERE title ILIKE 'welcome to the game' "
        "ORDER BY upload_date ASC, release_timestamp ASC"
    )
    query = parse_query(source)
    records = [
        {
            "id": "live-id",
            "title": "Welcome to the Game",
            "upload_date": "20240202",
            "release_timestamp": 20,
            "_yt_sql_source": "@Insym",
            "_yt_sql_source_facet": "live",
        },
        {
            "id": "video-id",
            "title": "welcome to the game",
            "upload_date": "20240101",
            "release_timestamp": 10,
            "_yt_sql_source": "@Insym",
            "_yt_sql_source_facet": "videos",
        },
    ]
    resolved = resolve_query(query, QuerySchema(records), DateContext())
    assert [term.field for term in resolved.order_by] == ["upload_date", "release_timestamp"]
    assert apply_query(records, resolved) == [
        {"CONCAT(id, ' # ', title)": "video-id # welcome to the game"},
        {"CONCAT(id, ' # ', title)": "live-id # Welcome to the Game"},
    ]


def test_explicit_union_does_not_gain_multi_facet_order_scope() -> None:
    query = parse_query(
        "SELECT id FROM @example OF videos UNION ALL SELECT id FROM @example OF live ORDER BY upload_date ASC"
    )
    assert not query.set_operations[0].facet_expansion
    with pytest.raises(QuerySyntaxError, match="Unknown field 'upload_date'"):
        resolve_query(query, QuerySchema(({"id": "x", "upload_date": "20240101"},)), DateContext())


def test_multi_facet_distinct_applies_after_facet_composition() -> None:
    source = (
        "SELECT DISTINCT CONCAT(id, ' # ', title) FROM @Insym OF videos, live "
        "WHERE title ILIKE '%welcome to the game%' "
        "ORDER BY upload_date ASC, release_timestamp ASC"
    )
    query = parse_query(source)
    records = [
        {
            "id": "same-id",
            "title": "Welcome to the Game",
            "upload_date": "20240101",
            "release_timestamp": 10,
            "_yt_sql_source": "@Insym",
            "_yt_sql_source_facet": "videos",
        },
        {
            "id": "same-id",
            "title": "Welcome to the Game",
            "upload_date": "20240202",
            "release_timestamp": 20,
            "_yt_sql_source": "@Insym",
            "_yt_sql_source_facet": "live",
        },
    ]
    resolved = resolve_query(query, QuerySchema(records), DateContext())
    assert apply_query(records, resolved) == [
        {"CONCAT(id, ' # ', title)": "same-id # Welcome to the Game"},
    ]


def test_multi_facet_distinct_expression_projection_is_not_blank() -> None:
    source = (
        "SELECT DISTINCT CONCAT(id, ' # ', title) FROM @Insym OF videos, live "
        "WHERE title ILIKE '%welcome to the game%' "
        "ORDER BY upload_date ASC, release_timestamp ASC"
    )
    query = parse_query(source)
    records = [
        {
            "id": "video-id",
            "title": "Welcome to the Game",
            "upload_date": "20240101",
            "release_timestamp": 10,
            "_yt_sql_source": "@Insym",
            "_yt_sql_source_facet": "videos",
        },
        {
            "id": "live-id",
            "title": "Welcome to the Game 2",
            "upload_date": "20240202",
            "release_timestamp": 20,
            "_yt_sql_source": "@Insym",
            "_yt_sql_source_facet": "live",
        },
    ]
    resolved = resolve_query(query, QuerySchema(records), DateContext())
    assert apply_query(records, resolved) == [
        {"CONCAT(id, ' # ', title)": "video-id # Welcome to the Game"},
        {"CONCAT(id, ' # ', title)": "live-id # Welcome to the Game 2"},
    ]


def test_multi_facet_of_without_distinct_preserves_cross_facet_duplicates() -> None:
    records = [
        {
            "id": "same-id",
            "title": "Same",
            "_yt_sql_source": "@example",
            "_yt_sql_source_facet": "videos",
        },
        {
            "id": "same-id",
            "title": "Same",
            "_yt_sql_source": "@example",
            "_yt_sql_source_facet": "live",
        },
    ]
    query = resolve_query(parse_query("SELECT id FROM @example OF videos, live"), QuerySchema(records), DateContext())
    assert apply_query(records, query) == [{"id": "same-id"}, {"id": "same-id"}]


def test_multi_facet_of_orders_and_slices_globally_across_three_facets() -> None:
    records = [
        {
            "id": "video-early",
            "upload_date": "20240101",
            "release_timestamp": 10,
            "_yt_sql_source": "@example",
            "_yt_sql_source_facet": "videos",
        },
        {
            "id": "short-middle",
            "upload_date": "20240201",
            "release_timestamp": 20,
            "_yt_sql_source": "@example",
            "_yt_sql_source_facet": "shorts",
        },
        {
            "id": "live-late",
            "upload_date": "20240301",
            "release_timestamp": 30,
            "_yt_sql_source": "@example",
            "_yt_sql_source_facet": "live",
        },
        {
            "id": "video-latest",
            "upload_date": "20240401",
            "release_timestamp": 40,
            "_yt_sql_source": "@example",
            "_yt_sql_source_facet": "videos",
        },
    ]
    query = resolve_query(
        parse_query(
            "SELECT id FROM @example OF videos, shorts, live "
            "ORDER BY upload_date ASC, release_timestamp ASC LIMIT 2 OFFSET 1"
        ),
        QuerySchema(records),
        DateContext(),
    )
    assert apply_query(records, query) == [{"id": "short-middle"}, {"id": "live-late"}]


def test_multi_facet_distinct_formatter_preserves_shorthand_semantics() -> None:
    source = (
        "SELECT DISTINCT CONCAT(id, ':', title) FROM @example OF videos, shorts, live "
        "ORDER BY upload_date ASC LIMIT 5 OFFSET 1"
    )
    canonical = format_query(parse_query(source))
    assert canonical == source
    reparsed = parse_query(canonical)
    assert format_query(reparsed) == canonical
    assert all(operation.facet_expansion for operation in reparsed.set_operations)
