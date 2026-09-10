"""Semantic identity helpers shared by yt-sql analysis and optimisation.

Source positions and display-only metadata are intentionally excluded where they
do not contribute to resolved query meaning. These helpers do not replace normal
dataclass equality, which remains useful for exact structural comparisons.
"""

from __future__ import annotations

from typing import Any

from .query_model import (
    AggregateFunction,
    Between,
    Binary,
    CaseWhen,
    CommonTableExpression,
    Field,
    InList,
    IsNull,
    Literal,
    OrderTerm,
    Query,
    ScalarBinary,
    ScalarCase,
    ScalarComparison,
    ScalarFunction,
    ScalarIsNull,
    ScalarUnary,
    SelectTerm,
    SetOperation,
    TextPredicate,
    Unary,
    QuerySyntaxError,
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
            "aggregate",
            node.name,
            tuple(semantic_key(arg) for arg in node.args),
            node.count_star,
            semantic_key(node.filter_predicate),
            node.kind,
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
            "query",
            semantic_key(node.predicate),
            tuple(semantic_key(term) for term in node.order_by),
            node.limit,
            tuple(semantic_key(term) for term in node.select),
            node.from_source,
            node.distinct,
            node.offset,
            tuple(semantic_key(item) for item in node.group_by),
            semantic_key(node.having),
            tuple(semantic_key(cte) for cte in node.ctes),
            tuple(semantic_key(operation) for operation in node.set_operations),
            node.from_facet,
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


def _contains_aggregate(expression: Any) -> bool:
    """Return whether a scalar expression contains an aggregate function."""
    if isinstance(expression, AggregateFunction):
        return True
    if isinstance(expression, ScalarUnary):
        return _contains_aggregate(expression.operand)
    if isinstance(expression, ScalarBinary):
        return _contains_aggregate(expression.left) or _contains_aggregate(expression.right)
    if isinstance(expression, ScalarFunction):
        return any(_contains_aggregate(arg) for arg in expression.args)
    if isinstance(expression, ScalarCase):
        return any(_contains_aggregate(branch.result) for branch in expression.whens) or (
            expression.else_result is not None and _contains_aggregate(expression.else_result)
        )
    return False


def _aggregate_query(query: Query) -> bool:
    return (
        bool(query.group_by)
        or any(_contains_aggregate(term.expression) for term in query.select if term.expression is not None)
        or any(_contains_aggregate(term.expression) for term in query.order_by if term.expression is not None)
        or _having_contains_aggregate(query.having)
    )


def _having_contains_aggregate(node: Any) -> bool:
    if node is None:
        return False
    if isinstance(node, Unary):
        return _having_contains_aggregate(node.operand)
    if isinstance(node, Binary) and node.operator in {"AND", "OR"}:
        return _having_contains_aggregate(node.left) or _having_contains_aggregate(node.right)
    if isinstance(node, ScalarComparison):
        return _contains_aggregate(node.left) or _contains_aggregate(node.right)
    if isinstance(node, ScalarIsNull):
        return _contains_aggregate(node.expression)
    return False


def _contains_random(expression: Any) -> bool:
    if expression is None:
        return False
    if isinstance(expression, ScalarFunction):
        return expression.name == "RANDOM" or any(_contains_random(arg) for arg in expression.args)
    if isinstance(expression, AggregateFunction):
        return any(_contains_random(arg) for arg in expression.args) or _contains_random(expression.filter_predicate)
    if isinstance(expression, (ScalarUnary, Unary)):
        return _contains_random(expression.operand)
    if isinstance(expression, (ScalarBinary, Binary, ScalarComparison)):
        return _contains_random(expression.left) or _contains_random(expression.right)
    if isinstance(expression, ScalarIsNull):
        return _contains_random(expression.expression)
    if isinstance(expression, ScalarCase):
        return any(
            _contains_random(branch.condition) or _contains_random(branch.result) for branch in expression.whens
        ) or _contains_random(expression.else_result)
    if isinstance(expression, Between):
        return (
            _contains_random(expression.field)
            or _contains_random(expression.lower)
            or _contains_random(expression.upper)
        )
    if isinstance(expression, InList):
        return _contains_random(expression.field) or any(_contains_random(value) for value in expression.values)
    if isinstance(expression, IsNull):
        return _contains_random(expression.field)
    if isinstance(expression, TextPredicate):
        return _contains_random(expression.field) or _contains_random(expression.value)
    return False


def _direct_from_sources(query: Query) -> tuple[str, ...]:
    """Return FROM references directly used by one composed query, excluding nested CTE declarations."""
    result: list[str] = []
    if query.from_source is not None:
        result.append(query.from_source)
    for operation in query.set_operations:
        if operation.query.from_source is not None:
            result.append(operation.query.from_source)
    return tuple(result)


def query_physical_source_requests(query: Query) -> tuple[tuple[str, str | None], ...]:
    """Return physical source/facet requests in deterministic first-use order."""
    cte_names = {cte.name.casefold() for cte in query.ctes}
    seen: set[tuple[str, str | None]] = set()
    result: list[tuple[str, str | None]] = []

    def visit(candidate: Query) -> None:
        direct: list[tuple[str, str | None]] = []
        if candidate.from_source is not None:
            direct.append((candidate.from_source, candidate.from_facet))
        for operation in candidate.set_operations:
            if operation.query.from_source is not None:
                direct.append((operation.query.from_source, operation.query.from_facet))
        for source_name, facet in direct:
            if source_name.casefold() in cte_names:
                if facet is not None:
                    raise QuerySyntaxError(
                        query.source,
                        "OF applies only to physical sources, not CTE result relations.",
                        0,
                    )
                continue
            key = (source_name, facet)
            if key in seen:
                continue
            seen.add(key)
            result.append(key)

    for cte in query.ctes:
        visit(cte.query)
    visit(query)
    return tuple(result)


def query_physical_sources(query: Query) -> tuple[str, ...]:
    """Return physical source references in deterministic first-use order."""
    seen: set[str] = set()
    result: list[str] = []
    for source_name, _facet in query_physical_source_requests(query):
        if source_name in seen:
            continue
        seen.add(source_name)
        result.append(source_name)
    return tuple(result)


def query_single_physical_source(query: Query) -> str | None:
    """Return the sole physical source, rejecting genuinely multi-source composition."""
    sources = query_physical_sources(query)
    if len(sources) > 1:
        raise QuerySyntaxError(
            query.source,
            "This operation requires a single physical source; the query contains UNION composition across multiple sources.",
            0,
        )
    return sources[0] if sources else None
