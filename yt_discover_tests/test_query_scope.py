"""Focused tests for semantic relation scope and logical row identity."""

from __future__ import annotations

from yt_media_tools.query_scope import (
    LogicalRowIdentity,
    RelationBinding,
    RelationIdentity,
    SemanticScope,
    relation_binding,
)
from yt_media_tools.schema import FieldInfo, QuerySchema


def _schema(*names: str) -> QuerySchema:
    return QuerySchema.from_field_infos([FieldInfo(name, "string", True, dynamic=True) for name in names])


def test_relation_identity_is_case_sensitive_for_source_names_and_facet_sensitive() -> None:
    videos = RelationIdentity("@Channel", "videos")
    same = RelationIdentity("@channel", "videos")
    shorts = RelationIdentity("@channel", "shorts")
    assert videos.key != same.key
    assert videos.key != shorts.key


def test_relation_binding_prefers_cte_schema_over_physical_source_resolution() -> None:
    physical = _schema("id")
    cte = _schema("projected")
    binding = relation_binding("Recent", None, physical, {"Recent": cte}, {("Recent", None): physical})
    assert binding.identity.kind == "cte"
    assert binding.identity.name == "Recent"
    assert binding.schema is cte


def test_semantic_scope_resolves_field_ownership_for_single_relation() -> None:
    relation = RelationIdentity("@alpha", "videos")
    scope = SemanticScope.single(RelationBinding(relation, _schema("id", "title")))
    resolved = scope.resolve_unqualified_field("title")
    assert resolved is not None
    assert resolved.relation == relation
    assert resolved.field.name == "title"
    assert scope.resolve_unqualified_field("TITLE") is None


def test_semantic_scope_refuses_ambiguous_unqualified_field() -> None:
    scope = SemanticScope(
        (
            RelationBinding(RelationIdentity("@alpha"), _schema("id")),
            RelationBinding(RelationIdentity("@beta"), _schema("id")),
        )
    )
    assert scope.resolve_unqualified_field("id") is None


def test_logical_row_identity_includes_relation_identity() -> None:
    alpha = LogicalRowIdentity(RelationIdentity("@alpha", "videos"), ("abc123",))
    alpha_again = LogicalRowIdentity(RelationIdentity("@ALPHA", "videos"), ("abc123",))
    beta = LogicalRowIdentity(RelationIdentity("@beta", "videos"), ("abc123",))
    assert alpha.key != alpha_again.key
    assert alpha.key != beta.key
