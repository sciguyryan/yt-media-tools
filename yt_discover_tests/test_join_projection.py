"""Projection semantics for staged multi-relation yt-sql queries."""

from __future__ import annotations

import pytest

from yt_media_tools.query import QuerySemanticError, RelationField, parse_query, resolve_join_references, resolve_query
from yt_media_tools.schema import QuerySchema


def _schema(*records: dict[str, object]) -> QuerySchema:
    return QuerySchema(list(records))


def test_plain_star_expands_only_primary_relation() -> None:
    left = _schema({"id": "left", "title": "Left"})
    right = _schema({"id": "right", "right_only_marker": "Right"})
    query = parse_query("SELECT * FROM @left AS l JOIN @right AS r ON l.id = r.id")
    resolved = resolve_join_references(
        query,
        left,
        source_schemas={
            ("@left", None): left,
            ("@right", None): right,
        },
    )
    assert resolved.select
    assert all(isinstance(term.expression, RelationField) for term in resolved.select)
    assert {term.expression.qualifier for term in resolved.select} == {"l"}
    assert "right_only_marker" not in {term.output_name for term in resolved.select}


def test_relation_wildcard_expands_only_named_relation() -> None:
    left = _schema({"id": "left", "title": "Left"})
    right = _schema({"id": "right", "channel": "Right"})
    query = parse_query("SELECT r.* FROM @left AS l JOIN @right AS r ON l.id = r.id")
    resolved = resolve_join_references(
        query,
        left,
        source_schemas={
            ("@left", None): left,
            ("@right", None): right,
        },
    )
    assert resolved.select
    assert {term.expression.qualifier for term in resolved.select} == {"r"}
    assert "channel" in {term.output_name for term in resolved.select}


def test_explicit_right_projection_does_not_flatten_unselected_fields() -> None:
    schema = _schema({"id": "x", "title": "Title", "channel": "Channel"})
    query = parse_query("SELECT l.id, r.title AS right_title FROM @left AS l JOIN @right AS r ON l.id = r.id")
    resolved = resolve_join_references(query, schema)
    assert [term.output_name for term in resolved.select] == ["id", "right_title"]
    assert [term.expression.qualifier for term in resolved.select] == ["l", "r"]


def test_duplicate_explicit_join_projection_names_require_alias() -> None:
    query = parse_query("SELECT l.id, r.id FROM @left AS l JOIN @right AS r ON l.id = r.id")
    with pytest.raises(QuerySemanticError, match="Duplicate SELECT output name 'id'"):
        resolve_query(query, _schema({"id": "x"}))


def test_overlapping_relation_wildcards_require_unique_output_names() -> None:
    query = parse_query("SELECT l.*, r.* FROM @left AS l JOIN @right AS r ON l.id = r.id")
    with pytest.raises(QuerySemanticError, match="Duplicate SELECT output name 'id'"):
        resolve_query(query, _schema({"id": "x", "title": "Title"}))


def test_relation_wildcard_can_mix_with_uniquely_aliased_projection() -> None:
    left = _schema({"id": "left"})
    right = _schema({"title": "Right"})
    query = parse_query("SELECT l.*, r.title AS right_title FROM @left AS l JOIN @right AS r ON l.id = r.title")
    resolved = resolve_join_references(
        query,
        left,
        source_schemas={
            ("@left", None): left,
            ("@right", None): right,
        },
    )
    assert [term.output_name for term in resolved.select][-1] == "right_title"
    assert resolved.select[-1].expression.qualifier == "r"


def test_unknown_relation_wildcard_alias_is_rejected() -> None:
    query = parse_query("SELECT missing.* FROM @left AS l JOIN @right AS r ON l.id = r.id")
    with pytest.raises(QuerySemanticError, match="Unknown relation alias 'missing'"):
        resolve_query(query, _schema({"id": "x"}))


def test_valid_join_projection_still_stops_at_execution_boundary() -> None:
    query = parse_query("SELECT l.id, r.title AS right_title FROM @left AS l JOIN @right AS r ON l.id = r.id")
    with pytest.raises(
        QuerySemanticError, match="JOIN syntax is recognised, but JOIN execution is not implemented yet"
    ):
        resolve_query(query, _schema({"id": "x", "title": "Title"}))
