from __future__ import annotations

import re
from datetime import datetime


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def compare_number(actual: int | None, operator: str, expected: int) -> bool:
    if actual is None:
        return False
    if operator == "=":
        return actual == expected
    if operator == "!=":
        return actual != expected
    if operator == ">":
        return actual > expected
    if operator == ">=":
        return actual >= expected
    if operator == "<":
        return actual < expected
    if operator == "<=":
        return actual <= expected
    raise ValueError(f"unsupported numeric operator: {operator}")


def tokenise_expression(expression: str) -> list[str]:
    tokens: list[str] = []
    token = ""
    quote: str | None = None
    index = 0

    while index < len(expression):
        char = expression[index]

        if quote is not None:
            token += char
            if char == quote:
                quote = None
            index += 1
            continue

        if char in {"'", '"'}:
            token += char
            quote = char
            index += 1
            continue

        if char.isspace():
            if token:
                tokens.append(token)
                token = ""
            index += 1
            continue

        if char in "()":
            if token:
                tokens.append(token)
                token = ""
            tokens.append(char)
            index += 1
            continue

        if char in "<>!=":
            if token:
                tokens.append(token)
                token = ""
            operator = char
            if index + 1 < len(expression) and expression[index + 1] == "=":
                operator += "="
                index += 1
            tokens.append(operator)
            index += 1
            continue

        token += char
        index += 1

    if quote is not None:
        raise ValueError("unterminated quoted value")
    if token:
        tokens.append(token)

    return tokens


class ExpressionParser:
    def __init__(self, tokens: list[str]):
        self.tokens = tokens
        self.index = 0

    def current(self) -> str | None:
        if self.index >= len(self.tokens):
            return None
        return self.tokens[self.index]

    def take(self) -> str:
        token = self.current()
        if token is None:
            raise ValueError("unexpected end of expression")
        self.index += 1
        return token

    def parse(self):
        expression = self.parse_boolean_chain()
        if self.current() is not None:
            raise ValueError(f"unexpected token: {self.current()}")
        return expression

    def parse_boolean_chain(self):
        node = self.parse_unary()
        while True:
            token = self.current()
            if token is None or token.lower() not in {"and", "or"}:
                return node
            operator = self.take().lower()
            right = self.parse_unary()
            node = (operator, node, right)

    def parse_unary(self):
        token = self.current()
        if token is not None and token.lower() == "not":
            self.take()
            return ("not", self.parse_unary())

        if token == "(":
            self.take()
            node = self.parse_boolean_chain()
            if self.take() != ")":
                raise ValueError("expected closing parenthesis")
            return node

        return self.parse_term()

    def parse_term(self):
        field = self.take().lower()

        if field in {"title", "uploader"}:
            operator = self.take().lower()
            if operator != "contains":
                raise ValueError(f"unsupported operator for {field}: {operator}")
            return ("contains", field, unquote(self.take()))

        if field == "duration":
            operator = self.take()
            if operator not in {"=", "!=", "<", "<=", ">", ">="}:
                raise ValueError(f"unsupported duration operator: {operator}")
            value = self.take()
            if not value.isdigit():
                raise ValueError("duration comparison requires a whole number")
            return ("duration", operator, int(value))

        if field == "date":
            operator = self.take()
            if operator not in {"=", "!=", "<", "<=", ">", ">="}:
                raise ValueError(f"unsupported date operator: {operator}")
            value = self.take()
            try:
                parsed = datetime.strptime(value, "%Y-%m-%d")
            except ValueError as exc:
                raise ValueError("date comparison requires YYYY-MM-DD") from exc
            return ("date", operator, parsed)

        if field == "live":
            if self.take() != "=":
                raise ValueError("live only supports =")
            value = self.take().lower()
            if value not in {"true", "false"}:
                raise ValueError("live comparison requires true or false")
            return ("live", value == "true")

        raise ValueError(f"unknown field: {field}")


def parse_expression(expression: str):
    tokens = tokenise_expression(expression)
    if not tokens:
        raise ValueError("expression cannot be empty")
    return ExpressionParser(tokens).parse()


