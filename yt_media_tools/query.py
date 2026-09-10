"""Compatibility facade for the yt-sql query language."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .query_evaluator import (
    _compile_like_pattern as _compile_like_pattern,
    apply_query as apply_query,
    canonical_record_value as canonical_record_value,
    evaluate as evaluate,
    evaluate_scalar_expression as evaluate_scalar_expression,
    like_matches as like_matches,
)
from .query_formatter import (
    format_expression as format_expression,
    format_query as format_query,
    format_scalar_expression as format_scalar_expression,
)
from .query_model import (
    AggregateFunction as AggregateFunction,
    Between as Between,
    Binary as Binary,
    CaseWhen as CaseWhen,
    CommonTableExpression as CommonTableExpression,
    Field as Field,
    InList as InList,
    IsNull as IsNull,
    Literal as Literal,
    OrderTerm as OrderTerm,
    Query as Query,
    QuerySyntaxError as QuerySyntaxError,
    ScalarBinary as ScalarBinary,
    ScalarCase as ScalarCase,
    ScalarComparison as ScalarComparison,
    ScalarFunction as ScalarFunction,
    ScalarIsNull as ScalarIsNull,
    ScalarUnary as ScalarUnary,
    SelectTerm as SelectTerm,
    SetOperation as SetOperation,
    TextPredicate as TextPredicate,
    Token as Token,
    Unary as Unary,
)
from .query_parser import (
    Parser as Parser,
    parse_query as parse_query,
    parse_where as parse_where,
    tokenise as tokenise,
)
from .query_resolver import _parse_duration_text as _parse_duration_text
from .query_resolver import resolve_query as resolve_query
from .query_semantics import (
    query_physical_source_requests as query_physical_source_requests,
    query_physical_sources as query_physical_sources,
    query_single_physical_source as query_single_physical_source,
)
from .schema import FieldInfo as FieldInfo
from .schema import QuerySchema as QuerySchema


def merge_queries(base: Query, extra: Query) -> Query:
    predicate = base.predicate
    if extra.predicate is not None:
        predicate = extra.predicate if predicate is None else Binary("AND", predicate, extra.predicate)
    order_by = extra.order_by or base.order_by
    limit = extra.limit if extra.limit is not None else base.limit
    source = base.source or extra.source
    select = extra.select or base.select
    from_source = extra.from_source or base.from_source
    from_facet = extra.from_facet if extra.from_source is not None else base.from_facet
    distinct = extra.distinct or base.distinct
    offset = extra.offset if extra.offset else base.offset
    group_by = extra.group_by or base.group_by
    having = extra.having if extra.having is not None else base.having
    return Query(
        predicate,
        order_by,
        limit,
        source,
        select,
        from_source,
        distinct,
        offset,
        group_by,
        having,
        extra.ctes or base.ctes,
        extra.set_operations or base.set_operations,
        from_facet,
    )


def _display_resolved_value(value: Any) -> str:
    """Render a typed resolved literal for human-facing explanations."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def explain_expression(node: Any) -> str:
    """Describe a parsed or resolved predicate in compact human-readable prose."""
    if isinstance(node, Unary):
        return f"NOT ({explain_expression(node.operand)})"
    if isinstance(node, Binary) and node.operator in {"AND", "OR"}:
        return f"({explain_expression(node.left)} {node.operator} {explain_expression(node.right)})"
    if isinstance(node, Binary):
        return f"{node.left.name} {node.operator} {_display_resolved_value(node.right.value)}"
    if isinstance(node, Between):
        wording = "is not between" if node.negated else "is between"
        return (
            f"{node.field.name} {wording} {_display_resolved_value(node.lower.value)} "
            f"and {_display_resolved_value(node.upper.value)}, inclusive"
        )
    if isinstance(node, InList):
        wording = "is not in" if node.negated else "is in"
        values = ", ".join(_display_resolved_value(item.value) for item in node.values)
        return f"{node.field.name} {wording} ({values})"
    if isinstance(node, IsNull):
        return f"{node.field.name} is {'not ' if node.negated else ''}NULL"
    if isinstance(node, TextPredicate):
        wording = f"does not {node.operator.casefold()}" if node.negated else node.operator.casefold()
        return f"{node.field.name} {wording} {_display_resolved_value(node.value.value)!r}"
    return format_expression(node)
