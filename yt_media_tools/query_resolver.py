"""Semantic resolution for parsed yt-sql queries."""

from __future__ import annotations

import difflib
import re
from dataclasses import replace
from datetime import date, datetime
from typing import Any, Sequence

from .dates import DateContext, parse_date_literal, parse_datetime_literal, parse_temporal_infinity
from .query_evaluator import _coerce_char_codepoint, _compile_like_pattern, evaluate_scalar_expression
from .query_formatter import format_scalar_expression
from .query_model import (
    AggregateFunction,
    Between,
    Binary,
    CaseWhen,
    CommonTableExpression,
    CollectionCount,
    CollectionFilter,
    CollectionProjection,
    CollectionElementReference,
    CollectionPredicate,
    Field,
    InList,
    IsNull,
    Literal,
    OrderTerm,
    Query,
    RelationField,
    QuerySemanticError,
    QuerySyntaxError,
    ScalarBinary,
    ScalarCase,
    ScalarComparison,
    ScalarFunction,
    ScalarIndex,
    ScalarMember,
    ScalarIsNull,
    ScalarUnary,
    SelectTerm,
    SetOperation,
    TextPredicate,
    Unary,
)
from .query_parser import _parse_integer_literal_text, _parse_number_text, _validate_like_pattern
from .join_resolution import prepare_join_query
from .query_scope import relation_binding
from .query_traversal import walk_ast
from .query_semantics import (
    _aggregate_query,
    _contains_aggregate,
    _contains_random,
    _direct_from_sources,
)
from .query_types import QueryType
from .schema import FieldInfo, QuerySchema
from .units import load_default_unit_registry


_DURATION_PART_RE = re.compile(
    r"(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>[^\W\d_]+(?:-[^\W\d_]+)*)",
    re.IGNORECASE,
)


def _diagnostic_position(node: Any, default: int = 0) -> int:
    """Return the earliest useful source position owned by an AST subtree."""
    positions = [
        position
        for item in walk_ast(node)
        if isinstance((position := getattr(item, "position", None)), int) and position >= 0
    ]
    return min(positions) if positions else default


def _random_position(node: Any, default: int = 0) -> int:
    """Return the source position of the first RANDOM expression in a subtree."""
    for item in walk_ast(node):
        if isinstance(item, ScalarFunction) and item.name == "RANDOM":
            return item.position
    return _diagnostic_position(node, default)


def _parse_duration_text(text: str, source: str, position: int) -> int:
    value = " ".join(text.strip().split())
    if re.fullmatch(r"\d+(?::\d{1,2}){1,2}", value):
        parts = [int(part) for part in value.split(":")]
        if len(parts) == 2:
            minutes, seconds = parts
            if seconds >= 60:
                raise QuerySemanticError(source, "Duration seconds must be below 60.", position)
            return minutes * 60 + seconds
        hours, minutes, seconds = parts
        if minutes >= 60 or seconds >= 60:
            raise QuerySemanticError(source, "Duration minutes and seconds must be below 60.", position)
        return hours * 3600 + minutes * 60 + seconds

    if re.fullmatch(r"\d+(?:\.\d+)?", value):
        raise QuerySemanticError(
            source,
            "A duration needs a unit, for example 30s, 10m, 2h, or 1h30m.",
            position,
        )

    compact = value.replace(" ", "")
    if re.fullmatch(r"(?:\d+(?:\.\d+)?(?:h|m|s))+", compact, re.IGNORECASE):
        value = compact

    total = 0.0
    cursor = 0
    matched = False
    registry = load_default_unit_registry()
    for match in _DURATION_PART_RE.finditer(value):
        if value[cursor : match.start()].strip():
            raise QuerySemanticError(source, f"Could not understand duration {text!r}.", position + cursor)
        try:
            unit = registry.resolve(match.group("unit"))
        except ValueError as exc:
            raise QuerySemanticError(
                source,
                f"Unknown duration unit {match.group('unit')!r}.",
                position + match.start("unit"),
            ) from exc
        if unit.kind != "fixed":
            raise QuerySemanticError(
                source,
                f"Calendar unit {match.group('unit')!r} cannot be used for a duration.",
                position + match.start("unit"),
            )
        matched = True
        total += float(match.group("number")) * unit.amount
        cursor = match.end()
    if not matched or value[cursor:].strip():
        raise QuerySemanticError(source, f"Could not understand duration {text!r}.", position + cursor)
    return round(total)


def _parse_count_text(text: str, source: str, position: int) -> int:
    compact = re.sub(r"\s+", "", text)
    if re.match(r"[+-]?0[xXoObB]", compact):
        return _parse_integer_literal_text(compact, source, position)

    match = re.fullmatch(r"(\d+(?:_\d+)*(?:\.\d+(?:_\d+)*)?)([kKmMbB]?)", compact)
    if not match:
        raise QuerySemanticError(source, f"Could not understand count {text!r}.", position)
    multiplier = {"": 1, "k": 1_000, "m": 1_000_000, "b": 1_000_000_000}[match.group(2).lower()]
    number = match.group(1).replace("_", "")
    return round(float(number) * multiplier)


def _resolve_field(field: Field | RelationField, schema: QuerySchema, source: str) -> Field | RelationField:
    if isinstance(field, RelationField):
        return field
    info = schema.resolve(field.name)
    if info is None:
        candidates = [item.name for item in schema.available_fields()]
        if field.name.casefold().startswith("raw."):
            candidates.extend(item.name for item in schema.raw_scalar_paths())
        suggestion = difflib.get_close_matches(field.name, candidates, n=1, cutoff=0.6)
        message = f"Unknown field {field.name!r}."
        if suggestion:
            message += f" Did you mean {suggestion[0]!r}?"
        raise QuerySemanticError(source, message, field.position)
    canonical = info.alias_of or info.name
    return Field(canonical, field.position, info.kind)


