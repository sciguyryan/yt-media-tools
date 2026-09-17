"""Local execution of resolved yt-sql queries over metadata records."""

from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import replace
from datetime import date, datetime
from functools import lru_cache
from typing import Any, Sequence

from .collection_semantics import existential_truth, universal_truth
from .dates import DateContext, parse_date_literal, timestamp_to_datetime
from .query_evaluation_context import EvaluationContext
from .query_model import (
    AggregateFunction,
    Between,
    CollectionCount,
    CollectionFilter,
    CollectionProjection,
    CollectionElementReference,
    CollectionPredicate,
    Binary,
    Field,
    InList,
    IsNull,
    Literal,
    OrderTerm,
    Query,
    JoinKind,
    RelationField,
    ScalarBinary,
    ScalarCase,
    ScalarComparison,
    ScalarFunction,
    ScalarIndex,
    ScalarMember,
    ScalarIsNull,
    ScalarUnary,
    SelectTerm,
    TextPredicate,
    Unary,
)
from .query_semantics import (
    _aggregate_query,
    _contains_aggregate,
    _contains_random,
    query_physical_source_requests,
)
from .query_values import comparison_values as _comparison_values
from .query_values import hashable_group_value as _hashable_group_value
from .schema import raw_path_value


def _coerce_char_codepoint(value: Any) -> int:
    """Convert one runtime CHAR argument into a valid Unicode scalar value."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("CHAR requires integer code-point values")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError("CHAR requires integer code-point values")
    codepoint = int(value)
    if codepoint < 0 or codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
        raise ValueError("CHAR code point is outside the Unicode scalar-value range")
    return codepoint


def _stable_random_identity(record: dict[str, Any]) -> str:
    """Return a stable logical identity for deterministic seeded randomness."""
    preferred = []
    for key in ("_yt_sql_source", "_yt_sql_source_facet", "extractor", "extractor_key", "webpage_url", "url", "id"):
        value = record.get(key)
        if value is not None:
            preferred.append((key, value))
    if preferred:
        return json.dumps(preferred, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    public = {key: value for key, value in record.items() if not key.startswith("_yt_sql_")}
    return json.dumps(public, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _evaluate_random(function: ScalarFunction, record: dict[str, Any]) -> float:
    """Evaluate volatile or reproducibly seeded row randomness."""
    if function.args:
        seed = function.args[0]
        assert isinstance(seed, Literal) and isinstance(seed.value, int) and not isinstance(seed.value, bool)
        payload = f"{seed.value}\0{_stable_random_identity(record)}".encode("utf-8")
        digest = hashlib.blake2b(payload, digest_size=8, person=b"yt-sql-rnd").digest()
        integer = int.from_bytes(digest, "big") >> 11
        return integer / float(1 << 53)

    cache = record.setdefault("_yt_sql_random_cache", {})
    key = function.position
    if key not in cache:
        cache[key] = random.SystemRandom().random()
    return float(cache[key])


def _runtime_indexed_value(collection: Any, index: Any) -> Any:
    """Return one zero-based sequence element using yt-sql NULL semantics.

    Resolved collection expressions guarantee the static operation is valid. Dynamic
    ``raw.*`` values still need a runtime guard because provider data may be absent or
    vary between records. Only ordered sequence containers are indexable: mappings,
    sets, strings and arbitrary iterables are never treated as collections merely
    because Python can iterate over them.
    """
    if collection is None or index is None:
        return None
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        return None
    if not isinstance(collection, (list, tuple)):
        return None
    return collection[index] if index < len(collection) else None


def _runtime_member_value(value: Any, member: str) -> Any:
    """Return one structured member using yt-sql NULL semantics.

    Semantic resolution has already proved that the expression has a structured type
    and that ``member`` belongs to its declared schema. Runtime metadata can still be
    absent, NULL or inconsistent, especially for provider-derived dynamic values. Keep
    that boundary conservative: only ordinary metadata dictionaries are structured
    values, and missing members evaluate to SQL NULL rather than falling through to
    Python attribute or arbitrary mapping behaviour.
    """
    if value is None or not isinstance(value, dict):
        return None
    if member not in value:
        return None
    return value[member]


def _evaluate_scalar_expression(expression: Any, context: EvaluationContext) -> Any:
    """Evaluate a scalar expression using an already-normalised runtime context."""
    record = context._record
    if isinstance(expression, CollectionElementReference):
        return context.collection_element(expression.scope_distance)
    if isinstance(expression, RelationField):
        relation_record = context.relation_record(expression.qualifier)
        if relation_record is None:
            return None
        return canonical_record_value(relation_record, expression.name, expression.kind)
    if isinstance(expression, Field):
        return canonical_record_value(record, expression)
    if isinstance(expression, Literal):
        return expression.value
    if isinstance(expression, ScalarUnary):
        value = _evaluate_scalar_expression(expression.operand, context)
        if value is None:
            return None
        try:
            return +value if expression.operator == "+" else -value
        except TypeError:
            return None
    if isinstance(expression, ScalarBinary):
        left = _evaluate_scalar_expression(expression.left, context)
        right = _evaluate_scalar_expression(expression.right, context)
        if left is None or right is None:
            return None
        try:
            if expression.operator == "+":
                return left + right
            if expression.operator == "-":
                return left - right
            if expression.operator == "*":
                return left * right
            if expression.operator == "/":
                return None if right == 0 else left / right
            if expression.operator == "%":
                return None if right == 0 else left % right
        except (TypeError, ValueError, OverflowError):
            return None
        raise AssertionError(f"Unsupported arithmetic operator {expression.operator}")
    if isinstance(expression, ScalarIndex):
        collection = _evaluate_scalar_expression(expression.collection, context)
        index = _evaluate_scalar_expression(expression.index, context)
        return _runtime_indexed_value(collection, index)
    if isinstance(expression, CollectionCount):
        collection = _evaluate_scalar_expression(expression.collection, context)
        if collection is None:
            return None
        if not isinstance(collection, (list, tuple)):
            return None
        count = 0
        for element in collection:
            if _evaluate_boolean_expression(expression.predicate, context.bind_collection_element(element)) is True:
                count += 1
        return count
    if isinstance(expression, CollectionFilter):
        collection = _evaluate_scalar_expression(expression.collection, context)
        if collection is None:
            return None
        if not isinstance(collection, (list, tuple)):
            return None
        return [
            element
            for element in collection
            if _evaluate_boolean_expression(expression.predicate, context.bind_collection_element(element)) is True
        ]
    if isinstance(expression, CollectionProjection):
        if expression.evaluation_fusion_safe:
            source_filter = expression.collection
            assert isinstance(source_filter, CollectionFilter)
            collection = _evaluate_scalar_expression(source_filter.collection, context)
            if collection is None:
                return None
            if not isinstance(collection, (list, tuple)):
                return None
            projected: list[Any] = []
            for element in collection:
                element_context = context.bind_collection_element(element)
                if _evaluate_boolean_expression(source_filter.predicate, element_context) is True:
                    projected.append(_evaluate_scalar_expression(expression.projection, element_context))
            return projected
        collection = _evaluate_scalar_expression(expression.collection, context)
        if collection is None:
            return None
        if not isinstance(collection, (list, tuple)):
            return None
        return [
            _evaluate_scalar_expression(expression.projection, context.bind_collection_element(element))
            for element in collection
        ]
    if isinstance(expression, ScalarMember):
        value = _evaluate_scalar_expression(expression.value, context)
        return _runtime_member_value(value, expression.member)
    if isinstance(expression, ScalarCase):
        for branch in expression.whens:
            if _evaluate_boolean_expression(branch.condition, context) is True:
                return _evaluate_scalar_expression(branch.result, context)
        if expression.else_result is not None:
            return _evaluate_scalar_expression(expression.else_result, context)
        return None
    if isinstance(expression, ScalarFunction):
        values = [_evaluate_scalar_expression(arg, context) for arg in expression.args]
        if expression.name == "LOWER":
            return values[0].lower() if isinstance(values[0], str) else None
        if expression.name == "UPPER":
            return values[0].upper() if isinstance(values[0], str) else None
        if expression.name == "LENGTH":
            return len(values[0]) if isinstance(values[0], str) else None
        if expression.name == "CARDINALITY":
            collection = values[0]
            if collection is None:
                return None
            return len(collection) if isinstance(collection, (list, tuple)) else None
        if expression.name == "COALESCE":
            return next((value for value in values if value is not None), None)
        if expression.name == "CONCAT":
            if any(value is None for value in values):
                return None
            return "".join(values) if all(isinstance(value, str) for value in values) else None
        if expression.name == "CHAR":
            if any(value is None for value in values):
                return None
            try:
                codepoints = [_coerce_char_codepoint(value) for value in values]
            except (TypeError, ValueError):
                return None
            return "".join(chr(codepoint) for codepoint in codepoints)
        if expression.name == "NULLIF":
            first, second = values
            if first is None:
                return None
            if second is None:
                return first
            try:
                return None if first == second else first
            except (TypeError, ValueError):
                return first
        if expression.name in {"GREATEST", "LEAST"}:
            if any(value is None for value in values):
                return None
            try:
                return max(values) if expression.name == "GREATEST" else min(values)
            except (TypeError, ValueError):
                return None
        if expression.name == "RANDOM":
            return _evaluate_random(expression, record)
        raise AssertionError(f"Unsupported scalar function {expression.name}")
    raise AssertionError(f"Unsupported scalar expression {expression!r}")


def evaluate_scalar_expression(
    expression: Any,
    record: dict[str, Any] | EvaluationContext,
    collection_bindings: tuple[Any, ...] = (),
) -> Any:
    """Evaluate a resolved scalar expression in an explicit runtime context.

    Compatibility coercion is intentionally confined to this public boundary. Internal
    recursion receives a normalised ``EvaluationContext`` directly, avoiding repeated
    type checks and context normalisation for every expression node.
    """
    context = (
        record
        if isinstance(record, EvaluationContext)
        else EvaluationContext(record=record, collection_bindings=collection_bindings)
    )
    return _evaluate_scalar_expression(expression, context)


def canonical_record_value(
    record: dict[str, Any], field: Field | RelationField | OrderTerm | SelectTerm | str, kind: str | None = None
) -> Any:
    if isinstance(field, RelationField):
        relation_record = EvaluationContext(record).relation_record(field.qualifier)
        if relation_record is None:
            return None
        return canonical_record_value(relation_record, field.name, field.kind)
    if isinstance(field, Field):
        name, field_kind = field.name, field.kind
    elif isinstance(field, OrderTerm):
        if field.expression is not None:
            return evaluate_scalar_expression(field.expression, record)
        name, field_kind = field.field, field.kind
    elif isinstance(field, SelectTerm):
        materialised_result = record.get("_yt_sql_aggregate_result") is True or record.get("_yt_sql_result_row") is True
        aggregate_projection = field.expression is not None and _contains_aggregate(field.expression)
        volatile_projection = field.expression is not None and _contains_random(field.expression)
        if field.output_name in record and (materialised_result or aggregate_projection or volatile_projection):
            return record.get(field.output_name)
        if field.expression is not None:
            return evaluate_scalar_expression(field.expression, record)
        name, field_kind = field.field, field.kind
    else:
        name, field_kind = field, kind

    if name.casefold().startswith("raw."):
        found, value = raw_path_value(record, name[4:])
        if not found:
            return None
    else:
        value = record.get(name)

    if value is None:
        return None
    if field_kind == "date":
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return parse_date_literal(value, DateContext(date_order="ymd"))
            except ValueError:
                return value
    if field_kind == "datetime":
        return timestamp_to_datetime(value)
    return value


def like_matches(value: str, pattern: str, *, case_insensitive: bool = False) -> bool:
    """Return whether one string satisfies an yt-sql LIKE pattern.

    Case-sensitive patterns containing no unescaped wildcard use direct string equality.
    This preserves yt-sql's exact Unicode/code-point semantics while avoiding regular-
    expression dispatch for the common literal-pattern case.
    """
    if not case_insensitive:
        exact, literal = _exact_like_literal(pattern)
        if exact:
            return value == literal
    return _compile_like_pattern(pattern, case_insensitive).fullmatch(value) is not None


@lru_cache(maxsize=512)
def _exact_like_literal(pattern: str) -> tuple[bool, str]:
    """Classify a LIKE pattern and decode it when it represents one exact string."""
    pieces: list[str] = []
    escaped = False
    for character in pattern:
        if escaped:
            pieces.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character in {"%", "_"}:
            return False, ""
        else:
            pieces.append(character)
    if escaped:
        return False, ""
    return True, "".join(pieces)


@lru_cache(maxsize=512)
def _compile_like_pattern(pattern: str, case_insensitive: bool) -> re.Pattern[str]:
    """Compile one yt-sql LIKE pattern to an anchored regular expression.

    ``%`` matches zero or more Unicode code points, including newlines, and
    ``_`` matches exactly one Unicode code point. Backslash quotes the next
    pattern character. The cache means a resolved literal pattern is compiled
    only once for repeated row evaluation.
    """
    pieces: list[str] = []
    escaped = False
    for character in pattern:
        if escaped:
            pieces.append(re.escape(character))
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == "%":
            pieces.append("[\\s\\S]*")
        elif character == "_":
            pieces.append("[\\s\\S]")
        else:
            pieces.append(re.escape(character))
    flags = re.IGNORECASE if case_insensitive else 0
    return re.compile("".join(pieces), flags)


def _evaluate_boolean_expression(node: Any, context: EvaluationContext) -> bool | None:
    """Evaluate a Boolean expression using an already-normalised runtime context."""
    record = context._record
    if node is None:
        return True
    if isinstance(node, Literal) and (node.value is None or isinstance(node.value, bool)):
        return node.value
    if isinstance(node, Unary):
        value = _evaluate_boolean_expression(node.operand, context)
        return None if value is None else not value
    if isinstance(node, Binary) and node.operator in {"AND", "OR"}:
        # Boolean evaluation is deliberately left-to-right. A dominating left
        # value makes the right operand unreachable; UNKNOWN does not. This is
        # part of yt-sql semantics rather than an optimiser convenience.
        left = _evaluate_boolean_expression(node.left, context)
        if node.operator == "AND":
            if left is False:
                return False
            right = _evaluate_boolean_expression(node.right, context)
            if right is False:
                return False
            if left is None or right is None:
                return None
            return True
        if left is True:
            return True
        right = _evaluate_boolean_expression(node.right, context)
        if right is True:
            return True
        if left is None or right is None:
            return None
        return False
    if isinstance(node, CollectionPredicate):
        collection = _evaluate_scalar_expression(node.collection, context)
        if collection is None:
            return (
                existential_truth((), collection_is_null=True)
                if node.quantifier == "ANY"
                else universal_truth((), collection_is_null=True)
            )
        if not isinstance(collection, (list, tuple)):
            return None
        results = (
            _evaluate_boolean_expression(node.predicate, context.bind_collection_element(element))
            for element in collection
        )
        if node.quantifier == "ANY":
            return existential_truth(results)
        if node.quantifier == "ALL":
            return universal_truth(results)
        raise AssertionError(f"Unsupported collection quantifier {node.quantifier}")
    if isinstance(node, ScalarIsNull):
        result = _evaluate_scalar_expression(node.expression, context) is None
        return not result if node.negated else result
    if isinstance(node, ScalarComparison):
        left = _evaluate_scalar_expression(node.left, context)
        right = _evaluate_scalar_expression(node.right, context)
        if left is None or right is None:
            return None
        try:
            if node.operator == "=":
                return left == right
            if node.operator == "!=":
                return left != right
            if node.operator == "<":
                return left < right
            if node.operator == "<=":
                return left <= right
            if node.operator == ">":
                return left > right
            if node.operator == ">=":
                return left >= right
        except TypeError:
            return False
        raise AssertionError(f"Unsupported operator {node.operator}")
    if isinstance(node, Binary):
        left = canonical_record_value(record, node.left)
        right = node.right.value
        if left is None or right is None:
            return None
        left, right = _comparison_values(node.left, left, right)
        try:
            if node.operator == "=":
                return left == right
            if node.operator == "!=":
                return left != right
            if node.operator == "<":
                return left < right
            if node.operator == "<=":
                return left <= right
            if node.operator == ">":
                return left > right
            if node.operator == ">=":
                return left >= right
        except TypeError:
            return False
        raise AssertionError(f"Unsupported operator {node.operator}")
    if isinstance(node, Between):
        value = canonical_record_value(record, node.field)
        if value is None:
            return None
        try:
            result = node.lower.value <= value <= node.upper.value
        except TypeError:
            result = False
        return not result if node.negated else result
    if isinstance(node, InList):
        value = canonical_record_value(record, node.field)
        if value is None:
            return None
        result = any(
            _comparison_values(node.field, value, item.value)[0] == _comparison_values(node.field, value, item.value)[1]
            for item in node.values
        )
        return not result if node.negated else result
    if isinstance(node, IsNull):
        result = canonical_record_value(record, node.field) is None
        return not result if node.negated else result
    if isinstance(node, TextPredicate):
        value = canonical_record_value(record, node.field)
        if value is None:
            return None
        if not isinstance(value, str):
            return False
        needle = str(node.value.value)
        if node.operator == "CONTAINS":
            result = needle.casefold() in value.casefold()
        elif node.operator == "MATCHES":
            result = re.search(needle, value) is not None
        elif node.operator in {"LIKE", "ILIKE"}:
            result = like_matches(value, needle, case_insensitive=node.operator == "ILIKE")
        else:
            raise AssertionError(f"Unsupported text operator {node.operator}")
        return not result if node.negated else result
    raise AssertionError(f"Unsupported query node {node!r}")


def _apply_scalar_function_values(name: str, values: list[Any]) -> Any:
    if name == "LOWER":
        return values[0].lower() if isinstance(values[0], str) else None
    if name == "UPPER":
        return values[0].upper() if isinstance(values[0], str) else None
    if name == "LENGTH":
        return len(values[0]) if isinstance(values[0], str) else None
    if name == "COALESCE":
        return next((value for value in values if value is not None), None)
    if name == "CONCAT":
        if any(value is None for value in values):
            return None
        return "".join(values) if all(isinstance(value, str) for value in values) else None
    if name == "CHAR":
        if any(value is None for value in values):
            return None
        try:
            return "".join(chr(_coerce_char_codepoint(value)) for value in values)
        except (TypeError, ValueError):
            return None
    if name == "NULLIF":
        first, second = values
        if first is None:
            return None
        if second is None:
            return first
        return None if first == second else first
    if name in {"GREATEST", "LEAST"}:
        if any(value is None for value in values):
            return None
        try:
            return max(values) if name == "GREATEST" else min(values)
        except (TypeError, ValueError):
            return None
    raise AssertionError(f"Unsupported scalar function {name}")


def _evaluate_group_expression(expression: Any, group: Sequence[dict[str, Any]]) -> Any:
    """Evaluate one resolved SELECT/HAVING/ORDER expression over an aggregate group."""
    if isinstance(expression, AggregateFunction):
        rows = list(group)
        if expression.filter_predicate is not None:
            rows = [row for row in rows if evaluate(expression.filter_predicate, row) is True]
        if expression.count_star:
            return len(rows)
        values = [evaluate_scalar_expression(expression.args[0], row) for row in rows]
        non_null = [value for value in values if value is not None]
        if expression.name == "COUNT":
            return len(non_null)
        if not non_null:
            return None
        if expression.name == "SUM":
            try:
                return sum(non_null)
            except TypeError:
                return None
        if expression.name == "AVG":
            try:
                return sum(non_null) / len(non_null)
            except TypeError:
                return None
        if expression.name == "MIN":
            try:
                return min(non_null)
            except TypeError:
                return None
        if expression.name == "MAX":
            try:
                return max(non_null)
            except TypeError:
                return None
        raise AssertionError(f"Unsupported aggregate function {expression.name}")
    representative = group[0] if group else {}
    if isinstance(expression, (Field, RelationField, Literal)):
        return evaluate_scalar_expression(expression, representative)
    if isinstance(expression, ScalarUnary):
        value = _evaluate_group_expression(expression.operand, group)
        if value is None:
            return None
        try:
            return +value if expression.operator == "+" else -value
        except TypeError:
            return None
    if isinstance(expression, ScalarBinary):
        left = _evaluate_group_expression(expression.left, group)
        right = _evaluate_group_expression(expression.right, group)
        if left is None or right is None:
            return None
        try:
            if expression.operator == "+":
                return left + right
            if expression.operator == "-":
                return left - right
            if expression.operator == "*":
                return left * right
            if expression.operator == "/":
                return None if right == 0 else left / right
            if expression.operator == "%":
                return None if right == 0 else left % right
        except TypeError:
            return None
    if isinstance(expression, ScalarFunction):
        if expression.name == "RANDOM":
            return _evaluate_random(expression, representative)
        return _apply_scalar_function_values(
            expression.name, [_evaluate_group_expression(arg, group) for arg in expression.args]
        )
    if isinstance(expression, ScalarCase):
        for branch in expression.whens:
            if evaluate(branch.condition, representative) is True:
                return _evaluate_group_expression(branch.result, group)
        return _evaluate_group_expression(expression.else_result, group) if expression.else_result is not None else None
    raise AssertionError(f"Unsupported aggregate scalar expression {expression!r}")


def _evaluate_having(node: Any, group: Sequence[dict[str, Any]]) -> bool | None:
    if node is None:
        return True
    if isinstance(node, Literal) and (node.value is None or isinstance(node.value, bool)):
        return node.value
    if isinstance(node, Unary):
        value = _evaluate_having(node.operand, group)
        return None if value is None else not value
    if isinstance(node, Binary) and node.operator in {"AND", "OR"}:
        # HAVING follows the same observable left-to-right Boolean contract as
        # row predicates, including the UNKNOWN cases.
        left = _evaluate_having(node.left, group)
        if node.operator == "AND":
            if left is False:
                return False
            right = _evaluate_having(node.right, group)
            if right is False:
                return False
            if left is None or right is None:
                return None
            return True
        if left is True:
            return True
        right = _evaluate_having(node.right, group)
        if right is True:
            return True
        if left is None or right is None:
            return None
        return False
    if isinstance(node, ScalarIsNull):
        result = _evaluate_group_expression(node.expression, group) is None
        return not result if node.negated else result
    if isinstance(node, ScalarComparison):
        left = _evaluate_group_expression(node.left, group)
        right = _evaluate_group_expression(node.right, group)
        if left is None or right is None:
            return None
        try:
            if node.operator == "=":
                return left == right
            if node.operator == "!=":
                return left != right
            if node.operator == "<":
                return left < right
            if node.operator == "<=":
                return left <= right
            if node.operator == ">":
                return left > right
            if node.operator == ">=":
                return left >= right
        except TypeError:
            return False
    raise AssertionError(f"Unsupported HAVING node {node!r}")


def _apply_aggregate_query(records: Sequence[dict[str, Any]], query: Query) -> list[dict[str, Any]]:
    filtered = [record for record in records if evaluate(query.predicate, record) is True]
    grouped: list[tuple[tuple[Any, ...], list[dict[str, Any]]]] = []
    if query.group_by:
        by_key: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
        order: list[tuple[Any, ...]] = []
        for record in filtered:
            values = tuple(evaluate_scalar_expression(expr, record) for expr in query.group_by)
            key = tuple(_hashable_group_value(value) for value in values)
            if key not in by_key:
                by_key[key] = []
                order.append(key)
            by_key[key].append(record)
        grouped = [(key, by_key[key]) for key in order]
    else:
        grouped = [((), filtered)]

    surviving = [group for _, group in grouped if _evaluate_having(query.having, group) is True]

    for term in reversed(query.order_by):
        present = []
        missing = []
        for group in surviving:
            value = _evaluate_group_expression(term.expression, group) if term.expression is not None else None
            (missing if value is None else present).append((group, value))
        try:
            present.sort(key=lambda item: item[1], reverse=term.descending)
        except TypeError:
            present.sort(key=lambda item: str(item[1]), reverse=term.descending)
        surviving = [group for group, _ in present] + [group for group, _ in missing]

    rows: list[dict[str, Any]] = []
    for group in surviving:
        row: dict[str, Any] = {"_yt_sql_aggregate_result": True}
        for term in query.select:
            if term.expression is not None:
                row[term.output_name] = _evaluate_group_expression(term.expression, group)
            elif group:
                row[term.output_name] = canonical_record_value(group[0], term)
            else:
                row[term.output_name] = None
        rows.append(row)

    if query.distinct:
        seen: set[tuple[Any, ...]] = set()
        unique = []
        for row in rows:
            key = tuple(_hashable_group_value(row.get(term.output_name)) for term in query.select)
            if key in seen:
                continue
            seen.add(key)
            unique.append(row)
        rows = unique
    if query.offset:
        rows = rows[query.offset :]
    if query.limit is not None:
        rows = rows[: query.limit]
    return rows


def _apply_query_body(records: Sequence[dict[str, Any]], query: Query) -> list[dict[str, Any]]:
    if _aggregate_query(query):
        return _apply_aggregate_query(records, query)
    result = [record for record in records if evaluate(query.predicate, record) is True]

    # Python's stable sort preserves source order as the final implicit tie-breaker.
    # Sort from the last term backwards so each ORDER BY direction remains independent.
    for term in reversed(query.order_by):
        present = [record for record in result if canonical_record_value(record, term) is not None]
        missing = [record for record in result if canonical_record_value(record, term) is None]
        try:
            present.sort(key=lambda record: canonical_record_value(record, term), reverse=term.descending)
        except TypeError:
            # Mixed extractor data is intentionally not coerced for predicates. For ordering only,
            # a deterministic textual fallback is preferable to failing an otherwise useful query.
            present.sort(key=lambda record: str(canonical_record_value(record, term)), reverse=term.descending)
        result = present + missing

    if query.distinct:
        seen: set[tuple[Any, ...]] = set()
        distinct_records: list[dict[str, Any]] = []
        for record in result:
            key_values = []
            for term in query.select:
                value = canonical_record_value(record, term)
                try:
                    hash(value)
                    key_values.append(value)
                except TypeError:
                    key_values.append(repr(value))
            key = tuple(key_values)
            if key not in seen:
                seen.add(key)
                distinct_records.append(record)
        result = distinct_records

    if query.offset:
        result = result[query.offset :]
    if query.limit is not None:
        result = result[: query.limit]

    random_terms = [term for term in query.select if term.expression is not None and _contains_random(term.expression)]
    if random_terms:
        materialised = []
        for record in result:
            row = dict(record)
            for term in random_terms:
                row[term.output_name] = canonical_record_value(record, term)
            materialised.append(row)
        result = materialised
    return result


def _project_result_rows(records: Sequence[dict[str, Any]], query: Query) -> list[dict[str, Any]]:
    if _aggregate_query(query):
        return [
            {
                **{term.output_name: record.get(term.output_name) for term in query.select},
                "_yt_sql_result_row": True,
            }
            for record in records
        ]
    return [
        {
            **{term.output_name: canonical_record_value(record, term) for term in query.select},
            "_yt_sql_result_row": True,
        }
        for record in records
    ]


def _records_for_source(
    records: Sequence[dict[str, Any]],
    source_name: str | None,
    source_facet: str | None,
    relations: dict[str, list[dict[str, Any]]],
    physical_requests: tuple[tuple[str, str | None], ...],
) -> list[dict[str, Any]]:
    if source_name is not None and source_name.casefold() in relations:
        return relations[source_name.casefold()]
    if source_name is None or len(physical_requests) <= 1:
        return list(records)
    return [
        record
        for record in records
        if record.get("_yt_sql_source") == source_name and record.get("_yt_sql_source_facet") == source_facet
    ]


def _union_row_key(row: dict[str, Any], output_names: tuple[str, ...]) -> tuple[Any, ...]:
    values = []
    for name in output_names:
        value = row.get(name)
        try:
            hash(value)
            values.append(value)
        except TypeError:
            values.append(repr(value))
    return tuple(values)


def _equality_join_fields(query: Query) -> tuple[RelationField, RelationField] | None:
    """Return left/right fields for a safely hashable equality JOIN shape.

    This recognises only the narrow resolved form whose equivalence is immediate:
    one equality comparison between fields owned by the two participating relations.
    Every other predicate remains on the deliberately simple nested-loop route.
    """
    join = query.joins[0]
    predicate = join.predicate
    if not isinstance(predicate, ScalarComparison) or predicate.operator != "=":
        return None
    if not isinstance(predicate.left, RelationField) or not isinstance(predicate.right, RelationField):
        return None
    left_alias = query.from_alias or ""
    right_alias = join.relation.alias or ""
    if predicate.left.qualifier == left_alias and predicate.right.qualifier == right_alias:
        return predicate.left, predicate.right
    if predicate.right.qualifier == left_alias and predicate.left.qualifier == right_alias:
        return predicate.right, predicate.left
    return None


def _hash_join_index(
    right_records: Sequence[dict[str, Any]], right_field: RelationField
) -> dict[Any, list[dict[str, Any]]] | None:
    """Build a stable right-side equality index, or decline unsafe values.

    SQL NULL never equality-matches. Unhashable values fall back to reference
    execution rather than acquiring a bespoke equality model in the optimiser.
    Lists preserve source order so INNER/LEFT multiplicity and ordering are unchanged.
    """
    index: dict[Any, list[dict[str, Any]]] = {}
    for record in right_records:
        value = canonical_record_value(record, right_field.name, right_field.kind)
        if value is None:
            continue
        try:
            hash(value)
        except TypeError:
            return None
        index.setdefault(value, []).append(record)
    return index


def _hash_join_matches(
    left_record: dict[str, Any], left_field: RelationField, index: dict[Any, list[dict[str, Any]]]
) -> list[dict[str, Any]] | None:
    value = canonical_record_value(left_record, left_field.name, left_field.kind)
    if value is None:
        return []
    try:
        hash(value)
    except TypeError:
        return None
    return index.get(value, [])


def _apply_existence_join(
    records: Sequence[dict[str, Any]],
    query: Query,
    relations: dict[str, list[dict[str, Any]]],
    physical_requests: tuple[tuple[str, str | None], ...],
    *,
    relational_optimisation: bool = True,
) -> list[dict[str, Any]]:
    """Apply one SEMI or ANTI join, with a proof-limited membership fast path."""
    join = query.joins[0]
    left_records = _records_for_source(records, query.from_source, query.from_facet, relations, physical_requests)
    right_records = _records_for_source(
        records, join.relation.source, join.relation.facet, relations, physical_requests
    )
    equality_fields = _equality_join_fields(query) if relational_optimisation else None
    if equality_fields is not None:
        left_field, right_field = equality_fields
        index = _hash_join_index(right_records, right_field)
        if index is not None:
            selected: list[dict[str, Any]] = []
            for left_record in left_records:
                matches = _hash_join_matches(left_record, left_field, index)
                if matches is None:
                    break
                matched = bool(matches)
                if (join.kind is JoinKind.SEMI and matched) or (join.kind is JoinKind.ANTI and not matched):
                    selected.append(left_record)
            else:
                return selected

    # Reference execution route. Keep this intentionally straightforward so tests
    # can differentially compare every relational optimisation against it.
    left_alias = query.from_alias or ""
    right_alias = join.relation.alias or ""
    selected = []
    for left_record in left_records:
        matched = False
        for right_record in right_records:
            context = EvaluationContext(
                left_record,
                relation_records={left_alias: left_record, right_alias: right_record},
            )
            if evaluate(join.predicate, context) is True:
                matched = True
                break
        if (join.kind is JoinKind.SEMI and matched) or (join.kind is JoinKind.ANTI and not matched):
            selected.append(left_record)
    return selected


def _apply_row_producing_join(
    records: Sequence[dict[str, Any]],
    query: Query,
    relations: dict[str, list[dict[str, Any]]],
    physical_requests: tuple[tuple[str, str | None], ...],
    *,
    relational_optimisation: bool = True,
) -> list[dict[str, Any]]:
    """Apply one INNER or LEFT JOIN while preserving explicit relation ownership."""
    join = query.joins[0]
    left_records = _records_for_source(records, query.from_source, query.from_facet, relations, physical_requests)
    right_records = _records_for_source(
        records, join.relation.source, join.relation.facet, relations, physical_requests
    )
    left_alias = query.from_alias or ""
    right_alias = join.relation.alias or ""

    equality_fields = _equality_join_fields(query) if relational_optimisation else None
    index = None
    left_field = None
    if equality_fields is not None:
        left_field, right_field = equality_fields
        index = _hash_join_index(right_records, right_field)

    joined: list[dict[str, Any]] = []
    for left_record in left_records:
        candidate_records: Sequence[dict[str, Any]] = right_records
        if index is not None and left_field is not None:
            indexed = _hash_join_matches(left_record, left_field, index)
            if indexed is None:
                # One unhashable left value invalidates the fast path for this row;
                # reference evaluation retains exact established semantics.
                candidate_records = right_records
            else:
                candidate_records = indexed
        matched = False
        for right_record in candidate_records:
            relation_records = {left_alias: left_record, right_alias: right_record}
            context = EvaluationContext(left_record, relation_records=relation_records)
            if evaluate(join.predicate, context) is not True:
                continue
            matched = True
            row = dict(left_record)
            row["_yt_sql_relation_records"] = relation_records
            joined.append(row)
        if join.kind is JoinKind.LEFT and not matched:
            row = dict(left_record)
            row["_yt_sql_relation_records"] = {left_alias: left_record, right_alias: {}}
            joined.append(row)
    return joined


def _apply_composed_query(
    records: Sequence[dict[str, Any]],
    query: Query,
    relations: dict[str, list[dict[str, Any]]],
    physical_requests: tuple[tuple[str, str | None], ...],
    *,
    relational_optimisation: bool = True,
) -> list[dict[str, Any]]:
    if not query.set_operations:
        if query.joins:
            if query.joins[0].kind in {JoinKind.INNER, JoinKind.LEFT}:
                input_records = _apply_row_producing_join(
                    records, query, relations, physical_requests, relational_optimisation=relational_optimisation
                )
            else:
                input_records = _apply_existence_join(
                    records, query, relations, physical_requests, relational_optimisation=relational_optimisation
                )
        else:
            input_records = _records_for_source(
                records, query.from_source, query.from_facet, relations, physical_requests
            )
        return _apply_query_body(input_records, query)

    left_body = replace(query, set_operations=(), order_by=(), limit=None, offset=0, ctes=())
    # A UNION branch is a complete relational query body. Apply its JOIN before
    # projection just as we do for a standalone query rather than bypassing the
    # relation operator through the older single-relation UNION path.
    left_rows = _apply_composed_query(
        records, left_body, relations, physical_requests, relational_optimisation=relational_optimisation
    )
    rows = _project_result_rows(left_rows, left_body)
    output_names = tuple(term.output_name for term in query.select)

    for operation in query.set_operations:
        branch = operation.query
        branch_body = replace(branch, set_operations=(), order_by=(), limit=None, offset=0, ctes=())
        branch_result = _apply_composed_query(
            records, branch_body, relations, physical_requests, relational_optimisation=relational_optimisation
        )
        branch_rows = _project_result_rows(branch_result, branch_body)
        branch_names = tuple(term.output_name for term in branch.select)
        remapped = [
            {
                **{target: row.get(source) for target, source in zip(output_names, branch_names, strict=True)},
                "_yt_sql_result_row": True,
            }
            for row in branch_rows
        ]
        rows.extend(remapped)
        if not operation.all:
            seen: set[tuple[Any, ...]] = set()
            unique: list[dict[str, Any]] = []
            for row in rows:
                key = _union_row_key(row, output_names)
                if key in seen:
                    continue
                seen.add(key)
                unique.append(row)
            rows = unique

    # Global ORDER BY, OFFSET and LIMIT apply to the already materialised logical
    # result relation. Do not feed the first branch's aggregate SELECT terms back
    # through _apply_query_body(), because that would aggregate the UNION result a
    # second time rather than merely ordering/slicing it.
    for term in reversed(query.order_by):
        present = [row for row in rows if canonical_record_value(row, term) is not None]
        missing = [row for row in rows if canonical_record_value(row, term) is None]
        try:
            present.sort(key=lambda row: canonical_record_value(row, term), reverse=term.descending)
        except TypeError:
            present.sort(key=lambda row: str(canonical_record_value(row, term)), reverse=term.descending)
        rows = present + missing
    if query.offset:
        rows = rows[query.offset :]
    if query.limit is not None:
        rows = rows[: query.limit]
    return rows


def apply_query(
    records: Sequence[dict[str, Any]], query: Query, *, relational_optimisation: bool = True
) -> list[dict[str, Any]]:
    """Apply a resolved query, materialising CTEs and set-composed relations."""
    for record in records:
        record.pop("_yt_sql_random_cache", None)
    physical_requests = query_physical_source_requests(query)
    if not query.ctes:
        result = _apply_composed_query(
            records, query, {}, physical_requests, relational_optimisation=relational_optimisation
        )
    else:
        relations: dict[str, list[dict[str, Any]]] = {}
        for cte in query.ctes:
            cte_result = _apply_composed_query(
                records, cte.query, relations, physical_requests, relational_optimisation=relational_optimisation
            )
            relations[cte.name.casefold()] = (
                _project_result_rows(cte_result, cte.query)
                if not cte.query.set_operations
                else [dict(row) for row in cte_result]
            )
        result = _apply_composed_query(
            records,
            replace(query, ctes=()),
            relations,
            physical_requests,
            relational_optimisation=relational_optimisation,
        )

    # Result-row markers are an internal execution detail used while materialising
    # CTEs and set operations. They must never escape through the public query API.
    execution_only_keys = {"_yt_sql_result_row", "_yt_sql_aggregate_result", "_yt_sql_random_cache"}
    return [{key: value for key, value in row.items() if key not in execution_only_keys} for row in result]


def evaluate(
    node: Any,
    record: dict[str, Any] | EvaluationContext,
    collection_bindings: tuple[Any, ...] = (),
) -> bool | None:
    """Evaluate a resolved AST using SQL-like three-valued Boolean logic.

    Compatibility coercion occurs once at the public boundary; recursive evaluation
    stays on the explicit context fast path.
    """
    context = (
        record
        if isinstance(record, EvaluationContext)
        else EvaluationContext(record=record, collection_bindings=collection_bindings)
    )
    return _evaluate_boolean_expression(node, context)
