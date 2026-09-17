"""Parser-level coverage for the staged yt-sql JOIN grammar."""

from __future__ import annotations

import pytest

from yt_media_tools.query import (
    JoinKind,
    QuerySemanticError,
    QuerySyntaxError,
    ScalarComparison,
    format_query,
    parse_query,
    resolve_query,
)
from yt_media_tools.schema import QuerySchema


def test_join_kinds_have_stable_parser_representation() -> None:
    cases = (
        ("JOIN", JoinKind.INNER),
        ("INNER JOIN", JoinKind.INNER),
        ("LEFT JOIN", JoinKind.LEFT),
        ("LEFT OUTER JOIN", JoinKind.LEFT),
        ("SEMI JOIN", JoinKind.SEMI),
        ("ANTI JOIN", JoinKind.ANTI),
    )
    for syntax, expected in cases:
        query = parse_query(f"SELECT id FROM @left AS l {syntax} @right AS r ON l.id = r.id")
        assert query.from_alias == "l"
        assert len(query.joins) == 1
        join = query.joins[0]
        assert join.kind is expected
        assert join.relation.source == "@right"
        assert join.relation.alias == "r"
        assert isinstance(join.predicate, ScalarComparison)
        assert join.predicate.left.name == "l.id"
        assert join.predicate.right.name == "r.id"


def test_join_relation_preserves_facet_alias_and_source_position() -> None:
    source = "SELECT id FROM @left OF videos AS l ANTI JOIN @right OF shorts AS r ON l.id = r.id"
    query = parse_query(source)
    join = query.joins[0]
    assert query.from_source == "@left"
    assert query.from_facet == "videos"
    assert query.from_alias == "l"
    assert join.relation.facet == "shorts"
    assert join.relation.position == source.index("@right")
    assert join.position == source.index("ANTI")


def test_multiple_join_edges_are_preserved_in_source_order() -> None:
    query = parse_query(
        "SELECT id FROM @left AS l SEMI JOIN first AS f ON l.id = f.id ANTI JOIN @second AS s ON l.id = s.id"
    )
    assert tuple(join.kind for join in query.joins) == (JoinKind.SEMI, JoinKind.ANTI)
    assert tuple(join.relation.source for join in query.joins) == ("first", "@second")


def test_join_composes_with_cte_union_and_row_clauses_at_parser_level() -> None:
    source = (
        "WITH known AS (SELECT id FROM @known) "
        "SELECT id FROM @left AS l JOIN known AS k ON l.id = k.id WHERE l.title ILIKE 'mars%' "
        "UNION ALL SELECT id FROM @other ORDER BY id ASC LIMIT 10 OFFSET 2"
    )
    query = parse_query(source)
    assert len(query.ctes) == 1
    assert len(query.joins) == 1
    assert len(query.set_operations) == 1
    assert query.predicate is not None
    assert query.limit == 10
    assert query.offset == 2


def test_join_formatter_is_canonical_and_round_trips() -> None:
    source = "SELECT id FROM @left AS l LEFT OUTER JOIN @right OF videos AS r ON l.id = r.id"
    canonical = "SELECT id FROM @left AS l LEFT JOIN @right OF videos AS r ON l.id = r.id"
    parsed = parse_query(source)
    assert format_query(parsed) == canonical
    assert parse_query(canonical) == parse_query(format_query(parsed))


@pytest.mark.parametrize("kind", ("RIGHT JOIN", "FULL JOIN", "FULL OUTER JOIN", "CROSS JOIN", "NATURAL JOIN"))
def test_unsupported_join_families_are_rejected_deterministically(kind: str) -> None:
    with pytest.raises(QuerySyntaxError, match="RIGHT, FULL, CROSS and NATURAL JOIN are not supported"):
        parse_query(f"SELECT id FROM @left AS l {kind} @right AS r ON l.id = r.id")


def test_join_requires_on_predicate() -> None:
    with pytest.raises(QuerySyntaxError, match="JOIN requires an ON predicate"):
        parse_query("SELECT id FROM @left AS l JOIN @right AS r")


def test_join_requires_on_expression() -> None:
    with pytest.raises(QuerySyntaxError, match="JOIN ON requires an expression"):
        parse_query("SELECT id FROM @left AS l JOIN @right AS r ON WHERE l.id = 'x'")


