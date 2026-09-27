"""Relation-oriented conformance groundwork using an independent semantic oracle."""

from __future__ import annotations

from yt_discover_tests.conformance.multi_source_fixture import heterogeneous_records
from yt_discover_tests.conformance.relation_oracle import (
    OracleLogicalRowIdentity,
    OracleRelation,
    OracleRelationScope,
)
from yt_media_tools.query_scope import LogicalRowIdentity, RelationIdentity


def _relations() -> OracleRelationScope:
    records = heterogeneous_records()
    names = tuple(dict.fromkeys(str(row["_yt_sql_source"]) for row in records))
    relations = tuple(
        OracleRelation.from_rows(name, (row for row in records if row["_yt_sql_source"] == name)) for name in names
    )
    return OracleRelationScope(relations)


def test_relation_oracle_detects_ambiguous_unqualified_fields() -> None:
    scope = _relations()
    assert scope.resolve_unqualified_field("id") is None
    assert scope.resolve_unqualified_field("title") is None


def test_relation_oracle_resolves_qualified_field_ownership() -> None:
    scope = _relations()
    resolved = scope.resolve_qualified_field("@youtube_playlist", "playlist_index")
    assert resolved is not None
    assert resolved.relation.name == "@youtube_playlist"
    assert resolved.key == (("physical", "@youtube_playlist", None), "playlist_index")


def test_relation_oracle_refuses_unknown_qualifier_or_field() -> None:
    scope = _relations()
    assert scope.resolve_qualified_field("@missing", "id") is None
    assert scope.resolve_qualified_field("@youtube_playlist", "missing") is None


def test_independent_row_identity_agrees_with_production_identity_contract() -> None:
    oracle = OracleLogicalRowIdentity(_relations().relations[0].identity, ("shared-id",))
    production = LogicalRowIdentity(RelationIdentity("@youtube_channel"), ("shared-id",))
    assert oracle.key == production.key


def test_same_row_values_from_different_relations_remain_distinct() -> None:
    scope = _relations()
    playlist = next(relation for relation in scope.relations if relation.identity.name == "@youtube_playlist")
    twitch = next(relation for relation in scope.relations if relation.identity.name == "@twitch_archive")
    playlist_row = OracleLogicalRowIdentity(playlist.identity, ("shared-id",))
    twitch_row = OracleLogicalRowIdentity(twitch.identity, ("shared-id",))
    assert playlist_row.key != twitch_row.key