def _resolve_literal(literal: Literal, field: Field | RelationField, source: str, dates: DateContext) -> Literal:
    if literal.value is None or isinstance(literal.value, bool):
        return literal
    text = str(literal.value)
    kind = field.kind or "unknown"
    if parse_temporal_infinity(text, expected="date") is not None and kind not in {"date", "datetime"}:
        raise QuerySemanticError(
            source,
            "INFINITY() and -INFINITY() are valid only for date or datetime fields.",
            literal.position,
        )
    try:
        if kind == "duration":
            value = _parse_duration_text(text, source, literal.position)
        elif kind == "count":
            value = _parse_count_text(text, source, literal.position)
        elif kind == "date":
            value = parse_temporal_infinity(text, expected="date")
            if value is None:
                value = parse_date_literal(text, dates)
        elif kind == "datetime":
            value = parse_temporal_infinity(text, expected="datetime")
            if value is None:
                value = parse_datetime_literal(text, dates)
        elif kind in {"integer"}:
            value = _parse_number_text(text, source, literal.position)
            if not isinstance(value, int):
                raise QuerySemanticError(source, f"Field {field.name!r} requires an integer.", literal.position)
        elif kind in {"number"}:
            value = _parse_number_text(text, source, literal.position)
        elif kind == "boolean":
            lowered = text.casefold()
            if lowered not in {"true", "false"}:
                raise QuerySemanticError(source, f"Field {field.name!r} requires TRUE or FALSE.", literal.position)
            value = lowered == "true"
        elif kind == "structured":
            raise QuerySemanticError(
                source,
                f"Field {field.name!r} is an object or array and cannot be used as a scalar value.",
                field.position,
            )
        elif kind == "mixed":
            value = _generic_literal(text, literal.quoted)
        elif kind == "string":
            value = text
        else:
            value = _generic_literal(text, literal.quoted)
    except ValueError as exc:
        raise QuerySemanticError(source, str(exc), literal.position) from exc
    return replace(literal, value=value)


def _generic_literal(text: str, quoted: bool) -> Any:
    if quoted:
        return text
    lowered = text.casefold()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    compact = re.sub(r"\s+", "", text)
    if re.match(r"[+-]?0[xXoObB]", compact) or re.match(r"[+-]?\d", compact):
        try:
            return _parse_number_text(compact, text, 0)
        except QuerySyntaxError:
            pass
    return text


def _scalar_kind(expression: Any) -> str | None:
    kind = getattr(expression, "kind", None)
    if kind is not None:
        return kind
    if isinstance(expression, Literal):
        value = expression.value
        if value is None:
            return None
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float):
            return "number"
        if isinstance(value, datetime):
            return "datetime"
        if isinstance(value, date):
            return "date"
        if isinstance(value, str):
            return "string"
    return None


def _scalar_query_type(expression: Any, schema: QuerySchema) -> QueryType | None:
    """Return the complete resolved yt-sql type when it is available."""
    resolved_type = getattr(expression, "resolved_type", None)
    if resolved_type is not None:
        return resolved_type
    if isinstance(expression, Field):
        info = schema.resolve(expression.name)
        if expression.kind == "collection" and (info is None or info.kind != "collection"):
            info = schema.resolve_index_operand(expression.name)
        return info.query_type if info is not None else None
    kind = _scalar_kind(expression)
    if kind is None:
        return None
    return QueryType.scalar(kind, nullable=True)


def _value_preserving_function_type(args: tuple[Any, ...], schema: QuerySchema) -> QueryType | None:
    """Return a compatible collection or structured result type for preserving functions."""
    types = [value for arg in args if (value := _scalar_query_type(arg, schema)) is not None]
    complex_types = [value for value in types if value.is_collection or value.is_structured]
    if not complex_types:
        return None
    first = complex_types[0]
    if any(value != first for value in complex_types[1:]):
        return None
    if any(not (value.is_collection or value.is_structured) for value in types):
        return None
    return first.with_nullable(True)


def _common_case_kind(expressions: Sequence[Any], source: str, position: int) -> str | None:
    """Return the compatible CASE result kind, ignoring NULL-only branches."""
    kinds = [kind for expression in expressions if (kind := _scalar_kind(expression)) is not None]
    if not kinds:
        return None
    unique = set(kinds)
    if len(unique) == 1:
        return kinds[0]
    if all(_is_numeric_kind(kind) for kind in kinds):
        return "number"
    if "mixed" in unique or "unknown" in unique:
        return "mixed"
    raise QuerySemanticError(
        source,
        "CASE result expressions must have compatible types; got " + ", ".join(sorted(unique)) + ".",
        position,
    )


def _common_scalar_kind(expressions: Sequence[Any], source: str, position: int, function_name: str) -> str | None:
    """Return one compatible scalar kind for multi-argument scalar functions."""
    kinds = [kind for expression in expressions if (kind := _scalar_kind(expression)) is not None]
    if not kinds:
        return None
    unique = set(kinds)
    if len(unique) == 1:
        return kinds[0]
    if all(_is_numeric_kind(kind) for kind in kinds):
        return "number"
    if "mixed" in unique or "unknown" in unique:
        return "mixed"
    raise QuerySemanticError(
        source,
        f"{function_name} arguments must have compatible types; got " + ", ".join(sorted(unique)) + ".",
        position,
    )


def _is_numeric_kind(kind: str | None) -> bool:
    return kind in {"integer", "number", "count", "duration"}