def test_join_syntax_fails_closed_before_semantic_execution() -> None:
    query = parse_query("SELECT l.id FROM @left AS l JOIN @right AS r ON l.id = r.id")
    with pytest.raises(
        QuerySemanticError, match="JOIN syntax is recognised, but JOIN execution is not implemented yet"
    ):
        resolve_query(query, QuerySchema([{"id": "x"}]))


def test_join_reference_resolution_distinguishes_relation_fields_from_structured_members() -> None:
    from yt_media_tools.query import RelationField, ScalarMember, resolve_join_references

    schema = QuerySchema([{"id": "x", "formats": [{"height": 1080}]}])
    query = parse_query("SELECT l.id, r.formats[0].height AS height FROM @left AS l JOIN @right AS r ON l.id = r.id")
    resolved = resolve_join_references(query, schema)
    left_id = resolved.select[0].expression
    height = resolved.select[1].expression
    assert isinstance(left_id, RelationField)
    assert left_id.qualifier == "l"
    assert left_id.name == "id"
    assert isinstance(height, ScalarMember)
    assert isinstance(height.value.collection, RelationField)
    assert height.value.collection.qualifier == "r"
    assert height.member == "height"


def test_join_unqualified_field_is_rejected_when_multiple_relations_expose_it() -> None:
    query = parse_query("SELECT id FROM @left AS l JOIN @right AS r ON l.id = r.id")
    with pytest.raises(QuerySemanticError, match="Ambiguous field 'id'; qualify it with a relation alias"):
        resolve_query(query, QuerySchema([{"id": "x"}]))


def test_join_unknown_relation_alias_is_rejected_deterministically() -> None:
    query = parse_query("SELECT l.id FROM @left AS l JOIN @right AS r ON l.id = missing.id")
    with pytest.raises(QuerySemanticError, match="Unknown relation alias 'missing'"):
        resolve_query(query, QuerySchema([{"id": "x"}]))


def test_join_unknown_qualified_field_names_owning_relation() -> None:
    query = parse_query("SELECT l.id FROM @left AS l JOIN @right AS r ON l.id = r.no_such_field")
    with pytest.raises(QuerySemanticError, match="Relation 'r' has no field 'no_such_field'"):
        resolve_query(query, QuerySchema([{"id": "x"}]))


def test_join_requires_explicit_aliases_for_each_relation() -> None:
    schema = QuerySchema([{"id": "x"}])
    left_missing = parse_query("SELECT id FROM @left JOIN @right AS r ON id = r.id")
    with pytest.raises(QuerySemanticError, match="primary relation in a JOIN query requires an AS alias"):
        resolve_query(left_missing, schema)

    right_missing = parse_query("SELECT l.id FROM @left AS l JOIN @right ON l.id = id")
    with pytest.raises(QuerySemanticError, match="Each joined relation requires an AS alias"):
        resolve_query(right_missing, schema)


def test_join_duplicate_relation_alias_is_rejected() -> None:
    query = parse_query("SELECT l.id FROM @left AS l JOIN @right AS l ON l.id = l.id")
    with pytest.raises(QuerySemanticError, match="Duplicate relation alias 'l'"):
        resolve_query(query, QuerySchema([{"id": "x"}]))


def test_valid_qualified_join_still_fails_closed_at_execution_boundary() -> None:
    query = parse_query("SELECT l.id FROM @left AS l JOIN @right AS r ON l.id = r.id")
    with pytest.raises(
        QuerySemanticError, match="JOIN syntax is recognised, but JOIN execution is not implemented yet"
    ):
        resolve_query(query, QuerySchema([{"id": "x"}]))


def test_join_parser_accepts_relation_wildcards_in_projection() -> None:
    query = parse_query("SELECT l.*, r.title AS right_title FROM @left AS l JOIN @right AS r ON l.id = r.id")
    assert query.select[0].field == "l.*"
    assert query.select[0].expression.qualifier == "l"
    assert format_query(query) == ("SELECT l.*, r.title AS right_title FROM @left AS l JOIN @right AS r ON l.id = r.id")


def test_relation_wildcard_cannot_have_output_alias() -> None:
    with pytest.raises(QuerySyntaxError, match="relation wildcard cannot have an AS alias"):
        parse_query("SELECT r.* AS right FROM @left AS l JOIN @right AS r ON l.id = r.id")
