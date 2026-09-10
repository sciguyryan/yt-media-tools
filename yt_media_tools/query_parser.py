"""Lexical analysis and recursive-descent parsing for yt-sql."""

from __future__ import annotations

import re
from typing import Any

from .query_formatter import format_scalar_expression
from .query_model import (
    AggregateFunction,
    Between,
    Binary,
    CaseWhen,
    CommonTableExpression,
    Field,
    InList,
    IsNull,
    Literal,
    OrderTerm,
    Query,
    QuerySyntaxError,
    ScalarBinary,
    ScalarCase,
    ScalarComparison,
    ScalarFunction,
    ScalarIsNull,
    ScalarUnary,
    SelectTerm,
    SetOperation,
    TextPredicate,
    Token,
    Unary,
)


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

_DECIMAL_INTEGER_RE = re.compile(r"[+-]?\d+(?:_\d+)*")

_DECIMAL_NUMBER_RE = re.compile(r"[+-]?\d+(?:_\d+)*(?:\.(?:\d+(?:_\d+)*))?")

_BASE_INTEGER_RE = re.compile(r"(?P<sign>[+-]?)(?P<prefix>0[xX]|0[oO]|0[bB])(?P<digits>[0-9A-Za-z]+(?:_[0-9A-Za-z]+)*)")

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

def _parse_number_text(text: str, source: str, position: int) -> int | float:
    compact = re.sub(r"\s+", "", text)
    if re.match(r"[+-]?0[xXoObB]", compact):
        return _parse_integer_literal_text(compact, source, position)
    if _DECIMAL_INTEGER_RE.fullmatch(compact):
        return int(compact.replace("_", ""), 10)
    if _DECIMAL_NUMBER_RE.fullmatch(compact) and "." in compact:
        return float(compact.replace("_", ""))
    raise QuerySyntaxError(source, f"Could not understand numeric value {text!r}.", position)

def _parse_generic_numeric_literal(text: str, source: str, position: int) -> int | float:
    """Parse a numeric token whose field type is not yet known."""
    return _parse_number_text(text, source, position)

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
                if self.current.kind == "RPAREN":
                    raise QuerySyntaxError(self.source, "CTE query cannot be empty.", self.current.position)
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
