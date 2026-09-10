"""Semantic properties consumed by optimisation and acquisition planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .query_model import (
    AggregateFunction,
    Binary,
    Field,
    Query,
    ScalarBinary,
    ScalarCase,
    ScalarComparison,
    ScalarFunction,
    ScalarIsNull,
    ScalarUnary,
    Unary,
)
from .query_semantics import _contains_aggregate
from .schema import ALIASES, KNOWN_FIELD_TYPES
from .source_capabilities import FieldCapability, field_capability, selected_facet_capabilities
from .source_model import SourceSpec


@dataclass(frozen=True)
class QueryProperties:
    """Stable semantic requirements derived from a resolved query."""

    required_fields: frozenset[str]
    dynamic_fields: tuple[str, ...]
    requires_aggregation: bool
    source: SourceSpec | None = None

    def field_capability(self, field: str) -> FieldCapability:
        """Return the selected source contract when available, otherwise the stable default."""
        if self.source is not None:
            return selected_facet_capabilities(self.source).field(field)
        return field_capability(field)


def _fields_in_predicate(node: Any) -> set[str]:
    if node is None:
        return set()
    if isinstance(node, Unary):
        return _fields_in_predicate(node.operand)
    if isinstance(node, Binary) and node.operator in {"AND", "OR"}:
        return _fields_in_predicate(node.left) | _fields_in_predicate(node.right)
    field = getattr(node, "field", None)
    if isinstance(field, Field):
        return {field.name.casefold()}
    if isinstance(node, Binary) and isinstance(node.left, Field):
        return {node.left.name.casefold()}
    return set()


def _fields_in_scalar(expression: Any) -> set[str]:
    if expression is None:
        return set()
    if isinstance(expression, Field):
        return {expression.name.casefold()}
    if isinstance(expression, ScalarUnary):
        return _fields_in_scalar(expression.operand)
    if isinstance(expression, ScalarBinary):
        return _fields_in_scalar(expression.left) | _fields_in_scalar(expression.right)
    if isinstance(expression, AggregateFunction):
        fields: set[str] = set()
        for arg in expression.args:
            fields.update(_fields_in_scalar(arg))
        fields.update(_fields_in_predicate(expression.filter_predicate))
        return fields
    if isinstance(expression, ScalarFunction):
        fields: set[str] = set()
        for arg in expression.args:
            fields.update(_fields_in_scalar(arg))
        return fields
    if isinstance(expression, ScalarCase):
        fields: set[str] = set()
        for branch in expression.whens:
            fields.update(_fields_in_predicate(branch.condition))
            fields.update(_fields_in_scalar(branch.result))
        fields.update(_fields_in_scalar(expression.else_result))
        return fields
    return set()


def _fields_in_having(node: Any) -> set[str]:
    if node is None:
        return set()
    if isinstance(node, Unary):
        return _fields_in_having(node.operand)
    if isinstance(node, Binary) and node.operator in {"AND", "OR"}:
        return _fields_in_having(node.left) | _fields_in_having(node.right)
    if isinstance(node, ScalarComparison):
        return _fields_in_scalar(node.left) | _fields_in_scalar(node.right)
    if isinstance(node, ScalarIsNull):
        return _fields_in_scalar(node.expression)
    return set()


def _required_body_fields(query: Query) -> set[str]:
    fields = _fields_in_predicate(query.predicate)
    for term in query.order_by:
        fields.update(_fields_in_scalar(term.expression) if term.expression is not None else {term.field.casefold()})
    for term in query.select or ():
        fields.update(_fields_in_scalar(term.expression) if term.expression is not None else {term.field.casefold()})
    for expression in query.group_by:
        fields.update(_fields_in_scalar(expression))
    fields.update(_fields_in_having(query.having))
    if not query.select:
        fields.add("id")
    return fields


def required_query_fields(query: Query) -> set[str]:
    """Return physical-source fields needed by a query, CTEs and UNION branches."""
    cte_names = {cte.name.casefold() for cte in query.ctes}
    fields: set[str] = set()

    def visit(candidate: Query) -> None:
        if (candidate.from_source or "").casefold() not in cte_names:
            fields.update(_required_body_fields(candidate))
        for operation in candidate.set_operations:
            visit(operation.query)

    for cte in query.ctes:
        visit(cte.query)
    visit(query)
    return fields


def analyse_query(query: Query, *, source: SourceSpec | None = None) -> QueryProperties:
    """Derive semantic requirements without performing source acquisition."""
    fields = required_query_fields(query)
    dynamic = tuple(
        sorted(
            field for field in fields if field.casefold() not in KNOWN_FIELD_TYPES and field.casefold() not in ALIASES
        )
    )
    aggregate = bool(
        query.group_by
        or query.having is not None
        or any(_contains_aggregate(term.expression) for term in query.select + query.order_by)
    )
    return QueryProperties(frozenset(fields), dynamic, aggregate, source)
