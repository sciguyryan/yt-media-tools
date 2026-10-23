"""Portable, engine-independent typed result validation and row comparison."""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation


class TypedValueError(ValueError):
    """Invalid portable typed value or comparison contract."""


_INTEGER = re.compile(r"-?(?:0|[1-9][0-9]*)\Z")
_DECIMAL = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")
_TIMESTAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)\Z")


def _typed(value: object) -> tuple[str, object]:
    if value is None:
        return ("null", None)
    if isinstance(value, bool):
        return ("boolean", value)
    if isinstance(value, str):
        if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise TypedValueError("unpaired Unicode surrogate")
        return ("text", value)
    if isinstance(value, (int, float)):
        raise TypedValueError("untagged JSON numbers are ambiguous; use integer or decimal")
    if not isinstance(value, dict) or set(value) != {"type", "value"}:
        raise TypedValueError("typed value must contain exactly type and value")
    kind, raw = value["type"], value["value"]
    if kind == "integer" and isinstance(raw, str) and _INTEGER.fullmatch(raw):
        return ("integer", int(raw))
    if kind == "decimal" and isinstance(raw, str) and _DECIMAL.fullmatch(raw):
        try:
            return ("decimal", Decimal(raw))
        except InvalidOperation as exc:
            raise TypedValueError("invalid decimal") from exc
    if kind == "timestamp" and isinstance(raw, str) and _TIMESTAMP.fullmatch(raw):
        if raw[-1] != "Z":
            hours, minutes = map(int, raw[-5:].split(":"))
            if hours > 23 or minutes > 59:
                raise TypedValueError("invalid timestamp offset")
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.utcoffset() is None:
                raise ValueError("missing offset")
            return ("timestamp", parsed.astimezone(timezone.utc))
        except ValueError as exc:
            raise TypedValueError("invalid timestamp") from exc
    raise TypedValueError(f"invalid typed value: {kind!r}")


def validate_values(rows: object, width: int) -> None:
    if not isinstance(rows, list):
        raise TypedValueError("rows must be an array")
    for row in rows:
        if not isinstance(row, list) or len(row) != width:
            raise TypedValueError("row width differs from columns")
        for value in row:
            _typed(value)


def _key(row: list[object]) -> tuple[tuple[str, object], ...]:
    return tuple(_typed(value) for value in row)


def compare_rows(expected: list[list[object]], actual: list[list[object]], *, ordered: bool) -> bool:
    """Compare typed rows exactly, retaining duplicates in unordered results."""
    if not isinstance(ordered, bool):
        raise TypedValueError("ordered must be boolean")
    if not isinstance(expected, list) or not isinstance(actual, list):
        raise TypedValueError("rows must be arrays")
    if any(not isinstance(row, list) for row in expected + actual):
        raise TypedValueError("each row must be an array")
    left = [_key(row) for row in expected]
    right = [_key(row) for row in actual]
    return left == right if ordered else Counter(left) == Counter(right)


def compare_tied_groups(expected: list[list[object]], actual: list[list[object]], *, group_sizes: list[int]) -> bool:
    """Match consecutive ordered groups, ignoring order only within each group.

    Group boundaries are supplied by an independently reviewed ordering-key
    analysis. They cannot be inferred from projected rows: ORDER BY expressions
    need not appear in the SELECT projection.
    """
    if (
        not isinstance(group_sizes, list)
        or any(type(size) is not int or size <= 0 for size in group_sizes)
        or not isinstance(expected, list)
        or not isinstance(actual, list)
        or sum(group_sizes) != len(expected)
        or len(actual) != len(expected)
    ):
        raise TypedValueError("invalid tied-group partition")
    validate_values(expected, len(expected[0]) if expected else 0)
    validate_values(actual, len(expected[0]) if expected else 0)
    start = 0
    for size in group_sizes:
        end = start + size
        if Counter(_key(row) for row in expected[start:end]) != Counter(_key(row) for row in actual[start:end]):
            return False
        start = end
    return True