def parse_query_statement(query: str) -> dict[str, object]:
    match = re.fullmatch(
        r"""\s*select\s+(?P<select>.+?)
        (?:\s+where\s+(?P<where>.+?))?
        (?:\s+order\s+by\s+(?P<order>[a-z_]+)(?:\s+(?P<direction>asc|desc))?)?
        (?:\s+limit\s+(?P<limit>\d+))?
        \s*""",
        query,
        flags=re.IGNORECASE | re.VERBOSE,
    )
    if not match:
        raise ValueError("expected SELECT with optional WHERE, ORDER BY and LIMIT")

    fields = [field.strip().lower() for field in match.group("select").split(",") if field.strip()]
    if not fields:
        raise ValueError("SELECT requires at least one field")

    allowed_fields = {"id", "title", "uploader", "duration", "date", "live"}
    unknown = [field for field in fields if field not in allowed_fields]
    if unknown:
        raise ValueError(f"unknown SELECT field: {unknown[0]}")

    order_field = match.group("order")
    if order_field is not None:
        order_field = order_field.lower()
        if order_field not in allowed_fields:
            raise ValueError(f"unknown ORDER BY field: {order_field}")

    limit_text = match.group("limit")
    limit = int(limit_text) if limit_text is not None else None

    where_text = match.group("where")
    where_expression = parse_expression(where_text) if where_text else None

    return {
        "fields": fields,
        "where": where_expression,
        "order": order_field,
        "direction": (match.group("direction") or "asc").lower(),
        "limit": limit,
    }


def field_value(entry: dict[str, object], field: str) -> object:
    if field == "id":
        return entry.get("id")
    if field == "title":
        return entry.get("title")
    if field == "uploader":
        return entry.get("uploader") or entry.get("channel")
    if field == "duration":
        value = entry.get("duration")
        return int(value) if isinstance(value, (int, float)) else None
    if field == "date":
        value = entry.get("upload_date")
        if isinstance(value, str):
            try:
                return datetime.strptime(value, "%Y%m%d").strftime("%Y-%m-%d")
            except ValueError:
                return None
        return None
    if field == "live":
        value = entry.get("live_status")
        if value in {"is_live", "was_live"}:
            return True
        if isinstance(value, str):
            return False
        value = entry.get("is_live")
        return value if isinstance(value, bool) else None
    raise ValueError(f"unknown field: {field}")


def evaluate_expression(entry: dict[str, object], node) -> bool:
    kind = node[0]
    if kind == "and":
        return evaluate_expression(entry, node[1]) and evaluate_expression(entry, node[2])
    if kind == "or":
        return evaluate_expression(entry, node[1]) or evaluate_expression(entry, node[2])
    if kind == "not":
        return not evaluate_expression(entry, node[1])
    if kind == "contains":
        _, field, expected = node
        value = field_value(entry, field)
        return isinstance(value, str) and expected.lower() in value.lower()
    if kind == "duration":
        _, operator, expected = node
        return compare_number(field_value(entry, "duration"), operator, expected)
    if kind == "date":
        _, operator, expected = node
        actual_text = field_value(entry, "date")
        if not isinstance(actual_text, str):
            return False
        actual = datetime.strptime(actual_text, "%Y-%m-%d")
        return compare_number(int(actual.timestamp()), operator, int(expected.timestamp()))
    if kind == "live":
        actual = field_value(entry, "live")
        return actual is not None and actual == node[1]
    raise ValueError(f"unknown expression node: {kind}")


def query_sort_key(entry: dict[str, object], field: str) -> tuple[bool, object]:
    value = field_value(entry, field)
    if isinstance(value, str):
        value = value.lower()
    return (value is None, value if value is not None else "")


def print_row(entry: dict[str, object], fields: list[str]) -> None:
    values = [field_value(entry, field) for field in fields]
    if len(values) == 1:
        value = values[0]
        print("" if value is None else value)
        return
    print("\t".join("" if value is None else str(value) for value in values))
