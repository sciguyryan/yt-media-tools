"""Independent relation-oriented semantic oracle primitives for future yt-sql conformance.

This module deliberately models relation ownership, qualification, ambiguity and logical
row identity without importing production query, schema or scope code. It is groundwork
for testing future multi-relation syntax rather than an implementation of that syntax.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping


@dataclass(frozen=True)
class OracleRelationIdentity:
    """Independent identity for a logical relation visible to an oracle query."""

    name: str | None
    facet: str | None = None
    kind: str = "physical"

    @property
    def key(self) -> tuple[str, str | None, str | None]:
        return (self.kind, self.name if self.name is not None else None, self.facet)


@dataclass(frozen=True)
class OracleRelation:
    """Named oracle relation with an explicit field surface and deterministic rows."""

    identity: OracleRelationIdentity
    fields: frozenset[str]
    rows: tuple[Mapping[str, Any], ...]

    @classmethod
    def from_rows(
        cls,
        name: str | None,
        rows: Iterable[Mapping[str, Any]],
        *,
        facet: str | None = None,
        kind: str = "physical",
    ) -> "OracleRelation":
        materialised = tuple(rows)
        fields = frozenset(str(key) for row in materialised for key in row if not str(key).startswith("_"))
        return cls(OracleRelationIdentity(name, facet, kind), fields, materialised)

    def has_field(self, name: str) -> bool:
        return name in self.fields


@dataclass(frozen=True)
class OracleFieldIdentity:
    """Independent ownership of one resolved field."""

    relation: OracleRelationIdentity
    name: str

    @property
    def key(self) -> tuple[tuple[str, str | None, str | None], str]:
        return (self.relation.key, self.name)


@dataclass(frozen=True)
class OracleLogicalRowIdentity:
    """Independent logical row identity scoped to its originating relation."""

    relation: OracleRelationIdentity
    values: tuple[Any, ...]

    @property
    def key(self) -> tuple[tuple[str, str | None, str | None], tuple[Any, ...]]:
        return (self.relation.key, self.values)


@dataclass(frozen=True)
class OracleRelationScope:
    """Independent set of relations visible while evaluating an oracle query body."""

    relations: tuple[OracleRelation, ...]

    def resolve_unqualified_field(self, name: str) -> OracleFieldIdentity | None:
        matches = [relation for relation in self.relations if relation.has_field(name)]
        if len(matches) != 1:
            return None
        return OracleFieldIdentity(matches[0].identity, name)

    def resolve_qualified_field(self, relation_name: str, name: str) -> OracleFieldIdentity | None:
        matches = [
            relation
            for relation in self.relations
            if relation.identity.name is not None
            and relation.identity.name == relation_name
            and relation.has_field(name)
        ]
        if len(matches) != 1:
            return None
        return OracleFieldIdentity(matches[0].identity, name)


def oracle_existence_join(
    left: OracleRelation,
    right: OracleRelation,
    predicate: Callable[[Mapping[str, Any], Mapping[str, Any]], bool | None],
    *,
    anti: bool = False,
) -> tuple[Mapping[str, Any], ...]:
    """Evaluate independent SEMI/ANTI existence semantics over two relations.

    The oracle deliberately accepts a plain Python predicate instead of production
    AST or evaluator objects. Only the literal Boolean value ``True`` constitutes a
    match. ``False`` and ``None`` therefore model SQL FALSE and UNKNOWN uniformly.
    Right-side multiplicity can establish existence but can never multiply a left row.
    """
    selected: list[Mapping[str, Any]] = []
    for left_row in left.rows:
        matched = any(predicate(left_row, right_row) is True for right_row in right.rows)
        if matched != anti:
            selected.append(left_row)
    return tuple(selected)