def _resolve_scalar_expression(
    expression: Any,
    schema: QuerySchema,
    source: str,
    dates: DateContext,
    aliases: dict[str, "SelectTerm"] | None = None,
    *,
    select_context: bool = False,
    allow_structured: bool = False,
    collection_scopes: tuple[QueryType, ...] = (),
) -> Any:
    """Resolve fields, aliases and types for a scalar expression."""
    if isinstance(expression, RelationField):
        # JOIN scope resolution has already established relation ownership and the
        # field kind. Preserve that binding while the ordinary scalar resolver
        # resolves surrounding literals, operators and functions.
        return expression
    if isinstance(expression, CollectionElementReference):
        index = len(collection_scopes) - 1 - expression.scope_distance
        if index < 0 or index >= len(collection_scopes):
            raise QuerySemanticError(
                source,
                f"Collection binding {expression.binding!r} is outside its lexical scope.",
                expression.position,
            )
        result_type = collection_scopes[index]
        return CollectionElementReference(
            expression.binding,
            expression.scope_distance,
            expression.position,
            result_type.kind,
            result_type,
        )
    if isinstance(expression, Field):
        if aliases is not None:
            alias = aliases.get(expression.name.casefold())
            if alias is not None:
                return (
                    alias.expression
                    if alias.expression is not None
                    else Field(alias.field, expression.position, alias.kind)
                )
        field = _resolve_field(expression, schema, source)
        if field.kind == "structured" and not allow_structured:
            if select_context:
                message = f"Cannot SELECT structured field {field.name!r}; select a scalar nested path instead."
            else:
                message = f"Field {field.name!r} is structured; use a scalar nested path instead."
            raise QuerySemanticError(source, message, field.position)
        return field
    if isinstance(expression, Literal):
        if expression.value is None:
            return expression
        if isinstance(expression.value, bool):
            return replace(expression, value=bool(expression.value))
        if isinstance(expression.value, (int, float)):
            return expression
        return replace(expression, value=_generic_literal(str(expression.value), expression.quoted))
    if isinstance(expression, ScalarUnary):
        operand = _resolve_scalar_expression(
            expression.operand,
            schema,
            source,
            dates,
            aliases,
            select_context=select_context,
            collection_scopes=collection_scopes,
        )
        kind = _scalar_kind(operand)
        if not _is_numeric_kind(kind) and not isinstance(operand, Literal):
            raise QuerySemanticError(
                source, f"Unary {expression.operator} requires a numeric value.", expression.position
            )
        if isinstance(operand, Literal) and operand.value is not None and not isinstance(operand.value, (int, float)):
            raise QuerySemanticError(
                source, f"Unary {expression.operator} requires a numeric value.", expression.position
            )
        return ScalarUnary(expression.operator, operand, expression.position, kind or "number")
    if isinstance(expression, ScalarBinary):
        left = _resolve_scalar_expression(
            expression.left,
            schema,
            source,
            dates,
            aliases,
            select_context=select_context,
            collection_scopes=collection_scopes,
        )
        right = _resolve_scalar_expression(
            expression.right,
            schema,
            source,
            dates,
            aliases,
            select_context=select_context,
            collection_scopes=collection_scopes,
        )
        for operand in (left, right):
            kind = _scalar_kind(operand)
            if kind is not None and not _is_numeric_kind(kind):
                raise QuerySemanticError(
                    source, f"Arithmetic operator {expression.operator!r} requires numeric values.", expression.position
                )
            if (
                isinstance(operand, Literal)
                and operand.value is not None
                and not isinstance(operand.value, (int, float))
            ):
                raise QuerySemanticError(
                    source, f"Arithmetic operator {expression.operator!r} requires numeric values.", expression.position
                )
        return ScalarBinary(expression.operator, left, right, expression.position, "number")
    if isinstance(expression, ScalarCase):
        resolved_whens: list[CaseWhen] = []
        results: list[Any] = []
        for branch in expression.whens:
            condition = _resolve_predicate(branch.condition, schema, source, dates, collection_scopes=collection_scopes)
            result = _resolve_scalar_expression(
                branch.result,
                schema,
                source,
                dates,
                aliases,
                select_context=select_context,
                collection_scopes=collection_scopes,
            )
            resolved_whens.append(CaseWhen(condition, result, branch.position))
            results.append(result)
        else_result = None
        if expression.else_result is not None:
            else_result = _resolve_scalar_expression(
                expression.else_result,
                schema,
                source,
                dates,
                aliases,
                select_context=select_context,
                collection_scopes=collection_scopes,
            )
            results.append(else_result)
        kind = _common_case_kind(results, source, expression.position)
        return ScalarCase(tuple(resolved_whens), else_result, expression.position, kind)
    if isinstance(expression, ScalarMember):
        value = _resolve_scalar_expression(
            expression.value,
            schema,
            source,
            dates,
            aliases,
            select_context=select_context,
            allow_structured=True,
            collection_scopes=collection_scopes,
        )
        value_type = _scalar_query_type(value, schema)
        if value_type is None or not value_type.is_structured:
            kind = _scalar_kind(value) or "unknown"
            raise QuerySemanticError(
                source,
                f"Structured member access requires a structured value; got {kind}.",
                expression.position,
            )
        if not value_type.has_declared_members:
            raise QuerySemanticError(
                source,
                "Structured member access requires a declared member schema; got opaque structured value.",
                expression.position,
            )
        result_type = value_type.member_result_type(expression.member)
        if result_type is None:
            raise QuerySemanticError(
                source,
                f"Structured value has no member {expression.member!r}.",
                expression.position,
            )
        return ScalarMember(value, expression.member, expression.position, result_type.kind, result_type)
    if isinstance(expression, ScalarIndex):
        if isinstance(expression.collection, Field) and not (
            aliases is not None and expression.collection.name.casefold() in aliases
        ):
            # Resolve a direct field without applying the standalone structured-value
            # selection restriction first. Indexing owns the diagnostic for whether
            # that field is a valid collection operand.
            index_field = schema.resolve_index_operand(expression.collection.name)
            if index_field is None:
                collection = _resolve_field(expression.collection, schema, source)
            else:
                collection = Field(
                    index_field.name,
                    expression.collection.position,
                    index_field.kind,
                )
        else:
            collection = _resolve_scalar_expression(
                expression.collection,
                schema,
                source,
                dates,
                aliases,
                select_context=select_context,
                collection_scopes=collection_scopes,
            )
        index = _resolve_scalar_expression(
            expression.index,
            schema,
            source,
            dates,
            aliases,
            select_context=select_context,
            collection_scopes=collection_scopes,
        )
        collection_type = _scalar_query_type(collection, schema)
        if collection_type is None or not collection_type.is_collection:
            kind = _scalar_kind(collection) or "unknown"
            raise QuerySemanticError(
                source,
                f"Collection indexing requires a collection value; got {kind}.",
                expression.position,
            )
        if not collection_type.supports_positional_indexing:
            raise QuerySemanticError(
                source,
                "Collection indexing requires a stable logical collection ordering.",
                expression.position,
            )

        index_kind = _scalar_kind(index)
        if _is_constant_scalar_expression(index):
            index_value = evaluate_scalar_expression(index, {})
            if index_value is not None:
                if isinstance(index_value, bool) or not isinstance(index_value, int):
                    raise QuerySemanticError(source, "Collection index must be an integer value.", expression.position)
                if index_value < 0:
                    raise QuerySemanticError(source, "Collection index must not be negative.", expression.position)
        elif index_kind not in {"integer", "count", None}:
            raise QuerySemanticError(source, "Collection index must be an integer value.", expression.position)

        result_type = collection_type.indexed_result_type()
        return ScalarIndex(collection, index, expression.position, result_type.kind, result_type)
    if isinstance(expression, CollectionCount):
        collection = _resolve_scalar_expression(
            expression.collection,
            schema,
            source,
            dates,
            aliases,
            select_context=select_context,
            allow_structured=True,
            collection_scopes=collection_scopes,
        )
        collection_type = _scalar_query_type(collection, schema)
        if collection_type is None or not collection_type.is_collection:
            kind = _scalar_kind(collection) or "unknown"
            raise QuerySemanticError(
                source,
                f"Collection COUNT requires a collection value; got {kind}.",
                expression.position,
            )
        assert collection_type.element_type is not None
        predicate = _resolve_predicate(
            expression.predicate,
            schema,
            source,
            dates,
            collection_scopes=collection_scopes + (collection_type.element_type,),
        )
        result_type = QueryType.scalar("integer", nullable=collection_type.nullable)
        return CollectionCount(
            collection,
            expression.binding,
            predicate,
            expression.position,
            "integer",
            result_type,
        )
    if isinstance(expression, CollectionFilter):
        collection = _resolve_scalar_expression(
            expression.collection,
            schema,
            source,
            dates,
            aliases,
            select_context=select_context,
            allow_structured=True,
            collection_scopes=collection_scopes,
        )
        collection_type = _scalar_query_type(collection, schema)
        if collection_type is None or not collection_type.is_collection:
            kind = _scalar_kind(collection) or "unknown"
            raise QuerySemanticError(
                source,
                f"FILTER requires a collection value; got {kind}.",
                expression.position,
            )
        assert collection_type.element_type is not None
        predicate = _resolve_predicate(
            expression.predicate,
            schema,
            source,
            dates,
            collection_scopes=collection_scopes + (collection_type.element_type,),
        )
        return CollectionFilter(
            collection,
            expression.binding,
            predicate,
            expression.position,
            "collection",
            collection_type,
        )
    if isinstance(expression, CollectionProjection):
        collection = _resolve_scalar_expression(
            expression.collection,
            schema,
            source,
            dates,
            aliases,
            select_context=select_context,
            allow_structured=True,
            collection_scopes=collection_scopes,
        )
        collection_type = _scalar_query_type(collection, schema)
        if collection_type is None or not collection_type.is_collection:
            kind = _scalar_kind(collection) or "unknown"
            raise QuerySemanticError(
                source,
                f"MAP requires a collection value; got {kind}.",
                expression.position,
            )
        assert collection_type.element_type is not None
        projection = _resolve_scalar_expression(
            expression.projection,
            schema,
            source,
            dates,
            aliases,
            allow_structured=True,
            collection_scopes=collection_scopes + (collection_type.element_type,),
        )
        if _contains_aggregate(projection):
            raise QuerySemanticError(
                source,
                "MAP projection cannot contain aggregate functions.",
                expression.position,
            )
        projection_type = _scalar_query_type(projection, schema)
        if projection_type is None:
            kind = _scalar_kind(projection) or "unknown"
            projection_type = QueryType.scalar(kind, nullable=True)
        result_type = QueryType.collection(
            projection_type,
            nullable=collection_type.nullable,
            ordering=collection_type.ordering,
        )
        evaluation_fusion_safe = (
            isinstance(collection, CollectionFilter)
            and not _contains_random(collection.predicate)
            and not _contains_random(projection)
        )
        return CollectionProjection(
            collection,
            expression.binding,
            projection,
            expression.position,
            "collection",
            result_type,
            evaluation_fusion_safe,
        )
    if isinstance(expression, AggregateFunction):
        args = tuple(
            _resolve_scalar_expression(
                arg,
                schema,
                source,
                dates,
                aliases,
                select_context=select_context,
                collection_scopes=collection_scopes,
            )
            for arg in expression.args
        )
        if any(_contains_aggregate(arg) for arg in args):
            raise QuerySemanticError(source, "Aggregate functions cannot be nested.", expression.position)
        filter_predicate = _resolve_predicate(expression.filter_predicate, schema, source, dates)
        if expression.name == "COUNT":
            result_kind = "integer"
        elif expression.name == "AVG":
            arg_kind = _scalar_kind(args[0])
            if arg_kind is not None and not _is_numeric_kind(arg_kind):
                raise QuerySemanticError(source, "AVG requires a numeric value.", expression.position)
            result_kind = "number"
        elif expression.name == "SUM":
            arg_kind = _scalar_kind(args[0])
            if arg_kind is not None and not _is_numeric_kind(arg_kind):
                raise QuerySemanticError(source, "SUM requires a numeric value.", expression.position)
            result_kind = "number" if arg_kind == "number" else arg_kind or "number"
        else:
            result_kind = _scalar_kind(args[0])
        return AggregateFunction(
            expression.name, args, expression.count_star, filter_predicate, expression.position, result_kind
        )
    if isinstance(expression, ScalarFunction):
        preserve_structured = allow_structured and expression.name in {"COALESCE", "NULLIF"}
        args = tuple(
            _resolve_scalar_expression(
                arg,
                schema,
                source,
                dates,
                aliases,
                select_context=select_context,
                allow_structured=preserve_structured,
                collection_scopes=collection_scopes,
            )
            for arg in expression.args
        )
        if expression.name in {"LOWER", "UPPER"}:
            kind = _scalar_kind(args[0])
            if kind not in {"string", "mixed", "unknown", None}:
                raise QuerySemanticError(source, f"{expression.name} requires a text field.", expression.position)
            result_kind = "string"
        elif expression.name == "LENGTH":
            kind = _scalar_kind(args[0])
            if kind not in {"string", "mixed", "unknown", None}:
                raise QuerySemanticError(source, "LENGTH requires a text value.", expression.position)
            result_kind = "integer"
        elif expression.name == "CARDINALITY":
            collection_type = _scalar_query_type(args[0], schema)
            if collection_type is None or not collection_type.is_collection:
                kind = _scalar_kind(args[0]) or "unknown"
                raise QuerySemanticError(
                    source,
                    f"CARDINALITY requires a collection value; got {kind}.",
                    expression.position,
                )
            result_kind = "integer"
        elif expression.name == "CONCAT":
            for arg in args:
                kind = _scalar_kind(arg)
                if kind not in {"string", "mixed", "unknown", None}:
                    raise QuerySemanticError(source, "CONCAT requires text values.", expression.position)
            result_kind = "string"
        elif expression.name == "CHAR":
            for arg in args:
                kind = _scalar_kind(arg)
                if kind is not None and not _is_numeric_kind(kind):
                    raise QuerySemanticError(source, "CHAR requires integer code-point values.", expression.position)
                if _is_constant_scalar_expression(arg):
                    value = evaluate_scalar_expression(arg, {})
                    if value is not None:
                        _validate_char_codepoint(value, source, expression.position)
            result_kind = "string"
        elif expression.name == "NULLIF":
            result_kind = _common_scalar_kind(args, source, expression.position, "NULLIF")
            first_kind = _scalar_kind(args[0])
            if first_kind is not None:
                result_kind = first_kind
        elif expression.name in {"GREATEST", "LEAST"}:
            result_kind = _common_scalar_kind(args, source, expression.position, expression.name)
        elif expression.name == "COALESCE":
            result_kind = _common_scalar_kind(args, source, expression.position, "COALESCE")
        elif expression.name == "RANDOM":
            if args:
                seed = args[0]
                if not isinstance(seed, Literal) or isinstance(seed.value, bool) or not isinstance(seed.value, int):
                    raise QuerySemanticError(
                        source, "RANDOM seed must be a constant integer literal.", expression.position
                    )
            result_kind = "number"
        else:
            non_null_kinds = [kind for arg in args if (kind := _scalar_kind(arg)) is not None]
            result_kind = (
                non_null_kinds[0] if non_null_kinds and all(k == non_null_kinds[0] for k in non_null_kinds) else "mixed"
            )
        result_type = None
        if expression.name in {"COALESCE", "NULLIF"}:
            result_type = _value_preserving_function_type(args, schema)
        elif expression.name == "CARDINALITY":
            collection_type = _scalar_query_type(args[0], schema)
            assert collection_type is not None and collection_type.is_collection
            result_type = QueryType.scalar("integer", nullable=collection_type.nullable)
        if result_type is None and result_kind is not None and result_kind != "collection":
            result_type = QueryType.scalar(result_kind, nullable=True)
        return ScalarFunction(expression.name, args, expression.position, result_kind, result_type)
    raise AssertionError(f"Unsupported scalar expression {expression!r}")


