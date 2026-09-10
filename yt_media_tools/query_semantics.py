"""Semantic identity helpers shared by yt-sql analysis and optimisation.

Source positions and display-only metadata are intentionally excluded where they
do not contribute to resolved query meaning. These helpers do not replace normal
dataclass equality, which remains useful for exact structural comparisons.
"""

from __future__ import annotations

from typing import Any

from .query_model import (
    AggregateFunction, Between, Binary, CaseWhen, CommonTableExpression, Field,
    InList, IsNull, Literal, OrderTerm, Query, ScalarBinary, ScalarCase,
    ScalarComparison, ScalarFunction, ScalarIsNull, ScalarUnary, SelectTerm,
    SetOperation, TextPredicate, Unary,
)


def semantic_key(node: Any) -> Any:
    """Return semantic identity while ignoring non-semantic source positions."""
    if isinstance(node, ScalarUnary):
        return ("scalar-unary", node.operator, semantic_key(node.operand), node.kind)
    if isinstance(node, ScalarBinary):
        return ("scalar-binary", node.operator, semantic_key(node.left), semantic_key(node.right), node.kind)
    if isinstance(node, ScalarComparison):
        return ("scalar-comparison", node.operator, semantic_key(node.left), semantic_key(node.right))
    if isinstance(node, ScalarIsNull):
        return ("scalar-is-null", semantic_key(node.expression), node.negated)
    if isinstance(node, ScalarFunction):
        return ("scalar-function", node.name, tuple(semantic_key(arg) for arg in node.args), node.kind)
    if isinstance(node, AggregateFunction):
        return (
            "aggregate", node.name, tuple(semantic_key(arg) for arg in node.args),
            node.count_star, semantic_key(node.filter_predicate), node.kind,
        )
    if isinstance(node, CaseWhen):
        return ("case-when", semantic_key(node.condition), semantic_key(node.result))
    if isinstance(node, ScalarCase):
        return (
            "scalar-case",
            tuple((semantic_key(branch.condition), semantic_key(branch.result)) for branch in node.whens),
            semantic_key(node.else_result),
            node.kind,
        )
    if isinstance(node, Unary):
        return ("unary", node.operator, semantic_key(node.operand))
    if isinstance(node, Binary):
        return ("binary", node.operator, semantic_key(node.left), semantic_key(node.right))
    if isinstance(node, Between):
        return ("between", semantic_key(node.field), semantic_key(node.lower), semantic_key(node.upper), node.negated)
    if isinstance(node, InList):
        return ("in", semantic_key(node.field), tuple(semantic_key(item) for item in node.values), node.negated)
    if isinstance(node, IsNull):
        return ("is-null", semantic_key(node.field), node.negated)
    if isinstance(node, TextPredicate):
        return ("text", node.operator, semantic_key(node.field), semantic_key(node.value), node.negated)
    if isinstance(node, Field):
        return ("field", node.name.casefold(), node.kind)
    if isinstance(node, Literal):
        return ("literal", _hashable_value(node.value), node.quoted)
    if isinstance(node, SelectTerm):
        return ("select", node.field, node.alias, node.kind, semantic_key(node.expression))
    if isinstance(node, OrderTerm):
        return ("order", node.field, node.descending, node.kind, semantic_key(node.expression))
    if isinstance(node, CommonTableExpression):
        return ("cte", node.name.casefold(), semantic_key(node.query))
    if isinstance(node, SetOperation):
        return ("set-operation", node.all, semantic_key(node.query))
    if isinstance(node, Query):
        return (
            "query", semantic_key(node.predicate), tuple(semantic_key(term) for term in node.order_by),
            node.limit, tuple(semantic_key(term) for term in node.select), node.from_source,
            node.distinct, node.offset, tuple(semantic_key(item) for item in node.group_by),
            semantic_key(node.having), tuple(semantic_key(cte) for cte in node.ctes),
            tuple(semantic_key(operation) for operation in node.set_operations), node.from_facet,
        )
    return node


def same_field(left: Any, right: Any) -> bool:
    """Compare resolved fields without treating source positions as semantic."""
    return (
        isinstance(left, Field)
        and isinstance(right, Field)
        and left.name.casefold() == right.name.casefold()
        and left.kind == right.kind
    )


def _hashable_value(value: Any) -> Any:
    try:
        hash(value)
    except TypeError:
        return repr(value)
    return value
