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
        allowed_fields = {"id", "title", "uploader", "duration", "date", "live"}
        if field not in allowed_fields:
            raise ValueError(f"unknown field: {field}")

        operator = self.take().lower()

        if operator == "is":
            if self.current() is not None and self.current().lower() == "not":
                self.take()
                if self.take().lower() != "null":
                    raise ValueError("expected NULL after IS NOT")
                return ("is_not_null", field)
            if self.take().lower() != "null":
                raise ValueError("expected NULL after IS")
            return ("is_null", field)

        if operator == "between":
            lower = self.take()
            if self.take().lower() != "and":
                raise ValueError("BETWEEN requires AND")
            upper = self.take()
            return ("between", field, lower, upper)

        if operator == "in":
            if self.take() != "(":
                raise ValueError("IN requires a parenthesised value list")
            values: list[str] = []
            while True:
                token = self.take()
                if token == ")":
                    break
                if token.endswith(","):
                    values.append(unquote(token[:-1]))
                elif self.current() == ")":
                    values.append(unquote(token))
                else:
                    values.append(unquote(token.rstrip(",")))
                if self.current() == ")":
                    self.take()
                    break
            if not values:
                raise ValueError("IN requires at least one value")
            return ("in", field, values)

        if operator in {"contains", "matches"}:
            if field not in {"title", "uploader", "id"}:
                raise ValueError(f"{operator.upper()} is not supported for {field}")
            return (operator, field, unquote(self.take()))

        if operator not in {"=", "!=", "<", "<=", ">", ">="}:
            raise ValueError(f"unsupported operator for {field}: {operator}")

        value = self.take()
        return ("compare", field, operator, unquote(value))


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
    if field in {"id", "title", "uploader", "duration", "date", "live"}:
        return entry.get(field)
    raise ValueError(f"unknown field: {field}")


def coerce_value(field: str, value: object) -> object:
    if value is None:
        return None

    if field == "duration":
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return None

    if field == "date":
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            for fmt in ("%Y-%m-%d", "%Y%m%d"):
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    pass
        return None

    if field == "live":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.lower()
            if lowered in {"true", "yes", "1"}:
                return True
            if lowered in {"false", "no", "0"}:
                return False
        return None

    return str(value)


def compare_values(actual: object, operator: str, expected: object) -> bool:
    if actual is None:
        # Early YT-SQL treats NULL as unequal to ordinary values.
        return operator == "!="

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
    raise ValueError(f"unsupported comparison operator: {operator}")


def evaluate_expression(entry: dict[str, object], node) -> bool:
    kind = node[0]

    if kind == "and":
        return evaluate_expression(entry, node[1]) and evaluate_expression(entry, node[2])
    if kind == "or":
        return evaluate_expression(entry, node[1]) or evaluate_expression(entry, node[2])
    if kind == "not":
        return not evaluate_expression(entry, node[1])

    if kind == "is_null":
        return field_value(entry, node[1]) is None
    if kind == "is_not_null":
        return field_value(entry, node[1]) is not None

    if kind == "contains":
        _, field, expected = node
        value = field_value(entry, field)
        return isinstance(value, str) and expected.lower() in value.lower()

    if kind == "matches":
        _, field, expected = node
        value = field_value(entry, field)
        if not isinstance(value, str):
            return False
        try:
            return re.search(expected, value, flags=re.IGNORECASE) is not None
        except re.error as exc:
            raise ValueError(f"invalid regular expression: {exc}") from exc

    if kind == "compare":
        _, field, operator, expected_text = node
        actual = coerce_value(field, field_value(entry, field))
        expected = coerce_value(field, expected_text)
        if expected is None and expected_text is not None:
            raise ValueError(f"could not coerce value for {field}: {expected_text}")
        return compare_values(actual, operator, expected)

    if kind == "between":
        _, field, lower_text, upper_text = node
        actual = coerce_value(field, field_value(entry, field))
        lower = coerce_value(field, unquote(lower_text))
        upper = coerce_value(field, unquote(upper_text))
        if actual is None or lower is None or upper is None:
            return False
        return lower <= actual <= upper

    if kind == "in":
        _, field, raw_values = node
        actual = coerce_value(field, field_value(entry, field))
        expected_values = [coerce_value(field, value) for value in raw_values]
        return actual in expected_values

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
