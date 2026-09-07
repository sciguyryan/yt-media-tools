#!/usr/bin/env python3

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime


VERSION = "0.5.0"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Discover video IDs from a YouTube channel or playlist.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )
    parser.add_argument("source", help="YouTube channel or playlist URL")
    parser.add_argument(
        "--after",
        help="Only include videos uploaded on or after YYYY-MM-DD",
    )
    parser.add_argument(
        "--before",
        help="Only include videos uploaded on or before YYYY-MM-DD",
    )
    parser.add_argument(
        "--title",
        help="Only include videos whose title contains this text",
    )
    parser.add_argument(
        "--title-regex",
        help="Only include videos whose title matches this regular expression",
    )
    parser.add_argument(
        "--uploader",
        help="Only include videos whose uploader contains this text",
    )
    parser.add_argument(
        "--min-duration",
        type=int,
        help="Only include videos at least this many seconds long",
    )
    parser.add_argument(
        "--max-duration",
        type=int,
        help="Only include videos at most this many seconds long",
    )
    parser.add_argument(
        "--live",
        choices=("yes", "no"),
        help="Only include or exclude entries marked as live",
    )
    parser.add_argument(
        "--sort",
        choices=("source", "date", "title", "duration"),
        default="source",
        help="Sort matching entries before printing them",
    )
    parser.add_argument(
        "--reverse",
        action="store_true",
        help="Reverse the selected output order",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Print at most this many matching IDs",
    )
    parser.add_argument(
        "--where",
        help="YT-SQL filter expression",
    )
    parser.add_argument(
        "--query",
        help="Complete YT-SQL query statement",
    )
    return parser.parse_args()


def parse_date(value: str | None) -> datetime | None:
    if value is None:
        return None

    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"invalid date {value!r}; expected YYYY-MM-DD") from exc


def enumerate_source(source: str) -> list[dict[str, object]]:
    command = [
        "yt-dlp",
        "--flat-playlist",
        "--dump-single-json",
        source,
    ]

    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or "yt-dlp failed"
        raise RuntimeError(message)

    data = json.loads(completed.stdout)
    entries = data.get("entries") or []
    return [entry for entry in entries if isinstance(entry, dict)]


def upload_date(entry: dict[str, object]) -> datetime | None:
    value = entry.get("upload_date")
    if not isinstance(value, str):
        return None

    try:
        return datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return None


def duration(entry: dict[str, object]) -> int | None:
    value = entry.get("duration")
    if isinstance(value, (int, float)):
        return int(value)
    return None


def is_live(entry: dict[str, object]) -> bool | None:
    value = entry.get("live_status")
    if value in {"is_live", "was_live"}:
        return True
    if isinstance(value, str):
        return False

    value = entry.get("is_live")
    if isinstance(value, bool):
        return value

    return None



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
        # Early YT-SQL keeps AND and OR at the same precedence.
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
            value = self.take()
            return ("contains", field, unquote(value))

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
        if field == "title":
            value = entry.get("title")
        else:
            value = entry.get("uploader") or entry.get("channel")
        return isinstance(value, str) and expected.lower() in value.lower()

    if kind == "duration":
        _, operator, expected = node
        return compare_number(duration(entry), operator, expected)

    if kind == "date":
        _, operator, expected = node
        actual = upload_date(entry)
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

    if kind == "live":
        actual = is_live(entry)
        return actual is not None and actual == node[1]

    raise ValueError(f"unknown expression node: {kind}")



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

    select_text = match.group("select").strip()
    fields = [field.strip().lower() for field in select_text.split(",") if field.strip()]
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
    if limit is not None and limit < 1:
        raise ValueError("LIMIT must be at least 1")

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
        return duration(entry)
    if field == "date":
        value = upload_date(entry)
        return value.strftime("%Y-%m-%d") if value else None
    if field == "live":
        return is_live(entry)
    raise ValueError(f"unknown field: {field}")


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


