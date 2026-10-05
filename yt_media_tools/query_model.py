"""Stable internal data model for parsed and resolved yt-sql queries.

The structures in this module deliberately retain the field names and equality
semantics established before the 0.27.x refactor. Parser, resolver, optimiser and
evaluator layers may share these types without depending on one another.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


@dataclass(frozen=True, slots=True)
class QuerySourceLocation:
    """One deterministic absolute and line/column location in query source."""

    position: int
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class QuerySourceSpan:
    """Half-open source span owned by yt-sql rather than a parser implementation."""

    start: QuerySourceLocation
    end: QuerySourceLocation

    @property
    def start_position(self) -> int:
        return self.start.position

    @property
    def end_position(self) -> int:
        return self.end.position


@dataclass(frozen=True, slots=True)
class QueryDiagnosticContext:
    """Parser-independent structured context for one yt-sql diagnostic."""

    category: str
    span: QuerySourceSpan
    expected: tuple[str, ...] = ()
    reason: str = "invalid"

    @property
    def location(self) -> QuerySourceLocation:
        """Compatibility alias for the primary failure location."""

        return self.span.start


def _source_location(source: str, position: int) -> QuerySourceLocation:
    bounded = max(0, min(position, len(source)))
    line_start = source.rfind("\n", 0, bounded) + 1
    return QuerySourceLocation(
        bounded,
        source.count("\n", 0, bounded) + 1,
        bounded - line_start + 1,
    )


class QuerySyntaxError(ValueError):
    """Raised when valid yt-sql tokens cannot form a legal grammatical structure."""

    diagnostic_category = "syntax"

    def __init__(
        self,
        source: str,
        message: str,
        position: int = 0,
        *,
        end_position: int | None = None,
        expected: tuple[str, ...] = (),
        category: str | None = None,
        reason: str = "invalid",
    ) -> None:
        super().__init__(message)
        self.source = source
        self.message = message
        self.position = max(0, min(position, len(source)))
        raw_end = self.position if end_position is None else end_position
        self.end_position = max(self.position, min(raw_end, len(source)))
        self.expected = tuple(dict.fromkeys(expected))
        self.span = QuerySourceSpan(
            _source_location(source, self.position),
            _source_location(source, self.end_position),
        )
        self.location = self.span.start
        self.reason = reason
        self.context = QueryDiagnosticContext(
            category or self.diagnostic_category,
            self.span,
            self.expected,
            reason,
        )

    def format(self) -> str:
        line_start = self.source.rfind("\n", 0, self.position) + 1
        line_end = self.source.find("\n", self.position)
        if line_end < 0:
            line_end = len(self.source)
        line = self.source[line_start:line_end]
        column = self.location.column - 1
        return f"{self.message} (line {self.location.line}, column {self.location.column})\n  {line}\n  {' ' * column}^"


class QueryLexicalError(QuerySyntaxError):
    """Raised when source text cannot be tokenised as valid yt-sql lexical input."""

    diagnostic_category = "lexical"


class QuerySemanticError(QuerySyntaxError):
    """Raised when parsed yt-sql is invalid in its semantic context."""

    diagnostic_category = "semantic"


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    position: int
    value: Any = None
    end_position: int | None = None

    @property
    def span(self) -> tuple[int, int]:
        """Return the token's half-open absolute source span."""

        return self.position, self.position + len(self.text) if self.end_position is None else self.end_position


@dataclass(frozen=True)
class Field:
    name: str
    position: int = 0
    kind: str | None = None


@dataclass(frozen=True)
class RelationWildcard:
    """Projection wildcard owned by one explicitly aliased relation."""

    qualifier: str
    position: int = 0


@dataclass(frozen=True)
class RelationField:
    """Field resolved to one relation in a multi-relation semantic scope."""

    qualifier: str
    name: str
    position: int = 0
    kind: str | None = None
    relation_key: tuple[str, str | None, str | None] | None = None


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
    """Collection produced by projecting each element through a scoped expression.

    ``evaluation_fusion_safe`` is resolver-owned execution metadata. It permits the
    evaluator to stream an immediately nested FILTER into MAP only after resolution
    has proved that doing so does not cross a RANDOM evaluation-order boundary.
    """

    collection: Any
    binding: str
    projection: Any
    position: int = 0
    kind: str | None = None
    resolved_type: Any | None = None
    evaluation_fusion_safe: bool = False


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
class TruthTest:
    """Total TRUE/FALSE inspection of a three-valued Boolean predicate."""

    operand: Any
    truth: str
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
    facet_expansion: bool = False
    grouped: bool = False


class JoinKind(str, Enum):
    """Parser-stable join kinds reserved by the yt-sql relational grammar."""

    INNER = "INNER"
    LEFT = "LEFT"
    SEMI = "SEMI"
    ANTI = "ANTI"


@dataclass(frozen=True)
class RelationReference:
    """One source/facet relation participating in relational composition."""

    source: str
    facet: str | None = None
    alias: str | None = None
    position: int = 0


@dataclass(frozen=True)
class JoinClause:
    """One parser-level JOIN edge whose executable semantics are resolved later."""

    kind: JoinKind
    relation: RelationReference
    predicate: Any
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
    from_alias: str | None = None
    joins: tuple[JoinClause, ...] = ()
    left_query: "Query | None" = None
