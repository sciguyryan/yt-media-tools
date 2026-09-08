"""Shared yt-sql query language for yt-dlp metadata records."""

from __future__ import annotations

import difflib
import hashlib
import json
import random
import re
from functools import lru_cache
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Any, Sequence

from .dates import (
    DateContext,
    parse_date_literal,
    parse_datetime_literal,
    parse_temporal_infinity,
    timestamp_to_datetime,
)
from .schema import FieldInfo, QuerySchema, raw_path_value
from .units import load_default_unit_registry


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


_TOKEN_RE = re.compile(
    r"""
    (?P<SPACE>\s+)
  | (?P<INFINITY>-?INFINITY\(\))
  | (?P<OP><=|>=|!=|<>|=|<|>)
  | (?P<LPAREN>\()
  | (?P<ATIDENT>@[A-Za-z0-9_.-]+)
  | (?P<RPAREN>\))
  | (?P<STRING>'(?:''|\\.|[^'\\])*'|\"(?:\"\"|\\.|[^\"\\])*\")
  | (?P<TEMPORAL>(?:TODAY|NOW)\(\)(?:\s*[+-]\s*\d+(?:\.\d+)?\s*[^\W\d_]+(?:-[^\W\d_]+)*)?)
  | (?P<DATETIME>\d{4}-\d{1,2}-\d{1,2}T\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)
  | (?P<DATE>\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{4})
  | (?P<TIME>\d{1,3}:\d{1,2}(?::\d{1,2})?)
  | (?P<NUMBER>(?:0[xX][0-9A-Za-z_]*|0[oO][0-9A-Za-z_]*|0[bB][0-9A-Za-z_]*|\d[\d_]*(?:\.\d[\d_]*)?(?:[kKmMbB])?))
  | (?P<IDENT>[^\W\d][\w-]*(?:\.[^\W\d][\w-]*)*)
  | (?P<COMMA>,)
  | (?P<STAR>\*)
  | (?P<PLUS>\+)
  | (?P<MINUS>-)
  | (?P<SLASH>/)
  | (?P<PERCENT>%)
  | (?P<MISMATCH>.)
    """,
    re.VERBOSE,
)

_DURATION_PART_RE = re.compile(
    r"(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>[^\W\d_]+(?:-[^\W\d_]+)*)",
    re.IGNORECASE,
)


def _unescape_string(text: str) -> str:
    quote = text[0]
    body = text[1:-1]
    body = body.replace(quote * 2, quote)
    body = body.replace("\\\\", "\\")
    body = body.replace(f"\\{quote}", quote)
    body = body.replace("\\n", "\n").replace("\\t", "\t")
    return body


def tokenise(source: str) -> list[Token]:
    tokens: list[Token] = []
    position = 0
    while position < len(source):
        match = _TOKEN_RE.match(source, position)
        if match is None:
            raise QuerySyntaxError(source, "Could not tokenise query.", position)
        kind = match.lastgroup or ""
        text = match.group(0)
        if kind == "SPACE":
            position = match.end()
            continue
        if kind == "MISMATCH":
            raise QuerySyntaxError(source, f"Unexpected character {text!r}.", position)
        value: Any = _unescape_string(text) if kind == "STRING" else text
        tokens.append(Token(kind, text, position, value))
        position = match.end()
    tokens.append(Token("EOF", "", len(source), None))
    return tokens


