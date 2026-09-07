#!/usr/bin/env python3

import argparse
import pathlib
import re
import sqlite3
import sys
from datetime import UTC, datetime

from yt_cache import (
    DEFAULT_MAX_AGE,
    append_new_entries,
    connect,
    load_source,
    source_status,
    store_source,
    update_entries,
)
from yt_metadata import normalise_entries
from yt_planner import acquisition_limit, execution_analysis, explain_plan, plan_query
from yt_query import evaluate_expression, parse_expression, parse_query_statement, print_row, query_sort_key
from yt_sources import backend_status, enumerate_source, fetch_details


VERSION = "0.17.0"


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
        "--analyse-execution",
        action="store_true",
        help="Explain whether source acquisition can safely stop early",
    )
    parser.add_argument(
        "--list-backends",
        action="store_true",
        help="Show available source backends and exit",
    )
    parser.add_argument(
        "--cache",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().with_name("discover-cache.sqlite3"),
        help="SQLite metadata cache path",
    )
    parser.add_argument(
        "--cache-max-age",
        type=int,
        default=DEFAULT_MAX_AGE,
        help="Maximum cache age in seconds",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable reading and writing the metadata cache",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore cached source metadata and refresh it",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Refresh a cached newest-first source by appending only entries before a confirmed overlap",
    )
    parser.add_argument(
        "--refresh-details",
        action="store_true",
        help="Refresh detailed metadata for incomplete cached entries",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use cached metadata only and never contact a source backend",
    )
    parser.add_argument(
        "--cache-status",
        action="store_true",
        help="Show cached source status before execution",
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
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="Bind a named YT-SQL parameter; may be repeated",
    )
    parser.add_argument(
        "--show-provenance",
        action="store_true",
        help="Show whether the result came from cache or live acquisition",
    )
    return parser.parse_args()


def parse_params(values: list[str]) -> dict[str, object]:
    params: dict[str, object] = {}
    for item in values:
        if "=" not in item:
            raise ValueError(f"invalid parameter binding: {item}")
        name, raw = item.split("=", 1)
        name = name.strip()
        if not name:
            raise ValueError("parameter name cannot be empty")
        text = raw.strip()
        lowered = text.lower()
        if lowered == "null":
            value: object = None
        elif lowered == "true":
            value = True
        elif lowered == "false":
            value = False
        else:
            try:
                value = int(text)
            except ValueError:
                try:
                    value = float(text)
                except ValueError:
                    value = text
        if name in params:
            raise ValueError(f"duplicate parameter binding: {name}")
        params[name] = value
    return params


def parse_date(value: str | None) -> datetime | None:
    if value is None:
        return None

    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError as exc:
        raise ValueError(f"invalid date {value!r}; expected YYYY-MM-DD") from exc


def upload_date(entry: dict[str, object]) -> datetime | None:
    value = entry.get("date")
    if not isinstance(value, str):
        return None

    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
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
    query_params: dict[str, object] | None = None,
) -> bool:
    if where_expression is not None and not evaluate_expression(entry, where_expression, query_params):
        return False

    title = entry.get("title")

    if args.title and (not isinstance(title, str) or args.title.lower() not in title.lower()):
        return False

    if title_pattern and (not isinstance(title, str) or not title_pattern.search(title)):
        return False

    if args.uploader:
        uploader = entry.get("uploader") or entry.get("channel")
        if not isinstance(uploader, str) or args.uploader.lower() not in uploader.lower():
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
    if args.min_duration is not None and (entry_duration is None or entry_duration < args.min_duration):
        return False
    if args.max_duration is not None and (entry_duration is None or entry_duration > args.max_duration):
        return False

    if args.live is not None:
        entry_live = is_live(entry)
        wanted_live = args.live == "yes"
        if entry_live is None or entry_live != wanted_live:
            return False

    return True


def sort_key(entry: dict[str, object], field: str) -> object:
    if field == "date":
        return upload_date(entry) or datetime.min.replace(tzinfo=UTC)
    if field == "title":
        title = entry.get("title")
        return title.lower() if isinstance(title, str) else ""
    if field == "duration":
        return duration(entry) or -1
    return 0


