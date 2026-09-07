"""Acquisition capability modelling and conservative lightweight query evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from .dates import DateContext, parse_date_literal
from .query import Between, Binary, Field, InList, IsNull, Literal, TextPredicate, Unary


EXACT = "exact"
APPROXIMATE = "approximate"
UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class FieldCapability:
    """Describe how authoritatively one acquisition stage can supply a field."""

    field: str
    youtubejs: str
    ytdlp_flat: str
    ytdlp_detailed: str = EXACT


_FIELD_CAPABILITIES = {
    "id": FieldCapability("id", EXACT, EXACT),
    "title": FieldCapability("title", EXACT, EXACT),
    "upload_date": FieldCapability("upload_date", APPROXIMATE, APPROXIMATE),
    "date": FieldCapability("date", APPROXIMATE, APPROXIMATE),
    "duration": FieldCapability("duration", UNAVAILABLE, APPROXIMATE),
    "view_count": FieldCapability("view_count", APPROXIMATE, APPROXIMATE),
    "views": FieldCapability("views", APPROXIMATE, APPROXIMATE),
    "source_index": FieldCapability("source_index", EXACT, EXACT),
}


def field_capability(field: str) -> FieldCapability:
    """Return the conservative capability declaration for a query field."""
    key = field.casefold()
    return _FIELD_CAPABILITIES.get(key, FieldCapability(field, UNAVAILABLE, UNAVAILABLE, EXACT))


def capabilities_for_fields(fields: set[str]) -> list[FieldCapability]:
    """Return capabilities for fields in deterministic order."""
    return [field_capability(field) for field in sorted(fields)]


def _date_literal(literal: Literal, dates: DateContext) -> date | None:
    if isinstance(literal.value, date):
        return literal.value
    try:
        return parse_date_literal(str(literal.value), dates)
    except ValueError:
        return None


def _date_interval(record: dict[str, Any]) -> tuple[date, date] | None:
    oldest = record.get("approximate_upload_date_oldest")
    newest = record.get("approximate_upload_date_newest")
    if not oldest or not newest:
        return None
    try:
        return date.fromisoformat(str(oldest)), date.fromisoformat(str(newest))
    except ValueError:
        return None


def _exact_value(record: dict[str, Any], field: Field) -> tuple[bool, Any]:
    name = field.name.casefold()
    if name in {"id", "title", "source_index"} and name in record:
        return True, record.get(name)
    return False, None


def _compare(operator: str, left: Any, right: Any) -> bool:
    if operator == "=":
        return left == right
    if operator == "!=":
        return left != right
    if operator == "<":
        return left < right
    if operator == "<=":
        return left <= right
    if operator == ">":
        return left > right
    if operator == ">=":
        return left >= right
    raise AssertionError(operator)


def _date_comparison_truth(record: dict[str, Any], operator: str, literal: Literal, dates: DateContext) -> bool | None:
    interval = _date_interval(record)
    target = _date_literal(literal, dates)
    if interval is None or target is None:
        return None
    oldest, newest = interval

    # Return a truth value only where the complete plausible interval proves it.
    if operator == "<":
        if newest < target:
            return True
        if oldest >= target:
            return False
    elif operator == "<=":
        if newest <= target:
            return True
        if oldest > target:
            return False
    elif operator == ">":
        if oldest > target:
            return True
        if newest <= target:
            return False
    elif operator == ">=":
        if oldest >= target:
            return True
        if newest < target:
            return False
    elif operator == "=":
        if oldest == newest == target:
            return True
        if target < oldest or target > newest:
            return False
    elif operator == "!=":
        if target < oldest or target > newest:
            return True
        if oldest == newest == target:
            return False
    return None


def lightweight_truth(node: Any, record: dict[str, Any], dates: DateContext) -> bool | None:
    """Evaluate only what lightweight metadata can prove without risking false rejection.

    True and False are returned only when the available metadata proves the result. None means
    that authoritative detailed metadata is required. Callers may safely discard a candidate
    only when this function returns False.
    """
    if node is None:
        return True
    if isinstance(node, Unary):
        value = lightweight_truth(node.operand, record, dates)
        return None if value is None else not value
    if isinstance(node, Binary) and node.operator in {"AND", "OR"}:
        left = lightweight_truth(node.left, record, dates)
        right = lightweight_truth(node.right, record, dates)
        if node.operator == "AND":
            if left is False or right is False:
                return False
            if left is True and right is True:
                return True
            return None
        if left is True or right is True:
            return True
        if left is False and right is False:
            return False
        return None
    if isinstance(node, Binary) and isinstance(node.left, Field):
        if node.left.name.casefold() in {"upload_date", "date"}:
            return _date_comparison_truth(record, node.operator, node.right, dates)
        available, left = _exact_value(record, node.left)
        if not available or left is None:
            return None
        try:
            return _compare(node.operator, left, node.right.value)
        except TypeError:
            return False
    if isinstance(node, Between):
        if node.field.name.casefold() in {"upload_date", "date"}:
            lower = _date_literal(node.lower, dates)
            upper = _date_literal(node.upper, dates)
            interval = _date_interval(record)
            if lower is None or upper is None or interval is None:
                return None
            oldest, newest = interval
            if newest < lower or oldest > upper:
                result: bool | None = False
            elif oldest >= lower and newest <= upper:
                result = True
            else:
                result = None
            return None if result is None else (not result if node.negated else result)
        available, value = _exact_value(record, node.field)
        if not available or value is None:
            return None
        try:
            result = node.lower.value <= value <= node.upper.value
        except TypeError:
            result = False
        return not result if node.negated else result
    if isinstance(node, InList):
        available, value = _exact_value(record, node.field)
        if not available or value is None:
            return None
        result = any(value == item.value for item in node.values)
        return not result if node.negated else result
    if isinstance(node, IsNull):
        available, value = _exact_value(record, node.field)
        if not available:
            return None
        result = value is None
        return not result if node.negated else result
    if isinstance(node, TextPredicate):
        available, value = _exact_value(record, node.field)
        if not available or not isinstance(value, str):
            return None
        needle = str(node.value.value)
        if node.operator == "CONTAINS":
            result = needle.casefold() in value.casefold()
        else:
            # Regex matching is deliberately deferred rather than duplicating query-engine
            # semantics in the acquisition planner.
            return None
        return not result if node.negated else result
    return None


def safely_reject_lightweight(node: Any, record: dict[str, Any], dates: DateContext) -> bool:
    """Return True only when lightweight metadata proves a predicate cannot match."""
    return lightweight_truth(node, record, dates) is False