class Parser:
    """Recursive-descent parser. It deliberately knows no yt-dlp field schema."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.tokens = tokenise(source)
        self.index = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def advance(self) -> Token:
        token = self.current
        if token.kind != "EOF":
            self.index += 1
        return token

    def keyword(self, word: str) -> bool:
        return self.current.kind == "IDENT" and self.current.text.upper() == word

    def consume_keyword(self, word: str) -> Token | None:
        if self.keyword(word):
            return self.advance()
        return None

    def expect_keyword(self, word: str, message: str | None = None) -> Token:
        token = self.consume_keyword(word)
        if token is None:
            raise QuerySyntaxError(self.source, message or f"Expected {word}.", self.current.position)
        return token

    def expect(self, kind: str, message: str) -> Token:
        if self.current.kind != kind:
            raise QuerySyntaxError(self.source, message, self.current.position)
        return self.advance()

    def parse_query(
        self,
        where_only: bool = False,
        *,
        stop_at_rparen: bool = False,
        allow_with: bool = True,
        set_branch: bool = False,
    ) -> Query:
        predicate = None
        order_by: tuple[OrderTerm, ...] = ()
        limit = None
        select: tuple[SelectTerm, ...] = ()
        from_source: str | None = None
        from_facet: str | None = None
        distinct = False
        offset = 0
        group_by: tuple[Any, ...] = ()
        having = None
        ctes: list[CommonTableExpression] = []
        set_operations: list[SetOperation] = []

        def at_end() -> bool:
            return self.current.kind == "EOF" or (stop_at_rparen and self.current.kind == "RPAREN")

        if not where_only and not allow_with and self.keyword("WITH"):
            raise QuerySyntaxError(self.source, "Nested WITH clauses are not supported.", self.current.position)

        if not where_only and allow_with and self.consume_keyword("WITH"):
            if self.consume_keyword("RECURSIVE"):
                raise QuerySyntaxError(
                    self.source,
                    "Recursive CTEs are not supported.",
                    self.current.position,
                )
            seen_names: set[str] = set()
            while True:
                name_token = self.expect("IDENT", "Expected a CTE name after WITH.")
                key = name_token.text.casefold()
                if key in seen_names:
                    raise QuerySyntaxError(self.source, f"Duplicate CTE name {name_token.text!r}.", name_token.position)
                seen_names.add(key)
                self.expect_keyword("AS", "Expected AS after CTE name.")
                self.expect("LPAREN", "Expected '(' before CTE query.")
                subquery = self.parse_query(stop_at_rparen=True, allow_with=False)
                self.expect("RPAREN", "Expected ')' after CTE query.")
                ctes.append(CommonTableExpression(name_token.text, subquery, name_token.position))
                if self.current.kind != "COMMA":
                    break
                self.advance()

        if where_only:
            if not at_end():
                predicate = self.parse_or()
        else:
            if self.consume_keyword("SELECT"):
                distinct = bool(self.consume_keyword("DISTINCT"))
                select = self.parse_select_list()

            if self.consume_keyword("FROM"):
                from_source = self.parse_from_source()
                if self.consume_keyword("OF"):
                    facet = self.current
                    if facet.kind != "IDENT":
                        raise QuerySyntaxError(self.source, "OF requires a collection/facet name.", facet.position)
                    from_facet = facet.text.casefold()
                    self.advance()

            if self.consume_keyword("WHERE"):
                if (
                    at_end()
                    or self.keyword("GROUP")
                    or self.keyword("HAVING")
                    or self.keyword("UNION")
                    or self.keyword("ORDER")
                    or self.keyword("LIMIT")
                    or self.keyword("OFFSET")
                ):
                    raise QuerySyntaxError(self.source, "WHERE requires an expression.", self.current.position)
                predicate = self.parse_or()
            elif (
                not self.keyword("GROUP")
                and not self.keyword("HAVING")
                and not self.keyword("UNION")
                and not self.keyword("ORDER")
                and not self.keyword("LIMIT")
                and not self.keyword("OFFSET")
                and not at_end()
            ):
                if select or from_source is not None:
                    raise QuerySyntaxError(
                        self.source,
                        "Expected WHERE, GROUP BY, HAVING, ORDER BY, LIMIT, OFFSET, or end of query.",
                        self.current.position,
                    )
                predicate = self.parse_or()

        if self.consume_keyword("GROUP"):
            self.expect_keyword("BY", "Expected BY after GROUP.")
            group_by = self.parse_group_by()

        if self.consume_keyword("HAVING"):
            if not group_by and not select:
                raise QuerySyntaxError(
                    self.source, "HAVING requires an aggregate SELECT or GROUP BY.", self.current.position
                )
            having = self.parse_having_or()

        if (
            not where_only
            and set_branch
            and (
                at_end()
                or self.keyword("UNION")
                or self.keyword("ORDER")
                or self.keyword("LIMIT")
                or self.keyword("OFFSET")
            )
        ):
            return Query(
                predicate,
                order_by,
                limit,
                self.source,
                select,
                from_source,
                distinct,
                offset,
                group_by,
                having,
                tuple(ctes),
                (),
                from_facet,
            )

        if not where_only and not set_branch:
            while self.consume_keyword("UNION"):
                union_position = self.tokens[self.index - 1].position
                union_all = bool(self.consume_keyword("ALL"))
                branch = self.parse_query(
                    stop_at_rparen=stop_at_rparen,
                    allow_with=False,
                    set_branch=True,
                )
                if not branch.select:
                    raise QuerySyntaxError(self.source, "UNION requires a SELECT query on both sides.", union_position)
                set_operations.append(SetOperation(branch, union_all, union_position))

        if self.consume_keyword("ORDER"):
            self.expect_keyword("BY", "Expected BY after ORDER.")
            order_by = self.parse_order_by()

        if self.consume_keyword("LIMIT"):
            token = self.current
            if token.kind != "NUMBER" or not re.fullmatch(r"\d[\d_]*", token.text):
                raise QuerySyntaxError(self.source, "LIMIT requires a positive integer.", token.position)
            limit = int(token.text.replace("_", ""))
            if limit <= 0:
                raise QuerySyntaxError(self.source, "LIMIT must be greater than zero.", token.position)
            self.advance()

        if self.consume_keyword("OFFSET"):
            token = self.current
            if token.kind == "MINUS":
                raise QuerySyntaxError(self.source, "OFFSET requires a non-negative integer.", token.position)
            if token.kind != "NUMBER" or not re.fullmatch(r"\d[\d_]*", token.text):
                raise QuerySyntaxError(self.source, "OFFSET requires a non-negative integer.", token.position)
            offset = int(token.text.replace("_", ""))
            self.advance()

        if not at_end():
            raise QuerySyntaxError(self.source, f"Unexpected token {self.current.text!r}.", self.current.position)
        return Query(
            predicate,
            order_by,
            limit,
            self.source,
            select,
            from_source,
            distinct,
            offset,
            group_by,
            having,
            tuple(ctes),
            tuple(set_operations),
            from_facet,
        )

    def parse_select_list(self) -> tuple[SelectTerm, ...]:
        terms: list[SelectTerm] = []
        while True:
            if self.current.kind == "STAR":
                star = self.advance()
                if terms or self.current.kind == "COMMA":
                    raise QuerySyntaxError(
                        self.source,
                        "SELECT * must be used by itself; it cannot be mixed with explicit projections.",
                        star.position,
                    )
                return (SelectTerm("*", position=star.position),)
            position = self.current.position
            expression = self.parse_scalar_expression()
            field_text = format_scalar_expression(expression)
            alias = None
            if self.consume_keyword("AS"):
                alias_token = self.expect("IDENT", "Expected an alias name after AS.")
                alias = alias_token.text
            terms.append(SelectTerm(field_text, alias, position, expression=expression))
            if self.current.kind != "COMMA":
                break
            self.advance()
        return tuple(terms)

    def parse_scalar_expression(self) -> Any:
        """Parse a scalar expression using SQL-like arithmetic precedence."""
        return self.parse_scalar_additive()

    def parse_scalar_additive(self) -> Any:
        node = self.parse_scalar_multiplicative()
        while self.current.kind in {"PLUS", "MINUS"}:
            token = self.advance()
            node = ScalarBinary(token.text, node, self.parse_scalar_multiplicative(), token.position)
        return node

    def parse_scalar_multiplicative(self) -> Any:
        node = self.parse_scalar_unary()
        while self.current.kind in {"STAR", "SLASH", "PERCENT"}:
            token = self.advance()
            node = ScalarBinary(token.text, node, self.parse_scalar_unary(), token.position)
        return node

    def parse_scalar_unary(self) -> Any:
        if self.current.kind in {"PLUS", "MINUS"}:
            token = self.advance()
            return ScalarUnary(token.text, self.parse_scalar_unary(), token.position)
        return self.parse_scalar_atom()

    def parse_scalar_atom(self) -> Any:
        token = self.current
        if self.keyword("CASE"):
            return self.parse_scalar_case()
        if token.kind == "LPAREN":
            self.advance()
            node = self.parse_scalar_expression()
            self.expect("RPAREN", "Expected ')' to close the scalar expression.")
            return node
        if token.kind == "IDENT":
            self.advance()
            if self.current.kind == "LPAREN":
                return self.parse_scalar_function(token)
            lowered = token.text.casefold()
            if lowered == "null":
                return Literal(None, token.text, token.position)
            if lowered == "true":
                return Literal(True, token.text, token.position)
            if lowered == "false":
                return Literal(False, token.text, token.position)
            return Field(token.text, token.position)
        if token.kind == "STRING":
            self.advance()
            return Literal(token.value, token.text, token.position, True)
        if token.kind == "NUMBER":
            self.advance()
            return Literal(
                _parse_generic_numeric_literal(token.text, self.source, token.position),
                token.text,
                token.position,
                False,
            )
        raise QuerySyntaxError(
            self.source, "Expected a scalar field, literal, function, or parenthesised expression.", token.position
        )

    def parse_scalar_case(self) -> ScalarCase:
        """Parse a searched CASE expression. Simple CASE is intentionally unsupported."""
        case_token = self.expect_keyword("CASE")
        if not self.keyword("WHEN"):
            if self.current.kind == "EOF":
                raise QuerySyntaxError(self.source, "CASE requires at least one WHEN clause.", case_token.position)
            raise QuerySyntaxError(
                self.source,
                "Only searched CASE is supported; write CASE WHEN <condition> THEN <value> ... END.",
                self.current.position,
            )

        whens: list[CaseWhen] = []
        while self.consume_keyword("WHEN"):
            when_position = self.tokens[self.index - 1].position
            if self.keyword("THEN") or self.keyword("WHEN") or self.keyword("ELSE") or self.keyword("END"):
                raise QuerySyntaxError(
                    self.source, "CASE WHEN requires a condition before THEN.", self.current.position
                )
            condition = self.parse_or()
            self.expect_keyword("THEN", "Expected THEN after CASE WHEN condition.")
            if self.keyword("WHEN") or self.keyword("ELSE") or self.keyword("END") or self.current.kind == "EOF":
                raise QuerySyntaxError(
                    self.source, "CASE THEN requires a scalar result expression.", self.current.position
                )
            result = self.parse_scalar_expression()
            whens.append(CaseWhen(condition, result, when_position))

        else_result = None
        if self.consume_keyword("ELSE"):
            if self.keyword("END") or self.current.kind == "EOF":
                raise QuerySyntaxError(
                    self.source, "CASE ELSE requires a scalar result expression.", self.current.position
                )
            else_result = self.parse_scalar_expression()

        self.expect_keyword("END", "Expected END to close CASE expression.")
        return ScalarCase(tuple(whens), else_result, case_token.position)

    def parse_scalar_function(self, name_token: Token) -> Any:
        name = name_token.text.upper()
        aggregate_names = {"COUNT", "SUM", "MIN", "MAX", "AVG"}
        scalar_names = {"LOWER", "UPPER", "LENGTH", "COALESCE", "CHAR", "NULLIF", "GREATEST", "LEAST", "RANDOM"}
        if name not in scalar_names | aggregate_names:
            raise QuerySyntaxError(
                self.source, f"Unsupported scalar function {name_token.text!r}.", name_token.position
            )
        self.expect("LPAREN", "Expected '(' after function name.")
        if name in aggregate_names:
            count_star = False
            args: list[Any] = []
            if name == "COUNT" and self.current.kind == "STAR":
                self.advance()
                count_star = True
            elif self.current.kind != "RPAREN":
                args.append(self.parse_scalar_expression())
                if self.current.kind == "COMMA":
                    raise QuerySyntaxError(self.source, f"{name} requires exactly one argument.", self.current.position)
            self.expect("RPAREN", "Expected ')' after aggregate arguments.")
            if name == "COUNT":
                if not count_star and len(args) != 1:
                    raise QuerySyntaxError(
                        self.source, "COUNT requires * or exactly one argument.", name_token.position
                    )
            elif len(args) != 1:
                raise QuerySyntaxError(self.source, f"{name} requires exactly one argument.", name_token.position)
            filter_predicate = None
            if self.consume_keyword("FILTER"):
                self.expect("LPAREN", "Expected '(' after FILTER.")
                self.expect_keyword("WHERE", "Expected WHERE inside aggregate FILTER.")
                filter_predicate = self.parse_or()
                self.expect("RPAREN", "Expected ')' after aggregate FILTER predicate.")
            return AggregateFunction(name, tuple(args), count_star, filter_predicate, name_token.position)
        args: list[Any] = []
        if self.current.kind != "RPAREN":
            while True:
                args.append(self.parse_scalar_expression())
                if self.current.kind != "COMMA":
                    break
                self.advance()
        self.expect("RPAREN", "Expected ')' after function arguments.")
        if name in {"LOWER", "UPPER", "LENGTH"} and len(args) != 1:
            raise QuerySyntaxError(self.source, f"{name} requires exactly one argument.", name_token.position)
        if name == "COALESCE" and len(args) < 2:
            raise QuerySyntaxError(self.source, "COALESCE requires at least two arguments.", name_token.position)
        if name == "CHAR" and not args:
            raise QuerySyntaxError(self.source, "CHAR requires at least one argument.", name_token.position)
        if name == "NULLIF" and len(args) != 2:
            raise QuerySyntaxError(self.source, "NULLIF requires exactly two arguments.", name_token.position)
        if name in {"GREATEST", "LEAST"} and len(args) < 2:
            raise QuerySyntaxError(self.source, f"{name} requires at least two arguments.", name_token.position)
        if name == "RANDOM" and len(args) > 1:
            raise QuerySyntaxError(self.source, "RANDOM accepts zero or one seed argument.", name_token.position)
        return ScalarFunction(name, tuple(args), name_token.position)

    def parse_from_source(self) -> str:
        token = self.current
        if token.kind == "ATIDENT":
            self.advance()
            return token.text
        if token.kind == "IDENT":
            self.advance()
            return token.text
        if token.kind == "STRING":
            self.advance()
            return str(token.value)
        raise QuerySyntaxError(
            self.source,
            "Expected a channel/playlist identifier after FROM. Quote full URLs.",
            token.position,
        )

    def parse_group_by(self) -> tuple[Any, ...]:
        """Parse the deterministic scalar expressions that define aggregate groups."""
        terms: list[Any] = []
        while True:
            terms.append(self.parse_scalar_expression())
            if self.current.kind != "COMMA":
                break
            self.advance()
        if not terms:
            raise QuerySyntaxError(self.source, "GROUP BY requires at least one expression.", self.current.position)
        return tuple(terms)

    def parse_having_or(self) -> Any:
        node = self.parse_having_and()
        while self.consume_keyword("OR"):
            node = Binary("OR", node, self.parse_having_and())
        return node

    def parse_having_and(self) -> Any:
        node = self.parse_having_not()
        while self.consume_keyword("AND"):
            node = Binary("AND", node, self.parse_having_not())
        return node

    def parse_having_not(self) -> Any:
        if self.consume_keyword("NOT"):
            return Unary("NOT", self.parse_having_not())
        if self.current.kind == "LPAREN":
            # A leading parenthesis can wrap either a scalar expression on the
            # left of a comparison or a Boolean HAVING subtree. Try the scalar
            # interpretation first, then restore the parser position and fall
            # back to Boolean grouping if the comparison form does not parse.
            start = self.index
            try:
                return self.parse_having_predicate()
            except QuerySyntaxError:
                self.index = start
                self.advance()
                node = self.parse_having_or()
                self.expect("RPAREN", "Expected ')' to close HAVING expression.")
                return node
        return self.parse_having_predicate()

    def parse_having_predicate(self) -> Any:
        """Parse aggregate-aware HAVING comparisons without changing WHERE grammar."""
        left = self.parse_scalar_expression()
        if self.consume_keyword("IS"):
            negated = bool(self.consume_keyword("NOT"))
            self.expect_keyword("NULL", "Expected NULL after IS in HAVING.")
            return ScalarIsNull(left, negated)
        if self.current.kind != "OP":
            raise QuerySyntaxError(
                self.source, "HAVING requires a comparison operator or IS NULL.", self.current.position
            )
        operator = self.advance().text
        if operator == "<>":
            operator = "!="
        right = self.parse_scalar_expression()
        return ScalarComparison(operator, left, right)

    def parse_order_by(self) -> tuple[OrderTerm, ...]:
        terms: list[OrderTerm] = []
        while True:
            position = self.current.position
            expression = self.parse_scalar_expression()
            descending = False
            if self.consume_keyword("ASC"):
                descending = False
            elif self.consume_keyword("DESC"):
                descending = True
            terms.append(OrderTerm(format_scalar_expression(expression), descending, position, expression=expression))
            if self.current.kind != "COMMA":
                break
            self.advance()
        return tuple(terms)

    def parse_or(self) -> Any:
        node = self.parse_and()
        while self.consume_keyword("OR"):
            node = Binary("OR", node, self.parse_and())
        return node

    def parse_and(self) -> Any:
        node = self.parse_not()
        while self.consume_keyword("AND"):
            node = Binary("AND", node, self.parse_not())
        return node

    def parse_not(self) -> Any:
        if self.consume_keyword("NOT"):
            return Unary("NOT", self.parse_not())
        return self.parse_primary()

    def parse_primary(self) -> Any:
        if self.current.kind == "LPAREN":
            self.advance()
            node = self.parse_or()
            self.expect("RPAREN", "Expected ')' to close the expression.")
            return node
        return self.parse_predicate()

    def parse_predicate(self) -> Any:
        field_token = self.expect("IDENT", "Expected a field name.")
        field = Field(field_token.text, field_token.position)

        negated = bool(self.consume_keyword("NOT"))

        if self.consume_keyword("BETWEEN"):
            lower = self.parse_literal(stop_keywords={"AND"})
            self.expect_keyword(
                "AND",
                "Expected AND after the lower bound of BETWEEN.",
            )
            upper = self.parse_literal(
                stop_keywords={"AND", "OR", "UNION", "ORDER", "LIMIT", "OFFSET", "THEN", "WHEN", "ELSE", "END"}
            )
            return Between(field, lower, upper, negated)

        if self.consume_keyword("IN"):
            self.expect("LPAREN", "Expected '(' after IN.")
            values: list[Literal] = []
            if self.current.kind == "RPAREN":
                raise QuerySyntaxError(self.source, "IN requires at least one value.", self.current.position)
            while True:
                values.append(self.parse_literal(stop_kinds={"COMMA", "RPAREN"}, stop_keywords=set()))
                if self.current.kind != "COMMA":
                    break
                self.advance()
            self.expect("RPAREN", "Expected ')' after IN values.")
            return InList(field, tuple(values), negated)

        if self.consume_keyword("IS"):
            if self.consume_keyword("NOT"):
                negated = not negated
            if self.consume_keyword("NULL"):
                return IsNull(field, negated)
            if self.consume_keyword("TRUE"):
                node = Binary("=", field, Literal(True, "TRUE", self.current.position))
                return Unary("NOT", node) if negated else node
            if self.consume_keyword("FALSE"):
                node = Binary("=", field, Literal(False, "FALSE", self.current.position))
                return Unary("NOT", node) if negated else node
            raise QuerySyntaxError(self.source, "Expected NULL, TRUE, or FALSE after IS.", self.current.position)

        if self.consume_keyword("DOES"):
            self.expect_keyword("NOT", "Expected NOT after DOES.")
            if self.consume_keyword("CONTAIN") or self.consume_keyword("CONTAINS"):
                return TextPredicate("CONTAINS", field, self.parse_text_literal(), True)
            if self.consume_keyword("MATCH") or self.consume_keyword("MATCHES"):
                return TextPredicate("MATCHES", field, self.parse_regex_literal(), True)
            if self.consume_keyword("ILIKE"):
                return TextPredicate("ILIKE", field, self.parse_like_literal(), True)
            if self.consume_keyword("LIKE"):
                return TextPredicate("LIKE", field, self.parse_like_literal(), True)
            raise QuerySyntaxError(
                self.source, "Expected CONTAIN, MATCH, LIKE, or ILIKE after DOES NOT.", self.current.position
            )

        if self.consume_keyword("CONTAINS") or self.consume_keyword("CONTAIN"):
            return TextPredicate("CONTAINS", field, self.parse_text_literal(), negated)
        if self.consume_keyword("MATCHES") or self.consume_keyword("MATCH"):
            return TextPredicate("MATCHES", field, self.parse_regex_literal(), negated)
        if self.consume_keyword("ILIKE"):
            return TextPredicate("ILIKE", field, self.parse_like_literal(), negated)
        if self.consume_keyword("LIKE"):
            return TextPredicate("LIKE", field, self.parse_like_literal(), negated)

        if negated:
            if self._at_expression_boundary():
                return Unary("NOT", Binary("=", field, Literal(True, "TRUE", field.position)))
            raise QuerySyntaxError(
                self.source,
                "NOT must be followed by BETWEEN, IN, CONTAINS, MATCHES, LIKE, ILIKE, IS, or used with a Boolean field.",
                self.current.position,
            )

        natural_operator = self.parse_natural_operator()
        if natural_operator is not None:
            return Binary(natural_operator, field, self.parse_literal())

        if self.current.kind == "OP":
            operator = self.advance().text
            if operator == "<>":
                operator = "!="
            return Binary(operator, field, self.parse_literal())

        if self._at_expression_boundary():
            return Binary("=", field, Literal(True, "TRUE", field.position))

        raise QuerySyntaxError(
            self.source,
            "Expected a comparison operator, BETWEEN, IN, IS NULL, CONTAINS, MATCHES, LIKE, or ILIKE.",
            self.current.position,
        )

    def parse_natural_operator(self) -> str | None:
        start = self.index
        phrases = (
            (("AT", "LEAST"), ">="),
            (("AT", "MOST"), "<="),
            (("GREATER", "THAN"), ">"),
            (("MORE", "THAN"), ">"),
            (("LESS", "THAN"), "<"),
            (("EQUAL", "TO"), "="),
            (("OVER",), ">"),
            (("ABOVE",), ">"),
            (("UNDER",), "<"),
            (("BELOW",), "<"),
            (("EQUALS",), "="),
        )
        for words, operator in phrases:
            self.index = start
            if all(self.consume_keyword(word) for word in words):
                return operator
        self.index = start
        return None

    def parse_text_literal(self) -> Literal:
        token = self.current
        if token.kind == "STRING":
            self.advance()
            return Literal(token.value, token.text, token.position, True)
        if token.kind in {"IDENT", "NUMBER", "DATE", "DATETIME", "TIME", "TEMPORAL"}:
            self.advance()
            return Literal(token.text, token.text, token.position, False)
        raise QuerySyntaxError(self.source, "Expected a text value.", token.position)

    def parse_like_literal(self) -> Literal:
        """Parse a quoted SQL-like pattern without consuming LIKE escapes.

        Ordinary string literals interpret a small set of backslash escapes at
        tokenisation time. LIKE needs the backslashes themselves because they
        are part of the pattern language, so reconstruct the pattern from the
        token text and only collapse doubled SQL quote characters here.
        """
        token = self.current
        if token.kind != "STRING":
            raise QuerySyntaxError(self.source, "LIKE requires a quoted text pattern.", token.position)
        self.advance()
        quote = token.text[0]
        value = token.text[1:-1].replace(quote * 2, quote)
        literal = Literal(value, token.text, token.position, True)
        _validate_like_pattern(value, self.source, token.position)
        return literal

    def parse_regex_literal(self) -> Literal:
        literal = self.parse_text_literal()
        try:
            re.compile(str(literal.value))
        except re.error as exc:
            raise QuerySyntaxError(
                self.source,
                f"Invalid regular expression: {exc.msg}.",
                literal.position,
            ) from exc
        return literal

    def parse_literal(
        self,
        *,
        stop_keywords: set[str] | None = None,
        stop_kinds: set[str] | None = None,
    ) -> Literal:
        stop_keywords = (
            {"AND", "OR", "UNION", "ORDER", "LIMIT", "OFFSET", "THEN", "WHEN", "ELSE", "END"}
            if stop_keywords is None
            else stop_keywords
        )
        stop_kinds = {"RPAREN", "COMMA", "EOF"} if stop_kinds is None else stop_kinds | {"EOF"}
        token = self.current
        if token.kind == "STRING":
            self.advance()
            return Literal(token.value, token.text, token.position, True)

        parts: list[Token] = []
        while self.current.kind not in stop_kinds:
            if self.current.kind == "IDENT" and self.current.text.upper() in stop_keywords:
                break
            if self.current.kind in {"LPAREN", "OP"}:
                break
            parts.append(self.advance())
        if not parts:
            raise QuerySyntaxError(self.source, "Expected a value.", token.position)

        raw = " ".join(part.text for part in parts)
        if len(parts) == 1:
            raw = parts[0].text
        lowered = raw.casefold()
        if lowered == "null":
            return Literal(None, raw, parts[0].position)
        if lowered == "true":
            return Literal(True, raw, parts[0].position)
        if lowered == "false":
            return Literal(False, raw, parts[0].position)
        return Literal(raw, raw, parts[0].position, False)

    def _at_expression_boundary(self) -> bool:
        return (
            self.current.kind in {"EOF", "RPAREN"}
            or self.keyword("AND")
            or self.keyword("OR")
            or self.keyword("ORDER")
            or self.keyword("LIMIT")
            or self.keyword("OFFSET")
            or self.keyword("THEN")
            or self.keyword("WHEN")
            or self.keyword("ELSE")
            or self.keyword("END")
        )


def parse_query(source: str) -> Query:
    return Parser(source).parse_query(where_only=False)


def parse_where(source: str) -> Query:
    return Parser(source).parse_query(where_only=True)


def _parse_duration_text(text: str, source: str, position: int) -> int:
    value = " ".join(text.strip().split())
    if re.fullmatch(r"\d+(?::\d{1,2}){1,2}", value):
        parts = [int(part) for part in value.split(":")]
        if len(parts) == 2:
            minutes, seconds = parts
            if seconds >= 60:
                raise QuerySyntaxError(source, "Duration seconds must be below 60.", position)
            return minutes * 60 + seconds
        hours, minutes, seconds = parts
        if minutes >= 60 or seconds >= 60:
            raise QuerySyntaxError(source, "Duration minutes and seconds must be below 60.", position)
        return hours * 3600 + minutes * 60 + seconds

    if re.fullmatch(r"\d+(?:\.\d+)?", value):
        raise QuerySyntaxError(
            source,
            "A duration needs a unit, for example 30s, 10m, 2h, or 1h30m.",
            position,
        )

    compact = value.replace(" ", "")
    if re.fullmatch(r"(?:\d+(?:\.\d+)?(?:h|m|s))+", compact, re.IGNORECASE):
        value = compact

    total = 0.0
    cursor = 0
    matched = False
    registry = load_default_unit_registry()
    for match in _DURATION_PART_RE.finditer(value):
        if value[cursor : match.start()].strip():
            raise QuerySyntaxError(source, f"Could not understand duration {text!r}.", position + cursor)
        try:
            unit = registry.resolve(match.group("unit"))
        except ValueError as exc:
            raise QuerySyntaxError(
                source,
                f"Unknown duration unit {match.group('unit')!r}.",
                position + match.start("unit"),
            ) from exc
        if unit.kind != "fixed":
            raise QuerySyntaxError(
                source,
                f"Calendar unit {match.group('unit')!r} cannot be used for a duration.",
                position + match.start("unit"),
            )
        matched = True
        total += float(match.group("number")) * unit.amount
        cursor = match.end()
    if not matched or value[cursor:].strip():
        raise QuerySyntaxError(source, f"Could not understand duration {text!r}.", position + cursor)
    return round(total)


_DECIMAL_INTEGER_RE = re.compile(r"[+-]?\d+(?:_\d+)*")
_DECIMAL_NUMBER_RE = re.compile(r"[+-]?\d+(?:_\d+)*(?:\.(?:\d+(?:_\d+)*))?")
_BASE_INTEGER_RE = re.compile(r"(?P<sign>[+-]?)(?P<prefix>0[xX]|0[oO]|0[bB])(?P<digits>[0-9A-Za-z]+(?:_[0-9A-Za-z]+)*)")


def _parse_integer_literal_text(text: str, source: str, position: int) -> int:
    """Parse a decimal, hexadecimal, octal or binary integer literal."""
    compact = re.sub(r"\s+", "", text)
    if _DECIMAL_INTEGER_RE.fullmatch(compact):
        return int(compact.replace("_", ""), 10)

    match = _BASE_INTEGER_RE.fullmatch(compact)
    if match:
        prefix = match.group("prefix").casefold()
        base = {"0x": 16, "0o": 8, "0b": 2}[prefix]
        digits = match.group("digits").replace("_", "")
        valid_digits = {
            16: r"[0-9a-fA-F]+",
            8: r"[0-7]+",
            2: r"[01]+",
        }[base]
        if not re.fullmatch(valid_digits, digits):
            raise QuerySyntaxError(source, f"Invalid base-{base} integer literal {text!r}.", position)
        value = int(digits, base)
        return -value if match.group("sign") == "-" else value

    if re.match(r"[+-]?0[xXoObB]", compact):
        raise QuerySyntaxError(source, f"Invalid non-decimal integer literal {text!r}.", position)
    raise QuerySyntaxError(source, f"Could not understand integer value {text!r}.", position)


def _parse_count_text(text: str, source: str, position: int) -> int:
    compact = re.sub(r"\s+", "", text)
    if re.match(r"[+-]?0[xXoObB]", compact):
        return _parse_integer_literal_text(compact, source, position)

    match = re.fullmatch(r"(\d+(?:_\d+)*(?:\.\d+(?:_\d+)*)?)([kKmMbB]?)", compact)
    if not match:
        raise QuerySyntaxError(source, f"Could not understand count {text!r}.", position)
    multiplier = {"": 1, "k": 1_000, "m": 1_000_000, "b": 1_000_000_000}[match.group(2).lower()]
    number = match.group(1).replace("_", "")
    return round(float(number) * multiplier)


def _parse_number_text(text: str, source: str, position: int) -> int | float:
    compact = re.sub(r"\s+", "", text)
    if re.match(r"[+-]?0[xXoObB]", compact):
        return _parse_integer_literal_text(compact, source, position)
    if _DECIMAL_INTEGER_RE.fullmatch(compact):
        return int(compact.replace("_", ""), 10)
    if _DECIMAL_NUMBER_RE.fullmatch(compact) and "." in compact:
        return float(compact.replace("_", ""))
    raise QuerySyntaxError(source, f"Could not understand numeric value {text!r}.", position)


def _resolve_field(field: Field, schema: QuerySchema, source: str) -> Field:
    info = schema.resolve(field.name)
    if info is None:
        candidates = [item.name for item in schema.available_fields()]
        if field.name.casefold().startswith("raw."):
            candidates.extend(item.name for item in schema.raw_scalar_paths())
        suggestion = difflib.get_close_matches(field.name, candidates, n=1, cutoff=0.6)
        message = f"Unknown field {field.name!r}."
        if suggestion:
            message += f" Did you mean {suggestion[0]!r}?"
        raise QuerySyntaxError(source, message, field.position)
    canonical = info.alias_of or info.name
    return Field(canonical, field.position, info.kind)


def _resolve_literal(literal: Literal, field: Field, source: str, dates: DateContext) -> Literal:
    if literal.value is None or isinstance(literal.value, bool):
        return literal
    text = str(literal.value)
    kind = field.kind or "unknown"
    if parse_temporal_infinity(text, expected="date") is not None and kind not in {"date", "datetime"}:
        raise QuerySyntaxError(
            source,
            "INFINITY() and -INFINITY() are valid only for date or datetime fields.",
            literal.position,
        )
    try:
        if kind == "duration":
            value = _parse_duration_text(text, source, literal.position)
        elif kind == "count":
            value = _parse_count_text(text, source, literal.position)
        elif kind == "date":
            value = parse_temporal_infinity(text, expected="date")
            if value is None:
                value = parse_date_literal(text, dates)
        elif kind == "datetime":
            value = parse_temporal_infinity(text, expected="datetime")
            if value is None:
                value = parse_datetime_literal(text, dates)
        elif kind in {"integer"}:
            value = _parse_number_text(text, source, literal.position)
            if not isinstance(value, int):
                raise QuerySyntaxError(source, f"Field {field.name!r} requires an integer.", literal.position)
        elif kind in {"number"}:
            value = _parse_number_text(text, source, literal.position)
        elif kind == "boolean":
            lowered = text.casefold()
            if lowered not in {"true", "false"}:
                raise QuerySyntaxError(source, f"Field {field.name!r} requires TRUE or FALSE.", literal.position)
            value = lowered == "true"
        elif kind == "structured":
            raise QuerySyntaxError(
                source,
                f"Field {field.name!r} is an object or array and cannot be used as a scalar value.",
                field.position,
            )
        elif kind == "mixed":
            value = _generic_literal(text, literal.quoted)
        elif kind == "string":
            value = text
        else:
            value = _generic_literal(text, literal.quoted)
    except ValueError as exc:
        raise QuerySyntaxError(source, str(exc), literal.position) from exc
    return replace(literal, value=value)


def _parse_generic_numeric_literal(text: str, source: str, position: int) -> int | float:
    """Parse a numeric token whose field type is not yet known."""
    return _parse_number_text(text, source, position)


def _generic_literal(text: str, quoted: bool) -> Any:
    if quoted:
        return text
    lowered = text.casefold()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    compact = re.sub(r"\s+", "", text)
    if re.match(r"[+-]?0[xXoObB]", compact) or re.match(r"[+-]?\d", compact):
        try:
            return _parse_number_text(compact, text, 0)
        except QuerySyntaxError:
            pass
    return text


def format_scalar_expression(expression: Any) -> str:
    """Render a scalar expression in canonical yt-sql form."""
    if isinstance(expression, Field):
        return expression.name
    if isinstance(expression, Literal):
        if expression.value is None:
            return "NULL"
        if isinstance(expression.value, bool):
            return "TRUE" if expression.value else "FALSE"
        return expression.raw
    if isinstance(expression, ScalarUnary):
        operand = format_scalar_expression(expression.operand)
        if isinstance(expression.operand, ScalarBinary):
            operand = f"({operand})"
        return f"{expression.operator}{operand}"
    if isinstance(expression, ScalarBinary):
        return (
            f"({format_scalar_expression(expression.left)} {expression.operator} "
            f"{format_scalar_expression(expression.right)})"
        )
    if isinstance(expression, ScalarFunction):
        return f"{expression.name}({', '.join(format_scalar_expression(arg) for arg in expression.args)})"
    if isinstance(expression, AggregateFunction):
        inner = "*" if expression.count_star else ", ".join(format_scalar_expression(arg) for arg in expression.args)
        text = f"{expression.name}({inner})"
        if expression.filter_predicate is not None:
            text += f" FILTER (WHERE {format_expression(expression.filter_predicate)})"
        return text
    if isinstance(expression, ScalarCase):
        parts = ["CASE"]
        for branch in expression.whens:
            parts.append(f"WHEN {format_expression(branch.condition)} THEN {format_scalar_expression(branch.result)}")
        if expression.else_result is not None:
            parts.append(f"ELSE {format_scalar_expression(expression.else_result)}")
        parts.append("END")
        return " ".join(parts)
    raise AssertionError(f"Unsupported scalar expression {expression!r}")


def _scalar_kind(expression: Any) -> str | None:
    kind = getattr(expression, "kind", None)
    if kind is not None:
        return kind
    if isinstance(expression, Literal):
        value = expression.value
        if value is None:
            return None
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float):
            return "number"
        if isinstance(value, datetime):
            return "datetime"
        if isinstance(value, date):
            return "date"
        if isinstance(value, str):
            return "string"
    return None


def _common_case_kind(expressions: Sequence[Any], source: str, position: int) -> str | None:
    """Return the compatible CASE result kind, ignoring NULL-only branches."""
    kinds = [kind for expression in expressions if (kind := _scalar_kind(expression)) is not None]
    if not kinds:
        return None
    unique = set(kinds)
    if len(unique) == 1:
        return kinds[0]
    if all(_is_numeric_kind(kind) for kind in kinds):
        return "number"
    if "mixed" in unique or "unknown" in unique:
        return "mixed"
    raise QuerySyntaxError(
        source,
        "CASE result expressions must have compatible types; got " + ", ".join(sorted(unique)) + ".",
        position,
    )


def _common_scalar_kind(expressions: Sequence[Any], source: str, position: int, function_name: str) -> str | None:
    """Return one compatible scalar kind for multi-argument scalar functions."""
    kinds = [kind for expression in expressions if (kind := _scalar_kind(expression)) is not None]
    if not kinds:
        return None
    unique = set(kinds)
    if len(unique) == 1:
        return kinds[0]
    if all(_is_numeric_kind(kind) for kind in kinds):
        return "number"
    if "mixed" in unique or "unknown" in unique:
        return "mixed"
    raise QuerySyntaxError(
        source,
        f"{function_name} arguments must have compatible types; got " + ", ".join(sorted(unique)) + ".",
        position,
    )


def _is_numeric_kind(kind: str | None) -> bool:
    return kind in {"integer", "number", "count", "duration"}


def _resolve_scalar_expression(
    expression: Any,
    schema: QuerySchema,
    source: str,
    dates: DateContext,
    aliases: dict[str, "SelectTerm"] | None = None,
    *,
    select_context: bool = False,
) -> Any:
    """Resolve fields, aliases and types for a scalar expression."""
    if isinstance(expression, Field):
        if aliases is not None:
            alias = aliases.get(expression.name.casefold())
            if alias is not None:
                return (
                    alias.expression
                    if alias.expression is not None
                    else Field(alias.field, expression.position, alias.kind)
                )
        field = _resolve_field(expression, schema, source)
        if field.kind == "structured":
            if select_context:
                message = f"Cannot SELECT structured field {field.name!r}; select a scalar nested path instead."
            else:
                message = f"Field {field.name!r} is structured; use a scalar nested path instead."
            raise QuerySyntaxError(source, message, field.position)
        return field
    if isinstance(expression, Literal):
        if expression.value is None:
            return expression
        if isinstance(expression.value, bool):
            return replace(expression, value=bool(expression.value))
        if isinstance(expression.value, (int, float)):
            return expression
        return replace(expression, value=_generic_literal(str(expression.value), expression.quoted))
    if isinstance(expression, ScalarUnary):
        operand = _resolve_scalar_expression(
            expression.operand, schema, source, dates, aliases, select_context=select_context
        )
        kind = _scalar_kind(operand)
        if not _is_numeric_kind(kind) and not isinstance(operand, Literal):
            raise QuerySyntaxError(
                source, f"Unary {expression.operator} requires a numeric value.", expression.position
            )
        if isinstance(operand, Literal) and operand.value is not None and not isinstance(operand.value, (int, float)):
            raise QuerySyntaxError(
                source, f"Unary {expression.operator} requires a numeric value.", expression.position
            )
        return ScalarUnary(expression.operator, operand, expression.position, kind or "number")
    if isinstance(expression, ScalarBinary):
        left = _resolve_scalar_expression(
            expression.left, schema, source, dates, aliases, select_context=select_context
        )
        right = _resolve_scalar_expression(
            expression.right, schema, source, dates, aliases, select_context=select_context
        )
        for operand in (left, right):
            kind = _scalar_kind(operand)
            if kind is not None and not _is_numeric_kind(kind):
                raise QuerySyntaxError(
                    source, f"Arithmetic operator {expression.operator!r} requires numeric values.", expression.position
                )
            if (
                isinstance(operand, Literal)
                and operand.value is not None
                and not isinstance(operand.value, (int, float))
            ):
                raise QuerySyntaxError(
                    source, f"Arithmetic operator {expression.operator!r} requires numeric values.", expression.position
                )
        return ScalarBinary(expression.operator, left, right, expression.position, "number")
    if isinstance(expression, ScalarCase):
        resolved_whens: list[CaseWhen] = []
        results: list[Any] = []
        for branch in expression.whens:
            condition = _resolve_predicate(branch.condition, schema, source, dates)
            result = _resolve_scalar_expression(
                branch.result, schema, source, dates, aliases, select_context=select_context
            )
            resolved_whens.append(CaseWhen(condition, result, branch.position))
            results.append(result)
        else_result = None
        if expression.else_result is not None:
            else_result = _resolve_scalar_expression(
                expression.else_result, schema, source, dates, aliases, select_context=select_context
            )
            results.append(else_result)
        kind = _common_case_kind(results, source, expression.position)
        return ScalarCase(tuple(resolved_whens), else_result, expression.position, kind)
    if isinstance(expression, AggregateFunction):
        args = tuple(
            _resolve_scalar_expression(arg, schema, source, dates, aliases, select_context=select_context)
            for arg in expression.args
        )
        if any(_contains_aggregate(arg) for arg in args):
            raise QuerySyntaxError(source, "Aggregate functions cannot be nested.", expression.position)
        filter_predicate = _resolve_predicate(expression.filter_predicate, schema, source, dates)
        if expression.name == "COUNT":
            result_kind = "integer"
        elif expression.name == "AVG":
            arg_kind = _scalar_kind(args[0])
            if arg_kind is not None and not _is_numeric_kind(arg_kind):
                raise QuerySyntaxError(source, "AVG requires a numeric value.", expression.position)
            result_kind = "number"
        elif expression.name == "SUM":
            arg_kind = _scalar_kind(args[0])
            if arg_kind is not None and not _is_numeric_kind(arg_kind):
                raise QuerySyntaxError(source, "SUM requires a numeric value.", expression.position)
            result_kind = "number" if arg_kind == "number" else arg_kind or "number"
        else:
            result_kind = _scalar_kind(args[0])
        return AggregateFunction(
            expression.name, args, expression.count_star, filter_predicate, expression.position, result_kind
        )
    if isinstance(expression, ScalarFunction):
        args = tuple(
            _resolve_scalar_expression(arg, schema, source, dates, aliases, select_context=select_context)
            for arg in expression.args
        )
        if expression.name in {"LOWER", "UPPER"}:
            kind = _scalar_kind(args[0])
            if kind not in {"string", "mixed", "unknown", None}:
                raise QuerySyntaxError(source, f"{expression.name} requires a text field.", expression.position)
            result_kind = "string"
        elif expression.name == "LENGTH":
            kind = _scalar_kind(args[0])
            if kind not in {"string", "mixed", "unknown", None}:
                raise QuerySyntaxError(source, "LENGTH requires a text value.", expression.position)
            result_kind = "integer"
        elif expression.name == "CHAR":
            for arg in args:
                kind = _scalar_kind(arg)
                if kind is not None and not _is_numeric_kind(kind):
                    raise QuerySyntaxError(source, "CHAR requires integer code-point values.", expression.position)
                if _is_constant_scalar_expression(arg):
                    value = evaluate_scalar_expression(arg, {})
                    if value is not None:
                        _validate_char_codepoint(value, source, expression.position)
            result_kind = "string"
        elif expression.name == "NULLIF":
            result_kind = _common_scalar_kind(args, source, expression.position, "NULLIF")
            first_kind = _scalar_kind(args[0])
            if first_kind is not None:
                result_kind = first_kind
        elif expression.name in {"GREATEST", "LEAST"}:
            result_kind = _common_scalar_kind(args, source, expression.position, expression.name)
        elif expression.name == "COALESCE":
            result_kind = _common_scalar_kind(args, source, expression.position, "COALESCE")
        elif expression.name == "RANDOM":
            if args:
                seed = args[0]
                if not isinstance(seed, Literal) or isinstance(seed.value, bool) or not isinstance(seed.value, int):
                    raise QuerySyntaxError(
                        source, "RANDOM seed must be a constant integer literal.", expression.position
                    )
            result_kind = "number"
        else:
            non_null_kinds = [kind for arg in args if (kind := _scalar_kind(arg)) is not None]
            result_kind = (
                non_null_kinds[0] if non_null_kinds and all(k == non_null_kinds[0] for k in non_null_kinds) else "mixed"
            )
        return ScalarFunction(expression.name, args, expression.position, result_kind)
    raise AssertionError(f"Unsupported scalar expression {expression!r}")


def _is_constant_scalar_expression(expression: Any) -> bool:
    """Return whether an expression can be evaluated without row metadata."""
    if isinstance(expression, Literal):
        return True
    if isinstance(expression, ScalarUnary):
        return _is_constant_scalar_expression(expression.operand)
    if isinstance(expression, ScalarBinary):
        return _is_constant_scalar_expression(expression.left) and _is_constant_scalar_expression(expression.right)
    if isinstance(expression, ScalarFunction):
        return all(_is_constant_scalar_expression(arg) for arg in expression.args)
    return False


def _contains_aggregate(expression: Any) -> bool:
    """Return whether a scalar expression contains an aggregate function."""
    if isinstance(expression, AggregateFunction):
        return True
    if isinstance(expression, ScalarUnary):
        return _contains_aggregate(expression.operand)
    if isinstance(expression, ScalarBinary):
        return _contains_aggregate(expression.left) or _contains_aggregate(expression.right)
    if isinstance(expression, ScalarFunction):
        return any(_contains_aggregate(arg) for arg in expression.args)
    if isinstance(expression, ScalarCase):
        return any(_contains_aggregate(branch.result) for branch in expression.whens) or (
            expression.else_result is not None and _contains_aggregate(expression.else_result)
        )
    return False


def _fields_outside_aggregates(expression: Any) -> set[str]:
    """Return field names evaluated once per group rather than inside an aggregate."""
    if expression is None or isinstance(expression, (Literal, AggregateFunction)):
        return set()
    if isinstance(expression, Field):
        return {expression.name.casefold()}
    if isinstance(expression, ScalarUnary):
        return _fields_outside_aggregates(expression.operand)
    if isinstance(expression, ScalarBinary):
        return _fields_outside_aggregates(expression.left) | _fields_outside_aggregates(expression.right)
    if isinstance(expression, ScalarFunction):
        fields: set[str] = set()
        for arg in expression.args:
            fields.update(_fields_outside_aggregates(arg))
        return fields
    if isinstance(expression, ScalarCase):
        fields: set[str] = set()
        for branch in expression.whens:
            fields.update(_fields_in_predicate(branch.condition))
            fields.update(_fields_outside_aggregates(branch.result))
        fields.update(_fields_outside_aggregates(expression.else_result))
        return fields
    return set()


def _fields_in_predicate(node: Any) -> set[str]:
    if node is None:
        return set()
    if isinstance(node, Unary):
        return _fields_in_predicate(node.operand)
    if isinstance(node, Binary) and node.operator in {"AND", "OR"}:
        return _fields_in_predicate(node.left) | _fields_in_predicate(node.right)
    field = getattr(node, "field", None)
    if isinstance(field, Field):
        return {field.name.casefold()}
    if isinstance(node, Binary) and isinstance(node.left, Field):
        return {node.left.name.casefold()}
    return set()


def _aggregate_query(query: Query) -> bool:
    return (
        bool(query.group_by)
        or any(_contains_aggregate(term.expression) for term in query.select if term.expression is not None)
        or any(_contains_aggregate(term.expression) for term in query.order_by if term.expression is not None)
        or _having_contains_aggregate(query.having)
    )


def _having_contains_aggregate(node: Any) -> bool:
    if node is None:
        return False
    if isinstance(node, Unary):
        return _having_contains_aggregate(node.operand)
    if isinstance(node, Binary) and node.operator in {"AND", "OR"}:
        return _having_contains_aggregate(node.left) or _having_contains_aggregate(node.right)
    if isinstance(node, ScalarComparison):
        return _contains_aggregate(node.left) or _contains_aggregate(node.right)
    if isinstance(node, ScalarIsNull):
        return _contains_aggregate(node.expression)
    return False


def _coerce_char_codepoint(value: Any) -> int:
    """Convert one runtime CHAR argument into a valid Unicode scalar value."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("CHAR requires integer code-point values")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError("CHAR requires integer code-point values")
    codepoint = int(value)
    if codepoint < 0 or codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
        raise ValueError("CHAR code point is outside the Unicode scalar-value range")
    return codepoint


