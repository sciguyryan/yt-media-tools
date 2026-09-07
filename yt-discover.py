#!/usr/bin/env python3

import argparse
import json
import subprocess
import sys
from datetime import datetime


VERSION = "0.1.0"


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
        "--reverse",
        action="store_true",
        help="Print the oldest matching videos first",
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


def matches(
    entry: dict[str, object],
    after: datetime | None,
    before: datetime | None,
    title_text: str | None,
) -> bool:
    if title_text:
        title = entry.get("title")
        if not isinstance(title, str) or title_text.lower() not in title.lower():
            return False

    if after or before:
        date = upload_date(entry)
        if date is None:
            return False
        if after and date < after:
            return False
        if before and date > before:
            return False

    return True


def main() -> int:
    args = parse_args()

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
        entries = enumerate_source(args.source)
    except (RuntimeError, json.JSONDecodeError) as exc:
        print(f"could not enumerate source: {exc}", file=sys.stderr)
        return 1

    matches_found = [
        entry
        for entry in entries
        if matches(entry, after, before, args.title)
    ]

    if args.reverse:
        matches_found.reverse()

    for entry in matches_found:
        video_id = entry.get("id")
        if isinstance(video_id, str):
            print(video_id)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
