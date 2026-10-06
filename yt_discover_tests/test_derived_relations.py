"""Derived-relation grammar, model, formatting and semantic-boundary coverage."""

import pytest

from yt_media_tools.query_formatter import format_query
from yt_media_tools.query_model import QuerySemanticError, QuerySyntaxError
from yt_media_tools.query_parser import parse_query
from yt_media_tools.query_resolver import resolve_query
from yt_media_tools.schema import QuerySchema


ROWS = [
    {"id": "a", "title": "Alpha", "view_count": 10, "duration": 30},
    {"id": "b", "title": "Beta", "view_count": 20, "duration": 60},
]
SCHEMA = QuerySchema(ROWS)
SOURCE_SCHEMAS = {("@a", None): SCHEMA, ("@b", None): SCHEMA, ("@c", None): SCHEMA}


def _resolve(source: str):
    return resolve_query(parse_query(source), SCHEMA, source_schemas=SOURCE_SCHEMAS)


def test_parse_unaliased_derived_relation_preserves_nested_query():
    query = parse_query("SELECT id FROM (SELECT id FROM @a)")
    assert query.from_source is None
    assert query.from_relation is not None
    assert query.from_relation.source is None
    assert query.from_relation.alias is None
    assert query.from_relation.derived is not None
    assert query.from_relation.derived.query.from_source == "@a"


def test_derived_relation_preserves_opening_parenthesis_source_position():
    source = "SELECT id FROM (SELECT id FROM @a)"
    query = parse_query(source)
    assert query.from_relation is not None
    assert query.from_relation.position == source.index("(")
    assert query.from_relation.derived is not None
    assert query.from_relation.derived.position == source.index("(")


def test_parse_aliased_derived_relation():
    query = parse_query("SELECT id FROM (SELECT id FROM @a) AS combined")
    assert query.from_relation is not None
    assert query.from_relation.alias == "combined"


def test_explicit_derived_alias_qualifies_exported_columns():
    resolved = _resolve("SELECT combined.id FROM (SELECT id FROM @a) AS combined")
    assert resolved.select[0].output_name == "combined.id"
    with pytest.raises(QuerySemanticError, match="Unknown field 'combined.title'"):
        _resolve("SELECT combined.title FROM (SELECT id FROM @a) AS combined")


def test_derived_relation_exports_only_projected_columns():
    resolved = _resolve("SELECT id FROM (SELECT id FROM @a)")
    assert resolved.select[0].output_name == "id"
    with pytest.raises(QuerySemanticError, match="Unknown field 'title'"):
        _resolve("SELECT title FROM (SELECT id FROM @a)")


def test_union_first_branch_defines_derived_relation_output_names():
    resolved = _resolve("SELECT first FROM (SELECT id AS first FROM @a UNION SELECT title AS second FROM @b)")
    assert resolved.select[0].output_name == "first"
    with pytest.raises(QuerySemanticError, match="Unknown field 'second'"):
        _resolve("SELECT second FROM (SELECT id AS first FROM @a UNION SELECT title AS second FROM @b)")


def test_recursive_cte_reference_hidden_inside_derived_relation_is_rejected():
    with pytest.raises(QuerySemanticError, match="Recursive reference to CTE 'x'"):
        _resolve("WITH x AS (SELECT id FROM (SELECT id FROM x)) SELECT id FROM x")


def test_forward_cte_reference_hidden_inside_derived_relation_is_rejected():
    with pytest.raises(QuerySemanticError, match="cannot reference later CTE 'later'"):
        _resolve(
            "WITH first AS (SELECT id FROM (SELECT id FROM later)), later AS (SELECT id FROM @a) SELECT id FROM first"
        )


def test_outer_cte_is_visible_inside_derived_relation():
    resolved = _resolve("WITH base AS (SELECT id FROM @a) SELECT id FROM (SELECT id FROM base)")
    assert resolved.from_relation is not None
    assert resolved.from_relation.derived is not None
    assert resolved.from_relation.derived.query.from_source == "base"


