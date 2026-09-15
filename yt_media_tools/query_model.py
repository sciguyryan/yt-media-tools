"""Stable internal data model for parsed and resolved yt-sql queries.

The structures in this module deliberately retain the field names and equality
semantics established before the 0.27.x refactor. Parser, resolver, optimiser and
evaluator layers may share these types without depending on one another.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class QuerySourceLocation:
    """One deterministic source location for a query diagnostic."""

    position: int
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class QueryDiagnosticContext:
    """Structured context shared by syntax and semantic query diagnostics."""

    category: str
    location: QuerySourceLocation


class QuerySyntaxError(ValueError):
    """Raised when a query cannot be parsed or semantically resolved."""

    diagnostic_category = "syntax"

    def __init__(
        self,
        source: str,
        message: str,
        position: int = 0,
        *,
        category: str | None = None,
    ) -> None:
        super().__init__(message)
        self.source = source
        self.message = message
        self.position = max(0, min(position, len(source)))
        line_start = self.source.rfind("\n", 0, self.position) + 1
        self.location = QuerySourceLocation(
            self.position,
            self.source.count("\n", 0, self.position) + 1,
            self.position - line_start + 1,
        )
        self.context = QueryDiagnosticContext(category or self.diagnostic_category, self.location)

    def format(self) -> str:
        line_start = self.source.rfind("\n", 0, self.position) + 1
        line_end = self.source.find("\n", self.position)
        if line_end < 0:
            line_end = len(self.source)
        line = self.source[line_start:line_end]
        column = self.location.column - 1
        return f"{self.message} (line {self.location.line}, column {self.location.column})\n  {line}\n  {' ' * column}^"


class QuerySemanticError(QuerySyntaxError):
    """Raised when parsed yt-sql is invalid in its semantic context."""

    diagnostic_category = "semantic"


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    position: int
    value: Any = None


@dataclass(frozen=True)
class Field:
    name: str
    position: int = 0
    kind: str | None = None


@dataclass(frozen=True)
class Literal:
    value: Any
    raw: str
    position: int = 0
    quoted: bool = False


@dataclass(frozen=True)
class Unary:
    operator: str
    operand: Any


@dataclass(frozen=True)
class Binary:
    operator: str
    left: Any
    right: Any


@dataclass(frozen=True)
class Between:
    field: Field
    lower: Literal
    upper: Literal
    negated: bool = False


@dataclass(frozen=True)
class InList:
    field: Field
    values: tuple[Literal, ...]
    negated: bool = False


@dataclass(frozen=True)
class IsNull:
    field: Field
    negated: bool = False


@dataclass(frozen=True)
class TextPredicate:
    operator: str
    field: Field
    value: Literal
    negated: bool = False


@dataclass(frozen=True)
class CollectionElementReference:
    """Reference to a lexically bound collection element.

    ``scope_distance`` is zero for the innermost matching binding and increases
    by one for each enclosing collection predicate scope. The original binding
    name is retained for canonical formatting and diagnostics. Resolved element
    references retain their complete yt-sql type so postfix member/index
    operations can compose without consulting row-field schema.
    """

    binding: str
    scope_distance: int = 0
    position: int = 0
    kind: str | None = None
    resolved_type: Any | None = None


@dataclass(frozen=True)
class CollectionPredicate:
    """Syntax-level existential or universal predicate over collection elements."""

    quantifier: str
    collection: Any
    binding: str
    predicate: Any
    position: int = 0


@dataclass(frozen=True)
class CollectionCount:
    """Scalar count of collection elements whose scoped predicate is TRUE."""

    collection: Any
    binding: str
    predicate: Any
    position: int = 0
    kind: str | None = None
    resolved_type: Any | None = None


@dataclass(frozen=True)
class CollectionFilter:
    """Collection containing elements whose scoped predicate is TRUE."""

    collection: Any
    binding: str
    predicate: Any
    position: int = 0
    kind: str | None = None
    resolved_type: Any | None = None


@dataclass(frozen=True)
class CollectionProjection:
    """Collection produced by projecting each element through a scoped expression."""

    collection: Any
    binding: str
    projection: Any
    position: int = 0
    kind: str | None = None
    resolved_type: Any | None = None


@dataclass(frozen=True)
class ScalarIndex:
    """Postfix positional indexing of a collection-valued scalar expression."""

    collection: Any
    index: Any
    position: int = 0
    kind: str | None = None
    resolved_type: Any | None = None


@dataclass(frozen=True)
class ScalarMember:
    """Postfix member access over a structured-valued scalar expression."""

    value: Any
    member: str
    position: int = 0
    kind: str | None = None
    resolved_type: Any | None = None


@dataclass(frozen=True)
class ScalarFunction:
    name: str
    args: tuple[Any, ...]
    position: int = 0
    kind: str | None = None
    resolved_type: Any | None = None


@dataclass(frozen=True)
class AggregateFunction:
    """One SQL aggregate evaluated over the current group."""

    name: str
    args: tuple[Any, ...] = ()
    count_star: bool = False
    filter_predicate: Any | None = None
    position: int = 0
    kind: str | None = None


@dataclass(frozen=True)
class ScalarComparison:
    """Comparison between scalar expressions, used by aggregate HAVING."""

    operator: str
    left: Any
    right: Any


@dataclass(frozen=True)
class ScalarIsNull:
    """NULL test over a scalar expression, used by aggregate HAVING."""

    expression: Any
    negated: bool = False


@dataclass(frozen=True)
class ScalarUnary:
    operator: str
    operand: Any
    position: int = 0
    kind: str | None = None


@dataclass(frozen=True)
class ScalarBinary:
    operator: str
    left: Any
    right: Any
    position: int = 0
    kind: str | None = None


@dataclass(frozen=True)
class CaseWhen:
    condition: Any
    result: Any
    position: int = 0


@dataclass(frozen=True)
class ScalarCase:
    whens: tuple[CaseWhen, ...]
    else_result: Any | None = None
    position: int = 0
    kind: str | None = None


@dataclass(frozen=True)
class OrderTerm:
    field: str
    descending: bool = False
    position: int = 0
    kind: str | None = None
    expression: Any | None = None


@dataclass(frozen=True)
class SelectTerm:
    field: str
    alias: str | None = None
    position: int = 0
    kind: str | None = None
    expression: Any | None = None

    @property
    def output_name(self) -> str:
        return self.alias or self.field


@dataclass(frozen=True)
class CommonTableExpression:
    """One non-recursive common table expression."""

    name: str
    query: "Query"
    position: int = 0


@dataclass(frozen=True)
class SetOperation:
    """One positional UNION or UNION ALL branch."""

    query: "Query"
    all: bool = False
    position: int = 0


@dataclass(frozen=True)
class Query:
    predicate: Any | None = None
    order_by: tuple[OrderTerm, ...] = ()
    limit: int | None = None
    source: str = ""
    select: tuple[SelectTerm, ...] = ()
    from_source: str | None = None
    distinct: bool = False
    offset: int = 0
    group_by: tuple[Any, ...] = ()
    having: Any | None = None
    ctes: tuple[CommonTableExpression, ...] = ()
    set_operations: tuple[SetOperation, ...] = ()
    from_facet: str | None = None
