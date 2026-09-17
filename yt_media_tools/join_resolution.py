"""Semantic relation binding for staged yt-sql JOIN queries.

This module resolves relation aliases and field ownership without making JOIN
executable. It is intentionally usable before relational evaluation exists so
later JOIN phases inherit deterministic scope and ambiguity rules.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass, replace
from typing import Any

from .query_model import (
    AggregateFunction,
    Field,
    ScalarFunction,
    Query,
    QuerySemanticError,
    RelationField,
    RelationWildcard,
    SelectTerm,
)
from .query_scope import SemanticScope, relation_binding
from .query_traversal import walk_ast
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


def _scope_through_join(scope: SemanticScope, join_index: int) -> SemanticScope:
    """Return the relations visible to one JOIN edge, including its right side."""
    return SemanticScope(scope.relations[: join_index + 2])


def _validate_join_predicate(predicate: Any, source: str) -> None:
    """Reject row-unsafe expressions from a JOIN ON predicate.

    JOIN matching is defined over individual relation rows. Aggregate evaluation
    and volatile randomness therefore cannot participate in ON semantics.
    """
    for node in walk_ast(predicate):
        if isinstance(node, AggregateFunction):
            raise QuerySemanticError(
                source,
                "Aggregate functions are not allowed in JOIN ON predicates.",
                node.position,
            )
        if isinstance(node, ScalarFunction) and node.name == "RANDOM":
            raise QuerySemanticError(
                source,
                "RANDOM is not allowed in JOIN ON predicates.",
                node.position,
            )


def _projection_output_name(term: SelectTerm) -> str:
    """Return the externally visible name of one resolved projection term."""
    if term.alias is not None:
        return term.alias
    if isinstance(term.expression, RelationField):
        return term.expression.name
    return term.field


def _expand_join_projection(query: Query, scope: SemanticScope) -> tuple[SelectTerm, ...]:
    """Expand relation wildcards and enforce unique joined projection names."""
    selected = query.select or (SelectTerm("id"),)
    expanded: list[SelectTerm] = []

    if len(selected) == 1 and selected[0].field == "*" and selected[0].expression is None:
        primary = scope.relations[0]
        for info in primary.schema.select_star_fields():
            canonical = info.alias_of or info.name
            expression = RelationField(
                primary.qualifier or "",
                canonical,
                selected[0].position,
                info.kind,
                primary.identity.key,
            )
            expanded.append(SelectTerm(canonical, canonical, selected[0].position, info.kind, expression))
    else:
        for term in selected:
            if isinstance(term.expression, RelationWildcard):
                binding = scope.binding_for_qualifier(term.expression.qualifier)
                if binding is None:
                    raise QuerySemanticError(
                        query.source,
                        f"Unknown relation alias {term.expression.qualifier!r}.",
                        term.position,
                    )
                for info in binding.schema.select_star_fields():
                    canonical = info.alias_of or info.name
                    expression = RelationField(
                        binding.qualifier or "",
                        canonical,
                        term.position,
                        info.kind,
                        binding.identity.key,
                    )
                    expanded.append(SelectTerm(canonical, canonical, term.position, info.kind, expression))
            else:
                output_name = _projection_output_name(term)
                expanded.append(replace(term, alias=output_name))

    names: set[str] = set()
    for term in expanded:
        output_name = _projection_output_name(term)
        key = output_name.casefold()
        if key in names:
            raise QuerySemanticError(
                query.source,
                f"Duplicate SELECT output name {output_name!r}; use AS to give fields unique names.",
                term.position,
            )
        names.add(key)
    return tuple(expanded)


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

    resolved_joins = []
    for index, join in enumerate(query.joins):
        join_scope = _scope_through_join(scope, index)
        predicate = _rewrite_value(join.predicate, join_scope, query.source)
        _validate_join_predicate(predicate, query.source)
        resolved_joins.append(replace(join, predicate=predicate))
    joins = tuple(resolved_joins)
    select = tuple(_rewrite_value(term, scope, query.source) for term in query.select)
    projection_query = replace(query, select=select)
    select = _expand_join_projection(projection_query, scope)
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


def prepare_join_query(
    query: Query,
    physical_schema: QuerySchema,
    *,
    cte_schemas: dict[str, QuerySchema] | None = None,
    source_schemas: dict[tuple[str, str | None], QuerySchema] | None = None,
) -> Query:
    """Prepare one executable single JOIN after relation-scope resolution.

    Phase 7 completes issue #62 by adding LEFT JOIN to the existing INNER, SEMI
    and ANTI execution boundary. Row-producing joins retain explicit relation
    bindings for downstream filtering, ordering and projection. Multi-way JOIN
    execution remains a deterministic future boundary.
    """
    resolved = resolve_join_references(
        query,
        physical_schema,
        cte_schemas=cte_schemas,
        source_schemas=source_schemas,
    )
    if len(resolved.joins) != 1:
        raise QuerySemanticError(
            query.source,
            "Multi-way JOIN execution is not implemented yet.",
            resolved.joins[1].position if len(resolved.joins) > 1 else 0,
        )
    join = resolved.joins[0]
    if join.kind.value not in {"SEMI", "ANTI", "INNER", "LEFT"}:
        raise QuerySemanticError(
            query.source,
            "JOIN syntax is recognised, but JOIN execution is not implemented yet.",
            join.position,
        )

    if join.kind.value in {"INNER", "LEFT"}:
        return resolved

    primary_alias = resolved.from_alias or ""

    def left_only(value: Any) -> Any:
        if isinstance(value, RelationField):
            if value.qualifier != primary_alias:
                raise QuerySemanticError(
                    query.source,
                    f"{join.kind.value} JOIN does not expose fields from relation {value.qualifier!r}.",
                    value.position,
                )
            return Field(value.name, value.position, value.kind)
        if isinstance(value, tuple):
            return tuple(left_only(item) for item in value)
        if isinstance(value, list):
            return [left_only(item) for item in value]
        if is_dataclass(value):
            changes: dict[str, Any] = {}
            for field_info in fields(value):
                current = getattr(value, field_info.name)
                if is_dataclass(current) or isinstance(current, (tuple, list)):
                    rewritten = left_only(current)
                    if rewritten != current:
                        changes[field_info.name] = rewritten
            return replace(value, **changes) if changes else value
        return value

    return replace(
        resolved,
        select=left_only(resolved.select),
        order_by=left_only(resolved.order_by),
        group_by=left_only(resolved.group_by),
        predicate=left_only(resolved.predicate),
        having=left_only(resolved.having),
    )