def _is_constant_scalar_expression(expression: Any) -> bool:
    """Return whether an expression can be evaluated without row metadata."""
    if isinstance(expression, Literal):
        return True
    if isinstance(expression, ScalarUnary):
        return _is_constant_scalar_expression(expression.operand)
    if isinstance(expression, ScalarBinary):
        return _is_constant_scalar_expression(expression.left) and _is_constant_scalar_expression(expression.right)
    if isinstance(expression, ScalarFunction):
        return all(_is_constant_scalar_expression(arg) for arg in expression.args)
    if isinstance(expression, ScalarIndex):
        return _is_constant_scalar_expression(expression.collection) and _is_constant_scalar_expression(
            expression.index
        )
    return False


def _fields_outside_aggregates(expression: Any) -> set[str]:
    """Return field names evaluated once per group rather than inside an aggregate."""
    if expression is None or isinstance(expression, (Literal, AggregateFunction)):
        return set()
    if isinstance(expression, Field):
        return {expression.name.casefold()}
    if isinstance(expression, ScalarUnary):
        return _fields_outside_aggregates(expression.operand)
    if isinstance(expression, ScalarBinary):
        return _fields_outside_aggregates(expression.left) | _fields_outside_aggregates(expression.right)
    if isinstance(expression, ScalarIndex):
        return _fields_outside_aggregates(expression.collection) | _fields_outside_aggregates(expression.index)
    if isinstance(expression, (CollectionCount, CollectionFilter)):
        return _fields_outside_aggregates(expression.collection) | _fields_in_predicate(expression.predicate)
    if isinstance(expression, CollectionProjection):
        return _fields_outside_aggregates(expression.collection) | _fields_outside_aggregates(expression.projection)
    if isinstance(expression, ScalarFunction):
        fields: set[str] = set()
        for arg in expression.args:
            fields.update(_fields_outside_aggregates(arg))
        return fields
    if isinstance(expression, ScalarCase):
        fields: set[str] = set()
        for branch in expression.whens:
            fields.update(_fields_in_predicate(branch.condition))
            fields.update(_fields_outside_aggregates(branch.result))
        fields.update(_fields_outside_aggregates(expression.else_result))
        return fields
    return set()


