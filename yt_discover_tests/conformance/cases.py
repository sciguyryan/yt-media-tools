"""Independently authored yt-sql queries and Python semantic oracles."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any, Callable

from .oracle import OracleQuery, field

Rows = list[dict[str, Any]]
Oracle = Callable[[Rows], list[Any]]


@dataclass(frozen=True)
class ConformanceCase:
    name: str
    query: str
    oracle: Oracle
    columns: tuple[str, ...] = ("id",)
    output_format: str = "lines"
    params: tuple[str, ...] = ()
    profiles: tuple[str, ...] = ("small", "normal")


def _source_order(rows: Rows) -> list[Any]:
    return OracleQuery(rows).select(lambda r: r["id"]).take(10).to_list()


def _chronological(rows: Rows) -> list[Any]:
    return (
        OracleQuery(rows)
        .where(lambda r: r["upload_date"] is not None and "20260801" <= str(r["upload_date"]) <= "20260831")
        .where(lambda r: r["duration"] is not None and int(r["duration"]) < 3600)
        .order_by(lambda r: r["upload_date"])
        .then_by(lambda r: r["release_timestamp"])
        .select(lambda r: r["id"])
        .to_list()
    )


def _duration_boundary(rows: Rows) -> list[Any]:
    return (
        OracleQuery(rows)
        .where(lambda r: r["upload_date"] in {"20260830", "20260831"})
        .where(lambda r: r["duration"] is not None and int(r["duration"]) < 3600)
        .order_by(lambda r: r["release_timestamp"])
        .select(lambda r: r["id"])
        .to_list()
    )


def _timestamp_text(value: object) -> str | None:
    """Express the documented timestamp projection independently of production code."""
    if value is None:
        return None
    return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()


def _null_timestamp(rows: Rows) -> list[Any]:
    return (
        OracleQuery(rows)
        .where(lambda r: r["upload_date"] is not None and str(r["upload_date"]) >= "20260810")
        .order_by(lambda r: r["release_timestamp"])
        .select(lambda r: {"id": r["id"], "release_timestamp": _timestamp_text(r["release_timestamp"])})
        .to_list()
    )


def _distinct_titles(rows: Rows) -> list[Any]:
    return (
        OracleQuery(rows)
        .where(lambda r: r["title"] in {"Duplicate", "Case Test", "case test"})
        .order_by(lambda r: r["source_index"])
        .select(lambda r: r["title"])
        .distinct()
        .to_list()
    )


def _offset_limit(rows: Rows) -> list[Any]:
    return (
        OracleQuery(rows)
        .where(lambda r: r["view_count"] is not None)
        .order_by(lambda r: r["view_count"], descending=True)
        .select(lambda r: r["id"])
        .skip(3)
        .take(5)
        .to_list()
    )


def _contains(rows: Rows) -> list[Any]:
    return (
        OracleQuery(rows)
        .where(lambda r: r["title"] is not None and "mars" in str(r["title"]).casefold())
        .order_by(lambda r: r["upload_date"])
        .select(lambda r: {"id": r["id"], "title": r["title"]})
        .to_list()
    )


def _matches(rows: Rows) -> list[Any]:
    pattern = re.compile(r"^Mars|MARS")
    return (
        OracleQuery(rows)
        .where(lambda r: r["title"] is not None and pattern.search(str(r["title"])) is not None)
        .order_by(lambda r: r["source_index"])
        .select(lambda r: {"id": r["id"], "title": r["title"]})
        .to_list()
    )


def _null_boolean(rows: Rows) -> list[Any]:
    return (
        OracleQuery(rows)
        .where(lambda r: (r["view_count"] is None or r["view_count"] == 0) and not bool(r["is_live"]))
        .order_by(lambda r: r["source_index"])
        .select(lambda r: r["id"])
        .to_list()
    )


def _functions(rows: Rows) -> list[Any]:
    def projected(row: dict[str, Any]) -> dict[str, Any]:
        title = row["title"]
        return {
            "id": row["id"],
            "folded": None if title is None else str(title).lower(),
            "chars": None if title is None else len(str(title)),
            "views": row["view_count"] if row["view_count"] is not None else -1,
        }

    return (
        OracleQuery(rows)
        .where(lambda r: r["upload_date"] is not None and "20260822" <= str(r["upload_date"]) <= "20260824")
        .select(projected)
        .order_by(lambda r: r["folded"])
        .to_list()
    )


def _bound_parameters(rows: Rows) -> list[Any]:
    return (
        OracleQuery(rows)
        .where(lambda r: r["upload_date"] is not None and str(r["upload_date"]) >= "20260820")
        .where(lambda r: r["duration"] is not None and int(r["duration"]) < 1800)
        .order_by(lambda r: r["upload_date"])
        .then_by(lambda r: r["release_timestamp"])
        .select(lambda r: r["id"])
        .take(6)
        .to_list()
    )


def _count_enum(rows: Rows) -> list[Any]:
    return (
        OracleQuery(rows)
        .where(lambda r: r["view_count"] is not None and int(r["view_count"]) >= 1_000_000)
        .where(lambda r: r["availability"] is not None and str(r["availability"]).casefold() == "public")
        .order_by(lambda r: r["view_count"], descending=True)
        .then_by(lambda r: r["id"])
        .select(lambda r: {"id": r["id"], "view_count": r["view_count"], "availability": r["availability"]})
        .to_list()
    )


def _raw_dynamic(rows: Rows) -> list[Any]:
    return (
        OracleQuery(rows)
        .where(lambda r: field(r, "raw.fixture_group") in {1, 3})
        .order_by(lambda r: field(r, "raw.fixture_group"))
        .then_by(lambda r: r["source_index"])
        .select(lambda r: {"id": r["id"], "bucket": field(r, "raw.fixture_group")})
        .take(8)
        .to_list()
    )


def _convoluted(rows: Rows) -> list[Any]:
    def predicate(r: dict[str, Any]) -> bool:
        duration_branch = (
            r["duration"] is not None
            and 600 <= int(r["duration"]) <= 3600
            and (
                (r["title"] is not None and "mars" in str(r["title"]).casefold())
                or (r["view_count"] is not None and int(r["view_count"]) >= 1_000_000)
            )
        )
        null_branch = r["view_count"] is None and r["title"] is not None
        return (duration_branch or null_branch) and r["upload_date"] is not None

    return (
        OracleQuery(rows)
        .where(predicate)
        .order_by(lambda r: r["upload_date"], descending=True)
        .then_by(lambda r: r["release_timestamp"])
        .select(lambda r: {"id": r["id"], "folded": str(r["title"]).lower()})
        .distinct()
        .skip(1)
        .take(9)
        .to_list()
    )


CASES = (
    ConformanceCase("source_order_limit", "SELECT id FROM @yt_sql_fixture LIMIT 10", _source_order),
    ConformanceCase(
        "chronological_same_day_subsort",
        "SELECT id FROM @yt_sql_fixture WHERE upload_date BETWEEN 2026-08-01 AND 2026-08-31 AND duration < 1h ORDER BY upload_date ASC, release_timestamp ASC",
        _chronological,
    ),
    ConformanceCase(
        "duration_boundary",
        "SELECT id FROM @yt_sql_fixture WHERE upload_date BETWEEN 2026-08-30 AND 2026-08-31 AND duration < 1h ORDER BY release_timestamp ASC",
        _duration_boundary,
    ),
    ConformanceCase(
        "null_timestamp_last",
        "SELECT id, release_timestamp FROM @yt_sql_fixture WHERE upload_date >= 2026-08-10 ORDER BY release_timestamp ASC",
        _null_timestamp,
        ("id", "release_timestamp"),
        "jsonl",
    ),
    ConformanceCase(
        "distinct_projection",
        "SELECT DISTINCT title FROM @yt_sql_fixture WHERE title IN ('Duplicate', 'Case Test', 'case test') ORDER BY source_index ASC",
        _distinct_titles,
        ("title",),
    ),
    ConformanceCase(
        "offset_limit",
        "SELECT id FROM @yt_sql_fixture WHERE view_count IS NOT NULL ORDER BY view_count DESC LIMIT 5 OFFSET 3",
        _offset_limit,
    ),
    ConformanceCase(
        "contains_case_insensitive",
        "SELECT id, title FROM @yt_sql_fixture WHERE title CONTAINS 'mars' ORDER BY upload_date ASC",
        _contains,
        ("id", "title"),
        "tsv",
    ),
    ConformanceCase(
        "matches_regex",
        "SELECT id, title FROM @yt_sql_fixture WHERE title MATCHES '^Mars|MARS' ORDER BY source_index ASC",
        _matches,
        ("id", "title"),
        "jsonl",
    ),
    ConformanceCase(
        "null_and_boolean_logic",
        "SELECT id FROM @yt_sql_fixture WHERE (view_count IS NULL OR view_count = 0) AND NOT is_live ORDER BY source_index ASC",
        _null_boolean,
    ),
    ConformanceCase(
        "scalar_functions_and_alias_order",
        "SELECT id, LOWER(title) AS folded, LENGTH(title) AS chars, COALESCE(view_count, -1) AS views FROM @yt_sql_fixture WHERE upload_date BETWEEN 2026-08-22 AND 2026-08-24 ORDER BY folded ASC",
        _functions,
        ("id", "folded", "chars", "views"),
        "jsonl",
    ),
    ConformanceCase(
        "bound_parameters",
        "SELECT id FROM @yt_sql_fixture WHERE upload_date >= :start AND duration < :maximum ORDER BY upload_date ASC, release_timestamp ASC LIMIT 6",
        _bound_parameters,
        params=("start=2026-08-20", "maximum=30m"),
    ),
    ConformanceCase(
        "count_suffix_and_enum_case",
        "SELECT id, view_count, availability FROM @yt_sql_fixture WHERE view_count >= 1m AND availability = 'PUBLIC' ORDER BY view_count DESC, id ASC",
        _count_enum,
        ("id", "view_count", "availability"),
        "csv",
    ),
    ConformanceCase(
        "raw_dynamic_field",
        "SELECT id, raw.fixture_group AS bucket FROM @yt_sql_fixture WHERE raw.fixture_group IN (1, 3) ORDER BY raw.fixture_group ASC, source_index ASC LIMIT 8",
        _raw_dynamic,
        ("id", "bucket"),
        "tsv",
    ),
    ConformanceCase(
        "convoluted_existing_language",
        "SELECT DISTINCT id, LOWER(title) AS folded FROM @yt_sql_fixture WHERE ((duration BETWEEN 10m AND 1h AND (title CONTAINS 'mars' OR view_count >= 1m)) OR (view_count IS NULL AND title IS NOT NULL)) AND upload_date IS NOT NULL ORDER BY upload_date DESC, release_timestamp ASC LIMIT 9 OFFSET 1",
        _convoluted,
        ("id", "folded"),
        "jsonl",
    ),
)