def test_correlated_outer_row_reference_is_not_visible_inside_derived_relation():
    with pytest.raises(QuerySemanticError, match="Unknown field 'outer_rel.id'"):
        _resolve(
            "SELECT outer_rel.id FROM @a AS outer_rel "
            "JOIN (SELECT outer_rel.id AS id FROM @b) AS inner_rel ON outer_rel.id = inner_rel.id"
        )


def test_predicate_only_derived_query_retains_normal_implicit_id_projection():
    resolved = _resolve("SELECT id FROM (id = 'a')")
    assert resolved.from_relation is not None
    assert resolved.from_relation.derived is not None
    assert [term.output_name for term in resolved.from_relation.derived.query.select] == ["id"]


def test_nested_with_remains_unsupported_inside_derived_relation():
    with pytest.raises(QuerySyntaxError, match="Nested WITH clauses are not supported"):
        parse_query("SELECT id FROM (WITH x AS (SELECT id FROM @a) SELECT id FROM x)")


def test_of_is_rejected_for_derived_relation():
    with pytest.raises(QuerySyntaxError, match="OF applies only to physical source relations"):
        parse_query("SELECT id FROM (SELECT id FROM @a) OF videos")


def test_unclosed_derived_relation_reports_relation_boundary():
    with pytest.raises(QuerySyntaxError, match=r"Expected '\)' after derived relation query"):
        parse_query("SELECT id FROM (SELECT id FROM @a")


def test_empty_derived_relation_is_rejected():
    with pytest.raises(QuerySyntaxError, match="Derived relation query cannot be empty"):
        parse_query("SELECT id FROM ()")


def test_derived_relation_parentheses_survive_canonical_round_trip():
    source = "SELECT id FROM (SELECT id FROM @a UNION SELECT id FROM @b) AS combined ORDER BY id ASC"
    formatted = format_query(parse_query(source))
    assert "FROM (\n" in formatted
    assert "\n) AS combined" in formatted
    assert format_query(parse_query(formatted)) == formatted


def test_derived_relation_can_appear_as_join_operand_syntactically():
    query = parse_query(
        "SELECT a.id FROM @a AS a INNER JOIN "
        "(SELECT id FROM @b UNION SELECT id FROM @c) AS combined ON a.id = combined.id"
    )
    assert len(query.joins) == 1
    relation = query.joins[0].relation
    assert relation.source is None
    assert relation.alias == "combined"
    assert relation.derived is not None


def test_derived_primary_relation_can_participate_in_join_with_alias():
    resolved = _resolve(
        "SELECT left_rel.id, b.title FROM (SELECT id FROM @a) AS left_rel JOIN @b AS b ON left_rel.id = b.id"
    )
    assert [term.output_name for term in resolved.select] == ["id", "title"]


def test_derived_join_resolves_only_exported_columns():
    resolved = _resolve(
        "SELECT a.id, combined.title FROM @a AS a JOIN (SELECT id, title FROM @b) AS combined ON a.id = combined.id"
    )
    assert [term.output_name for term in resolved.select] == ["id", "title"]
    with pytest.raises(QuerySemanticError, match="has no field 'duration'"):
        _resolve("SELECT a.id FROM @a AS a JOIN (SELECT id, title FROM @b) AS combined ON a.id = combined.duration")


def test_derived_relation_in_join_requires_alias_under_existing_join_rules():
    with pytest.raises(QuerySemanticError, match="Each joined relation requires an AS alias"):
        _resolve("SELECT a.id FROM @a AS a JOIN (SELECT id FROM @b) ON a.id = id")


def test_torture_nested_composition_preserves_boundaries_and_round_trips():
    source = (
        "WITH base AS (SELECT id, title, view_count FROM @a WHERE view_count >= 10) "
        "SELECT id, MAX(view_count) AS peak FROM ("
        "SELECT id, title, view_count FROM base WHERE title IS NOT NULL "
        "UNION ALL (SELECT id, title, view_count FROM @b WHERE duration > 30s ORDER BY view_count DESC LIMIT 50)"
        ") AS combined WHERE id IS NOT NULL GROUP BY id HAVING MAX(view_count) >= 10 "
        "ORDER BY peak DESC LIMIT 25 OFFSET 1"
    )
    query = parse_query(source)
    formatted = format_query(query)
    assert format_query(parse_query(formatted)) == formatted
    resolved = resolve_query(query, SCHEMA, source_schemas=SOURCE_SCHEMAS)
    assert [term.output_name for term in resolved.select] == ["id", "peak"]


