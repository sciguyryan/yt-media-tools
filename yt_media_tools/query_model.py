"""Stable internal data model for parsed and resolved yt-sql queries.

The structures in this module deliberately retain the field names and equality
semantics established before the 0.27.x refactor. Parser, resolver, optimiser and
evaluator layers may share these types without depending on one another.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class QuerySyntaxError(ValueError):
    """Raised when a query cannot be parsed or semantically resolved."""

    def __init__(self, source: str, message: str, position: int = 0) -> None:
        super().__init__(message)
        self.source = source
        self.message = message
        self.position = max(0, min(position, len(source)))

    def format(self) -> str:
        line_start = self.source.rfind("\n", 0, self.position) + 1
        line_end = self.source.find("\n", self.position)
        if line_end < 0:
            line_end = len(self.source)
        line = self.source[line_start:line_end]
        column = self.position - line_start
        line_number = self.source.count("\n", 0, self.position) + 1
        return f"{self.message} (line {line_number}, column {column + 1})\n  {line}\n  {' ' * column}^"


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
class ScalarFunction:
    name: str
    args: tuple[Any, ...]
    position: int = 0
    kind: str | None = None


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

