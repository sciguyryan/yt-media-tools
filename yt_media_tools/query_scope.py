"""Semantic relation scope and logical row identity for yt-sql.

The current language resolves one input relation per query body. Keeping relation
identity explicit here avoids baking that single-relation assumption into future
JOIN resolution, while leaving parser and evaluator behaviour unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .schema import FieldInfo, QuerySchema


@dataclass(frozen=True)
class RelationIdentity:
    """Stable semantic identity for one logical relation in a query body."""

    name: str | None
    facet: str | None = None
    kind: str = "physical"

    @property
    def key(self) -> tuple[str, str | None, str | None]:
        return (self.kind, self.name if self.name is not None else None, self.facet)


@dataclass(frozen=True)
class RelationBinding:
    """One relation identity paired with the schema and visible qualifier."""

    identity: RelationIdentity
    schema: QuerySchema
    qualifier: str | None = None


@dataclass(frozen=True)
class ResolvedFieldIdentity:
    """Semantic ownership of a field after scope resolution."""

    relation: RelationIdentity
    field: FieldInfo

    @property
    def key(self) -> tuple[tuple[str, str | None, str | None], str]:
        canonical = self.field.alias_of or self.field.name
        return (self.relation.key, canonical)


@dataclass(frozen=True)
class LogicalRowIdentity:
    """Backend-neutral identity of a logical row within one relation."""

    relation: RelationIdentity
    values: tuple[Any, ...]

    @property
    def key(self) -> tuple[tuple[str, str | None, str | None], tuple[Any, ...]]:
        return (self.relation.key, self.values)


@dataclass(frozen=True)
class SemanticScope:
    """Relations visible while resolving one query body."""

    relations: tuple[RelationBinding, ...]

    @classmethod
    def single(cls, binding: RelationBinding) -> "SemanticScope":
        return cls((binding,))

    def field_matches(self, name: str) -> tuple[ResolvedFieldIdentity, ...]:
        """Return all relation-owned matches for an unqualified field name."""
        matches: list[ResolvedFieldIdentity] = []
        for binding in self.relations:
            field = binding.schema.resolve(name)
            if field is not None:
                matches.append(ResolvedFieldIdentity(binding.identity, field))
        return tuple(matches)

    def resolve_unqualified_field(self, name: str) -> ResolvedFieldIdentity | None:
        """Resolve an unqualified field, refusing ambiguous multi-relation matches."""
        matches = self.field_matches(name)
        return matches[0] if len(matches) == 1 else None

    def binding_for_qualifier(self, qualifier: str) -> RelationBinding | None:
        """Return the uniquely visible relation bound to ``qualifier``."""
        matches = tuple(
            binding for binding in self.relations if binding.qualifier is not None and binding.qualifier == qualifier
        )
        return matches[0] if len(matches) == 1 else None


def relation_binding(
    source_name: str | None,
    source_facet: str | None,
    physical_schema: QuerySchema,
    cte_schemas: dict[str, QuerySchema],
    source_schemas: dict[tuple[str, str | None], QuerySchema],
) -> RelationBinding:
    """Resolve the single relation used by the current query-body grammar."""
    if source_name is None:
        return RelationBinding(RelationIdentity(None, source_facet, "implicit"), physical_schema, None)
    logical = cte_schemas.get(source_name)
    if logical is not None:
        return RelationBinding(RelationIdentity(source_name, None, "cte"), logical, source_name)
    schema = source_schemas.get((source_name, source_facet), physical_schema)
    return RelationBinding(RelationIdentity(source_name, source_facet, "physical"), schema, source_name)
