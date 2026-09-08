"""Shared yt-sql query language for yt-dlp metadata records."""

from __future__ import annotations

import difflib
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
from .schema import QuerySchema, raw_path_value
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
class Query:
    predicate: Any | None = None
    order_by: tuple[OrderTerm, ...] = ()
    limit: int | None = None
    source: str = ""
    select: tuple[SelectTerm, ...] = ()
    from_source: str | None = None
    distinct: bool = False
    offset: int = 0


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
  | (?P<NUMBER>(?:\d{1,3}(?:,\d{3})+(?!\d)|\d[\d_]*)(?:\.\d+)?(?:[kKmMbB])?)
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

    def parse_query(self, where_only: bool = False) -> Query:
        predicate = None
        order_by: tuple[OrderTerm, ...] = ()
        limit = None
        select: tuple[SelectTerm, ...] = ()
        from_source: str | None = None
        distinct = False
        offset = 0

        if where_only:
            if self.current.kind != "EOF":
                predicate = self.parse_or()
        else:
            if self.consume_keyword("SELECT"):
                distinct = bool(self.consume_keyword("DISTINCT"))
                select = self.parse_select_list()

            if self.consume_keyword("FROM"):
                from_source = self.parse_from_source()

            if self.consume_keyword("WHERE"):
                if (
                    self.current.kind == "EOF"
                    or self.keyword("ORDER")
                    or self.keyword("LIMIT")
                    or self.keyword("OFFSET")
                ):
                    raise QuerySyntaxError(self.source, "WHERE requires an expression.", self.current.position)
                predicate = self.parse_or()
            elif (
                not self.keyword("ORDER")
                and not self.keyword("LIMIT")
                and not self.keyword("OFFSET")
                and self.current.kind != "EOF"
            ):
                if select or from_source is not None:
                    raise QuerySyntaxError(
                        self.source, "Expected WHERE, ORDER BY, LIMIT, OFFSET, or end of query.", self.current.position
                    )
                predicate = self.parse_or()

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

        if self.current.kind != "EOF":
            raise QuerySyntaxError(self.source, f"Unexpected token {self.current.text!r}.", self.current.position)
        return Query(predicate, order_by, limit, self.source, select, from_source, distinct, offset)

    def parse_select_list(self) -> tuple[SelectTerm, ...]:
        terms: list[SelectTerm] = []
        while True:
            if self.current.kind == "STAR":
                raise QuerySyntaxError(
                    self.source,
                    "SELECT * is not supported because yt-dlp metadata is dynamic; name the scalar fields you want.",
                    self.current.position,
                )
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
            return Literal(_generic_literal(token.text, False), token.text, token.position, False)
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

    def parse_scalar_function(self, name_token: Token) -> ScalarFunction:
        name = name_token.text.upper()
        if name not in {"LOWER", "UPPER", "LENGTH", "COALESCE", "CHAR"}:
            raise QuerySyntaxError(
                self.source, f"Unsupported scalar function {name_token.text!r}.", name_token.position
            )
        self.expect("LPAREN", "Expected '(' after function name.")
        args: list[Any] = []
        if self.current.kind != "RPAREN":
            while True:
                self._split_grouped_number_at_function_boundary()
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
        return ScalarFunction(name, tuple(args), name_token.position)

    def _split_grouped_number_at_function_boundary(self) -> None:
        """Treat commas inside a numeric token as function argument separators.

        yt-sql accepts comma-grouped numbers in ordinary value positions, but scalar
        function calls use commas as argument separators. Inside a call the latter is
        unambiguous and follows conventional function syntax, so ``CHAR(65,66)`` must
        parse as two arguments even though the context-free lexer can otherwise see a
        grouped numeric token.
        """
        token = self.current
        if token.kind != "NUMBER" or "," not in token.text:
            return
        parts = token.text.split(",")
        replacement: list[Token] = []
        offset = 0
        for index, part in enumerate(parts):
            replacement.append(Token("NUMBER", part, token.position + offset, _generic_literal(part, False)))
            offset += len(part)
            if index != len(parts) - 1:
                replacement.append(Token("COMMA", ",", token.position + offset))
                offset += 1
        self.tokens[self.index : self.index + 1] = replacement

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
                stop_keywords={"AND", "OR", "ORDER", "LIMIT", "OFFSET", "THEN", "WHEN", "ELSE", "END"}
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
            {"AND", "OR", "ORDER", "LIMIT", "OFFSET", "THEN", "WHEN", "ELSE", "END"}
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


