"""Resolved yt-sql type declarations shared by semantic layers.

The current language is predominantly scalar, but collection indexing needs a
stable type contract before parser and evaluator syntax is introduced.  Keep
that contract backend-neutral so source adapters can describe what they expose
without defining yt-sql semantics themselves.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class CollectionOrdering(str, Enum):
    """Logical ordering contract for a collection value.

    Positional indexing is meaningful only for ``STABLE`` collections.  An
    ``UNORDERED`` collection is known not to have a positional contract, while
    ``UNKNOWN`` means that no portable ordering guarantee has been established.
    """

    STABLE = "stable"
    UNORDERED = "unordered"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class QueryType:
    """One resolved yt-sql value type.

    ``kind`` retains the established scalar-kind vocabulary.  Collections use
    the distinguished ``collection`` kind and carry a declared element type and
    logical ordering contract.  Element nullability belongs to the element type
    itself so nested collections remain representable without special cases.
    """

    kind: str
    nullable: bool = True
    element_type: "QueryType | None" = None
    ordering: CollectionOrdering | None = None

    def __post_init__(self) -> None:
        if self.kind == "collection":
            if self.element_type is None:
                raise ValueError("Collection types require a declared element type.")
            if self.ordering is None:
                raise ValueError("Collection types require an explicit logical ordering contract.")
            return
        if self.element_type is not None or self.ordering is not None:
            raise ValueError("Only collection types may declare element types or collection ordering.")

    @classmethod
    def scalar(cls, kind: str, *, nullable: bool = True) -> "QueryType":
        """Construct a scalar yt-sql type using the existing kind vocabulary."""
        if kind == "collection":
            raise ValueError("Use QueryType.collection() for collection values.")
        return cls(kind=kind, nullable=nullable)

    @classmethod
    def collection(
        cls,
        element_type: "QueryType",
        *,
        nullable: bool = True,
        ordering: CollectionOrdering = CollectionOrdering.UNKNOWN,
    ) -> "QueryType":
        """Construct a typed collection with an explicit logical ordering contract."""
        return cls(
            kind="collection",
            nullable=nullable,
            element_type=element_type,
            ordering=ordering,
        )

    @property
    def is_collection(self) -> bool:
        """Return whether this type represents a collection value."""
        return self.kind == "collection"

    @property
    def supports_positional_indexing(self) -> bool:
        """Return whether yt-sql may assign positional meaning to this collection."""
        return self.is_collection and self.ordering is CollectionOrdering.STABLE

    def with_nullable(self, nullable: bool = True) -> "QueryType":
        """Return this type with the requested top-level NULLability."""
        if self.nullable == nullable:
            return self
        return replace(self, nullable=nullable)

    def indexed_result_type(self) -> "QueryType":
        """Return the result type of valid zero-based positional indexing.

        Indexing can produce SQL NULL even when declared collection elements are
        non-NULL because a runtime index may be out of range.  A NULL collection
        also yields SQL NULL.  The resulting type is therefore always nullable.
        """
        if not self.is_collection:
            raise TypeError(f"Type {self.describe()} is not a collection.")
        if not self.supports_positional_indexing:
            raise TypeError("Positional indexing requires a stable logical collection ordering.")
        assert self.element_type is not None
        return self.element_type.with_nullable(True)

    def describe(self) -> str:
        """Return a deterministic human-readable type description."""
        if not self.is_collection:
            suffix = "?" if self.nullable else ""
            return f"{self.kind}{suffix}"
        assert self.element_type is not None
        assert self.ordering is not None
        suffix = "?" if self.nullable else ""
        return f"collection<{self.element_type.describe()}>[{self.ordering.value}]{suffix}"
