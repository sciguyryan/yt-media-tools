"""ORDER BY name resolution and canonicalisation contract for issue #122."""

import pytest

from yt_media_tools.query import QuerySemanticError, apply_query, parse_query, resolve_query
from yt_media_tools.dates import DateContext
from yt_media_tools.optimizer import optimise_query
from yt_media_tools.planner import plan_source_boundaries, required_query_fields
from yt_media_tools.query_formatter import format_query
from yt_media_tools.query_properties import analyse_query
from yt_media_tools.schema import QuerySchema
from yt_media_tools.sources import resolve_source_request


def _join_records() -> list[dict[str, object]]:
    return [
        {"id": "a", "title": "Alpha", "view_count": 10, "_yt_sql_source": "@left"},
        {"id": "b", "title": "Beta", "view_count": 30, "_yt_sql_source": "@left"},
        {"id": "a", "title": "Right A", "view_count": 2, "_yt_sql_source": "@right"},
        {"id": "b", "title": "Right B", "view_count": 1, "_yt_sql_source": "@right"},
    ]


def _resolve_join(text: str):
    records = _join_records()
    left = [row for row in records if row["_yt_sql_source"] == "@left"]
    right = [row for row in records if row["_yt_sql_source"] == "@right"]
    schemas = {("@left", None): QuerySchema(left), ("@right", None): QuerySchema(right)}
    return records, resolve_query(parse_query(text), QuerySchema(records), source_schemas=schemas)


def test_order_by_explicit_projection_alias_precedes_same_named_input_field() -> None:
    records = [
        {"id": "z", "title": "Alpha"},
        {"id": "a", "title": "Zulu"},
    ]
    query = resolve_query(parse_query("SELECT title AS id FROM @x ORDER BY id ASC"), QuerySchema(records))
    assert [row["id"] for row in apply_query(records, query)] == ["z", "a"]


def test_join_order_by_projection_alias_is_resolved_after_relation_ownership() -> None:
    records, query = _resolve_join(
        "SELECT l.id, l.view_count * 2 AS score "
        "FROM @left AS l INNER JOIN @right AS r ON l.id = r.id "
        "ORDER BY score DESC"
    )
    assert [row["id"] for row in apply_query(records, query)] == ["b", "a"]


def test_join_order_by_expression_can_reference_projection_alias() -> None:
    records, query = _resolve_join(
        "SELECT l.id, l.view_count * 2 AS score "
        "FROM @left AS l INNER JOIN @right AS r ON l.id = r.id "
        "ORDER BY score + 1 DESC"
    )
    assert [row["id"] for row in apply_query(records, query)] == ["b", "a"]


def test_join_order_by_alias_precedes_ambiguous_input_name() -> None:
    records, query = _resolve_join(
        "SELECT l.id, l.title AS view_count "
        "FROM @left AS l INNER JOIN @right AS r ON l.id = r.id "
        "ORDER BY view_count ASC"
    )
    assert [row["id"] for row in apply_query(records, query)] == ["a", "b"]


def test_join_order_by_unaliased_ambiguous_input_field_still_requires_qualification() -> None:
    with pytest.raises(QuerySemanticError, match="Ambiguous field 'title'; qualify it with a relation alias"):
        _resolve_join("SELECT l.id FROM @left AS l INNER JOIN @right AS r ON l.id = r.id ORDER BY title ASC")


def test_join_order_by_qualified_input_field_remains_valid() -> None:
    records, query = _resolve_join(
        "SELECT l.id FROM @left AS l INNER JOIN @right AS r ON l.id = r.id ORDER BY r.view_count ASC"
    )
    assert [row["id"] for row in apply_query(records, query)] == ["b", "a"]


def test_order_by_canonicalisation_preserves_alias_expression_and_explicit_direction() -> None:
    source = (
        "SELECT l.id, l.view_count*2 AS score FROM @left AS l "
        "INNER JOIN @right AS r ON l.id=r.id ORDER BY score+1 desc, r.title"
    )
    canonical = format_query(parse_query(source))
    assert canonical == (
        "SELECT l.id, (l.view_count * 2) AS score FROM @left AS l "
        "JOIN @right AS r ON l.id = r.id ORDER BY (score + 1) DESC, r.title ASC"
    )
    assert format_query(parse_query(canonical)) == canonical


def test_order_by_quoted_unicode_alias_is_exact_and_round_trips() -> None:
    source = "SELECT title AS `café score` FROM @x ORDER BY `café score` DESC"
    canonical = format_query(parse_query(source))
    assert canonical == source
    assert format_query(parse_query(canonical)) == canonical


