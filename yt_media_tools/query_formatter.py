"""Canonical yt-sql formatting for parsed and resolved query models."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any

from .dates import TemporalInfinity, canonicalise_temporal_expression

from .query_model import (
    AggregateFunction,
    Between,
    Binary,
    CollectionCount,
    CollectionFilter,
    CollectionProjection,
    CollectionElementReference,
    CollectionPredicate,
    Field,
    InList,
    JoinClause,
    IsNull,
    Literal,
    Query,
    RelationField,
    ScalarBinary,
    ScalarCase,
    ScalarComparison,
    ScalarFunction,
    ScalarIndex,
    ScalarIsNull,
    ScalarMember,
    ScalarUnary,
    TextPredicate,
    TruthTest,
    Unary,
)


_RESERVED_IDENTIFIER_WORDS = {"TRUE", "FALSE", "NULL"}


def _is_identifier_component(value: str) -> bool:
    """Return whether *value* is one ordinary unquoted yt-sql identifier component."""
    if not value or not (value[0] == "_" or value[0].isidentifier()):
        return False
    return all(("A" + character).isidentifier() or character == "-" for character in value[1:])


def _format_identifier_component(value: str) -> str:
    """Render one identifier component, quoting only when the ordinary grammar cannot express it."""
    if _is_identifier_component(value) and value.upper() not in _RESERVED_IDENTIFIER_WORDS:
        return value
    return "`" + value.replace("`", "``") + "`"


def _format_identifier(value: str) -> str:
    """Render a possibly dotted legacy field path with independently quoted components."""
    return ".".join(_format_identifier_component(component) for component in value.split("."))


def _format_literal(literal: Literal, *, expected_kind: str | None = None) -> str:
    """Render a literal, normalising established temporal spellings where type information permits."""
    if literal.value is None:
        return "NULL"
    if isinstance(literal.value, bool):
        return "TRUE" if literal.value else "FALSE"

    temporal_expression = canonicalise_temporal_expression(literal.raw)
    if temporal_expression is not None:
        return temporal_expression

    if isinstance(literal.value, TemporalInfinity):
        return str(literal.value)
    if expected_kind == "date" and isinstance(literal.value, date) and not isinstance(literal.value, datetime):
        return literal.value.isoformat()
    if expected_kind == "datetime" and isinstance(literal.value, datetime):
        value = literal.value.isoformat(timespec="auto")
        if literal.value.utcoffset() == timezone.utc.utcoffset(literal.value):
            value = value.removesuffix("+00:00") + "Z"
        return value
    if expected_kind == "duration" and isinstance(literal.value, (int, float)) and not isinstance(literal.value, bool):
        if isinstance(literal.value, float) and not literal.value.is_integer():
            return f"{literal.value:g}s"
        return f"{int(literal.value)}s"
    return literal.raw


def _format_field_literal(field: Field | RelationField, literal: Literal) -> str:
    return _format_literal(literal, expected_kind=field.kind)


def format_scalar_expression(expression: Any) -> str:
    """Render a scalar expression in canonical yt-sql form."""
    if isinstance(expression, Field):
        return _format_identifier(expression.name)
    if isinstance(expression, RelationField):
        return f"{_format_identifier_component(expression.qualifier)}.{_format_identifier(expression.name)}"
    if isinstance(expression, CollectionElementReference):
        return _format_identifier_component(expression.binding)
    if isinstance(expression, Literal):
        return _format_literal(expression)
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
    if isinstance(expression, ScalarIndex):
        return f"{format_scalar_expression(expression.collection)}[{format_scalar_expression(expression.index)}]"
    if isinstance(expression, ScalarMember):
        value = format_scalar_expression(expression.value)
        # Bare dotted identifiers are an established field-path syntax. Preserve the
        # explicit postfix-member AST when formatting a member whose base would
        # otherwise be re-tokenised as part of that legacy dotted field name.
        if isinstance(expression.value, (Field, Literal, ScalarUnary, ScalarCase)):
            value = f"({value})"
        return f"{value}.{_format_identifier_component(expression.member)}"
    if isinstance(expression, CollectionCount):
        return (
            f"COUNT({format_scalar_expression(expression.collection)} AS {_format_identifier_component(expression.binding)} "
            f"WHERE {format_expression(expression.predicate)})"
        )
    if isinstance(expression, CollectionFilter):
        return (
            f"FILTER({format_scalar_expression(expression.collection)} AS {_format_identifier_component(expression.binding)} "
            f"WHERE {format_expression(expression.predicate)})"
        )
    if isinstance(expression, CollectionProjection):
        return (
            f"MAP({format_scalar_expression(expression.collection)} AS {_format_identifier_component(expression.binding)} "
            f"SELECT {format_scalar_expression(expression.projection)})"
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
    if isinstance(node, RelationField):
        return f"{node.qualifier}.{node.name}"
    if isinstance(node, Literal):
        return _format_literal(node)
    if isinstance(node, Unary):
        return f"NOT ({format_expression(node.operand)})"
    if isinstance(node, Binary):
        if node.operator in {"AND", "OR"}:
            return f"({format_expression(node.left)} {node.operator} {format_expression(node.right)})"
        right = (
            _format_field_literal(node.left, node.right)
            if isinstance(node.left, (Field, RelationField)) and isinstance(node.right, Literal)
            else format_expression(node.right)
        )
        return f"{format_expression(node.left)} {node.operator} {right}"
    if isinstance(node, Between):
        not_part = " NOT" if node.negated else ""
        return (
            f"{node.field.name}{not_part} BETWEEN {_format_field_literal(node.field, node.lower)} "
            f"AND {_format_field_literal(node.field, node.upper)}"
        )
    if isinstance(node, InList):
        not_part = " NOT" if node.negated else ""
        values = ", ".join(_format_field_literal(node.field, value) for value in node.values)
        return f"{node.field.name}{not_part} IN ({values})"
    if isinstance(node, IsNull):
        return f"{node.field.name} IS {'NOT ' if node.negated else ''}NULL"
    if isinstance(node, TextPredicate):
        not_part = " NOT" if node.negated else ""
        return f"{node.field.name}{not_part} {node.operator} {_format_field_literal(node.field, node.value)}"
    if isinstance(node, CollectionPredicate):
        return (
            f"{node.quantifier}({format_scalar_expression(node.collection)} AS {node.binding} "
            f"WHERE {format_expression(node.predicate)})"
        )
    if isinstance(node, ScalarComparison):
        right = (
            _format_field_literal(node.left, node.right)
            if isinstance(node.left, (Field, RelationField)) and isinstance(node.right, Literal)
            else format_scalar_expression(node.right)
        )
        return f"{format_scalar_expression(node.left)} {node.operator} {right}"
    if isinstance(node, TruthTest):
        # Preserve the established compact Boolean-field spelling while making
        # general predicate inspection unambiguous in canonical output.
        if (
            isinstance(node.operand, Binary)
            and node.operand.operator == "="
            and isinstance(node.operand.left, (Field, RelationField))
            and isinstance(node.operand.right, Literal)
            and node.operand.right.value is True
        ):
            operand = format_expression(node.operand.left)
        else:
            operand = f"({format_expression(node.operand)})"
        return f"{operand} IS {'NOT ' if node.negated else ''}{node.truth}"
    if isinstance(node, ScalarIsNull):
        return f"{format_scalar_expression(node.expression)} IS {'NOT ' if node.negated else ''}NULL"
    raise AssertionError(f"Unsupported query node {node!r}")


def _format_relation_source(
    source: str, facet: str | None = None, alias: str | None = None, *, identifier_source: bool = False
) -> str:
    """Render one relation reference without changing source identity."""
    if identifier_source:
        text = _format_identifier_component(source)
    elif re.fullmatch(r"@[A-Za-z0-9_.-]+|[A-Za-z_][A-Za-z0-9_.-]*", source):
        text = source
    else:
        escaped = source.replace("'", "''")
        text = f"'{escaped}'"
    if facet is not None:
        text += f" OF {_format_identifier_component(facet)}"
    if alias is not None:
        text += f" AS {_format_identifier_component(alias)}"
    return text


def _format_join(join: JoinClause, *, identifier_sources: frozenset[str] = frozenset()) -> str:
    """Render one parser-level JOIN clause canonically."""
    keyword = "JOIN" if join.kind.value == "INNER" else f"{join.kind.value} JOIN"
    relation = _format_relation_source(
        join.relation.source,
        join.relation.facet,
        join.relation.alias,
        identifier_source=join.relation.source in identifier_sources,
    )
    return f"{keyword} {relation} ON {format_expression(join.predicate)}"


def _format_select_term(term: Any) -> str:
    """Render one SELECT term without adding a redundant semantic-name alias."""
    field_text = term.field
    implicit_name = term.expression.name if isinstance(term.expression, Field) else term.field
    if term.alias and term.alias != implicit_name:
        return f"{field_text} AS {_format_identifier_component(term.alias)}"
    return field_text


def format_query(query: Query, *, _identifier_sources: frozenset[str] = frozenset()) -> str:
    parts: list[str] = []
    local_identifier_sources = _identifier_sources | frozenset(cte.name for cte in query.ctes)
    if query.ctes:
        cte_text = ", ".join(
            f"{_format_identifier_component(cte.name)} AS ({format_query(cte.query, _identifier_sources=local_identifier_sources)})"
            for cte in query.ctes
        )
        parts.append(f"WITH {cte_text}")
    if query.select:
        parts.append(
            ("SELECT DISTINCT " if query.distinct else "SELECT ")
            + ", ".join(_format_select_term(term) for term in query.select)
        )
    if query.from_source is not None:
        parts.append(
            f"FROM {_format_relation_source(query.from_source, query.from_facet, query.from_alias, identifier_source=query.from_source in local_identifier_sources)}"
        )
        parts.extend(_format_join(join, identifier_sources=local_identifier_sources) for join in query.joins)
    if query.predicate is not None:
        parts.append(f"WHERE {format_expression(query.predicate)}")
    if query.group_by:
        parts.append("GROUP BY " + ", ".join(format_scalar_expression(item) for item in query.group_by))
    if query.having is not None:
        parts.append(f"HAVING {format_expression(query.having)}")
    for operation in query.set_operations:
        parts.append(
            ("UNION ALL " if operation.all else "UNION ")
            + format_query(operation.query, _identifier_sources=local_identifier_sources)
        )
    if query.order_by:
        parts.append(
            "ORDER BY " + ", ".join(f"{term.field} {'DESC' if term.descending else 'ASC'}" for term in query.order_by)
        )
    if query.limit is not None:
        parts.append(f"LIMIT {query.limit}")
    if query.offset:
        parts.append(f"OFFSET {query.offset}")
    return " ".join(parts) if parts else "<no projection, source, filtering, ordering, or limit>"