def matches(
    entry: dict[str, object],
    args: argparse.Namespace,
    after: datetime | None,
    before: datetime | None,
    title_pattern: re.Pattern[str] | None,
    where_expression,
) -> bool:
    if where_expression is not None and not evaluate_expression(entry, where_expression):
        return False

    title = entry.get("title")

    if args.title:
        if not isinstance(title, str) or args.title.lower() not in title.lower():
            return False

    if title_pattern:
        if not isinstance(title, str) or not title_pattern.search(title):
            return False

    if args.uploader:
        uploader = entry.get("uploader") or entry.get("channel")
        if (
            not isinstance(uploader, str)
            or args.uploader.lower() not in uploader.lower()
        ):
            return False

    if after or before:
        date = upload_date(entry)
        if date is None:
            return False
        if after and date < after:
            return False
        if before and date > before:
            return False

    entry_duration = duration(entry)
    if args.min_duration is not None:
        if entry_duration is None or entry_duration < args.min_duration:
            return False
    if args.max_duration is not None:
        if entry_duration is None or entry_duration > args.max_duration:
            return False

    if args.live is not None:
        entry_live = is_live(entry)
        wanted_live = args.live == "yes"
        if entry_live is None or entry_live != wanted_live:
            return False

    return True


def sort_key(entry: dict[str, object], field: str) -> object:
    if field == "date":
        return upload_date(entry) or datetime.min
    if field == "title":
        title = entry.get("title")
        return title.lower() if isinstance(title, str) else ""
    if field == "duration":
        return duration(entry) or -1
    return 0


def validate_args(args: argparse.Namespace) -> str | None:
    if args.min_duration is not None and args.min_duration < 0:
        return "--min-duration cannot be negative"
    if args.max_duration is not None and args.max_duration < 0:
        return "--max-duration cannot be negative"
    if (
        args.min_duration is not None
        and args.max_duration is not None
        and args.min_duration > args.max_duration
    ):
        return "--min-duration cannot be greater than --max-duration"
    if args.limit is not None and args.limit < 1:
        return "--limit must be at least 1"
    return None


def main() -> int:
    args = parse_args()

    error = validate_args(args)
    if error:
        print(error, file=sys.stderr)
        return 2

    try:
        after = parse_date(args.after)
        before = parse_date(args.before)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    if after and before and after > before:
        print("--after cannot be later than --before", file=sys.stderr)
        return 2

    try:
        title_pattern = re.compile(args.title_regex, re.IGNORECASE) if args.title_regex else None
    except re.error as exc:
        print(f"invalid title regular expression: {exc}", file=sys.stderr)
        return 2

    if args.query and args.where:
        print("--query and --where cannot be used together", file=sys.stderr)
        return 2

    query = None
    try:
        if args.query:
            query = parse_query_statement(args.query)
            where_expression = query["where"]
        else:
            where_expression = parse_expression(args.where) if args.where else None
    except ValueError as exc:
        print(f"invalid YT-SQL: {exc}", file=sys.stderr)
        return 2

    try:
        entries = enumerate_source(args.source)
    except (RuntimeError, json.JSONDecodeError) as exc:
        print(f"could not enumerate source: {exc}", file=sys.stderr)
        return 1

    matches_found = [
        entry
        for entry in entries
        if matches(entry, args, after, before, title_pattern, where_expression)
    ]

    if query is not None:
        query_limit = query["limit"]
        if query_limit is not None:
            matches_found = matches_found[:query_limit]

        order_field = query["order"]
        if order_field is not None:
            matches_found.sort(
                key=lambda entry: query_sort_key(entry, order_field),
                reverse=query["direction"] == "desc",
            )

        for entry in matches_found:
            print_row(entry, query["fields"])
        return 0

    if args.sort != "source":
        matches_found.sort(key=lambda entry: sort_key(entry, args.sort))

    if args.reverse:
        matches_found.reverse()

    if args.limit is not None:
        matches_found = matches_found[: args.limit]

    for entry in matches_found:
        video_id = entry.get("id")
        if isinstance(video_id, str):
            print(video_id)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
