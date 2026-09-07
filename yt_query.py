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


def split_projection_list(text: str) -> list[str]:
    parts: list[str] = []
    token = ""
    depth = 0
    quote: str | None = None
    for char in text:
        if quote is not None:
            token += char
            if char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
            token += char
            continue
        if char == "(":
            depth += 1
            token += char
            continue
        if char == ")":
            depth -= 1
            if depth < 0:
                raise ValueError("unbalanced projection parentheses")
            token += char
            continue
        if char == "," and depth == 0:
            if not token.strip():
                raise ValueError("empty SELECT expression")
            parts.append(token.strip())
            token = ""
            continue
        token += char
    if quote is not None or depth != 0:
        raise ValueError("unterminated SELECT expression")
    if token.strip():
        parts.append(token.strip())
    return parts


def parse_projection(expression: str):
    expression = expression.strip()
    lowered = expression.lower()
    allowed_fields = {"id", "title", "uploader", "duration", "date", "live"}
    if lowered in allowed_fields:
        return ("field", lowered)

    match = re.fullmatch(r"(?P<name>lower|upper|length|coalesce)\((?P<args>.*)\)", expression, re.IGNORECASE)
    if not match:
        raise ValueError(f"unknown SELECT expression: {expression}")
    name = match.group("name").lower()
    args = [parse_projection(arg) if arg.strip().lower() in allowed_fields or re.match(r"^(lower|upper|length|coalesce)\(", arg.strip(), re.I) else ("literal", unquote(arg.strip())) for arg in split_projection_list(match.group("args"))]
    if name in {"lower", "upper", "length"} and len(args) != 1:
        raise ValueError(f"{name.upper()} requires exactly one argument")
    if name == "coalesce" and not args:
        raise ValueError("COALESCE requires at least one argument")
    return ("function", name, args)


def projection_label(node) -> str:
    if node[0] == "field":
        return node[1]
    if node[0] == "literal":
        return str(node[1])
    return f"{node[1].upper()}({', '.join(projection_label(arg) for arg in node[2])})"


def projection_value(entry: dict[str, object], node) -> object:
    if node[0] == "field":
        return field_value(entry, node[1])
    if node[0] == "literal":
        return node[1]
    _, name, args = node
    values = [projection_value(entry, arg) for arg in args]
    if name == "lower":
        return None if values[0] is None else str(values[0]).lower()
    if name == "upper":
        return None if values[0] is None else str(values[0]).upper()
    if name == "length":
        return None if values[0] is None else len(str(values[0]))
    if name == "coalesce":
        return next((value for value in values if value is not None), None)
    raise ValueError(f"unknown scalar function: {name}")


def parse_query_statement(query: str) -> dict[str, object]:
    match = re.fullmatch(
        r"""\s*select\s+(?P<distinct>distinct\s+)?(?P<select>.+?)
        (?:\s+where\s+(?P<where>.+?))?
        (?:\s+order\s+by\s+(?P<order>[a-z_]+)(?:\s+(?P<direction>asc|desc))?)?
        (?:\s+limit\s+(?P<limit>\d+))?
        (?:\s+offset\s+(?P<offset>\d+))?
        \s*""",
        query,
        flags=re.IGNORECASE | re.VERBOSE,
    )
    if not match:
        raise ValueError("expected SELECT with optional DISTINCT, WHERE, ORDER BY, LIMIT and OFFSET")

    projection_text = split_projection_list(match.group("select"))
    if not projection_text:
        raise ValueError("SELECT requires at least one expression")
    fields = [parse_projection(item) for item in projection_text]

    allowed_fields = {"id", "title", "uploader", "duration", "date", "live"}
    order_field = match.group("order")
    if order_field is not None:
        order_field = order_field.lower()
        if order_field not in allowed_fields:
            raise ValueError(f"unknown ORDER BY field: {order_field}")

    where_text = match.group("where")
    return {
        "fields": fields,
        "where": parse_expression(where_text) if where_text else None,
        "order": order_field,
        "direction": (match.group("direction") or "asc").lower(),
        "limit": int(match.group("limit")) if match.group("limit") else None,
        "offset": int(match.group("offset")) if match.group("offset") else 0,
        "distinct": match.group("distinct") is not None,
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


def resolve_parameter(value: object, params: dict[str, object] | None) -> object:
    if isinstance(value, str) and value.startswith(":"):
        name = value[1:]
        if not params or name not in params:
            raise ValueError(f"missing query parameter: {name}")
        return params[name]
    return value


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


def evaluate_expression(entry: dict[str, object], node, params: dict[str, object] | None = None) -> bool:
    kind = node[0]

    if kind == "and":
        return evaluate_expression(entry, node[1], params) and evaluate_expression(entry, node[2], params)
    if kind == "or":
        return evaluate_expression(entry, node[1], params) or evaluate_expression(entry, node[2], params)
    if kind == "not":
        return not evaluate_expression(entry, node[1], params)

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
        resolved_expected = resolve_parameter(expected_text, params)
        expected = coerce_value(field, resolved_expected)
        if expected is None and resolved_expected is not None:
            raise ValueError(f"could not coerce value for {field}: {resolved_expected}")
        return compare_values(actual, operator, expected)

    if kind == "between":
        _, field, lower_text, upper_text = node
        actual = coerce_value(field, field_value(entry, field))
        lower_raw = resolve_parameter(unquote(lower_text), params)
        upper_raw = resolve_parameter(unquote(upper_text), params)
        lower = coerce_value(field, lower_raw)
        upper = coerce_value(field, upper_raw)
        if actual is None or lower is None or upper is None:
            return False
        return lower <= actual <= upper

    if kind == "in":
        _, field, raw_values = node
        actual = coerce_value(field, field_value(entry, field))
        expected_values = [coerce_value(field, resolve_parameter(value, params)) for value in raw_values]
        return actual in expected_values

    raise ValueError(f"unknown expression node: {kind}")



def query_sort_key(entry: dict[str, object], field: str) -> tuple[bool, object]:
    value = field_value(entry, field)
    if isinstance(value, str):
        value = value.lower()
    return (value is None, value if value is not None else "")


def print_row(entry: dict[str, object], fields: list[object]) -> None:
    values = [projection_value(entry, field) for field in fields]
    if len(values) == 1:
        value = values[0]
        print("" if value is None else value)
        return
    print("\t".join("" if value is None else str(value) for value in values))
