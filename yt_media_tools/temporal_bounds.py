"""Conservative temporal-bound inference for acquisition planning."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from .dates import DateContext, parse_date_literal, parse_datetime_literal
from .query_model import Binary, Between, Field, InList, Literal, Unary


@dataclass(frozen=True)
class TemporalBound:
    """One proven lower or upper bound on a temporal query field."""

    field: str
    kind: str
    value: date | datetime
    inclusive: bool


@dataclass(frozen=True)
class TemporalFieldBounds:
    """Proven temporal interval for one field."""

    field: str
    kind: str
    lower: TemporalBound | None = None
    upper: TemporalBound | None = None

    @property
    def contradictory(self) -> bool:
        """Return whether the proven interval contains no possible value."""
        if self.lower is None or self.upper is None:
            return False
        if self.lower.value > self.upper.value:
            return True
        return self.lower.value == self.upper.value and not (self.lower.inclusive and self.upper.inclusive)


@dataclass(frozen=True)
class TemporalBoundPlan:
    """Temporal constraints proven from the WHERE expression."""

    fields: tuple[TemporalFieldBounds, ...]
    reason: str

    def for_field(self, name: str) -> TemporalFieldBounds | None:
        """Return inferred bounds for ``name`` using case-insensitive field identity."""
        key = name.casefold()
        return next((item for item in self.fields if item.field.casefold() == key), None)


_TEMPORAL_FIELDS = {
    "upload_date": "date",
    "date": "date",
    "timestamp": "datetime",
    "release_timestamp": "datetime",
    "modified_timestamp": "datetime",
}


def _parse_literal(literal: Literal, kind: str, context: DateContext) -> date | datetime | None:
    value = literal.value
    if kind == "date" and isinstance(value, date) and not isinstance(value, datetime):
        return value
    if kind == "datetime" and isinstance(value, datetime):
        return value
    try:
        if kind == "date":
            return parse_date_literal(str(value), context)
        return parse_datetime_literal(str(value), context)
    except ValueError:
        return None


def _stronger_lower(left: TemporalBound | None, right: TemporalBound | None) -> TemporalBound | None:
    if left is None:
        return right
    if right is None:
        return left
    if right.value > left.value:
        return right
    if right.value < left.value:
        return left
    return TemporalBound(left.field, left.kind, left.value, left.inclusive and right.inclusive)


def _stronger_upper(left: TemporalBound | None, right: TemporalBound | None) -> TemporalBound | None:
    if left is None:
        return right
    if right is None:
        return left
    if right.value < left.value:
        return right
    if right.value > left.value:
        return left
    return TemporalBound(left.field, left.kind, left.value, left.inclusive and right.inclusive)


def _weaker_lower(left: TemporalBound | None, right: TemporalBound | None) -> TemporalBound | None:
    if left is None or right is None:
        return None
    if right.value < left.value:
        return right
    if right.value > left.value:
        return left
    return TemporalBound(left.field, left.kind, left.value, left.inclusive or right.inclusive)


def _weaker_upper(left: TemporalBound | None, right: TemporalBound | None) -> TemporalBound | None:
    if left is None or right is None:
        return None
    if right.value > left.value:
        return right
    if right.value < left.value:
        return left
    return TemporalBound(left.field, left.kind, left.value, left.inclusive or right.inclusive)


def _merge_and(
    left: dict[str, TemporalFieldBounds], right: dict[str, TemporalFieldBounds]
) -> dict[str, TemporalFieldBounds]:
    result = dict(left)
    for key, candidate in right.items():
        current = result.get(key)
        if current is None:
            result[key] = candidate
            continue
        result[key] = TemporalFieldBounds(
            current.field,
            current.kind,
            _stronger_lower(current.lower, candidate.lower),
            _stronger_upper(current.upper, candidate.upper),
        )
    return result


def _merge_or(
    left: dict[str, TemporalFieldBounds], right: dict[str, TemporalFieldBounds]
) -> dict[str, TemporalFieldBounds]:
    result: dict[str, TemporalFieldBounds] = {}
    for key in left.keys() & right.keys():
        first = left[key]
        second = right[key]
        result[key] = TemporalFieldBounds(
            first.field,
            first.kind,
            _weaker_lower(first.lower, second.lower),
            _weaker_upper(first.upper, second.upper),
        )
    return {key: value for key, value in result.items() if value.lower is not None or value.upper is not None}


def _infer(node: Any, context: DateContext) -> dict[str, TemporalFieldBounds]:
    if node is None or isinstance(node, Unary):
        return {}
    if isinstance(node, Binary) and node.operator in {"AND", "OR"}:
        left = _infer(node.left, context)
        right = _infer(node.right, context)
        return _merge_and(left, right) if node.operator == "AND" else _merge_or(left, right)

    field: Field | None = None
    lower: TemporalBound | None = None
    upper: TemporalBound | None = None

    if isinstance(node, Between) and not node.negated:
        field = node.field
        kind = _TEMPORAL_FIELDS.get(field.name.casefold())
        if kind is None:
            return {}
        low = _parse_literal(node.lower, kind, context)
        high = _parse_literal(node.upper, kind, context)
        if low is None or high is None:
            return {}
        lower = TemporalBound(field.name, kind, low, True)
        upper = TemporalBound(field.name, kind, high, True)
    elif isinstance(node, InList) and not node.negated:
        field = node.field
        kind = _TEMPORAL_FIELDS.get(field.name.casefold())
        if kind is None or not node.values:
            return {}
        values = [_parse_literal(item, kind, context) for item in node.values]
        if any(value is None for value in values):
            return {}
        parsed = [value for value in values if value is not None]
        lower = TemporalBound(field.name, kind, min(parsed), True)
        upper = TemporalBound(field.name, kind, max(parsed), True)
    elif isinstance(node, Binary) and isinstance(node.left, Field) and isinstance(node.right, Literal):
        field = node.left
        kind = _TEMPORAL_FIELDS.get(field.name.casefold())
        if kind is None:
            return {}
        value = _parse_literal(node.right, kind, context)
        if value is None:
            return {}
        if node.operator == ">":
            lower = TemporalBound(field.name, kind, value, False)
        elif node.operator == ">=":
            lower = TemporalBound(field.name, kind, value, True)
        elif node.operator == "<":
            upper = TemporalBound(field.name, kind, value, False)
        elif node.operator == "<=":
            upper = TemporalBound(field.name, kind, value, True)
        elif node.operator == "=":
            lower = TemporalBound(field.name, kind, value, True)
            upper = TemporalBound(field.name, kind, value, True)
        else:
            return {}
    else:
        return {}

    assert field is not None
    key = field.name.casefold()
    return {key: TemporalFieldBounds(field.name, _TEMPORAL_FIELDS[key], lower, upper)}


def infer_temporal_bounds(predicate: Any, context: DateContext) -> TemporalBoundPlan:
    """Infer only bounds logically implied by the complete predicate."""
    inferred = _infer(predicate, context)
    fields = tuple(inferred[key] for key in sorted(inferred))
    if not fields:
        return TemporalBoundPlan((), "the WHERE expression implies no safe temporal acquisition bounds")
    return TemporalBoundPlan(fields, "temporal bounds were proven from the complete WHERE expression")


def upload_date_frontier(bounds: TemporalBoundPlan) -> date | None:
    """Return the inclusive day frontier implied for upload_date/date acquisition."""
    candidate = bounds.for_field("upload_date") or bounds.for_field("date")
    if candidate is None or candidate.lower is None or candidate.kind != "date":
        return None
    value = candidate.lower.value
    assert isinstance(value, date) and not isinstance(value, datetime)
    return value if candidate.lower.inclusive else value + timedelta(days=1)