def _fields_in_predicate(node: Any) -> set[str]:
    if node is None:
        return set()
    if isinstance(node, Unary):
        return _fields_in_predicate(node.operand)
    if isinstance(node, Binary) and node.operator in {"AND", "OR"}:
        return _fields_in_predicate(node.left) | _fields_in_predicate(node.right)
    if isinstance(node, ScalarComparison):
        return _fields_outside_aggregates(node.left) | _fields_outside_aggregates(node.right)
    if isinstance(node, ScalarIsNull):
        return _fields_outside_aggregates(node.expression)
    if isinstance(node, CollectionPredicate):
        return _fields_outside_aggregates(node.collection) | _fields_in_predicate(node.predicate)
    field = getattr(node, "field", None)
    if isinstance(field, Field):
        return {field.name.casefold()}
    if isinstance(node, Binary) and isinstance(node.left, Field):
        return {node.left.name.casefold()}
    return set()


def _validate_char_codepoint(value: Any, source: str, position: int) -> int:
    """Validate a constant CHAR argument and raise a query diagnostic on failure."""
    try:
        return _coerce_char_codepoint(value)
    except TypeError as exc:
        raise QuerySemanticError(source, "CHAR requires integer code-point values.", position) from exc
    except ValueError as exc:
        if isinstance(value, (int, float)) and not isinstance(value, bool) and float(value).is_integer():
            raise QuerySemanticError(
                source,
                "CHAR code points must be Unicode scalar values from 0 to 1114111, excluding surrogates.",
                position,
            ) from exc
        raise QuerySemanticError(source, "CHAR requires integer code-point values.", position) from exc