def test_order_by_alias_does_not_become_a_physical_metadata_requirement() -> None:
    query = parse_query("SELECT view_count * 2 AS score FROM @left ORDER BY score + 1 DESC")
    properties = analyse_query(query)
    assert required_query_fields(query) == {"view_count"}
    assert properties.required_order_fields == frozenset({"view_count"})
    assert "score" not in properties.dynamic_fields


def test_join_order_by_alias_is_attributed_to_projection_owner_during_acquisition_planning() -> None:
    query = parse_query(
        "SELECT l.view_count * 2 AS score FROM @left OF videos AS l "
        "JOIN @right OF videos AS r ON l.id = r.id ORDER BY score DESC"
    )
    requests = (("@left", "videos"), ("@right", "videos"))
    sources = tuple(resolve_source_request(name, facet=facet) for name, facet in requests)
    plans = plan_source_boundaries(query, requests=requests, sources=sources, dates=DateContext())
    fields = {plan.source_name: plan.required_fields for plan in plans}
    assert fields["@left"] == frozenset({"id", "view_count"})
    assert fields["@right"] == frozenset({"id"})
    assert all("score" not in required for required in fields.values())


def test_join_order_by_alias_optimiser_equivalence_and_idempotence() -> None:
    records, query = _resolve_join(
        "SELECT l.id, l.view_count * 2 AS score FROM @left AS l JOIN @right AS r ON l.id = r.id ORDER BY score + 1 DESC"
    )
    expected = apply_query(records, query)
    optimised = optimise_query(query)
    assert apply_query(records, optimised.query) == expected
    assert optimise_query(optimised.query).query == optimised.query


def test_order_by_resolution_torture_across_join_alias_collisions_and_scalar_expressions() -> None:
    source = (
        "SELECT l.id, COALESCE(l.view_count, 0) * 2 AS `score Δ`, LOWER(l.title) AS title "
        "FROM @left AS l JOIN @right AS r ON l.id = r.id "
        "ORDER BY `score Δ` + LENGTH(title) DESC, r.view_count ASC"
    )
    canonical = format_query(parse_query(source))
    assert format_query(parse_query(canonical)) == canonical

    records, query = _resolve_join(canonical)
    expected = apply_query(records, query)
    assert [row["id"] for row in expected] == ["b", "a"]

    optimised = optimise_query(query)
    assert apply_query(records, optimised.query) == expected
    assert optimise_query(optimised.query).query == optimised.query

    parsed = parse_query(canonical)
    assert required_query_fields(parsed) == {"l.id", "l.view_count", "l.title", "r.view_count"}
    assert "score Δ" not in analyse_query(parsed).dynamic_fields


def test_order_by_resolves_cte_exported_projection_alias() -> None:
    records = [
        {"id": "a", "view_count": 10},
        {"id": "b", "view_count": 30},
    ]
    query = resolve_query(
        parse_query(
            "WITH ranked AS (SELECT id, view_count * 2 AS score FROM @fixture) "
            "SELECT id, score FROM ranked ORDER BY score DESC"
        ),
        QuerySchema(records),
    )
    assert apply_query(records, query) == [{"id": "b", "score": 60}, {"id": "a", "score": 20}]


def test_cte_exported_alias_hides_unprojected_underlying_name() -> None:
    records = [{"id": "a", "view_count": 10}]
    with pytest.raises(QuerySemanticError, match="Unknown field 'view_count'"):
        resolve_query(
            parse_query("WITH ranked AS (SELECT id, view_count AS score FROM @fixture) SELECT view_count FROM ranked"),
            QuerySchema(records),
        )


def test_order_by_chained_cte_alias_keeps_physical_dependencies_on_source_fields() -> None:
    source = (
        "WITH base AS (SELECT id, view_count * 2 AS score FROM @fixture), "
        "ranked AS (SELECT id, score FROM base ORDER BY score DESC) "
        "SELECT id, score FROM ranked ORDER BY score DESC"
    )
    query = parse_query(source)
    assert required_query_fields(query) == {"id", "view_count"}

    records = [
        {"id": "a", "view_count": 10},
        {"id": "b", "view_count": 30},
    ]
    resolved = resolve_query(query, QuerySchema(records))
    assert apply_query(records, resolved) == [{"id": "b", "score": 60}, {"id": "a", "score": 20}]
