#!/usr/bin/env python3

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime


VERSION = "0.3.0"


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
        help="Experimental filter expression",
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


def match_expression_term(entry: dict[str, object], term: str) -> bool:
    term = term.strip()

    contains_match = re.fullmatch(
        r"(title|uploader)\s+contains\s+(.+)",
        term,
        flags=re.IGNORECASE,
    )
    if contains_match:
        field = contains_match.group(1).lower()
        expected = unquote(contains_match.group(2)).lower()
        if field == "title":
            value = entry.get("title")
        else:
            value = entry.get("uploader") or entry.get("channel")
        return isinstance(value, str) and expected in value.lower()

    duration_match = re.fullmatch(
        r"duration\s*(<=|>=|!=|=|<|>)\s*(\d+)",
        term,
        flags=re.IGNORECASE,
    )
    if duration_match:
        return compare_number(
            duration(entry),
            duration_match.group(1),
            int(duration_match.group(2)),
        )

    live_match = re.fullmatch(
        r"live\s*=\s*(true|false)",
        term,
        flags=re.IGNORECASE,
    )
    if live_match:
        actual = is_live(entry)
        expected = live_match.group(1).lower() == "true"
        return actual is not None and actual == expected

    date_match = re.fullmatch(
        r"date\s*(<=|>=|!=|=|<|>)\s*(\d{4}-\d{2}-\d{2})",
        term,
        flags=re.IGNORECASE,
    )
    if date_match:
        actual = upload_date(entry)
        if actual is None:
            return False
        expected = datetime.strptime(date_match.group(2), "%Y-%m-%d")
        operator = date_match.group(1)
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

    raise ValueError(f"unsupported filter term: {term}")


def matches_expression(entry: dict[str, object], expression: str) -> bool:
    terms = re.split(r"\s+and\s+", expression, flags=re.IGNORECASE)
    return all(match_expression_term(entry, term) for term in terms)


def matches(
    entry: dict[str, object],
    args: argparse.Namespace,
    after: datetime | None,
    before: datetime | None,
    title_pattern: re.Pattern[str] | None,
) -> bool:
    if args.where and not matches_expression(entry, args.where):
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

    try:
        entries = enumerate_source(args.source)
    except (RuntimeError, json.JSONDecodeError) as exc:
        print(f"could not enumerate source: {exc}", file=sys.stderr)
        return 1

    try:
        matches_found = [
            entry
            for entry in entries
            if matches(entry, args, after, before, title_pattern)
        ]
    except ValueError as exc:
        print(f"invalid filter expression: {exc}", file=sys.stderr)
        return 2

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