def _resolve_predicate(
    node: Any,
    schema: QuerySchema,
    source: str,
    context: DateContext,
    *,
    collection_scopes: tuple[QueryType, ...] = (),
) -> Any:
    """Resolve one Boolean predicate tree against the established query schema."""
    if node is None:
        return None
    if isinstance(node, Unary):
        return Unary(
            node.operator,
            _resolve_predicate(node.operand, schema, source, context, collection_scopes=collection_scopes),
        )
    if isinstance(node, Binary) and node.operator in {"AND", "OR"}:
        return Binary(
            node.operator,
            _resolve_predicate(node.left, schema, source, context, collection_scopes=collection_scopes),
            _resolve_predicate(node.right, schema, source, context, collection_scopes=collection_scopes),
        )
    if isinstance(node, CollectionPredicate):
        collection = _resolve_scalar_expression(
            node.collection, schema, source, context, allow_structured=True, collection_scopes=collection_scopes
        )
        collection_type = _scalar_query_type(collection, schema)
        if collection_type is None or not collection_type.is_collection:
            kind = _scalar_kind(collection) or "unknown"
            raise QuerySemanticError(
                source,
                f"{node.quantifier} requires a collection value; got {kind}.",
                node.position,
            )
        assert collection_type.element_type is not None
        predicate = _resolve_predicate(
            node.predicate,
            schema,
            source,
            context,
            collection_scopes=collection_scopes + (collection_type.element_type,),
        )
        return CollectionPredicate(node.quantifier, collection, node.binding, predicate, node.position)
    if isinstance(node, ScalarComparison):
        left = _resolve_scalar_expression(node.left, schema, source, context, collection_scopes=collection_scopes)
        right = _resolve_scalar_expression(node.right, schema, source, context, collection_scopes=collection_scopes)
        left_kind = _scalar_kind(left)
        right_kind = _scalar_kind(right)
        if (
            left_kind is not None
            and right_kind is not None
            and left_kind != right_kind
            and not (_is_numeric_kind(left_kind) and _is_numeric_kind(right_kind))
            and "mixed" not in {left_kind, right_kind}
        ):
            raise QuerySemanticError(
                source,
                "WHERE comparison expressions must have compatible types.",
                _diagnostic_position(node),
            )
        return ScalarComparison(node.operator, left, right)
    if isinstance(node, ScalarIsNull):
        return ScalarIsNull(
            _resolve_scalar_expression(node.expression, schema, source, context, collection_scopes=collection_scopes),
            node.negated,
        )
    if isinstance(node, Binary):
        field = _resolve_field(node.left, schema, source)
        if field.kind == "structured":
            raise QuerySemanticError(
                source, f"Field {field.name!r} is structured; use a scalar nested path instead.", field.position
            )
        literal = _resolve_literal(node.right, field, source, context)
        if literal.value is None:
            raise QuerySemanticError(source, "Use IS NULL or IS NOT NULL for NULL tests.", literal.position)
        return Binary(node.operator, field, literal)
    if isinstance(node, Between):
        field = _resolve_field(node.field, schema, source)
        if field.kind == "structured":
            raise QuerySemanticError(
                source, f"Field {field.name!r} is structured; use a scalar nested path instead.", field.position
            )
        return Between(
            field,
            _resolve_literal(node.lower, field, source, context),
            _resolve_literal(node.upper, field, source, context),
            node.negated,
        )
    if isinstance(node, InList):
        field = _resolve_field(node.field, schema, source)
        if field.kind == "structured":
            raise QuerySemanticError(
                source, f"Field {field.name!r} is structured; use a scalar nested path instead.", field.position
            )
        return InList(
            field,
            tuple(_resolve_literal(item, field, source, context) for item in node.values),
            node.negated,
        )
    if isinstance(node, IsNull):
        return IsNull(_resolve_field(node.field, schema, source), node.negated)
    if isinstance(node, TextPredicate):
        field = _resolve_field(node.field, schema, source)
        if field.kind == "structured":
            raise QuerySemanticError(
                source, f"Field {field.name!r} is structured; use a scalar nested path instead.", field.position
            )
        if field.kind not in {"string", "mixed", "unknown"}:
            raise QuerySemanticError(
                source, f"{node.operator} requires a text field, not {field.kind}.", field.position
            )
        if node.operator in {"LIKE", "ILIKE"}:
            _validate_like_pattern(str(node.value.value), source, node.value.position)
            # Populate the pattern cache during resolution so row evaluation does not
            # pay the translation/compilation cost for a literal query pattern.
            _compile_like_pattern(str(node.value.value), node.operator == "ILIKE")
        return TextPredicate(node.operator, field, node.value, node.negated)
    raise AssertionError(f"Unsupported query node {node!r}")


def _resolve_having(
    node: Any,
    schema: QuerySchema,
    source: str,
    dates: DateContext,
    aliases: dict[str, SelectTerm],
) -> Any:
    if node is None:
        return None
    if isinstance(node, Unary):
        return Unary(node.operator, _resolve_having(node.operand, schema, source, dates, aliases))
    if isinstance(node, Binary) and node.operator in {"AND", "OR"}:
        return Binary(
            node.operator,
            _resolve_having(node.left, schema, source, dates, aliases),
            _resolve_having(node.right, schema, source, dates, aliases),
        )
    if isinstance(node, ScalarComparison):
        left = _resolve_scalar_expression(node.left, schema, source, dates, aliases)
        right = _resolve_scalar_expression(node.right, schema, source, dates, aliases)
        left_kind = _scalar_kind(left)
        right_kind = _scalar_kind(right)
        if (
            left_kind is not None
            and right_kind is not None
            and left_kind != right_kind
            and not (_is_numeric_kind(left_kind) and _is_numeric_kind(right_kind))
            and "mixed" not in {left_kind, right_kind}
        ):
            raise QuerySemanticError(
                source,
                "HAVING comparison expressions must have compatible types.",
                _diagnostic_position(node),
            )
        return ScalarComparison(node.operator, left, right)
    if isinstance(node, ScalarIsNull):
        return ScalarIsNull(_resolve_scalar_expression(node.expression, schema, source, dates, aliases), node.negated)
    raise AssertionError(f"Unsupported HAVING node {node!r}")


def _validate_group_compatibility(expression: Any, group_by: tuple[Any, ...], source: str, position: int) -> None:
    """Reject ambiguous row-level expressions in aggregate projection contexts."""
    if expression is None or not _fields_outside_aggregates(expression):
        return
    canonical_groups = {format_scalar_expression(item) for item in group_by}
    if not _contains_aggregate(expression) and format_scalar_expression(expression) in canonical_groups:
        return
    raise QuerySemanticError(
        source,
        "Non-aggregate SELECT/ORDER BY expressions in an aggregate query must match a GROUP BY expression.",
        position,
    )