def _validate_char_codepoint(value: Any, source: str, position: int) -> int:
    """Validate a constant CHAR argument and raise a query diagnostic on failure."""
    try:
        return _coerce_char_codepoint(value)
    except TypeError as exc:
        raise QuerySyntaxError(source, "CHAR requires integer code-point values.", position) from exc
    except ValueError as exc:
        if isinstance(value, (int, float)) and not isinstance(value, bool) and float(value).is_integer():
            raise QuerySyntaxError(
                source,
                "CHAR code points must be Unicode scalar values from 0 to 1114111, excluding surrogates.",
                position,
            ) from exc
        raise QuerySyntaxError(source, "CHAR requires integer code-point values.", position) from exc


def _stable_random_identity(record: dict[str, Any]) -> str:
    """Return a stable logical identity for deterministic seeded randomness."""
    preferred = []
    for key in ("_yt_sql_source", "_yt_sql_source_facet", "extractor", "extractor_key", "webpage_url", "url", "id"):
        value = record.get(key)
        if value is not None:
            preferred.append((key, value))
    if preferred:
        return json.dumps(preferred, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    public = {key: value for key, value in record.items() if not key.startswith("_yt_sql_")}
    return json.dumps(public, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _evaluate_random(function: ScalarFunction, record: dict[str, Any]) -> float:
    """Evaluate volatile or reproducibly seeded row randomness."""
    if function.args:
        seed = function.args[0]
        assert isinstance(seed, Literal) and isinstance(seed.value, int) and not isinstance(seed.value, bool)
        payload = f"{seed.value}\0{_stable_random_identity(record)}".encode("utf-8")
        digest = hashlib.blake2b(payload, digest_size=8, person=b"yt-sql-rnd").digest()
        integer = int.from_bytes(digest, "big") >> 11
        return integer / float(1 << 53)

    cache = record.setdefault("_yt_sql_random_cache", {})
    key = function.position
    if key not in cache:
        cache[key] = random.SystemRandom().random()
    return float(cache[key])


def evaluate_scalar_expression(expression: Any, record: dict[str, Any]) -> Any:
    """Evaluate a resolved scalar expression against one metadata record."""
    if isinstance(expression, Field):
        return canonical_record_value(record, expression)
    if isinstance(expression, Literal):
        return expression.value
    if isinstance(expression, ScalarUnary):
        value = evaluate_scalar_expression(expression.operand, record)
        if value is None:
            return None
        try:
            return +value if expression.operator == "+" else -value
        except TypeError:
            return None
    if isinstance(expression, ScalarBinary):
        left = evaluate_scalar_expression(expression.left, record)
        right = evaluate_scalar_expression(expression.right, record)
        if left is None or right is None:
            return None
        try:
            if expression.operator == "+":
                return left + right
            if expression.operator == "-":
                return left - right
            if expression.operator == "*":
                return left * right
            if expression.operator == "/":
                return None if right == 0 else left / right
            if expression.operator == "%":
                return None if right == 0 else left % right
        except (TypeError, ValueError, OverflowError):
            return None
        raise AssertionError(f"Unsupported arithmetic operator {expression.operator}")
    if isinstance(expression, ScalarCase):
        for branch in expression.whens:
            if evaluate(branch.condition, record) is True:
                return evaluate_scalar_expression(branch.result, record)
        if expression.else_result is not None:
            return evaluate_scalar_expression(expression.else_result, record)
        return None
    if isinstance(expression, ScalarFunction):
        values = [evaluate_scalar_expression(arg, record) for arg in expression.args]
        if expression.name == "LOWER":
            return values[0].lower() if isinstance(values[0], str) else None
        if expression.name == "UPPER":
            return values[0].upper() if isinstance(values[0], str) else None
        if expression.name == "LENGTH":
            return len(values[0]) if isinstance(values[0], str) else None
        if expression.name == "COALESCE":
            return next((value for value in values if value is not None), None)
        if expression.name == "CHAR":
            if any(value is None for value in values):
                return None
            try:
                codepoints = [_coerce_char_codepoint(value) for value in values]
            except (TypeError, ValueError):
                return None
            return "".join(chr(codepoint) for codepoint in codepoints)
        if expression.name == "NULLIF":
            first, second = values
            if first is None:
                return None
            if second is None:
                return first
            try:
                return None if first == second else first
            except (TypeError, ValueError):
                return first
        if expression.name in {"GREATEST", "LEAST"}:
            if any(value is None for value in values):
                return None
            try:
                return max(values) if expression.name == "GREATEST" else min(values)
            except (TypeError, ValueError):
                return None
        if expression.name == "RANDOM":
            return _evaluate_random(expression, record)
        raise AssertionError(f"Unsupported scalar function {expression.name}")
    raise AssertionError(f"Unsupported scalar expression {expression!r}")


def _resolve_predicate(node: Any, schema: QuerySchema, source: str, context: DateContext) -> Any:
    """Resolve one Boolean predicate tree against the established query schema."""
    if node is None:
        return None
    if isinstance(node, Unary):
        return Unary(node.operator, _resolve_predicate(node.operand, schema, source, context))
    if isinstance(node, Binary) and node.operator in {"AND", "OR"}:
        return Binary(
            node.operator,
            _resolve_predicate(node.left, schema, source, context),
            _resolve_predicate(node.right, schema, source, context),
        )
    if isinstance(node, Binary):
        field = _resolve_field(node.left, schema, source)
        if field.kind == "structured":
            raise QuerySyntaxError(
                source, f"Field {field.name!r} is structured; use a scalar nested path instead.", field.position
            )
        literal = _resolve_literal(node.right, field, source, context)
        if literal.value is None:
            raise QuerySyntaxError(source, "Use IS NULL or IS NOT NULL for NULL tests.", literal.position)
        return Binary(node.operator, field, literal)
    if isinstance(node, Between):
        field = _resolve_field(node.field, schema, source)
        if field.kind == "structured":
            raise QuerySyntaxError(
                source, f"Field {field.name!r} is structured; use a scalar nested path instead.", field.position
            )
        return Between(
            field,
            _resolve_literal(node.lower, field, source, context),
            _resolve_literal(node.upper, field, source, context),
            node.negated,
        )
    if isinstance(node, InList):
        field = _resolve_field(node.field, schema, source)
        if field.kind == "structured":
            raise QuerySyntaxError(
                source, f"Field {field.name!r} is structured; use a scalar nested path instead.", field.position
            )
        return InList(
            field,
            tuple(_resolve_literal(item, field, source, context) for item in node.values),
            node.negated,
        )
    if isinstance(node, IsNull):
        return IsNull(_resolve_field(node.field, schema, source), node.negated)
    if isinstance(node, TextPredicate):
        field = _resolve_field(node.field, schema, source)
        if field.kind == "structured":
            raise QuerySyntaxError(
                source, f"Field {field.name!r} is structured; use a scalar nested path instead.", field.position
            )
        if field.kind not in {"string", "mixed", "unknown"}:
            raise QuerySyntaxError(source, f"{node.operator} requires a text field, not {field.kind}.", field.position)
        if node.operator in {"LIKE", "ILIKE"}:
            _validate_like_pattern(str(node.value.value), source, node.value.position)
            # Populate the pattern cache during resolution so row evaluation does not
            # pay the translation/compilation cost for a literal query pattern.
            _compile_like_pattern(str(node.value.value), node.operator == "ILIKE")
        return TextPredicate(node.operator, field, node.value, node.negated)
    raise AssertionError(f"Unsupported query node {node!r}")


def _resolve_having(
    node: Any,
    schema: QuerySchema,
    source: str,
    dates: DateContext,
    aliases: dict[str, SelectTerm],
) -> Any:
    if node is None:
        return None
    if isinstance(node, Unary):
        return Unary(node.operator, _resolve_having(node.operand, schema, source, dates, aliases))
    if isinstance(node, Binary) and node.operator in {"AND", "OR"}:
        return Binary(
            node.operator,
            _resolve_having(node.left, schema, source, dates, aliases),
            _resolve_having(node.right, schema, source, dates, aliases),
        )
    if isinstance(node, ScalarComparison):
        left = _resolve_scalar_expression(node.left, schema, source, dates, aliases)
        right = _resolve_scalar_expression(node.right, schema, source, dates, aliases)
        left_kind = _scalar_kind(left)
        right_kind = _scalar_kind(right)
        if (
            left_kind is not None
            and right_kind is not None
            and left_kind != right_kind
            and not (_is_numeric_kind(left_kind) and _is_numeric_kind(right_kind))
            and "mixed" not in {left_kind, right_kind}
        ):
            raise QuerySyntaxError(source, "HAVING comparison expressions must have compatible types.", 0)
        return ScalarComparison(node.operator, left, right)
    if isinstance(node, ScalarIsNull):
        return ScalarIsNull(_resolve_scalar_expression(node.expression, schema, source, dates, aliases), node.negated)
    raise AssertionError(f"Unsupported HAVING node {node!r}")


def _validate_group_compatibility(expression: Any, group_by: tuple[Any, ...], source: str, position: int) -> None:
    """Reject ambiguous row-level expressions in aggregate projection contexts."""
    if expression is None or not _fields_outside_aggregates(expression):
        return
    canonical_groups = {format_scalar_expression(item) for item in group_by}
    if not _contains_aggregate(expression) and format_scalar_expression(expression) in canonical_groups:
        return
    raise QuerySyntaxError(
        source,
        "Non-aggregate SELECT/ORDER BY expressions in an aggregate query must match a GROUP BY expression.",
        position,
    )


def _validate_having_group_compatibility(node: Any, group_by: tuple[Any, ...], source: str) -> None:
    if node is None:
        return
    if isinstance(node, Unary):
        _validate_having_group_compatibility(node.operand, group_by, source)
        return
    if isinstance(node, Binary) and node.operator in {"AND", "OR"}:
        _validate_having_group_compatibility(node.left, group_by, source)
        _validate_having_group_compatibility(node.right, group_by, source)
        return
    expressions = []
    if isinstance(node, ScalarComparison):
        expressions = [node.left, node.right]
    elif isinstance(node, ScalarIsNull):
        expressions = [node.expression]
    canonical_groups = {format_scalar_expression(item) for item in group_by}
    for expression in expressions:
        if not _fields_outside_aggregates(expression):
            continue
        if not _contains_aggregate(expression) and format_scalar_expression(expression) in canonical_groups:
            continue
        raise QuerySyntaxError(
            source,
            "Non-aggregate HAVING expressions must match a GROUP BY expression or selected aggregate alias.",
            getattr(expression, "position", 0),
        )


def _contains_random(expression: Any) -> bool:
    if expression is None:
        return False
    if isinstance(expression, ScalarFunction):
        return expression.name == "RANDOM" or any(_contains_random(arg) for arg in expression.args)
    if isinstance(expression, AggregateFunction):
        return any(_contains_random(arg) for arg in expression.args) or _contains_random(expression.filter_predicate)
    if isinstance(expression, (ScalarUnary, Unary)):
        return _contains_random(expression.operand)
    if isinstance(expression, (ScalarBinary, Binary, ScalarComparison)):
        return _contains_random(expression.left) or _contains_random(expression.right)
    if isinstance(expression, ScalarIsNull):
        return _contains_random(expression.expression)
    if isinstance(expression, ScalarCase):
        return any(
            _contains_random(branch.condition) or _contains_random(branch.result) for branch in expression.whens
        ) or _contains_random(expression.else_result)
    if isinstance(expression, Between):
        return (
            _contains_random(expression.field)
            or _contains_random(expression.lower)
            or _contains_random(expression.upper)
        )
    if isinstance(expression, InList):
        return _contains_random(expression.field) or any(_contains_random(value) for value in expression.values)
    if isinstance(expression, IsNull):
        return _contains_random(expression.field)
    if isinstance(expression, TextPredicate):
        return _contains_random(expression.field) or _contains_random(expression.value)
    return False


def _validate_random_placement(query: Query) -> None:
    """Keep volatile randomness out of row-selection and grouping semantics."""
    if _contains_random(query.predicate):
        raise QuerySyntaxError(query.source, "RANDOM is not allowed in WHERE predicates.", 0)
    if any(_contains_random(expression) for expression in query.group_by):
        raise QuerySyntaxError(query.source, "RANDOM is not allowed in GROUP BY expressions.", 0)
    if _contains_random(query.having):
        raise QuerySyntaxError(query.source, "RANDOM is not allowed in HAVING predicates.", 0)
    for term in query.select:
        expression = term.expression
        if isinstance(expression, AggregateFunction) and _contains_random(expression.filter_predicate):
            raise QuerySyntaxError(
                query.source, "RANDOM is not allowed in aggregate FILTER predicates.", expression.position
            )


def _resolve_query_body(query: Query, schema: QuerySchema, dates: DateContext | None = None) -> Query:
    """Resolve fields and typed literals after metadata has established a schema."""
    context = dates or DateContext()
    source = query.source
    _validate_random_placement(query)

    predicate = _resolve_predicate(query.predicate, schema, source, context)
    group_by = tuple(_resolve_scalar_expression(item, schema, source, context) for item in query.group_by)
    for item in group_by:
        if _contains_aggregate(item):
            raise QuerySyntaxError(
                source, "GROUP BY expressions cannot contain aggregate functions.", getattr(item, "position", 0)
            )

    select_terms: list[SelectTerm] = []
    effective_select = query.select or (SelectTerm("id"),)
    if (
        len(effective_select) == 1
        and effective_select[0].field == "*"
        and effective_select[0].expression is None
        and (query.group_by or query.having is not None)
    ):
        raise QuerySyntaxError(
            source,
            "SELECT * is not supported in aggregate queries; select grouped and aggregate expressions explicitly.",
            effective_select[0].position,
        )
    if len(effective_select) == 1 and effective_select[0].field == "*" and effective_select[0].expression is None:
        effective_select = tuple(
            SelectTerm(info.name, position=effective_select[0].position) for info in schema.select_star_fields()
        )
    output_names: set[str] = set()
    explicit_aliases: dict[str, SelectTerm] = {}
    for original_term in effective_select:
        if original_term.expression is not None:
            expression = _resolve_scalar_expression(
                original_term.expression, schema, source, context, select_context=True
            )
            field_text = format_scalar_expression(expression)
            kind = _scalar_kind(expression)
            if isinstance(expression, Field):
                field_text = expression.name
        else:
            expression = None
            field = _resolve_field(Field(original_term.field, original_term.position), schema, source)
            if field.kind == "structured":
                raise QuerySyntaxError(
                    source,
                    f"Cannot SELECT structured field {field.name!r}; select a scalar nested path instead.",
                    original_term.position,
                )
            field_text = field.name
            kind = field.kind
        output_name = original_term.alias or original_term.field
        key = output_name.casefold()
        if key in output_names:
            raise QuerySyntaxError(
                source,
                f"Duplicate SELECT output name {output_name!r}; use AS to give fields unique names.",
                original_term.position,
            )
        output_names.add(key)
        resolved_term = SelectTerm(field_text, output_name, original_term.position, kind, expression)
        select_terms.append(resolved_term)
        if original_term.alias is not None:
            explicit_aliases[original_term.alias.casefold()] = resolved_term

    having = _resolve_having(query.having, schema, source, context, explicit_aliases)

    order_terms: list[OrderTerm] = []
    for term in query.order_by:
        if term.expression is not None:
            expression = _resolve_scalar_expression(term.expression, schema, source, context, explicit_aliases)
            field_text = format_scalar_expression(expression)
            kind = _scalar_kind(expression)
            if isinstance(expression, Field):
                field_text = expression.name
            order_terms.append(OrderTerm(field_text, term.descending, term.position, kind, expression))
            continue
        selected_alias = explicit_aliases.get(term.field.casefold())
        if selected_alias is not None:
            order_terms.append(
                OrderTerm(
                    selected_alias.field, term.descending, term.position, selected_alias.kind, selected_alias.expression
                )
            )
            continue
        field = _resolve_field(Field(term.field, term.position), schema, source)
        if field.kind == "structured":
            raise QuerySyntaxError(source, f"Cannot ORDER BY structured field {field.name!r}.", term.position)
        order_terms.append(OrderTerm(field.name, term.descending, term.position, field.kind))

    resolved = Query(
        predicate,
        tuple(order_terms),
        query.limit,
        source,
        tuple(select_terms),
        query.from_source,
        query.distinct,
        query.offset,
        group_by,
        having,
        (),
        (),
        query.from_facet,
    )
    if _aggregate_query(resolved):
        for term in resolved.select:
            _validate_group_compatibility(term.expression, group_by, source, term.position)
        for term in resolved.order_by:
            _validate_group_compatibility(term.expression, group_by, source, term.position)
        _validate_having_group_compatibility(having, group_by, source)
    elif having is not None:
        raise QuerySyntaxError(source, "HAVING requires GROUP BY or an aggregate expression.", 0)
    return resolved


def _union_common_kind(left: str | None, right: str | None) -> str:
    """Return the logical kind exported by two positional UNION columns."""
    left_kind = left or "unknown"
    right_kind = right or "unknown"
    if left_kind == right_kind:
        return left_kind
    if left_kind == "unknown":
        return right_kind
    if right_kind == "unknown":
        return left_kind
    numeric = {"integer", "number", "count", "duration"}
    if left_kind in numeric and right_kind in numeric:
        if left_kind == right_kind:
            return left_kind
        return "number"
    raise ValueError(f"incompatible UNION kinds {left_kind!r} and {right_kind!r}")


def _query_result_schema(query: Query) -> QuerySchema:
    """Build the logical schema exported by a resolved query result."""
    fields = [FieldInfo(term.output_name, term.kind or "unknown", True, dynamic=True) for term in query.select]
    return QuerySchema.from_field_infos(fields)


def _source_schema(
    source_name: str | None,
    source_facet: str | None,
    physical_schema: QuerySchema,
    cte_schemas: dict[str, QuerySchema],
    source_schemas: dict[tuple[str, str | None], QuerySchema],
) -> QuerySchema:
    if source_name is None:
        return physical_schema
    logical = cte_schemas.get(source_name.casefold())
    if logical is not None:
        return logical
    return source_schemas.get((source_name, source_facet), physical_schema)


def _resolve_union_order(
    order_by: tuple[OrderTerm, ...], schema: QuerySchema, source: str, context: DateContext
) -> tuple[OrderTerm, ...]:
    """Resolve global UNION ordering against the reconciled result relation."""
    terms: list[OrderTerm] = []
    for term in order_by:
        expression = _resolve_scalar_expression(term.expression, schema, source, context)
        field_text = format_scalar_expression(expression)
        kind = _scalar_kind(expression)
        if isinstance(expression, Field):
            field_text = expression.name
        terms.append(OrderTerm(field_text, term.descending, term.position, kind, expression))
    return tuple(terms)


def _resolve_composed_query(
    query: Query,
    physical_schema: QuerySchema,
    cte_schemas: dict[str, QuerySchema],
    context: DateContext,
    source_schemas: dict[tuple[str, str | None], QuerySchema],
) -> Query:
    """Resolve one query body and its positional set-composition branches."""
    if not query.set_operations:
        schema = _source_schema(query.from_source, query.from_facet, physical_schema, cte_schemas, source_schemas)
        return _resolve_query_body(replace(query, ctes=(), set_operations=()), schema, context)

    # ORDER BY/LIMIT/OFFSET belong to the complete set result, not the first branch.
    left_body = replace(query, ctes=(), set_operations=(), order_by=(), limit=None, offset=0)
    left = _resolve_query_body(
        left_body,
        _source_schema(query.from_source, query.from_facet, physical_schema, cte_schemas, source_schemas),
        context,
    )
    common_terms = list(left.select)
    resolved_ops: list[SetOperation] = []
    for operation in query.set_operations:
        branch = _resolve_query_body(
            replace(operation.query, ctes=(), set_operations=(), order_by=(), limit=None, offset=0),
            _source_schema(
                operation.query.from_source, operation.query.from_facet, physical_schema, cte_schemas, source_schemas
            ),
            context,
        )
        if len(branch.select) != len(common_terms):
            raise QuerySyntaxError(
                query.source,
                f"UNION branches must project the same number of columns; expected {len(common_terms)}, got {len(branch.select)}.",
                operation.position,
            )
        reconciled: list[SelectTerm] = []
        for index, (left_term, right_term) in enumerate(zip(common_terms, branch.select, strict=True), start=1):
            try:
                kind = _union_common_kind(left_term.kind, right_term.kind)
            except ValueError:
                raise QuerySyntaxError(
                    query.source,
                    f"UNION column {index} has incompatible kinds {left_term.kind or 'unknown'} and {right_term.kind or 'unknown'}.",
                    operation.position,
                ) from None
            reconciled.append(replace(left_term, kind=kind))
        common_terms = reconciled
        resolved_ops.append(SetOperation(branch, operation.all, operation.position))

    left = replace(left, select=tuple(common_terms))
    result_schema = _query_result_schema(left)
    order_by = _resolve_union_order(query.order_by, result_schema, query.source, context)
    return replace(
        left,
        order_by=order_by,
        limit=query.limit,
        offset=query.offset,
        set_operations=tuple(resolved_ops),
    )


def resolve_query(
    query: Query,
    schema: QuerySchema,
    dates: DateContext | None = None,
    *,
    source_schemas: dict[tuple[str, str | None], QuerySchema] | None = None,
) -> Query:
    """Resolve CTEs and positional set composition against logical and per-source schemas."""
    context = dates or DateContext()
    physical_source_schemas = source_schemas or {}
    resolved_ctes: list[CommonTableExpression] = []
    cte_schemas: dict[str, QuerySchema] = {}
    cte_names = {cte.name.casefold() for cte in query.ctes}

    for cte in query.ctes:
        referenced = [name.casefold() for name in _direct_from_sources(cte.query)]
        if cte.name.casefold() in referenced:
            raise QuerySyntaxError(
                query.source, f"Recursive reference to CTE {cte.name!r} is not supported.", cte.position
            )
        later = [name for name in referenced if name in cte_names and name not in cte_schemas]
        if later:
            raise QuerySyntaxError(
                query.source,
                f"CTE {cte.name!r} cannot reference later CTE {later[0]!r}; forward references are not supported.",
                cte.position,
            )
        resolved_subquery = _resolve_composed_query(
            replace(cte.query, ctes=()), schema, cte_schemas, context, physical_source_schemas
        )
        resolved_ctes.append(CommonTableExpression(cte.name, resolved_subquery, cte.position))
        cte_schemas[cte.name.casefold()] = _query_result_schema(resolved_subquery)

    resolved = _resolve_composed_query(replace(query, ctes=()), schema, cte_schemas, context, physical_source_schemas)
    return replace(resolved, ctes=tuple(resolved_ctes))


def _direct_from_sources(query: Query) -> tuple[str, ...]:
    """Return FROM references directly used by one composed query, excluding nested CTE declarations."""
    result: list[str] = []
    if query.from_source is not None:
        result.append(query.from_source)
    for operation in query.set_operations:
        if operation.query.from_source is not None:
            result.append(operation.query.from_source)
    return tuple(result)


def query_physical_source_requests(query: Query) -> tuple[tuple[str, str | None], ...]:
    """Return physical source/facet requests in deterministic first-use order."""
    cte_names = {cte.name.casefold() for cte in query.ctes}
    seen: set[tuple[str, str | None]] = set()
    result: list[tuple[str, str | None]] = []

    def visit(candidate: Query) -> None:
        direct: list[tuple[str, str | None]] = []
        if candidate.from_source is not None:
            direct.append((candidate.from_source, candidate.from_facet))
        for operation in candidate.set_operations:
            if operation.query.from_source is not None:
                direct.append((operation.query.from_source, operation.query.from_facet))
        for source_name, facet in direct:
            if source_name.casefold() in cte_names:
                if facet is not None:
                    raise QuerySyntaxError(
                        query.source,
                        "OF applies only to physical sources, not CTE result relations.",
                        0,
                    )
                continue
            key = (source_name, facet)
            if key in seen:
                continue
            seen.add(key)
            result.append(key)

    for cte in query.ctes:
        visit(cte.query)
    visit(query)
    return tuple(result)


def query_physical_sources(query: Query) -> tuple[str, ...]:
    """Return physical source references in deterministic first-use order."""
    seen: set[str] = set()
    result: list[str] = []
    for source_name, _facet in query_physical_source_requests(query):
        if source_name in seen:
            continue
        seen.add(source_name)
        result.append(source_name)
    return tuple(result)


def query_single_physical_source(query: Query) -> str | None:
    """Return the sole physical source, rejecting genuinely multi-source composition."""
    sources = query_physical_sources(query)
    if len(sources) > 1:
        raise QuerySyntaxError(
            query.source,
            "This operation requires a single physical source; the query contains UNION composition across multiple sources.",
            0,
        )
    return sources[0] if sources else None


def canonical_record_value(
    record: dict[str, Any], field: Field | OrderTerm | SelectTerm | str, kind: str | None = None
) -> Any:
    if isinstance(field, Field):
        name, field_kind = field.name, field.kind
    elif isinstance(field, OrderTerm):
        if field.expression is not None:
            return evaluate_scalar_expression(field.expression, record)
        name, field_kind = field.field, field.kind
    elif isinstance(field, SelectTerm):
        materialised_result = record.get("_yt_sql_aggregate_result") is True or record.get("_yt_sql_result_row") is True
        aggregate_projection = field.expression is not None and _contains_aggregate(field.expression)
        volatile_projection = field.expression is not None and _contains_random(field.expression)
        if field.output_name in record and (materialised_result or aggregate_projection or volatile_projection):
            return record.get(field.output_name)
        if field.expression is not None:
            return evaluate_scalar_expression(field.expression, record)
        name, field_kind = field.field, field.kind
    else:
        name, field_kind = field, kind

    if name.casefold().startswith("raw."):
        found, value = raw_path_value(record, name[4:])
        if not found:
            return None
    else:
        value = record.get(name)

    if value is None:
        return None
    if field_kind == "date":
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return parse_date_literal(value, DateContext(date_order="ymd"))
            except ValueError:
                return value
    if field_kind == "datetime":
        return timestamp_to_datetime(value)
    return value


def like_matches(value: str, pattern: str, *, case_insensitive: bool = False) -> bool:
    """Return whether one string satisfies an yt-sql LIKE pattern."""
    return _compile_like_pattern(pattern, case_insensitive).fullmatch(value) is not None


def _validate_like_pattern(pattern: str, source: str, position: int) -> None:
    """Validate yt-sql LIKE escaping.

    Percent and underscore are wildcards. A backslash quotes the following
    character, including percent, underscore, and backslash itself. A trailing
    escape is rejected so patterns are never silently reinterpreted.
    """
    escaped = False
    for character in pattern:
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
    if escaped:
        raise QuerySyntaxError(source, "LIKE pattern ends with an incomplete backslash escape.", position)


@lru_cache(maxsize=512)
def _compile_like_pattern(pattern: str, case_insensitive: bool) -> re.Pattern[str]:
    """Compile one yt-sql LIKE pattern to an anchored regular expression.

    ``%`` matches zero or more Unicode code points, including newlines, and
    ``_`` matches exactly one Unicode code point. Backslash quotes the next
    pattern character. The cache means a resolved literal pattern is compiled
    only once for repeated row evaluation.
    """
    pieces: list[str] = []
    escaped = False
    for character in pattern:
        if escaped:
            pieces.append(re.escape(character))
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == "%":
            pieces.append("[\\s\\S]*")
        elif character == "_":
            pieces.append("[\\s\\S]")
        else:
            pieces.append(re.escape(character))
    flags = re.IGNORECASE if case_insensitive else 0
    return re.compile("".join(pieces), flags)


_CASE_INSENSITIVE_ENUM_FIELDS = {"live_status", "availability"}


def _comparison_values(field: Field, left: Any, right: Any) -> tuple[Any, Any]:
    """Normalise comparison values where a field has explicit enum-like semantics."""
    if field.name.casefold() in _CASE_INSENSITIVE_ENUM_FIELDS and isinstance(left, str) and isinstance(right, str):
        return left.casefold(), right.casefold()
    return left, right


def evaluate(node: Any, record: dict[str, Any]) -> bool | None:
    """Evaluate a resolved AST using SQL-like three-valued Boolean logic."""
    if node is None:
        return True
    if isinstance(node, Unary):
        value = evaluate(node.operand, record)
        return None if value is None else not value
    if isinstance(node, Binary) and node.operator in {"AND", "OR"}:
        left = evaluate(node.left, record)
        right = evaluate(node.right, record)
        if node.operator == "AND":
            if left is False or right is False:
                return False
            if left is None or right is None:
                return None
            return True
        if left is True or right is True:
            return True
        if left is None or right is None:
            return None
        return False
    if isinstance(node, Binary):
        left = canonical_record_value(record, node.left)
        right = node.right.value
        if left is None or right is None:
            return None
        left, right = _comparison_values(node.left, left, right)
        try:
            if node.operator == "=":
                return left == right
            if node.operator == "!=":
                return left != right
            if node.operator == "<":
                return left < right
            if node.operator == "<=":
                return left <= right
            if node.operator == ">":
                return left > right
            if node.operator == ">=":
                return left >= right
        except TypeError:
            return False
        raise AssertionError(f"Unsupported operator {node.operator}")
    if isinstance(node, Between):
        value = canonical_record_value(record, node.field)
        if value is None:
            return None
        try:
            result = node.lower.value <= value <= node.upper.value
        except TypeError:
            result = False
        return not result if node.negated else result
    if isinstance(node, InList):
        value = canonical_record_value(record, node.field)
        if value is None:
            return None
        result = any(
            _comparison_values(node.field, value, item.value)[0] == _comparison_values(node.field, value, item.value)[1]
            for item in node.values
        )
        return not result if node.negated else result
    if isinstance(node, IsNull):
        result = canonical_record_value(record, node.field) is None
        return not result if node.negated else result
    if isinstance(node, TextPredicate):
        value = canonical_record_value(record, node.field)
        if value is None:
            return None
        if not isinstance(value, str):
            return False
        needle = str(node.value.value)
        if node.operator == "CONTAINS":
            result = needle.casefold() in value.casefold()
        elif node.operator == "MATCHES":
            result = re.search(needle, value) is not None
        elif node.operator in {"LIKE", "ILIKE"}:
            result = like_matches(value, needle, case_insensitive=node.operator == "ILIKE")
        else:
            raise AssertionError(f"Unsupported text operator {node.operator}")
        return not result if node.negated else result
    raise AssertionError(f"Unsupported query node {node!r}")


def _hashable_group_value(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple((key, _hashable_group_value(item)) for key, item in value.items())
    if isinstance(value, list):
        return tuple(_hashable_group_value(item) for item in value)
    return value


def _apply_scalar_function_values(name: str, values: list[Any]) -> Any:
    if name == "LOWER":
        return values[0].lower() if isinstance(values[0], str) else None
    if name == "UPPER":
        return values[0].upper() if isinstance(values[0], str) else None
    if name == "LENGTH":
        return len(values[0]) if isinstance(values[0], str) else None
    if name == "COALESCE":
        return next((value for value in values if value is not None), None)
    if name == "CHAR":
        if any(value is None for value in values):
            return None
        try:
            return "".join(chr(_coerce_char_codepoint(value)) for value in values)
        except (TypeError, ValueError):
            return None
    if name == "NULLIF":
        first, second = values
        if first is None:
            return None
        if second is None:
            return first
        return None if first == second else first
    if name in {"GREATEST", "LEAST"}:
        if any(value is None for value in values):
            return None
        try:
            return max(values) if name == "GREATEST" else min(values)
        except (TypeError, ValueError):
            return None
    raise AssertionError(f"Unsupported scalar function {name}")


def _evaluate_group_expression(expression: Any, group: Sequence[dict[str, Any]]) -> Any:
    """Evaluate one resolved SELECT/HAVING/ORDER expression over an aggregate group."""
    if isinstance(expression, AggregateFunction):
        rows = list(group)
        if expression.filter_predicate is not None:
            rows = [row for row in rows if evaluate(expression.filter_predicate, row) is True]
        if expression.count_star:
            return len(rows)
        values = [evaluate_scalar_expression(expression.args[0], row) for row in rows]
        non_null = [value for value in values if value is not None]
        if expression.name == "COUNT":
            return len(non_null)
        if not non_null:
            return None
        if expression.name == "SUM":
            try:
                return sum(non_null)
            except TypeError:
                return None
        if expression.name == "AVG":
            try:
                return sum(non_null) / len(non_null)
            except TypeError:
                return None
        if expression.name == "MIN":
            try:
                return min(non_null)
            except TypeError:
                return None
        if expression.name == "MAX":
            try:
                return max(non_null)
            except TypeError:
                return None
        raise AssertionError(f"Unsupported aggregate function {expression.name}")
    representative = group[0] if group else {}
    if isinstance(expression, (Field, Literal)):
        return evaluate_scalar_expression(expression, representative)
    if isinstance(expression, ScalarUnary):
        value = _evaluate_group_expression(expression.operand, group)
        if value is None:
            return None
        try:
            return +value if expression.operator == "+" else -value
        except TypeError:
            return None
    if isinstance(expression, ScalarBinary):
        left = _evaluate_group_expression(expression.left, group)
        right = _evaluate_group_expression(expression.right, group)
        if left is None or right is None:
            return None
        try:
            if expression.operator == "+":
                return left + right
            if expression.operator == "-":
                return left - right
            if expression.operator == "*":
                return left * right
            if expression.operator == "/":
                return None if right == 0 else left / right
            if expression.operator == "%":
                return None if right == 0 else left % right
        except TypeError:
            return None
    if isinstance(expression, ScalarFunction):
        if expression.name == "RANDOM":
            return _evaluate_random(expression, representative)
        return _apply_scalar_function_values(
            expression.name, [_evaluate_group_expression(arg, group) for arg in expression.args]
        )
    if isinstance(expression, ScalarCase):
        for branch in expression.whens:
            if evaluate(branch.condition, representative) is True:
                return _evaluate_group_expression(branch.result, group)
        return _evaluate_group_expression(expression.else_result, group) if expression.else_result is not None else None
    raise AssertionError(f"Unsupported aggregate scalar expression {expression!r}")


def _evaluate_having(node: Any, group: Sequence[dict[str, Any]]) -> bool | None:
    if node is None:
        return True
    if isinstance(node, Unary):
        value = _evaluate_having(node.operand, group)
        return None if value is None else not value
    if isinstance(node, Binary) and node.operator in {"AND", "OR"}:
        left = _evaluate_having(node.left, group)
        right = _evaluate_having(node.right, group)
        if node.operator == "AND":
            if left is False or right is False:
                return False
            if left is None or right is None:
                return None
            return True
        if left is True or right is True:
            return True
        if left is None or right is None:
            return None
        return False
    if isinstance(node, ScalarIsNull):
        result = _evaluate_group_expression(node.expression, group) is None
        return not result if node.negated else result
    if isinstance(node, ScalarComparison):
        left = _evaluate_group_expression(node.left, group)
        right = _evaluate_group_expression(node.right, group)
        if left is None or right is None:
            return None
        try:
            if node.operator == "=":
                return left == right
            if node.operator == "!=":
                return left != right
            if node.operator == "<":
                return left < right
            if node.operator == "<=":
                return left <= right
            if node.operator == ">":
                return left > right
            if node.operator == ">=":
                return left >= right
        except TypeError:
            return False
    raise AssertionError(f"Unsupported HAVING node {node!r}")


def _apply_aggregate_query(records: Sequence[dict[str, Any]], query: Query) -> list[dict[str, Any]]:
    filtered = [record for record in records if evaluate(query.predicate, record) is True]
    grouped: list[tuple[tuple[Any, ...], list[dict[str, Any]]]] = []
    if query.group_by:
        by_key: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
        order: list[tuple[Any, ...]] = []
        for record in filtered:
            values = tuple(evaluate_scalar_expression(expr, record) for expr in query.group_by)
            key = tuple(_hashable_group_value(value) for value in values)
            if key not in by_key:
                by_key[key] = []
                order.append(key)
            by_key[key].append(record)
        grouped = [(key, by_key[key]) for key in order]
    else:
        grouped = [((), filtered)]

    surviving = [group for _, group in grouped if _evaluate_having(query.having, group) is True]

    for term in reversed(query.order_by):
        present = []
        missing = []
        for group in surviving:
            value = _evaluate_group_expression(term.expression, group) if term.expression is not None else None
            (missing if value is None else present).append((group, value))
        try:
            present.sort(key=lambda item: item[1], reverse=term.descending)
        except TypeError:
            present.sort(key=lambda item: str(item[1]), reverse=term.descending)
        surviving = [group for group, _ in present] + [group for group, _ in missing]

    rows: list[dict[str, Any]] = []
    for group in surviving:
        row: dict[str, Any] = {"_yt_sql_aggregate_result": True}
        for term in query.select:
            if term.expression is not None:
                row[term.output_name] = _evaluate_group_expression(term.expression, group)
            elif group:
                row[term.output_name] = canonical_record_value(group[0], term)
            else:
                row[term.output_name] = None
        rows.append(row)

    if query.distinct:
        seen: set[tuple[Any, ...]] = set()
        unique = []
        for row in rows:
            key = tuple(_hashable_group_value(row.get(term.output_name)) for term in query.select)
            if key in seen:
                continue
            seen.add(key)
            unique.append(row)
        rows = unique
    if query.offset:
        rows = rows[query.offset :]
    if query.limit is not None:
        rows = rows[: query.limit]
    return rows


def _apply_query_body(records: Sequence[dict[str, Any]], query: Query) -> list[dict[str, Any]]:
    if _aggregate_query(query):
        return _apply_aggregate_query(records, query)
    result = [record for record in records if evaluate(query.predicate, record) is True]

    # Python's stable sort preserves source order as the final implicit tie-breaker.
    # Sort from the last term backwards so each ORDER BY direction remains independent.
    for term in reversed(query.order_by):
        present = [record for record in result if canonical_record_value(record, term) is not None]
        missing = [record for record in result if canonical_record_value(record, term) is None]
        try:
            present.sort(key=lambda record: canonical_record_value(record, term), reverse=term.descending)
        except TypeError:
            # Mixed extractor data is intentionally not coerced for predicates. For ordering only,
            # a deterministic textual fallback is preferable to failing an otherwise useful query.
            present.sort(key=lambda record: str(canonical_record_value(record, term)), reverse=term.descending)
        result = present + missing

    if query.distinct:
        seen: set[tuple[Any, ...]] = set()
        distinct_records: list[dict[str, Any]] = []
        for record in result:
            key_values = []
            for term in query.select:
                value = canonical_record_value(record, term)
                try:
                    hash(value)
                    key_values.append(value)
                except TypeError:
                    key_values.append(repr(value))
            key = tuple(key_values)
            if key not in seen:
                seen.add(key)
                distinct_records.append(record)
        result = distinct_records

    if query.offset:
        result = result[query.offset :]
    if query.limit is not None:
        result = result[: query.limit]

    random_terms = [term for term in query.select if term.expression is not None and _contains_random(term.expression)]
    if random_terms:
        materialised = []
        for record in result:
            row = dict(record)
            for term in random_terms:
                row[term.output_name] = canonical_record_value(record, term)
            materialised.append(row)
        result = materialised
    return result


def _project_result_rows(records: Sequence[dict[str, Any]], query: Query) -> list[dict[str, Any]]:
    if _aggregate_query(query):
        return [
            {
                **{term.output_name: record.get(term.output_name) for term in query.select},
                "_yt_sql_result_row": True,
            }
            for record in records
        ]
    return [
        {
            **{term.output_name: canonical_record_value(record, term) for term in query.select},
            "_yt_sql_result_row": True,
        }
        for record in records
    ]


def _records_for_source(
    records: Sequence[dict[str, Any]],
    source_name: str | None,
    source_facet: str | None,
    relations: dict[str, list[dict[str, Any]]],
    physical_requests: tuple[tuple[str, str | None], ...],
) -> list[dict[str, Any]]:
    if source_name is not None and source_name.casefold() in relations:
        return relations[source_name.casefold()]
    if source_name is None or len(physical_requests) <= 1:
        return list(records)
    return [
        record
        for record in records
        if record.get("_yt_sql_source") == source_name and record.get("_yt_sql_source_facet") == source_facet
    ]


def _union_row_key(row: dict[str, Any], output_names: tuple[str, ...]) -> tuple[Any, ...]:
    values = []
    for name in output_names:
        value = row.get(name)
        try:
            hash(value)
            values.append(value)
        except TypeError:
            values.append(repr(value))
    return tuple(values)


def _apply_composed_query(
    records: Sequence[dict[str, Any]],
    query: Query,
    relations: dict[str, list[dict[str, Any]]],
    physical_requests: tuple[tuple[str, str | None], ...],
) -> list[dict[str, Any]]:
    if not query.set_operations:
        input_records = _records_for_source(records, query.from_source, query.from_facet, relations, physical_requests)
        return _apply_query_body(input_records, query)

    left_body = replace(query, set_operations=(), order_by=(), limit=None, offset=0, ctes=())
    left_input = _records_for_source(records, query.from_source, query.from_facet, relations, physical_requests)
    rows = _project_result_rows(_apply_query_body(left_input, left_body), left_body)
    output_names = tuple(term.output_name for term in query.select)

    for operation in query.set_operations:
        branch = operation.query
        branch_input = _records_for_source(records, branch.from_source, branch.from_facet, relations, physical_requests)
        branch_rows = _project_result_rows(_apply_query_body(branch_input, branch), branch)
        branch_names = tuple(term.output_name for term in branch.select)
        remapped = [
            {
                **{target: row.get(source) for target, source in zip(output_names, branch_names, strict=True)},
                "_yt_sql_result_row": True,
            }
            for row in branch_rows
        ]
        rows.extend(remapped)
        if not operation.all:
            seen: set[tuple[Any, ...]] = set()
            unique: list[dict[str, Any]] = []
            for row in rows:
                key = _union_row_key(row, output_names)
                if key in seen:
                    continue
                seen.add(key)
                unique.append(row)
            rows = unique

    # Global ORDER BY, OFFSET and LIMIT apply to the already materialised logical
    # result relation. Do not feed the first branch's aggregate SELECT terms back
    # through _apply_query_body(), because that would aggregate the UNION result a
    # second time rather than merely ordering/slicing it.
    for term in reversed(query.order_by):
        present = [row for row in rows if canonical_record_value(row, term) is not None]
        missing = [row for row in rows if canonical_record_value(row, term) is None]
        try:
            present.sort(key=lambda row: canonical_record_value(row, term), reverse=term.descending)
        except TypeError:
            present.sort(key=lambda row: str(canonical_record_value(row, term)), reverse=term.descending)
        rows = present + missing
    if query.offset:
        rows = rows[query.offset :]
    if query.limit is not None:
        rows = rows[: query.limit]
    return rows


def apply_query(records: Sequence[dict[str, Any]], query: Query) -> list[dict[str, Any]]:
    """Apply a resolved query, materialising CTEs and set-composed relations."""
    for record in records:
        record.pop("_yt_sql_random_cache", None)
    physical_requests = query_physical_source_requests(query)
    if not query.ctes:
        result = _apply_composed_query(records, query, {}, physical_requests)
    else:
        relations: dict[str, list[dict[str, Any]]] = {}
        for cte in query.ctes:
            cte_result = _apply_composed_query(records, cte.query, relations, physical_requests)
            relations[cte.name.casefold()] = (
                _project_result_rows(cte_result, cte.query)
                if not cte.query.set_operations
                else [dict(row) for row in cte_result]
            )
        result = _apply_composed_query(records, replace(query, ctes=()), relations, physical_requests)

    # Result-row markers are an internal execution detail used while materialising
    # CTEs and set operations. They must never escape through the public query API.
    execution_only_keys = {"_yt_sql_result_row", "_yt_sql_aggregate_result", "_yt_sql_random_cache"}
    return [{key: value for key, value in row.items() if key not in execution_only_keys} for row in result]


def merge_queries(base: Query, extra: Query) -> Query:
    predicate = base.predicate
    if extra.predicate is not None:
        predicate = extra.predicate if predicate is None else Binary("AND", predicate, extra.predicate)
    order_by = extra.order_by or base.order_by
    limit = extra.limit if extra.limit is not None else base.limit
    source = base.source or extra.source
    select = extra.select or base.select
    from_source = extra.from_source or base.from_source
    from_facet = extra.from_facet if extra.from_source is not None else base.from_facet
    distinct = extra.distinct or base.distinct
    offset = extra.offset if extra.offset else base.offset
    group_by = extra.group_by or base.group_by
    having = extra.having if extra.having is not None else base.having
    return Query(
        predicate,
        order_by,
        limit,
        source,
        select,
        from_source,
        distinct,
        offset,
        group_by,
        having,
        extra.ctes or base.ctes,
        extra.set_operations or base.set_operations,
        from_facet,
    )


def format_expression(node: Any) -> str:
    if isinstance(node, Field):
        return node.name
    if isinstance(node, Literal):
        if node.value is None:
            return "NULL"
        if isinstance(node.value, bool):
            return "TRUE" if node.value else "FALSE"
        return node.raw
    if isinstance(node, Unary):
        return f"NOT ({format_expression(node.operand)})"
    if isinstance(node, Binary):
        if node.operator in {"AND", "OR"}:
            return f"({format_expression(node.left)} {node.operator} {format_expression(node.right)})"
        return f"{format_expression(node.left)} {node.operator} {format_expression(node.right)}"
    if isinstance(node, Between):
        not_part = " NOT" if node.negated else ""
        return (
            f"{node.field.name}{not_part} BETWEEN {format_expression(node.lower)} AND {format_expression(node.upper)}"
        )
    if isinstance(node, InList):
        not_part = " NOT" if node.negated else ""
        values = ", ".join(format_expression(value) for value in node.values)
        return f"{node.field.name}{not_part} IN ({values})"
    if isinstance(node, IsNull):
        return f"{node.field.name} IS {'NOT ' if node.negated else ''}NULL"
    if isinstance(node, TextPredicate):
        not_part = " NOT" if node.negated else ""
        return f"{node.field.name}{not_part} {node.operator} {format_expression(node.value)}"
    if isinstance(node, ScalarComparison):
        return f"{format_scalar_expression(node.left)} {node.operator} {format_scalar_expression(node.right)}"
    if isinstance(node, ScalarIsNull):
        return f"{format_scalar_expression(node.expression)} IS {'NOT ' if node.negated else ''}NULL"
    raise AssertionError(f"Unsupported query node {node!r}")


def format_query(query: Query) -> str:
    parts: list[str] = []
    if query.ctes:
        cte_text = ", ".join(f"{cte.name} AS ({format_query(cte.query)})" for cte in query.ctes)
        parts.append(f"WITH {cte_text}")
    if query.select:
        parts.append(
            ("SELECT DISTINCT " if query.distinct else "SELECT ")
            + ", ".join(
                f"{term.field} AS {term.alias}" if term.alias and term.alias != term.field else term.field
                for term in query.select
            )
        )
    if query.from_source is not None:
        source = query.from_source
        if re.fullmatch(r"@[A-Za-z0-9_.-]+|[A-Za-z_][A-Za-z0-9_.-]*", source):
            parts.append(f"FROM {source}")
        else:
            escaped = source.replace("'", "''")
            parts.append(f"FROM '{escaped}'")
        if query.from_facet is not None:
            parts.append(f"OF {query.from_facet}")
    if query.predicate is not None:
        parts.append(f"WHERE {format_expression(query.predicate)}")
    if query.group_by:
        parts.append("GROUP BY " + ", ".join(format_scalar_expression(item) for item in query.group_by))
    if query.having is not None:
        parts.append(f"HAVING {format_expression(query.having)}")
    for operation in query.set_operations:
        parts.append(("UNION ALL " if operation.all else "UNION ") + format_query(operation.query))
    if query.order_by:
        parts.append(
            "ORDER BY " + ", ".join(f"{term.field} {'DESC' if term.descending else 'ASC'}" for term in query.order_by)
        )
    if query.limit is not None:
        parts.append(f"LIMIT {query.limit}")
    if query.offset:
        parts.append(f"OFFSET {query.offset}")
    return " ".join(parts) if parts else "<no projection, source, filtering, ordering, or limit>"


def _display_resolved_value(value: Any) -> str:
    """Render a typed resolved literal for human-facing explanations."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def explain_expression(node: Any) -> str:
    """Describe a parsed or resolved predicate in compact human-readable prose."""
    if isinstance(node, Unary):
        return f"NOT ({explain_expression(node.operand)})"
    if isinstance(node, Binary) and node.operator in {"AND", "OR"}:
        return f"({explain_expression(node.left)} {node.operator} {explain_expression(node.right)})"
    if isinstance(node, Binary):
        return f"{node.left.name} {node.operator} {_display_resolved_value(node.right.value)}"
    if isinstance(node, Between):
        wording = "is not between" if node.negated else "is between"
        return (
            f"{node.field.name} {wording} {_display_resolved_value(node.lower.value)} "
            f"and {_display_resolved_value(node.upper.value)}, inclusive"
        )
    if isinstance(node, InList):
        wording = "is not in" if node.negated else "is in"
        values = ", ".join(_display_resolved_value(item.value) for item in node.values)
        return f"{node.field.name} {wording} ({values})"
    if isinstance(node, IsNull):
        return f"{node.field.name} is {'not ' if node.negated else ''}NULL"
    if isinstance(node, TextPredicate):
        wording = f"does not {node.operator.casefold()}" if node.negated else node.operator.casefold()
        return f"{node.field.name} {wording} {_display_resolved_value(node.value.value)!r}"
    return format_expression(node)