def validate_args(args: argparse.Namespace) -> str | None:
    if args.offline and args.no_cache:
        return "--offline cannot be combined with --no-cache"
    if args.offline and args.refresh:
        return "--offline cannot be combined with --refresh"
    if args.offline and args.incremental:
        return "--offline cannot be combined with --incremental"
    if args.refresh and args.incremental:
        return "--refresh cannot be combined with --incremental"
    if args.incremental and args.no_cache:
        return "--incremental requires the metadata cache"
    if args.offline and args.refresh_details:
        return "--offline cannot be combined with --refresh-details"
    if args.min_duration is not None and args.min_duration < 0:
        return "--min-duration cannot be negative"
    if args.max_duration is not None and args.max_duration < 0:
        return "--max-duration cannot be negative"
    if args.min_duration is not None and args.max_duration is not None and args.min_duration > args.max_duration:
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
        query_params = parse_params(args.param)
        if args.query:
            query = parse_query_statement(args.query)
            where_expression = query["where"]
        else:
            where_expression = parse_expression(args.where) if args.where else None
    except ValueError as exc:
        print(f"invalid YT-SQL: {exc}", file=sys.stderr)
        return 2

    cache_connection = None
    cached_status = None
    raw_entries = None

    try:
        if not args.no_cache:
            cache_connection = connect(args.cache)
            cached_status = source_status(
                cache_connection,
                args.source,
                max_age=args.cache_max_age,
            )
            raw_entries = load_source(
                cache_connection,
                args.source,
                max_age=args.cache_max_age,
                allow_stale=args.offline,
            )

        plan = plan_query(
            query=query,
            where_expression=where_expression,
            requested_backend=args.source_backend,
            cache_status=(cached_status if raw_entries is not None and not args.incremental else None),
            offline=args.offline,
        )

        if args.explain:
            print(explain_plan(plan), file=sys.stderr)

        if args.show_provenance:
            backend = plan.get("backend") or "unknown"
            print(f"provenance: mode={plan['mode']} backend={backend}", file=sys.stderr)

        source_limit = acquisition_limit(
            query,
            where_expression,
            str(plan["backend"]) if plan["mode"] == "live" else None,
        )

        if args.analyse_execution:
            analysis = execution_analysis(
                query,
                where_expression,
                str(plan["backend"]) if plan["mode"] == "live" else None,
            )
            if analysis["acquisition_limit"] is None:
                print("acquisition: full source required", file=sys.stderr)
            else:
                print(
                    f"acquisition: bounded to {analysis['acquisition_limit']} source entries",
                    file=sys.stderr,
                )
            print(f"proof: {analysis['proof']}", file=sys.stderr)

        if args.cache_status:
            if cached_status is None:
                print("cache: no entry for source", file=sys.stderr)
            else:
                freshness = "fresh" if cached_status["fresh"] else "stale"
                backend = cached_status["backend"] or "unknown"
                print(
                    f"cache: {freshness}, {cached_status['entry_count']} entries, "
                    f"age {cached_status['age']}s, backend {backend}",
                    file=sys.stderr,
                )

        if args.incremental:
            if cache_connection is None:
                raise RuntimeError("incremental refresh requires the metadata cache")
            observed_entries = enumerate_source(args.source, str(plan["backend"]))
            raw_entries, appended = append_new_entries(
                cache_connection,
                args.source,
                observed_entries,
                backend=str(plan["backend"]),
            )
            print(
                f"incremental refresh: appended {appended} new entr{'y' if appended == 1 else 'ies'}",
                file=sys.stderr,
            )
        elif plan["mode"] == "live":
            if args.refresh or raw_entries is None:
                raw_entries = enumerate_source(
                    args.source,
                    str(plan["backend"]),
                    limit=source_limit,
                )
                if cache_connection is not None:
                    store_source(
                        cache_connection,
                        args.source,
                        raw_entries,
                        backend=str(plan["backend"]),
                    )

        if raw_entries is None:
            raise RuntimeError("no source metadata is available")

        entries = normalise_entries(raw_entries)

        if args.refresh_details:
            incomplete_ids = [
                str(entry["id"])
                for entry in entries
                if entry.get("id")
                and any(entry.get(field) is None for field in ("title", "uploader", "duration", "date", "live"))
            ]
            if incomplete_ids:
                detailed = fetch_details(incomplete_ids, str(plan["backend"]))
                if cache_connection is not None:
                    update_entries(cache_connection, args.source, detailed)
                by_id = {str(entry.get("id")): entry for entry in raw_entries if entry.get("id")}
                for detail in detailed:
                    if detail.get("id"):
                        by_id[str(detail["id"])] = detail
                raw_entries = [by_id.get(str(entry.get("id")), entry) for entry in raw_entries]
                entries = normalise_entries(raw_entries)
    except (RuntimeError, OSError, sqlite3.Error) as exc:
        print(f"could not acquire source metadata: {exc}", file=sys.stderr)
        return 1
    finally:
        if cache_connection is not None:
            cache_connection.close()

    matches_found = [
        entry for entry in entries if matches(entry, args, after, before, title_pattern, where_expression, query_params)
    ]

    if query is not None:
        order_field = query["order"]
        if order_field is not None:
            matches_found.sort(
                key=lambda entry: query_sort_key(entry, order_field),
                reverse=query["direction"] == "desc",
            )

        if query["distinct"]:
            seen: set[tuple[object, ...]] = set()
            distinct_entries: list[dict[str, object]] = []
            from yt_query import projection_value

            for entry in matches_found:
                key = tuple(projection_value(entry, field) for field in query["fields"])
                if key in seen:
                    continue
                seen.add(key)
                distinct_entries.append(entry)
            matches_found = distinct_entries

        query_offset = query["offset"]
        if query_offset:
            matches_found = matches_found[query_offset:]

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
