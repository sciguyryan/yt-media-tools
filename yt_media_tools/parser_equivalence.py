"""Parser-independent equivalence helpers for yt-sql parser migration.

This module defines the comparison boundary for a future replacement parser.
It deliberately operates on yt-sql model objects and diagnostics rather than
on parser-library-native trees, tokens, or exception text.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any

from .query_model import QuerySyntaxError

# Construction metadata is not part of the normalised language model. Source
# origins are compared separately because they have a different equivalence
# contract from semantic structure.
_INCIDENTAL_MODEL_FIELDS = frozenset({"position", "source", "span", "location", "context"})


def normalised_parser_model(value: Any) -> Any:
    """Return a parser-neutral structural representation of a yt-sql model."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return (type(value).__name__, value.value)
    if isinstance(value, tuple):
        return tuple(normalised_parser_model(item) for item in value)
    if isinstance(value, list):
        return tuple(normalised_parser_model(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((key, normalised_parser_model(item)) for key, item in value.items()))
    if is_dataclass(value):
        members = tuple(
            (field.name, normalised_parser_model(getattr(value, field.name)))
            for field in fields(value)
            if field.name not in _INCIDENTAL_MODEL_FIELDS
        )
        return (type(value).__name__, members)
    return value


def user_origin_positions(value: Any) -> tuple[tuple[str, int], ...]:
    """Return available user-written AST start positions in traversal order.

    The current model stores start positions on many user-written nodes rather
    than complete spans. A candidate parser must preserve equivalent origins;
    richer source-span comparison applies where the model actually exposes it.
    """
    found: list[tuple[str, int]] = []

    def visit(node: Any) -> None:
        if is_dataclass(node):
            if hasattr(node, "position"):
                position = getattr(node, "position")
                if isinstance(position, int):
                    found.append((type(node).__name__, position))
            for field in fields(node):
                if field.name in {"source", "span", "location", "context"}:
                    continue
                visit(getattr(node, field.name))
        elif isinstance(node, (tuple, list)):
            for item in node:
                visit(item)
        elif isinstance(node, dict):
            for item in node.values():
                visit(item)

    visit(value)
    return tuple(found)


def normalised_diagnostic(error: QuerySyntaxError) -> tuple[Any, ...]:
    """Return the structured diagnostic properties required for equivalence."""
    context = error.context
    return (
        context.category,
        context.span.start.position,
        context.span.end.position,
        context.span.start.line,
        context.span.start.column,
        context.span.end.line,
        context.span.end.column,
        context.expected,
    )