def _validate_having_group_compatibility(node: Any, group_by: tuple[Any, ...], source: str) -> None:
    if node is None:
        return
    if isinstance(node, Unary):
        _validate_having_group_compatibility(node.operand, group_by, source)
        return
    if isinstance(node, Binary) and node.operator in {"AND", "OR"}:
        _validate_having_group_compatibility(node.left, group_by, source)
        _validate_having_group_compatibility(node.right, group_by, source)
        return
    expressions = []
    if isinstance(node, ScalarComparison):
        expressions = [node.left, node.right]
    elif isinstance(node, ScalarIsNull):
        expressions = [node.expression]
    canonical_groups = {format_scalar_expression(item) for item in group_by}
    for expression in expressions:
        if not _fields_outside_aggregates(expression):
            continue
        if not _contains_aggregate(expression) and format_scalar_expression(expression) in canonical_groups:
            continue
        raise QuerySemanticError(
            source,
            "Non-aggregate HAVING expressions must match a GROUP BY expression or selected aggregate alias.",
            getattr(expression, "position", 0),
        )


def _validate_random_placement(query: Query) -> None:
    """Keep volatile randomness out of row-selection and grouping semantics."""
    if _contains_random(query.predicate):
        raise QuerySemanticError(
            query.source, "RANDOM is not allowed in WHERE predicates.", _random_position(query.predicate)
        )
    if any(_contains_random(expression) for expression in query.group_by):
        raise QuerySemanticError(
            query.source,
            "RANDOM is not allowed in GROUP BY expressions.",
            min(_random_position(expression) for expression in query.group_by if _contains_random(expression)),
        )
    if _contains_random(query.having):
        raise QuerySemanticError(
            query.source, "RANDOM is not allowed in HAVING predicates.", _random_position(query.having)
        )
    for term in query.select:
        expression = term.expression
        if isinstance(expression, AggregateFunction) and _contains_random(expression.filter_predicate):
            raise QuerySemanticError(
                query.source, "RANDOM is not allowed in aggregate FILTER predicates.", expression.position
            )


def _resolve_query_body(query: Query, schema: QuerySchema, dates: DateContext | None = None) -> Query:
    """Resolve fields and typed literals after metadata has established a schema."""
    context = dates or DateContext()
    source = query.source
    _validate_random_placement(query)

    predicate = _resolve_predicate(query.predicate, schema, source, context)
    group_by = tuple(_resolve_scalar_expression(item, schema, source, context) for item in query.group_by)
    for item in group_by:
        if _contains_aggregate(item):
            raise QuerySemanticError(
                source, "GROUP BY expressions cannot contain aggregate functions.", getattr(item, "position", 0)
            )

    select_terms: list[SelectTerm] = []
    effective_select = query.select or (SelectTerm("id"),)
    if (
        len(effective_select) == 1
        and effective_select[0].field == "*"
        and effective_select[0].expression is None
        and (query.group_by or query.having is not None)
    ):
        raise QuerySemanticError(
            source,
            "SELECT * is not supported in aggregate queries; select grouped and aggregate expressions explicitly.",
            effective_select[0].position,
        )
    if len(effective_select) == 1 and effective_select[0].field == "*" and effective_select[0].expression is None:
        effective_select = tuple(
            SelectTerm(info.name, position=effective_select[0].position) for info in schema.select_star_fields()
        )
    output_names: set[str] = set()
    explicit_aliases: dict[str, SelectTerm] = {}
    for original_term in effective_select:
        if original_term.expression is not None:
            expression = _resolve_scalar_expression(
                original_term.expression, schema, source, context, select_context=True
            )
            field_text = format_scalar_expression(expression)
            kind = _scalar_kind(expression)
            if kind == "structured":
                raise QuerySemanticError(
                    source,
                    "Cannot SELECT structured expression; select a scalar nested path instead.",
                    original_term.position,
                )
            if isinstance(expression, Field):
                field_text = expression.name
        else:
            expression = None
            field = _resolve_field(Field(original_term.field, original_term.position), schema, source)
            if field.kind == "structured":
                raise QuerySemanticError(
                    source,
                    f"Cannot SELECT structured field {field.name!r}; select a scalar nested path instead.",
                    original_term.position,
                )
            field_text = field.name
            kind = field.kind
        output_name = original_term.alias or original_term.field
        key = output_name.casefold()
        if key in output_names:
            raise QuerySemanticError(
                source,
                f"Duplicate SELECT output name {output_name!r}; use AS to give fields unique names.",
                original_term.position,
            )
        output_names.add(key)
        resolved_term = SelectTerm(field_text, output_name, original_term.position, kind, expression)
        select_terms.append(resolved_term)
        if original_term.alias is not None:
            explicit_aliases[original_term.alias.casefold()] = resolved_term

    having = _resolve_having(query.having, schema, source, context, explicit_aliases)

    order_terms: list[OrderTerm] = []
    for term in query.order_by:
        if term.expression is not None:
            expression = _resolve_scalar_expression(term.expression, schema, source, context, explicit_aliases)
            field_text = format_scalar_expression(expression)
            kind = _scalar_kind(expression)
            if isinstance(expression, Field):
                field_text = expression.name
            order_terms.append(OrderTerm(field_text, term.descending, term.position, kind, expression))
            continue
        selected_alias = explicit_aliases.get(term.field.casefold())
        if selected_alias is not None:
            order_terms.append(
                OrderTerm(
                    selected_alias.field, term.descending, term.position, selected_alias.kind, selected_alias.expression
                )
            )
            continue
        field = _resolve_field(Field(term.field, term.position), schema, source)
        if field.kind == "structured":
            raise QuerySemanticError(source, f"Cannot ORDER BY structured field {field.name!r}.", term.position)
        order_terms.append(OrderTerm(field.name, term.descending, term.position, field.kind))

    resolved = Query(
        predicate,
        tuple(order_terms),
        query.limit,
        source,
        tuple(select_terms),
        query.from_source,
        query.distinct,
        query.offset,
        group_by,
        having,
        (),
        (),
        query.from_facet,
    )
    if _aggregate_query(resolved):
        for term in resolved.select:
            _validate_group_compatibility(term.expression, group_by, source, term.position)
        for term in resolved.order_by:
            _validate_group_compatibility(term.expression, group_by, source, term.position)
        _validate_having_group_compatibility(having, group_by, source)
    elif having is not None:
        raise QuerySemanticError(
            source,
            "HAVING requires GROUP BY or an aggregate expression.",
            _diagnostic_position(having),
        )
    return resolved