def _parse_count_text(text: str, source: str, position: int) -> int:
    cleaned = text.replace("_", "").replace(",", "").strip()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([kKmMbB]?)", cleaned)
    if not match:
        raise QuerySyntaxError(source, f"Could not understand count {text!r}.", position)
    multiplier = {"": 1, "k": 1_000, "m": 1_000_000, "b": 1_000_000_000}[match.group(2).lower()]
    return round(float(match.group(1)) * multiplier)


def _parse_number_text(text: str, source: str, position: int) -> int | float:
    cleaned = re.sub(r"\s+", "", text.replace("_", "").replace(",", ""))
    if re.fullmatch(r"[+-]?\d+", cleaned):
        return int(cleaned)
    if re.fullmatch(r"[+-]?(?:\d+\.\d*|\d*\.\d+)", cleaned):
        return float(cleaned)
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


def _generic_literal(text: str, quoted: bool) -> Any:
    if quoted:
        return text
    lowered = text.casefold()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    cleaned = re.sub(r"\s+", "", text.replace("_", "").replace(",", ""))
    if re.fullmatch(r"[+-]?\d+", cleaned):
        return int(cleaned)
    if re.fullmatch(r"[+-]?\d+\.\d+", cleaned):
        return float(cleaned)
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
    if isinstance(expression, ScalarCase):
        parts = ["CASE"]
        for branch in expression.whens:
            parts.append(f"WHEN {format_expression(branch.condition)} THEN {format_scalar_expression(branch.result)}")
        if expression.else_result is not None:
            parts.append(f"ELSE {format_scalar_expression(expression.else_result)}")
        parts.append("END")
        return " ".join(parts)
    raise AssertionError(f"Unsupported scalar expression {expression!r}")


def format_scalar_function(function: ScalarFunction) -> str:
    """Compatibility wrapper for callers that format a scalar function directly."""
    return format_scalar_expression(function)


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
        else:
            non_null_kinds = [kind for arg in args if (kind := _scalar_kind(arg)) is not None]
            result_kind = (
                non_null_kinds[0] if non_null_kinds and all(k == non_null_kinds[0] for k in non_null_kinds) else "mixed"
            )
        return ScalarFunction(expression.name, args, expression.position, result_kind)
    raise AssertionError(f"Unsupported scalar expression {expression!r}")


def _resolve_scalar_function(
    function: ScalarFunction, schema: QuerySchema, source: str, dates: DateContext
) -> ScalarFunction:
    """Compatibility wrapper around general scalar-expression resolution."""
    resolved = _resolve_scalar_expression(function, schema, source, dates)
    assert isinstance(resolved, ScalarFunction)
    return resolved


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
        raise AssertionError(f"Unsupported scalar function {expression.name}")
    raise AssertionError(f"Unsupported scalar expression {expression!r}")


def evaluate_scalar_function(function: ScalarFunction, record: dict[str, Any]) -> Any:
    """Compatibility wrapper for scalar function evaluation."""
    return evaluate_scalar_expression(function, record)


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


def resolve_query(query: Query, schema: QuerySchema, dates: DateContext | None = None) -> Query:
    """Resolve fields and typed literals after metadata has established a schema."""
    context = dates or DateContext()
    source = query.source

    predicate = _resolve_predicate(query.predicate, schema, source, context)

    select_terms: list[SelectTerm] = []
    effective_select = query.select or (SelectTerm("id"),)
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

    return Query(
        predicate,
        tuple(order_terms),
        query.limit,
        source,
        tuple(select_terms),
        query.from_source,
        query.distinct,
        query.offset,
    )


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


def apply_query(records: Sequence[dict[str, Any]], query: Query) -> list[dict[str, Any]]:
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
    return result


def merge_queries(base: Query, extra: Query) -> Query:
    predicate = base.predicate
    if extra.predicate is not None:
        predicate = extra.predicate if predicate is None else Binary("AND", predicate, extra.predicate)
    order_by = extra.order_by or base.order_by
    limit = extra.limit if extra.limit is not None else base.limit
    source = base.source or extra.source
    select = extra.select or base.select
    from_source = extra.from_source or base.from_source
    distinct = extra.distinct or base.distinct
    offset = extra.offset if extra.offset else base.offset
    return Query(predicate, order_by, limit, source, select, from_source, distinct, offset)


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
    raise AssertionError(f"Unsupported query node {node!r}")


def format_query(query: Query) -> str:
    parts: list[str] = []
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
    if query.predicate is not None:
        parts.append(f"WHERE {format_expression(query.predicate)}")
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