def test_torture_nested_derived_relations_and_union_schema_do_not_leak_fields():
    source = (
        "SELECT id FROM (SELECT id FROM (SELECT id, title FROM @a WHERE title IS NOT NULL) AS inner_rel "
        "UNION SELECT id FROM (SELECT id, duration FROM @b WHERE duration >= 30s) AS other_rel) AS outer_rel"
    )
    resolved = _resolve(source)
    assert resolved.select[0].output_name == "id"
    with pytest.raises(QuerySemanticError, match="Unknown field 'title'"):
        _resolve(source.replace("SELECT id FROM (", "SELECT title FROM (", 1))


def test_derived_relation_execution_materialises_exported_rows_before_outer_projection():
    from yt_media_tools.query_evaluator import apply_query

    resolved = _resolve("SELECT CONCAT(id, ' # ', title) AS line FROM (SELECT id, title FROM @a)")
    result = apply_query(ROWS, resolved)
    assert result == [{"id": "a", "title": "Alpha"}, {"id": "b", "title": "Beta"}]
    from yt_media_tools.query_evaluator import canonical_record_value

    assert [canonical_record_value(row, resolved.select[0]) for row in result] == ["a # Alpha", "b # Beta"]


def test_derived_relation_execution_does_not_leak_unexported_physical_values():
    from yt_media_tools.query_evaluator import apply_query

    resolved = _resolve("SELECT id FROM (SELECT id FROM @a)")
    result = apply_query(ROWS, resolved)
    assert result == [{"id": "a"}, {"id": "b"}]
    assert all("title" not in row and "duration" not in row for row in result)


def test_derived_union_execution_deduplicates_before_outer_projection():
    from yt_media_tools.query_evaluator import apply_query

    records = [
        {"id": "a", "title": "Alpha", "_yt_sql_source": "@a", "_yt_sql_source_facet": None},
        {"id": "b", "title": "Beta", "_yt_sql_source": "@a", "_yt_sql_source_facet": None},
        {"id": "b", "title": "Beta", "_yt_sql_source": "@b", "_yt_sql_source_facet": None},
        {"id": "c", "title": "Gamma", "_yt_sql_source": "@b", "_yt_sql_source_facet": None},
    ]
    resolved = _resolve(
        "SELECT CONCAT(id, ' # ', title) AS line FROM (SELECT id, title FROM @a UNION SELECT id, title FROM @b)"
    )
    result = apply_query(records, resolved)
    from yt_media_tools.query_evaluator import canonical_record_value

    assert [canonical_record_value(row, resolved.select[0]) for row in result] == [
        "a # Alpha",
        "b # Beta",
        "c # Gamma",
    ]


def test_derived_relation_planning_discovers_inner_physical_requirements_only():
    from datetime import datetime, timezone

    from yt_media_tools.dates import DateContext
    from yt_media_tools.planner import plan_source_boundaries
    from yt_media_tools.query import query_physical_source_requests
    from yt_media_tools.sources import resolve_source_request

    query = parse_query("SELECT id FROM (SELECT id, title FROM @a WHERE duration >= 30s)")
    requests = query_physical_source_requests(query)
    sources = tuple(resolve_source_request(source, facet=facet) for source, facet in requests)
    plans = plan_source_boundaries(
        query,
        requests=requests,
        sources=sources,
        dates=DateContext(now=datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)),
    )
    assert requests == (("@a", None),)
    assert len(plans) == 1
    assert plans[0].required_fields == frozenset({"id", "title", "duration"})


def test_torture_derived_union_planning_keeps_branch_requirements_on_their_sources():
    from datetime import datetime, timezone

    from yt_media_tools.dates import DateContext
    from yt_media_tools.planner import plan_source_boundaries
    from yt_media_tools.query import query_physical_source_requests
    from yt_media_tools.sources import resolve_source_request

    query = parse_query(
        "SELECT id FROM ("
        "SELECT id FROM @a WHERE title ILIKE '%alpha%' "
        "UNION ALL SELECT id FROM @b WHERE duration >= 30s"
        ") AS combined WHERE id IS NOT NULL"
    )
    requests = query_physical_source_requests(query)
    sources = tuple(resolve_source_request(source, facet=facet) for source, facet in requests)
    plans = plan_source_boundaries(
        query,
        requests=requests,
        sources=sources,
        dates=DateContext(now=datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)),
    )
    assert [(plan.source_name, plan.required_fields) for plan in plans] == [
        ("@a", frozenset({"id", "title"})),
        ("@b", frozenset({"id", "duration"})),
    ]


