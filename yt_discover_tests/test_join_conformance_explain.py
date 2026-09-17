"""Adversarial JOIN conformance, diagnostics, and explainability coverage."""

from __future__ import annotations

import pytest

from yt_media_tools.discover_explain import explain_user_query, explain_user_query_json
from yt_media_tools.explain_presentation import build_explain_graph, graph_to_dot
from yt_media_tools.query import QuerySemanticError, apply_query, parse_query, resolve_query
from yt_media_tools.schema import QuerySchema


def _records() -> list[dict[str, object]]:
    return [
        {"id": "a", "key": "x", "title": "Alpha", "_yt_sql_source": "@left", "_yt_sql_source_facet": "videos"},
        {"id": "b", "key": "x", "title": "Beta", "_yt_sql_source": "@left", "_yt_sql_source_facet": "videos"},
        {"id": None, "key": "n", "title": "Null", "_yt_sql_source": "@left", "_yt_sql_source_facet": "videos"},
        {"id": "a", "key": "x", "tag": "one", "_yt_sql_source": "@right", "_yt_sql_source_facet": "shorts"},
        {"id": "a", "key": "x", "tag": "two", "_yt_sql_source": "@right", "_yt_sql_source_facet": "shorts"},
        {"id": None, "key": "n", "tag": "null", "_yt_sql_source": "@right", "_yt_sql_source_facet": "shorts"},
    ]


def _resolved(text: str):
    records = _records()
    schemas = {
        ("@left", "videos"): QuerySchema([row for row in records if row["_yt_sql_source"] == "@left"]),
        ("@right", "shorts"): QuerySchema([row for row in records if row["_yt_sql_source"] == "@right"]),
    }
    return records, resolve_query(parse_query(text), QuerySchema(records), source_schemas=schemas)


def test_duplicate_join_keys_preserve_inner_multiplicity_and_null_never_equality_matches() -> None:
    records, query = _resolved(
        "SELECT l.id, r.tag FROM @left OF videos AS l INNER JOIN @right OF shorts AS r ON l.id = r.id ORDER BY r.tag"
    )
    result = apply_query(records, query)
    assert len(result) == 2
    assert [row["_yt_sql_relation_records"]["r"]["tag"] for row in result] == ["one", "two"]
    assert all(row["id"] == "a" for row in result)


def test_left_join_null_extension_remains_distinct_from_null_key_match() -> None:
    records, query = _resolved(
        "SELECT l.title, r.tag FROM @left OF videos AS l LEFT JOIN @right OF shorts AS r "
        "ON l.id = r.id ORDER BY l.title, r.tag"
    )
    result = apply_query(records, query)
    assert len(result) == 4
    bindings = [row["_yt_sql_relation_records"] for row in result]
    assert [binding["r"].get("tag") for binding in bindings] == ["one", "two", None, None]
    assert bindings[-1]["l"]["id"] is None
    assert bindings[-1]["r"] == {}


def test_ambiguous_overlapping_schema_field_is_rejected_at_field_location() -> None:
    source = "SELECT id FROM @left OF videos AS l INNER JOIN @right OF shorts AS r ON l.id = r.id"
    with pytest.raises(QuerySemanticError) as caught:
        _resolved(source)
    assert "Ambiguous field 'id'" in caught.value.message
    assert caught.value.position == source.index("id")


def test_alias_collision_is_rejected_at_second_relation() -> None:
    source = "SELECT l.id FROM @left OF videos AS l INNER JOIN @right OF shorts AS l ON l.id = l.id"
    with pytest.raises(QuerySemanticError) as caught:
        _resolved(source)
    assert "Duplicate relation alias 'l'" in caught.value.message
    assert caught.value.position == source.index("@right")


def test_chained_join_reaches_deterministic_execution_boundary() -> None:
    source = (
        "SELECT l.id FROM @left OF videos AS l INNER JOIN @right OF shorts AS r ON l.id = r.id "
        "ANTI JOIN @third AS t ON r.id = t.id"
    )
    schemas = {
        ("@left", "videos"): QuerySchema([{"id": "a"}]),
        ("@right", "shorts"): QuerySchema([{"id": "a"}]),
        ("@third", None): QuerySchema([{"id": "a"}]),
    }
    with pytest.raises(QuerySemanticError) as caught:
        resolve_query(parse_query(source), QuerySchema([{"id": "a"}]), source_schemas=schemas)
    assert caught.value.message == "Multi-way JOIN execution is not implemented yet."
    assert caught.value.position == source.index("ANTI JOIN")


def test_json_explain_exposes_relation_identity_dependencies_requirements_and_strategy() -> None:
    payload = explain_user_query_json(
        "SELECT l.title, r.duration FROM @left OF videos AS l INNER JOIN @right OF shorts AS r "
        "ON l.id = r.id WHERE r.view_count > 5",
        source_type="auto",
        tab="all",
        date_format="YMD",
    )
    [join] = payload["relational_joins"]
    assert join["kind"] == "INNER"
    assert join["left_relation"]["identity"] == "@left OF videos AS l"
    assert join["right_relation"]["identity"] == "@right OF shorts AS r"
    assert join["predicate_dependencies"] == ["l.id", "r.id"]
    assert join["left_relation"]["acquisition_requirements"] == ["id", "title"]
    assert join["right_relation"]["acquisition_requirements"] == ["duration", "id", "view_count"]
    assert join["execution_strategy"] == "stable-right-hash-with-reference-fallback"


def test_json_explain_reports_reference_strategy_for_non_equality_join() -> None:
    payload = explain_user_query_json(
        "SELECT l.id FROM @left AS l SEMI JOIN @right AS r ON l.duration < r.duration",
        source_type="auto",
        tab="all",
        date_format="YMD",
    )
    assert payload["relational_joins"][0]["execution_strategy"] == "nested-loop-reference"


def test_console_and_graphviz_explain_derive_relational_nodes_from_machine_plan() -> None:
    query = "SELECT l.id FROM @left AS l ANTI JOIN @right AS r ON l.id = r.id"
    payload = explain_user_query_json(query, source_type="auto", tab="all", date_format="YMD")
    human = explain_user_query(query, source_type="auto", tab="all", date_format="YMD", unicode=False)
    graph = build_explain_graph(payload)
    dot = graph_to_dot(graph)
    assert "ANTI JOIN" in human
    assert "stable-right-hash-with-reference-fallback" in human
    assert any(node.node_id == "join_0" and node.label == "ANTI JOIN" for node in graph.nodes)
    assert "ANTI JOIN" in dot
    assert "stable-right-hash-with-reference-fallback" in dot


def test_json_explain_exposes_structured_join_provability() -> None:
    payload = explain_user_query_json(
        "SELECT l.id FROM @left AS l INNER JOIN @right AS r ON 1 = 0",
        source_type="auto",
        tab="all",
        date_format="YMD",
    )
    proof = payload["relational_joins"][0]["provability"]
    assert proof["predicate_never_true"] is True
    assert proof["result_empty"] is True
    assert proof["right_relation_irrelevant"] is True
    assert proof["proof"]["claim"] == "join-consequence"
    assert proof["proof"]["premises"]


def test_json_explain_records_explicit_non_proof_for_dynamic_join() -> None:
    payload = explain_user_query_json(
        "SELECT l.id FROM @left AS l INNER JOIN @right AS r ON l.id = r.id",
        source_type="auto",
        tab="all",
        date_format="YMD",
    )
    proof = payload["relational_joins"][0]["provability"]
    assert proof == {
        "predicate_never_true": False,
        "result_empty": False,
        "right_relation_irrelevant": False,
        "proof": None,
    }
