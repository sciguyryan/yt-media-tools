"""Semantic relation binding for staged yt-sql JOIN queries.

This module resolves relation aliases and field ownership without making JOIN
executable. It is intentionally usable before relational evaluation exists so
later JOIN phases inherit deterministic scope and ambiguity rules.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass, replace
from typing import Any

from .query_model import Field, Query, QuerySemanticError, RelationField
from .query_scope import SemanticScope, relation_binding
from .schema import QuerySchema


def _rewrite_value(value: Any, scope: SemanticScope, source: str) -> Any:
    if isinstance(value, Field):
        parts = value.name.split(".", 1)
        if len(parts) == 2:
            qualifier, field_name = parts
            binding = scope.binding_for_qualifier(qualifier)
            if binding is not None:
                info = binding.schema.resolve(field_name)
                if info is None:
                    raise QuerySemanticError(
                        source,
                        f"Relation {qualifier!r} has no field {field_name!r}.",
                        value.position,
                    )
                canonical = info.alias_of or info.name
                return RelationField(qualifier, canonical, value.position, info.kind, binding.identity.key)

            # A dotted identifier can still be an established structured/raw field
            # path. Diagnose an unknown relation qualifier only when the suffix is a
            # visible row field, making the user's relational intent unambiguous.
            if any(binding.schema.resolve(field_name) is not None for binding in scope.relations):
                raise QuerySemanticError(source, f"Unknown relation alias {qualifier!r}.", value.position)

        matches = scope.field_matches(value.name)
        if not matches:
            raise QuerySemanticError(source, f"Unknown field {value.name!r}.", value.position)
        if len(matches) > 1:
            raise QuerySemanticError(
                source,
                f"Ambiguous field {value.name!r}; qualify it with a relation alias.",
                value.position,
            )
        match = matches[0]
        binding = next(binding for binding in scope.relations if binding.identity == match.relation)
        canonical = match.field.alias_of or match.field.name
        return RelationField(binding.qualifier or "", canonical, value.position, match.field.kind, match.relation.key)

    if isinstance(value, tuple):
        return tuple(_rewrite_value(item, scope, source) for item in value)
    if isinstance(value, list):
        return [_rewrite_value(item, scope, source) for item in value]
    if is_dataclass(value):
        changes: dict[str, Any] = {}
        for field_info in fields(value):
            current = getattr(value, field_info.name)
            # Primitive metadata is left alone. AST children are dataclasses/tuples.
            if is_dataclass(current) or isinstance(current, (tuple, list)):
                rewritten = _rewrite_value(current, scope, source)
                if rewritten != current:
                    changes[field_info.name] = rewritten
        return replace(value, **changes) if changes else value
    return value


def _scope_for_query(
    query: Query,
    physical_schema: QuerySchema,
    cte_schemas: dict[str, QuerySchema],
    source_schemas: dict[tuple[str, str | None], QuerySchema],
) -> SemanticScope:
    if query.from_alias is None:
        raise QuerySemanticError(
            query.source,
            "The primary relation in a JOIN query requires an AS alias.",
            query.source.find("FROM") if "FROM" in query.source else 0,
        )

    left = relation_binding(query.from_source, query.from_facet, physical_schema, cte_schemas, source_schemas)
    bindings = [replace(left, qualifier=query.from_alias)]
    aliases = {query.from_alias}
    for join in query.joins:
        alias = join.relation.alias
        if alias is None:
            raise QuerySemanticError(
                query.source,
                "Each joined relation requires an AS alias.",
                join.relation.position,
            )
        if alias in aliases:
            raise QuerySemanticError(query.source, f"Duplicate relation alias {alias!r}.", join.relation.position)
        aliases.add(alias)
        binding = relation_binding(
            join.relation.source,
            join.relation.facet,
            physical_schema,
            cte_schemas,
            source_schemas,
        )
        bindings.append(replace(binding, qualifier=alias))
    return SemanticScope(tuple(bindings))


def resolve_join_references(
    query: Query,
    physical_schema: QuerySchema,
    *,
    cte_schemas: dict[str, QuerySchema] | None = None,
    source_schemas: dict[tuple[str, str | None], QuerySchema] | None = None,
) -> Query:
    """Resolve aliases and field ownership for one JOIN query body.

    The returned query is still not executable. ``RelationField`` nodes record the
    owning relation independently from structured ``ScalarMember`` access.
    """
    if not query.joins:
        return query
    scope = _scope_for_query(query, physical_schema, cte_schemas or {}, source_schemas or {})

    joins = tuple(replace(join, predicate=_rewrite_value(join.predicate, scope, query.source)) for join in query.joins)
    select = tuple(_rewrite_value(term, scope, query.source) for term in query.select)
    order_by = tuple(_rewrite_value(term, scope, query.source) for term in query.order_by)
    group_by = tuple(_rewrite_value(item, scope, query.source) for item in query.group_by)
    predicate = _rewrite_value(query.predicate, scope, query.source) if query.predicate is not None else None
    having = _rewrite_value(query.having, scope, query.source) if query.having is not None else None
    return replace(
        query,
        joins=joins,
        select=select,
        order_by=order_by,
        group_by=group_by,
        predicate=predicate,
        having=having,
    )
