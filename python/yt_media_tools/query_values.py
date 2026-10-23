"""Common value helpers used across yt-sql execution and semantic layers."""

from __future__ import annotations

from typing import Any

from .query_model import Field


_CASE_INSENSITIVE_ENUM_FIELDS = {"live_status", "availability"}


def comparison_values(field: Field, left: Any, right: Any) -> tuple[Any, Any]:
    """Normalise comparison values for fields with explicit enum-like semantics."""
    if field.name.casefold() in _CASE_INSENSITIVE_ENUM_FIELDS and isinstance(left, str) and isinstance(right, str):
        return left.casefold(), right.casefold()
    return left, right


def hashable_group_value(value: Any) -> Any:
    """Return a deterministic hashable representation used for relation grouping."""
    if isinstance(value, dict):
        return tuple((key, hashable_group_value(item)) for key, item in value.items())
    if isinstance(value, list):
        return tuple(hashable_group_value(item) for item in value)
    return value
