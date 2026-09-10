"""Canonical yt-sql formatting for parsed and resolved query models."""

from __future__ import annotations

import re
from typing import Any

from .query_model import (
    AggregateFunction,
    Between,
    Binary,
    Field,
    InList,
    IsNull,
    Literal,
    Query,
    ScalarBinary,
    ScalarCase,
    ScalarComparison,
    ScalarFunction,
    ScalarIsNull,
    ScalarUnary,
    TextPredicate,
    Unary,
)


def format_scalar_expression(expression: Any) -> str:
    """Render a scalar expression in canonical yt-sql form."""
    if isinstance(expression, Field):
        return expression.name
    if isinstance(expression, Literal):
        if expression.value is None:
            return "NULL"
        if isinstance(expression.value, bool):
            return "TRUE" if expression.value else "FALSE"
        return expression.raw
    if isinstance(expression, ScalarUnary):
        operand = format_scalar_expression(expression.operand)
        if isinstance(expression.operand, ScalarBinary):
            operand = f"({operand})"
        return f"{expression.operator}{operand}"
    if isinstance(expression, ScalarBinary):
        return (
            f"({format_scalar_expression(expression.left)} {expression.operator} "
            f"{format_scalar_expression(expression.right)})"
        )
    if isinstance(expression, ScalarFunction):
        return f"{expression.name}({', '.join(format_scalar_expression(arg) for arg in expression.args)})"
    if isinstance(expression, AggregateFunction):
        inner = "*" if expression.count_star else ", ".join(format_scalar_expression(arg) for arg in expression.args)
        text = f"{expression.name}({inner})"
        if expression.filter_predicate is not None:
            text += f" FILTER (WHERE {format_expression(expression.filter_predicate)})"
        return text
    if isinstance(expression, ScalarCase):
        parts = ["CASE"]
        for branch in expression.whens:
            parts.append(f"WHEN {format_expression(branch.condition)} THEN {format_scalar_expression(branch.result)}")
        if expression.else_result is not None:
            parts.append(f"ELSE {format_scalar_expression(expression.else_result)}")
        parts.append("END")
        return " ".join(parts)
    raise AssertionError(f"Unsupported scalar expression {expression!r}")


def format_expression(node: Any) -> str:
    if isinstance(node, Field):
        return node.name
    if isinstance(node, Literal):
        if node.value is None:
            return "NULL"
        if isinstance(node.value, bool):
            return "TRUE" if node.value else "FALSE"
        return node.raw
    if isinstance(node, Unary):
        return f"NOT ({format_expression(node.operand)})"
    if isinstance(node, Binary):
        if node.operator in {"AND", "OR"}:
            return f"({format_expression(node.left)} {node.operator} {format_expression(node.right)})"
        return f"{format_expression(node.left)} {node.operator} {format_expression(node.right)}"
    if isinstance(node, Between):
        not_part = " NOT" if node.negated else ""
        return (
            f"{node.field.name}{not_part} BETWEEN {format_expression(node.lower)} AND {format_expression(node.upper)}"
        )
    if isinstance(node, InList):
        not_part = " NOT" if node.negated else ""
        values = ", ".join(format_expression(value) for value in node.values)
        return f"{node.field.name}{not_part} IN ({values})"
    if isinstance(node, IsNull):
        return f"{node.field.name} IS {'NOT ' if node.negated else ''}NULL"
    if isinstance(node, TextPredicate):
        not_part = " NOT" if node.negated else ""
        return f"{node.field.name}{not_part} {node.operator} {format_expression(node.value)}"
    if isinstance(node, ScalarComparison):
        return f"{format_scalar_expression(node.left)} {node.operator} {format_scalar_expression(node.right)}"
    if isinstance(node, ScalarIsNull):
        return f"{format_scalar_expression(node.expression)} IS {'NOT ' if node.negated else ''}NULL"
    raise AssertionError(f"Unsupported query node {node!r}")


def format_query(query: Query) -> str:
    parts: list[str] = []
    if query.ctes:
        cte_text = ", ".join(f"{cte.name} AS ({format_query(cte.query)})" for cte in query.ctes)
        parts.append(f"WITH {cte_text}")
    if query.select:
        parts.append(
            ("SELECT DISTINCT " if query.distinct else "SELECT ")
            + ", ".join(
                f"{term.field} AS {term.alias}" if term.alias and term.alias != term.field else term.field
                for term in query.select
            )
        )
    if query.from_source is not None:
        source = query.from_source
        if re.fullmatch(r"@[A-Za-z0-9_.-]+|[A-Za-z_][A-Za-z0-9_.-]*", source):
            parts.append(f"FROM {source}")
        else:
            escaped = source.replace("'", "''")
            parts.append(f"FROM '{escaped}'")
        if query.from_facet is not None:
            parts.append(f"OF {query.from_facet}")
    if query.predicate is not None:
        parts.append(f"WHERE {format_expression(query.predicate)}")
    if query.group_by:
        parts.append("GROUP BY " + ", ".join(format_scalar_expression(item) for item in query.group_by))
    if query.having is not None:
        parts.append(f"HAVING {format_expression(query.having)}")
    for operation in query.set_operations:
        parts.append(("UNION ALL " if operation.all else "UNION ") + format_query(operation.query))
    if query.order_by:
        parts.append(
            "ORDER BY " + ", ".join(f"{term.field} {'DESC' if term.descending else 'ASC'}" for term in query.order_by)
        )
    if query.limit is not None:
        parts.append(f"LIMIT {query.limit}")
    if query.offset:
        parts.append(f"OFFSET {query.offset}")
    return " ".join(parts) if parts else "<no projection, source, filtering, ordering, or limit>"
