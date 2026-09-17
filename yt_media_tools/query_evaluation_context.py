"""Explicit runtime context for yt-sql expression evaluation."""

from __future__ import annotations

from typing import Any


class EvaluationContext:
    """Immutable runtime state visible while evaluating one resolved expression.

    The metadata record and nested collection-element bindings are semantic runtime
    inputs, not properties of the AST. Keeping them together prevents evaluator APIs
    from accumulating parallel positional state as relational execution evolves.

    A small explicit slots-based representation is used rather than a frozen dataclass
    because contexts sit directly on evaluator hot paths. Public state is exposed only
    through read-only properties, so construction avoids frozen-dataclass assignment
    machinery without weakening the context's immutable interface.
    """

    __slots__ = ("_collection_bindings", "_record", "_relation_records")

    def __init__(
        self,
        record: dict[str, Any],
        collection_bindings: tuple[Any, ...] = (),
        relation_records: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._record = record
        self._collection_bindings = collection_bindings
        self._relation_records = relation_records or {}

    @property
    def record(self) -> dict[str, Any]:
        """Return the metadata record associated with this evaluation."""
        return self._record

    @property
    def collection_bindings(self) -> tuple[Any, ...]:
        """Return the immutable lexical collection-binding stack."""
        return self._collection_bindings

    def bind_collection_element(self, element: Any) -> EvaluationContext:
        """Return a child context with one additional lexical collection binding."""
        return EvaluationContext(
            self._record,
            self._collection_bindings + (element,),
            self._relation_records,
        )

    def collection_element(self, scope_distance: int) -> Any:
        """Resolve a lexical collection element by its resolver-assigned distance."""
        index = len(self._collection_bindings) - 1 - scope_distance
        return self._collection_bindings[index] if 0 <= index < len(self._collection_bindings) else None

    def relation_record(self, qualifier: str) -> dict[str, Any] | None:
        """Return the row bound to one resolved relation alias, if present."""
        return self._relation_records.get(qualifier)
