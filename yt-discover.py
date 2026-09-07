#!/usr/bin/env python3

import argparse
import re
import sys
from datetime import datetime

from yt_metadata import normalise_entries
from yt_planner import explain_plan, plan_query
from yt_query import evaluate_expression, field_value, parse_expression, parse_query_statement, print_row, query_sort_key
from yt_sources import backend_status, enumerate_source


VERSION = "0.10.1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Discover video IDs from a YouTube channel or playlist.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )
    parser.add_argument("source", nargs="?", help="YouTube channel or playlist URL")
    parser.add_argument(
        "--source-backend",
        choices=("auto", "yt-dlp", "youtubejs"),
        default="auto",
        help="Source enumeration backend",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="Explain the query acquisition plan before execution",
    )
    parser.add_argument(
        "--list-backends",
        action="store_true",
        help="Show available source backends and exit",
    )
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



def upload_date(entry: dict[str, object]) -> datetime | None:
    value = entry.get("date")
    if not isinstance(value, str):
        return None

    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None


def duration(entry: dict[str, object]) -> int | None:
    value = entry.get("duration")
    return value if isinstance(value, int) else None


def is_live(entry: dict[str, object]) -> bool | None:
    value = entry.get("live")
    return value if isinstance(value, bool) else None




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

    if args.list_backends:
        for name, available, detail in backend_status():
            state = "available" if available else "unavailable"
            print(f"{name}: {state} ({detail})")
        return 0

    if not args.source:
        print("source is required unless --list-backends is used", file=sys.stderr)
        return 2

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
        plan = plan_query(
            query=query,
            where_expression=where_expression,
            requested_backend=args.source_backend,
        )
    except RuntimeError as exc:
        print(f"could not plan query: {exc}", file=sys.stderr)
        return 1

    if args.explain:
        print(explain_plan(plan), file=sys.stderr)

    try:
        raw_entries = enumerate_source(args.source, plan["backend"])
        entries = normalise_entries(raw_entries)
    except RuntimeError as exc:
        print(f"could not enumerate source: {exc}", file=sys.stderr)
        return 1

    matches_found = [
        entry
        for entry in entries
        if matches(entry, args, after, before, title_pattern, where_expression)
    ]

    if query is not None:
        order_field = query["order"]
        if order_field is not None:
            matches_found.sort(
                key=lambda entry: query_sort_key(entry, order_field),
                reverse=query["direction"] == "desc",
            )

        query_limit = query["limit"]
        if query_limit is not None:
            matches_found = matches_found[:query_limit]

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
