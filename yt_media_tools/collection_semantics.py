"""Syntax-neutral semantic foundations for querying yt-sql collections.

Collection query syntax is deliberately defined elsewhere. This module records the
semantic contracts that syntax must lower into: nested element scopes, exact element
types, outer-scope addressing, and SQL three-valued quantifier reduction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .query_types import QueryType


SqlTruth = bool | None


@dataclass(frozen=True)
class CollectionElementScope:
    """One lexical collection-element scope.

    ``depth`` is assigned structurally rather than from user-facing identifier text.
    Future syntax may choose how an element is named, but semantic resolution can
    always address the current element at depth zero and enclosing collection
    elements by walking ``parent``. The exact collection element type is retained,
    including element NULLability and any nested collection or structured schema.
    """

    element_type: QueryType
    parent: "CollectionElementScope | None" = None

    @property
    def depth(self) -> int:
        """Return this scope's zero-based nesting depth from the outermost scope."""
        return 0 if self.parent is None else self.parent.depth + 1

    def outer(self, levels: int = 1) -> "CollectionElementScope":
        """Return an enclosing element scope by lexical distance.

        ``levels=1`` means the immediately enclosing collection element. The current
        element is intentionally not called an outer scope, so zero and negative
        distances are rejected rather than given ambiguous meanings.
        """
        if isinstance(levels, bool) or not isinstance(levels, int) or levels < 1:
            raise ValueError("Outer collection scope distance must be a positive integer.")
        scope: CollectionElementScope | None = self
        for _ in range(levels):
            scope = scope.parent
            if scope is None:
                raise LookupError("Collection element scope has no enclosing scope at that distance.")
        return scope


def bind_collection_element(
    collection_type: QueryType,
    *,
    parent: CollectionElementScope | None = None,
) -> CollectionElementScope:
    """Create a lexical scope for one collection's elements.

    Binding does not change element NULLability. A collection of ``string?`` binds a
    ``string?`` element, while collection-level NULLability remains a property of the
    collection expression rather than of every element.
    """
    if not collection_type.is_collection:
        raise TypeError(f"Type {collection_type.describe()} is not a collection.")
    assert collection_type.element_type is not None
    return CollectionElementScope(collection_type.element_type, parent)


def existential_truth(results: Iterable[SqlTruth], *, collection_is_null: bool = False) -> SqlTruth:
    """Reduce element predicate results using SQL existential three-valued logic.

    A NULL collection yields UNKNOWN. For a non-NULL collection, TRUE dominates;
    otherwise UNKNOWN dominates FALSE. The existential predicate over an empty
    collection is FALSE.
    """
    if collection_is_null:
        return None
    saw_unknown = False
    for result in results:
        if result is True:
            return True
        if result is None:
            saw_unknown = True
        elif result is not False:
            raise TypeError("Collection predicates must yield TRUE, FALSE or SQL NULL.")
    return None if saw_unknown else False


def universal_truth(results: Iterable[SqlTruth], *, collection_is_null: bool = False) -> SqlTruth:
    """Reduce element predicate results using SQL universal three-valued logic.

    A NULL collection yields UNKNOWN. For a non-NULL collection, FALSE dominates;
    otherwise UNKNOWN dominates TRUE. The universal predicate over an empty
    collection is TRUE, following ordinary vacuous truth.
    """
    if collection_is_null:
        return None
    saw_unknown = False
    for result in results:
        if result is False:
            return False
        if result is None:
            saw_unknown = True
        elif result is not True:
            raise TypeError("Collection predicates must yield TRUE, FALSE or SQL NULL.")
    return None if saw_unknown else True