def _union_common_kind(left: str | None, right: str | None) -> str:
    """Return the logical kind exported by two positional UNION columns."""
    left_kind = left or "unknown"
    right_kind = right or "unknown"
    if left_kind == right_kind:
        return left_kind
    if left_kind == "unknown":
        return right_kind
    if right_kind == "unknown":
        return left_kind
    numeric = {"integer", "number", "count", "duration"}
    if left_kind in numeric and right_kind in numeric:
        if left_kind == right_kind:
            return left_kind
        return "number"
    raise ValueError(f"incompatible UNION kinds {left_kind!r} and {right_kind!r}")


def _query_result_schema(query: Query) -> QuerySchema:
    """Build the logical schema exported by a resolved query result."""
    fields = [FieldInfo(term.output_name, term.kind or "unknown", True, dynamic=True) for term in query.select]
    return QuerySchema.from_field_infos(fields)


def _resolve_union_order(
    order_by: tuple[OrderTerm, ...], schema: QuerySchema, source: str, context: DateContext
) -> tuple[OrderTerm, ...]:
    """Resolve global UNION ordering against the reconciled result relation."""
    terms: list[OrderTerm] = []
    for term in order_by:
        expression = _resolve_scalar_expression(term.expression, schema, source, context)
        field_text = format_scalar_expression(expression)
        kind = _scalar_kind(expression)
        if isinstance(expression, Field):
            field_text = expression.name
        terms.append(OrderTerm(field_text, term.descending, term.position, kind, expression))
    return tuple(terms)


def _resolve_composed_query(
    query: Query,
    physical_schema: QuerySchema,
    cte_schemas: dict[str, QuerySchema],
    context: DateContext,
    source_schemas: dict[tuple[str, str | None], QuerySchema],
) -> Query:
    """Resolve one query body and its positional set-composition branches."""

    def resolve_body(body: Query) -> Query:
        schema = relation_binding(
            body.from_source, body.from_facet, physical_schema, cte_schemas, source_schemas
        ).schema
        if body.joins:
            prepared = prepare_join_query(
                body,
                physical_schema,
                cte_schemas=cte_schemas,
                source_schemas=source_schemas,
            )
            resolved_body = _resolve_query_body(replace(prepared, joins=()), schema, context)
            return replace(resolved_body, from_alias=prepared.from_alias, joins=prepared.joins)
        return _resolve_query_body(body, schema, context)

    if not query.set_operations:
        return resolve_body(replace(query, ctes=(), set_operations=()))

    # ORDER BY/LIMIT/OFFSET belong to the complete set result, not the first branch.
    left_body = replace(query, ctes=(), set_operations=(), order_by=(), limit=None, offset=0)
    left = resolve_body(left_body)
    common_terms = list(left.select)
    resolved_ops: list[SetOperation] = []
    for operation in query.set_operations:
        branch = resolve_body(replace(operation.query, ctes=(), set_operations=(), order_by=(), limit=None, offset=0))
        if len(branch.select) != len(common_terms):
            raise QuerySemanticError(
                query.source,
                f"UNION branches must project the same number of columns; expected {len(common_terms)}, got {len(branch.select)}.",
                operation.position,
            )
        reconciled: list[SelectTerm] = []
        for index, (left_term, right_term) in enumerate(zip(common_terms, branch.select, strict=True), start=1):
            try:
                kind = _union_common_kind(left_term.kind, right_term.kind)
            except ValueError:
                raise QuerySemanticError(
                    query.source,
                    f"UNION column {index} has incompatible kinds {left_term.kind or 'unknown'} and {right_term.kind or 'unknown'}.",
                    operation.position,
                ) from None
            reconciled.append(replace(left_term, kind=kind))
        common_terms = reconciled
        resolved_ops.append(SetOperation(branch, operation.all, operation.position))

    left = replace(left, select=tuple(common_terms))
    result_schema = _query_result_schema(left)
    order_by = _resolve_union_order(query.order_by, result_schema, query.source, context)
    return replace(
        left,
        order_by=order_by,
        limit=query.limit,
        offset=query.offset,
        set_operations=tuple(resolved_ops),
    )


def resolve_query(
    query: Query,
    schema: QuerySchema,
    dates: DateContext | None = None,
    *,
    source_schemas: dict[tuple[str, str | None], QuerySchema] | None = None,
) -> Query:
    """Resolve CTEs and positional set composition against logical and per-source schemas."""
    physical_source_schemas = source_schemas or {}
    context = dates or DateContext()

    # Preserve the historical direct resolver path for the overwhelmingly common
    # uncomposed query shape. Relational preparation is semantically unnecessary
    # when there is no source relation, CTE, JOIN or set composition.
    if not query.ctes and not query.joins and not query.set_operations and query.from_source is None:
        return _resolve_query_body(query, schema, context)

    resolved_ctes: list[CommonTableExpression] = []
    cte_schemas: dict[str, QuerySchema] = {}
    cte_names = {cte.name.casefold() for cte in query.ctes}

    for cte in query.ctes:
        referenced = [name.casefold() for name in _direct_from_sources(cte.query)]
        if cte.name.casefold() in referenced:
            raise QuerySemanticError(
                query.source, f"Recursive reference to CTE {cte.name!r} is not supported.", cte.position
            )
        later = [name for name in referenced if name in cte_names and name not in cte_schemas]
        if later:
            raise QuerySemanticError(
                query.source,
                f"CTE {cte.name!r} cannot reference later CTE {later[0]!r}; forward references are not supported.",
                cte.position,
            )
        resolved_subquery = _resolve_composed_query(
            replace(cte.query, ctes=()), schema, cte_schemas, context, physical_source_schemas
        )
        resolved_ctes.append(CommonTableExpression(cte.name, resolved_subquery, cte.position))
        cte_schemas[cte.name.casefold()] = _query_result_schema(resolved_subquery)

    resolved = _resolve_composed_query(replace(query, ctes=()), schema, cte_schemas, context, physical_source_schemas)
    return replace(resolved, ctes=tuple(resolved_ctes))