def test_derived_join_execution_materialises_right_relation_before_matching():
    from yt_media_tools.query_evaluator import apply_query, canonical_record_value

    records = [
        {"id": "a", "title": "Left A", "_yt_sql_source": "@a", "_yt_sql_source_facet": None},
        {"id": "b", "title": "Left B", "_yt_sql_source": "@a", "_yt_sql_source_facet": None},
        {"id": "b", "title": "Right B", "_yt_sql_source": "@b", "_yt_sql_source_facet": None},
    ]
    resolved = _resolve(
        "SELECT left_rel.id, right_rel.title FROM @a AS left_rel "
        "JOIN (SELECT id, title FROM @b) AS right_rel ON left_rel.id = right_rel.id"
    )
    result = apply_query(records, resolved)
    assert len(result) == 1
    assert [canonical_record_value(result[0], term) for term in resolved.select] == ["b", "Right B"]


def test_derived_primary_join_execution_materialises_left_relation_before_matching():
    from yt_media_tools.query_evaluator import apply_query, canonical_record_value

    records = [
        {"id": "a", "title": "Left A", "_yt_sql_source": "@a", "_yt_sql_source_facet": None},
        {"id": "b", "title": "Left B", "_yt_sql_source": "@a", "_yt_sql_source_facet": None},
        {"id": "b", "title": "Right B", "_yt_sql_source": "@b", "_yt_sql_source_facet": None},
    ]
    resolved = _resolve(
        "SELECT left_rel.id, right_rel.title FROM (SELECT id FROM @a) AS left_rel "
        "JOIN @b AS right_rel ON left_rel.id = right_rel.id"
    )
    result = apply_query(records, resolved)
    assert len(result) == 1
    assert [canonical_record_value(result[0], term) for term in resolved.select] == ["b", "Right B"]


def test_provability_propagates_empty_derived_from_relation():
    from yt_media_tools.semantic_provability import prove_query_relation_facts

    resolved = _resolve("SELECT id FROM (SELECT id FROM @a WHERE id = 'a' AND id = 'b')")
    facts = prove_query_relation_facts(resolved)
    assert facts.empty
    assert facts.proof is not None
    assert any("derived FROM relation is proven empty" in reason for reason in facts.proof.reasons)


def test_provability_propagates_empty_derived_inner_join_relation():
    from yt_media_tools.semantic_provability import prove_query_relation_facts

    resolved = _resolve(
        "SELECT left_rel.id FROM @a AS left_rel "
        "JOIN (SELECT id FROM @b WHERE id = 'a' AND id = 'b') AS right_rel ON left_rel.id = right_rel.id"
    )
    facts = prove_query_relation_facts(resolved)
    assert facts.empty
    assert facts.proof is not None
    assert any("derived relation is proven empty" in reason for reason in facts.proof.reasons)


def test_explain_preserves_derived_join_identity_and_inner_acquisition_requirements():
    from yt_media_tools.discover_explain import explain_user_query_json

    payload = explain_user_query_json(
        "SELECT left_rel.id FROM @a AS left_rel "
        "JOIN (SELECT id, title FROM @b) AS right_rel ON left_rel.id = right_rel.id",
        source_type="channel",
        tab="all",
        date_format="%Y%m%d",
    )
    relation = payload["relational_joins"][0]["right_relation"]
    assert relation["kind"] == "derived"
    assert relation["source"] is None
    assert relation["alias"] == "right_rel"
    assert relation["query"] == "SELECT id, title FROM @b"
    assert relation["acquisition_requirements"] == ["id", "title"]
    boundaries = {item["source"]: item for item in payload["source_boundaries"]}
    assert boundaries["@b"]["required_fields"] == ["id", "title"]
