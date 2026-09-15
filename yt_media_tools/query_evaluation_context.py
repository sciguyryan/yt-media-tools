"""Explicit runtime context for yt-sql expression evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class EvaluationContext:
    """Runtime state visible while evaluating one resolved expression.

    The metadata record and nested collection-element bindings are semantic runtime
    inputs, not properties of the AST. Keeping them together prevents evaluator APIs
    from accumulating parallel positional state as relational execution evolves.
    """

    record: dict[str, Any]
    collection_bindings: tuple[Any, ...] = ()

    def bind_collection_element(self, element: Any) -> EvaluationContext:
        """Return a child context with one additional lexical collection binding."""
        return EvaluationContext(self.record, self.collection_bindings + (element,))

    def collection_element(self, scope_distance: int) -> Any:
        """Resolve a lexical collection element by its resolver-assigned distance."""
        index = len(self.collection_bindings) - 1 - scope_distance
        return self.collection_bindings[index] if 0 <= index < len(self.collection_bindings) else None
