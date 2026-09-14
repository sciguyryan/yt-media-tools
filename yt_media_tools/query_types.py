"""Resolved yt-sql type declarations shared by semantic layers.

The language type model includes scalar, collection and structured values. Keep
these contracts backend-neutral so source adapters can describe what they expose
without defining yt-sql semantics themselves.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Iterable


class StructuredShape(str, Enum):
    """Schema contract carried by a structured yt-sql value.

    ``OPAQUE`` preserves the existing structured-value boundary without promising any
    accessible members. ``DECLARED`` describes a closed yt-sql schema. ``DYNAMIC``
    describes provider-derived structure whose currently known members may grow as
    runtime evidence changes.
    """

    OPAQUE = "opaque"
    DECLARED = "declared"
    DYNAMIC = "dynamic"


@dataclass(frozen=True)
class StructuredMember:
    """One named member in a structured yt-sql type."""

    name: str
    value_type: "QueryType"

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Structured member names must not be empty.")


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

    ``kind`` retains the established value-kind vocabulary. Collections carry a
    declared element type and logical ordering contract. Structured values carry an
    opaque, declared or dynamic schema shape and optional typed members. NULLability
    belongs to each type node so nested collections and structures compose directly.
    """

    kind: str
    nullable: bool = True
    element_type: "QueryType | None" = None
    ordering: CollectionOrdering | None = None
    structured_shape: StructuredShape | None = None
    members: tuple[StructuredMember, ...] = ()

    def __post_init__(self) -> None:
        if self.kind == "collection":
            if self.element_type is None:
                raise ValueError("Collection types require a declared element type.")
            if self.ordering is None:
                raise ValueError("Collection types require an explicit logical ordering contract.")
            if self.structured_shape is not None or self.members:
                raise ValueError("Collection types cannot declare structured-value metadata directly.")
            return
        if self.element_type is not None or self.ordering is not None:
            raise ValueError("Only collection types may declare element types or collection ordering.")
        if self.kind == "structured":
            shape = self.structured_shape or StructuredShape.OPAQUE
            object.__setattr__(self, "structured_shape", shape)
            if shape is StructuredShape.OPAQUE and self.members:
                raise ValueError("Opaque structured types cannot declare members.")
            names = [member.name for member in self.members]
            if len(set(names)) != len(names):
                raise ValueError("Structured member names must be unique.")
            return
        if self.structured_shape is not None or self.members:
            raise ValueError("Only structured types may declare structured-value metadata.")

    @classmethod
    def scalar(cls, kind: str, *, nullable: bool = True) -> "QueryType":
        """Construct a scalar yt-sql type using the existing kind vocabulary.

        ``structured`` remains accepted as a compatibility shorthand for an opaque
        structured value so existing schema declarations retain their exact boundary.
        """
        if kind == "collection":
            raise ValueError("Use QueryType.collection() for collection values.")
        if kind == "structured":
            return cls.structured_opaque(nullable=nullable)
        return cls(kind=kind, nullable=nullable)

    @classmethod
    def structured(
        cls,
        members: Iterable[StructuredMember],
        *,
        nullable: bool = True,
        shape: StructuredShape = StructuredShape.DECLARED,
    ) -> "QueryType":
        """Construct a structured type with named member contracts."""
        if shape is StructuredShape.OPAQUE:
            raise ValueError("Use QueryType.structured_opaque() for opaque structured values.")
        return cls(
            kind="structured",
            nullable=nullable,
            structured_shape=shape,
            members=tuple(members),
        )

    @classmethod
    def structured_opaque(cls, *, nullable: bool = True) -> "QueryType":
        """Construct a structured value whose member schema is intentionally unknown."""
        return cls(
            kind="structured",
            nullable=nullable,
            structured_shape=StructuredShape.OPAQUE,
        )

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
    def is_structured(self) -> bool:
        """Return whether this type represents a structured value."""
        return self.kind == "structured"

    @property
    def has_declared_members(self) -> bool:
        """Return whether this structured value exposes member type information."""
        return self.is_structured and self.structured_shape is not StructuredShape.OPAQUE

    def declared_member_type(self, name: str) -> "QueryType | None":
        """Return the exact declared member type without base NULL propagation."""
        if not self.has_declared_members:
            return None
        for member in self.members:
            if member.name == name:
                return member.value_type
        return None

    def member_result_type(self, name: str) -> "QueryType | None":
        """Return a member type with nullable-base SQL NULL propagation applied.

        A nullable structured base can itself evaluate to SQL NULL, so even a declared
        non-NULL member becomes nullable when accessed through such a base.
        """
        member_type = self.declared_member_type(name)
        if member_type is None:
            return None
        return member_type.with_nullable(member_type.nullable or self.nullable)

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
        suffix = "?" if self.nullable else ""
        if self.is_collection:
            assert self.element_type is not None
            assert self.ordering is not None
            return f"collection<{self.element_type.describe()}>[{self.ordering.value}]{suffix}"
        if self.is_structured:
            if self.structured_shape is StructuredShape.OPAQUE:
                return f"structured{suffix}"
            member_text = ",".join(f"{member.name}:{member.value_type.describe()}" for member in self.members)
            shape = "dynamic" if self.structured_shape is StructuredShape.DYNAMIC else "declared"
            return f"structured<{shape}>{{{member_text}}}{suffix}"
        return f"{self.kind}{suffix}"
