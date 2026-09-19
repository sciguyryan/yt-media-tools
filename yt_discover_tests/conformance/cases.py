"""Independently authored yt-sql queries and Python semantic oracles."""

from __future__ import annotations

import hashlib
import json
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
    cli_args: tuple[str, ...] = ()
    features: tuple[str, ...] = ()
    execution: str = "engine"


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


def _like_prefix(rows: Rows) -> list[Any]:
    return (
        OracleQuery(rows)
        .where(lambda r: r["title"] is not None and str(r["title"]).startswith("Mars"))
        .order_by(lambda r: r["source_index"])
        .select(lambda r: {"id": r["id"], "title": r["title"]})
        .to_list()
    )


def _ilike_contains(rows: Rows) -> list[Any]:
    pattern = re.compile(r"[\s\S]*mars[\s\S]*", re.IGNORECASE)
    return (
        OracleQuery(rows)
        .where(lambda r: r["title"] is not None and pattern.fullmatch(str(r["title"])) is not None)
        .order_by(lambda r: r["source_index"])
        .select(lambda r: r["id"])
        .to_list()
    )


def _like_single(rows: Rows) -> list[Any]:
    pattern = re.compile(r"Mars[\s\S]mission")
    return (
        OracleQuery(rows)
        .where(lambda r: r["title"] is not None and pattern.fullmatch(str(r["title"])) is not None)
        .order_by(lambda r: r["source_index"])
        .select(lambda r: r["id"])
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


def _scalar_arithmetic(rows: Rows) -> list[Any]:
    def minutes(row: dict[str, Any]) -> float | None:
        value = row["duration"]
        return None if value is None else int(value) / 60

    def score(row: dict[str, Any]) -> int | None:
        value = row["view_count"]
        return None if value is None else (int(value) + 10) * 2

    return (
        OracleQuery(rows)
        .where(lambda r: int(r["source_index"]) <= 16)
        .order_by(minutes, descending=True)
        .then_by(score)
        .select(lambda r: {"id": r["id"], "minutes": minutes(r), "score": score(r)})
        .to_list()
    )


def _scalar_nested_functions(rows: Rows) -> list[Any]:
    def adjusted(row: dict[str, Any]) -> int:
        value = row["view_count"]
        return 0 if value is None else int(value) + 1

    return (
        OracleQuery(rows)
        .where(lambda r: int(r["source_index"]) <= 12)
        .order_by(lambda r: adjusted(r), descending=True)
        .select(
            lambda r: {
                "id": r["id"],
                "adjusted": adjusted(r),
                "chars": None if r["title"] is None else len(str(r["title"]).lower()),
            }
        )
        .to_list()
    )


def _nullif_projection(rows: Rows) -> list[Any]:
    return (
        OracleQuery(rows)
        .where(lambda r: int(r["source_index"]) <= 6)
        .order_by(lambda r: r["source_index"])
        .select(
            lambda r: {
                "id": r["id"],
                "same": None,
                "distinct": "é",
                "null_second": r["title"],
            }
        )
        .to_list()
    )


def _greatest_projection(rows: Rows) -> list[Any]:
    return (
        OracleQuery(rows)
        .where(lambda r: int(r["source_index"]) <= 6)
        .order_by(lambda r: r["source_index"])
        .select(lambda r: {"id": r["id"], "numeric": 32, "unicode": max("é", "e\u0301", "ß")})
        .to_list()
    )


def _least_projection(rows: Rows) -> list[Any]:
    return (
        OracleQuery(rows)
        .where(lambda r: int(r["source_index"]) <= 6)
        .order_by(lambda r: r["source_index"])
        .select(lambda r: {"id": r["id"], "numeric": 3, "unicode": min("β", "α", "Ω")})
        .to_list()
    )


def _concat_projection(rows: Rows) -> list[Any]:
    return (
        OracleQuery(rows)
        .where(lambda r: int(r["source_index"]) <= 4)
        .order_by(lambda r: r["source_index"])
        .select(lambda r: {"annotated": None if r["title"] is None else f"{r['id']} # {r['title']}"})
        .to_list()
    )


def _char_projection(rows: Rows) -> list[Any]:
    return (
        OracleQuery(rows)
        .where(lambda r: int(r["source_index"]) <= 4)
        .order_by(lambda r: r["source_index"])
        .select(lambda r: {"id": r["id"], "chars": "Aβ😀", "decomposed": "e\u0301"})
        .to_list()
    )


def _mixed_base_projection(rows: Rows) -> list[Any]:
    return OracleQuery(rows).order_by(lambda r: r["source_index"]).take(1).select(lambda r: 36).to_list()


def _scalar_constant_folding(rows: Rows) -> list[Any]:
    return (
        OracleQuery(rows)
        .where(lambda r: int(r["source_index"]) <= 5)
        .order_by(lambda r: r["source_index"])
        .select(
            lambda r: {
                "id": r["id"],
                "zero": 0,
                "precedence": 7,
                "lowered": "abc",
                "fallback": 17,
                "division_by_zero": None,
            }
        )
        .to_list()
    )


def _case_bucket(rows: Rows) -> list[Any]:
    def bucket(row: dict[str, Any]) -> str:
        duration = row["duration"]
        if duration is not None and int(duration) < 600:
            return "short"
        if duration is not None and int(duration) < 3600:
            return "medium"
        return "long"

    return (
        OracleQuery(rows)
        .where(lambda r: int(r["source_index"]) <= 20)
        .order_by(lambda r: r["source_index"])
        .select(lambda r: {"id": r["id"], "bucket": bucket(r)})
        .to_list()
    )


def _case_null_fallthrough(rows: Rows) -> list[Any]:
    def state(row: dict[str, Any]) -> str:
        value = row["view_count"]
        if value is None:
            return "missing"
        if int(value) >= 1_000_000:
            return "popular"
        return "ordinary"

    return (
        OracleQuery(rows)
        .where(lambda r: int(r["source_index"]) <= 24)
        .order_by(lambda r: r["source_index"])
        .select(lambda r: {"id": r["id"], "state": state(r)})
        .to_list()
    )


def _case_without_else(rows: Rows) -> list[Any]:
    return (
        OracleQuery(rows)
        .where(lambda r: int(r["source_index"]) <= 16)
        .order_by(lambda r: r["source_index"])
        .select(
            lambda r: {
                "id": r["id"],
                "flag": 1 if r["duration"] is not None and int(r["duration"]) < 600 else None,
            }
        )
        .to_list()
    )


def _case_nested_result(rows: Rows) -> list[Any]:
    def score(row: dict[str, Any]) -> int | None:
        if row["view_count"] is None:
            title = row["title"]
            return None if title is None else len(str(title).lower())
        return (int(row["view_count"]) + 2) * 3

    return (
        OracleQuery(rows)
        .where(lambda r: int(r["source_index"]) <= 16)
        .order_by(lambda r: r["source_index"])
        .select(lambda r: {"id": r["id"], "score": score(r)})
        .to_list()
    )


def _case_ordering(rows: Rows) -> list[Any]:
    def bucket(row: dict[str, Any]) -> int:
        duration = row["duration"]
        if duration is not None and int(duration) < 600:
            return 1
        if duration is not None and int(duration) < 3600:
            return 2
        return 3

    return (
        OracleQuery(rows)
        .where(lambda r: int(r["source_index"]) <= 20)
        .order_by(bucket)
        .then_by(lambda r: r["source_index"])
        .select(lambda r: r["id"])
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


def _ids_where(
    predicate: Callable[[dict[str, Any]], bool],
    *,
    order: tuple[tuple[str, bool], ...] = (("source_index", False),),
    skip: int = 0,
    take: int | None = None,
) -> Oracle:
    """Build an independent ID oracle from explicit collection semantics."""

    def oracle(rows: Rows) -> list[Any]:
        query = OracleQuery(rows).where(predicate)
        if order:
            first_name, first_descending = order[0]
            query.order_by(lambda row, name=first_name: field(row, name), descending=first_descending)
            for name, descending in order[1:]:
                query.then_by(lambda row, name=name: field(row, name), descending=descending)
        query = query.select(lambda row: row["id"])
        if skip:
            query.skip(skip)
        if take is not None:
            query.take(take)
        return query.to_list()

    return oracle


def _project_where(
    predicate: Callable[[dict[str, Any]], bool],
    projector: Callable[[dict[str, Any]], Any],
    *,
    order: tuple[tuple[str, bool], ...] = (("source_index", False),),
    distinct: bool = False,
    skip: int = 0,
    take: int | None = None,
) -> Oracle:
    """Build an independent projection oracle without interpreting yt-sql text."""

    def oracle(rows: Rows) -> list[Any]:
        query = OracleQuery(rows).where(predicate)
        if order:
            first_name, first_descending = order[0]
            query.order_by(lambda row, name=first_name: field(row, name), descending=first_descending)
            for name, descending in order[1:]:
                query.then_by(lambda row, name=name: field(row, name), descending=descending)
        projected = query.select(projector)
        if distinct:
            projected.distinct()
        if skip:
            projected.skip(skip)
        if take is not None:
            projected.take(take)
        return projected.to_list()

    return oracle


def _unicode_exact_normalisation(rows: Rows) -> list[Any]:
    wanted = {"Café composed é", "Café decomposed é"}
    return (
        OracleQuery(rows)
        .where(lambda r: r["title"] in wanted)
        .order_by(lambda r: r["source_index"])
        .select(lambda r: {"id": r["id"], "title": r["title"]})
        .to_list()
    )


def _unicode_lengths(rows: Rows) -> list[Any]:
    wanted = {"vid037", "vid038", "vid040", "vid041", "vid042", "vid043", "vid056", "vid059", "vid060"}
    return (
        OracleQuery(rows)
        .where(lambda r: r["id"] in wanted)
        .order_by(lambda r: r["source_index"])
        .select(lambda r: {"id": r["id"], "chars": len(str(r["title"]))})
        .to_list()
    )


def _unicode_contains_casefold(rows: Rows) -> list[Any]:
    return (
        OracleQuery(rows)
        .where(lambda r: r["title"] is not None and "strasse" in str(r["title"]).casefold())
        .order_by(lambda r: r["source_index"])
        .select(lambda r: r["id"])
        .to_list()
    )


def _unicode_like_single_codepoint(rows: Rows) -> list[Any]:
    pattern = re.compile(r"Emoji [\s\S]")
    return (
        OracleQuery(rows)
        .where(lambda r: r["title"] is not None and pattern.fullmatch(str(r["title"])) is not None)
        .order_by(lambda r: r["source_index"])
        .select(lambda r: r["id"])
        .to_list()
    )


def _unicode_ilike_specials(rows: Rows) -> list[Any]:
    pattern = re.compile(r"[\s\S]*[isk][\s\S]*", re.IGNORECASE)
    wanted = {"vid045", "vid047", "vid048"}
    return (
        OracleQuery(rows)
        .where(lambda r: r["id"] in wanted and pattern.fullmatch(str(r["title"])) is not None)
        .order_by(lambda r: r["source_index"])
        .select(lambda r: r["id"])
        .to_list()
    )


def _unicode_case_functions(rows: Rows) -> list[Any]:
    wanted = {"vid044", "vid045", "vid046", "vid047", "vid048"}
    return (
        OracleQuery(rows)
        .where(lambda r: r["id"] in wanted)
        .order_by(lambda r: r["source_index"])
        .select(lambda r: {"id": r["id"], "lowered": str(r["title"]).lower(), "uppered": str(r["title"]).upper()})
        .to_list()
    )


def _unicode_regex_scripts(rows: Rows) -> list[Any]:
    pattern = re.compile(r"東京|مرحبا|שלום")
    return (
        OracleQuery(rows)
        .where(lambda r: r["title"] is not None and pattern.search(str(r["title"])) is not None)
        .order_by(lambda r: r["source_index"])
        .select(lambda r: r["id"])
        .to_list()
    )


def _unicode_codepoint_order(rows: Rows) -> list[Any]:
    wanted = {"vid044", "vid045", "vid046", "vid047", "vid048", "vid049", "vid050", "vid051"}
    return (
        OracleQuery(rows)
        .where(lambda r: r["id"] in wanted)
        .order_by(lambda r: r["title"])
        .select(lambda r: r["id"])
        .to_list()
    )


SELECT_STAR_COLUMNS = (
    "id",
    "title",
    "upload_date",
    "duration",
    "view_count",
    "like_count",
    "comment_count",
    "channel_follower_count",
    "playlist_index",
    "source_index",
    "uploader",
    "uploader_id",
    "channel",
    "channel_id",
    "live_status",
    "availability",
    "is_live",
    "was_live",
    "webpage_url",
    "playlist_id",
    "playlist_title",
    "timestamp",
    "release_timestamp",
    "modified_timestamp",
    "fixture_group",
    "fixture_nullable",
)


def _select_star_projection(rows: Rows) -> list[Any]:
    """Express the documented SELECT * contract independently of production schema code."""

    def project(row: dict[str, Any]) -> dict[str, Any]:
        result = {column: row.get(column) for column in SELECT_STAR_COLUMNS}
        upload_date = result["upload_date"]
        if upload_date is not None:
            text = str(upload_date)
            result["upload_date"] = f"{text[:4]}-{text[4:6]}-{text[6:8]}"
        for column in ("timestamp", "release_timestamp", "modified_timestamp"):
            result[column] = _timestamp_text(result[column])
        return result

    return OracleQuery(rows).where(lambda r: r["id"] == "vid001").select(project).to_list()


def _cte_chained_projection(rows: Rows) -> list[Any]:
    first = [r for r in rows if r.get("duration") is not None and int(r["duration"]) < 3600]
    projected = [{"id": r["id"], "title": r.get("title"), "minutes": (int(r["duration"]) / 60)} for r in first]
    second = [r for r in projected if r["title"] is not None and "mars" in str(r["title"]).casefold()]
    second.sort(key=lambda r: r["minutes"], reverse=True)
    return [{"id": r["id"], "minutes": r["minutes"]} for r in second[:7]]


def _union_distinct(rows: Rows) -> list[Any]:
    left = [str(r["id"]) for r in rows if int(r.get("fixture_group", -1)) in {1, 2}]
    right = [str(r["id"]) for r in rows if int(r.get("fixture_group", -1)) in {2, 3}]
    values = sorted(set(left + right))
    return values[:12]


def _union_all(rows: Rows) -> list[Any]:
    left = [str(r["id"]) for r in rows if int(r.get("fixture_group", -1)) == 1]
    right = [str(r["id"]) for r in rows if int(r.get("fixture_group", -1)) == 1]
    values = sorted(left + right)
    return values[:12]


def _seeded_random(rows: Rows) -> list[Any]:
    result = []
    for row in rows[:8]:
        identity = json.dumps(
            [["webpage_url", row["webpage_url"]], ["id", row["id"]]],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        payload = f"12648430\0{identity}".encode("utf-8")
        digest = hashlib.blake2b(payload, digest_size=8, person=b"yt-sql-rnd").digest()
        value = (int.from_bytes(digest, "big") >> 11) / float(1 << 53)
        result.append({"id": row["id"], "shuffle_key": value})
    result.sort(key=lambda item: item["id"])
    return result


def _aggregate_global(rows: Rows) -> list[Any]:
    values = [int(r["view_count"]) for r in rows if r.get("view_count") is not None]
    titles = [str(r["title"]) for r in rows if r.get("title") is not None]
    return [
        {
            "rows": len(rows),
            "known_views": len(values),
            "total_views": sum(values) if values else None,
            "mean_views": (sum(values) / len(values)) if values else None,
            "first_title": min(titles) if titles else None,
            "last_title": max(titles) if titles else None,
        }
    ]


def _aggregate_grouped_unicode(rows: Rows) -> list[Any]:
    grouped: dict[Any, list[dict[str, Any]]] = {}
    order: list[Any] = []
    for row in rows:
        key = row.get("title")
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(row)
    result = [{"title": key, "n": len(grouped[key])} for key in order if len(grouped[key]) > 1]
    result.sort(key=lambda item: item["n"], reverse=True)
    return result


def _aggregate_filter(rows: Rows) -> list[Any]:
    short = [r for r in rows if r.get("duration") is not None and int(r["duration"]) < 600]
    values = [int(r["view_count"]) for r in short if r.get("view_count") is not None]
    return [{"short": len(short), "short_views": sum(values) if values else None}]


def _aggregate_empty(rows: Rows) -> list[Any]:
    return [{"n": 0, "total": None}]


def _logical_taxonomy(value: Any) -> list[Any] | None:
    """Return the backend-independent logical order used by yt-sql taxonomy collections."""
    if value is None:
        return None
    return sorted(list(value), key=lambda item: (item is None, str(item) if item is not None else ""))


def _index_or_null(value: Any, index: int | None) -> Any:
    """Apply yt-sql's zero-based NULL/out-of-range collection indexing semantics."""
    if value is None or index is None or index < 0:
        return None
    sequence = list(value)
    return sequence[index] if index < len(sequence) else None


def _sql_eq(left: Any, right: Any) -> bool | None:
    """Return SQL equality without importing production three-valued helpers."""
    if left is None or right is None:
        return None
    return left == right


def _sql_ne(left: Any, right: Any) -> bool | None:
    """Return SQL inequality without importing production three-valued helpers."""
    equal = _sql_eq(left, right)
    return None if equal is None else not equal


def _collection_any(value: Any, predicate: Callable[[Any], bool | None]) -> bool | None:
    """Apply independent existential SQL three-valued collection semantics."""
    if value is None:
        return None
    saw_unknown = False
    for item in value:
        result = predicate(item)
        if result is True:
            return True
        if result is None:
            saw_unknown = True
    return None if saw_unknown else False


def _collection_all(value: Any, predicate: Callable[[Any], bool | None]) -> bool | None:
    """Apply independent universal SQL three-valued collection semantics."""
    if value is None:
        return None
    saw_unknown = False
    for item in value:
        result = predicate(item)
        if result is False:
            return False
        if result is None:
            saw_unknown = True
    return None if saw_unknown else True


def _collection_count(value: Any, predicate: Callable[[Any], bool | None]) -> int | None:
    """Count only TRUE predicate outcomes, preserving a NULL collection as NULL."""
    if value is None:
        return None
    return sum(predicate(item) is True for item in value)


def _collection_filter(value: Any, predicate: Callable[[Any], bool | None]) -> list[Any] | None:
    """Keep only TRUE predicate outcomes while preserving logical element order."""
    if value is None:
        return None
    return [item for item in value if predicate(item) is True]


def _collection_map(value: Any, projector: Callable[[Any], Any]) -> list[Any] | None:
    """Project each element independently while preserving logical element order."""
    if value is None:
        return None
    return [projector(item) for item in value]


def _collection_query_semantics(rows: Rows) -> list[Any]:
    """Exercise cardinality, scoped count, filtering and projection independently."""

    def projected(row: dict[str, Any]) -> dict[str, Any]:
        tags = _logical_taxonomy(row.get("tags"))
        return {
            "id": row["id"],
            "cardinality": None if tags is None else len(tags),
            "kept_count": _collection_count(tags, lambda tag: _sql_ne(tag, "skip")),
            "kept": _collection_filter(tags, lambda tag: _sql_ne(tag, "skip")),
            "upper": _collection_map(tags, lambda tag: None if tag is None else str(tag).upper()),
        }

    return (
        OracleQuery(rows)
        .where(lambda r: int(r["source_index"]) <= 12)
        .order_by(lambda r: r["source_index"])
        .select(projected)
        .to_list()
    )


def _collection_any_group_1(rows: Rows) -> list[Any]:
    return (
        OracleQuery(rows)
        .where(lambda r: _collection_any(_logical_taxonomy(r.get("tags")), lambda tag: _sql_eq(tag, "group-1")) is True)
        .order_by(lambda r: r["source_index"])
        .select(lambda r: r["id"])
        .take(12)
        .to_list()
    )


def _collection_not_any_group_1(rows: Rows) -> list[Any]:
    def matches(row: dict[str, Any]) -> bool:
        value = _collection_any(_logical_taxonomy(row.get("tags")), lambda tag: _sql_eq(tag, "group-1"))
        return value is False

    return (
        OracleQuery(rows)
        .where(matches)
        .order_by(lambda r: r["source_index"])
        .select(lambda r: r["id"])
        .take(12)
        .to_list()
    )


def _collection_all_known(rows: Rows) -> list[Any]:
    return (
        OracleQuery(rows)
        .where(lambda r: _collection_all(_logical_taxonomy(r.get("tags")), lambda tag: tag is not None) is True)
        .order_by(lambda r: r["source_index"])
        .select(lambda r: r["id"])
        .take(12)
        .to_list()
    )


def _collection_filter_map_composition(rows: Rows) -> list[Any]:
    """Exercise composed FILTER then MAP semantics over deterministic taxonomy collections."""

    def projected(row: dict[str, Any]) -> dict[str, Any]:
        tags = _logical_taxonomy(row.get("tags"))
        kept = _collection_filter(tags, lambda tag: _sql_ne(tag, "skip"))
        upper = _collection_map(kept, lambda tag: None if tag is None else str(tag).upper())
        return {"id": row["id"], "kept_upper": upper}

    return (
        OracleQuery(rows)
        .where(lambda r: int(r["source_index"]) <= 12)
        .order_by(lambda r: r["source_index"])
        .select(projected)
        .to_list()
    )


def _structured_collection_count(rows: Rows) -> list[Any]:
    """Exercise declared structured collection members through scoped COUNT."""

    def projected(row: dict[str, Any]) -> dict[str, Any]:
        formats = row.get("formats")
        count = _collection_count(
            formats,
            lambda format_record: (
                None
                if _structured_member_or_null(format_record, "height") is None
                else int(_structured_member_or_null(format_record, "height")) >= 700
            ),
        )
        return {"id": row["id"], "tall_formats": count}

    return (
        OracleQuery(rows)
        .where(lambda r: int(r["source_index"]) <= 18)
        .order_by(lambda r: r["source_index"])
        .select(projected)
        .to_list()
    )


def _dynamic_raw_filter_map(rows: Rows) -> list[Any]:
    """Exercise FILTER and MAP over backend-specific ordered raw scalar collections."""

    def projected(row: dict[str, Any]) -> dict[str, Any]:
        sequence = _structured_member_or_null(row.get("fixture_raw"), "sequence")
        kept = _collection_filter(sequence, lambda item: _sql_ne(item, "skip"))
        upper = _collection_map(kept, lambda item: None if item is None else str(item).upper())
        return {"id": row["id"], "raw_upper": upper}

    return (
        OracleQuery(rows)
        .where(lambda r: int(r["source_index"]) <= 12)
        .order_by(lambda r: r["source_index"])
        .select(projected)
        .to_list()
    )


def _nested_collection_scope(rows: Rows) -> list[Any]:
    """Exercise nested collection bindings with an inner reference to the outer element."""

    def matches(row: dict[str, Any]) -> bool:
        tags = _logical_taxonomy(row.get("tags"))
        sequence = _structured_member_or_null(row.get("fixture_raw"), "sequence")
        result = _collection_any(
            sequence,
            lambda raw_item: _collection_any(tags, lambda tag: _sql_eq(tag, raw_item)),
        )
        return result is True

    return (
        OracleQuery(rows)
        .where(matches)
        .order_by(lambda r: r["source_index"])
        .select(lambda r: r["id"])
        .take(8)
        .to_list()
    )


def _collection_index_projection(rows: Rows) -> list[Any]:
    return (
        OracleQuery(rows)
        .where(lambda r: int(r["source_index"]) <= 12)
        .order_by(lambda r: r["source_index"])
        .select(
            lambda r: {
                "id": r["id"],
                "first_tag": _index_or_null(_logical_taxonomy(r.get("tags")), 0),
                "missing_tag": _index_or_null(_logical_taxonomy(r.get("tags")), 99),
                "null_index": _index_or_null(_logical_taxonomy(r.get("tags")), None),
            }
        )
        .to_list()
    )


def _collection_output(rows: Rows) -> list[Any]:
    return (
        OracleQuery(rows)
        .where(lambda r: int(r["source_index"]) <= 6)
        .order_by(lambda r: r["source_index"])
        .select(lambda r: {"id": r["id"], "tags": _logical_taxonomy(r.get("tags"))})
        .to_list()
    )


def _raw_collection_index(rows: Rows) -> list[Any]:
    return (
        OracleQuery(rows)
        .where(lambda r: int(r["source_index"]) <= 12)
        .order_by(lambda r: r["source_index"])
        .select(lambda r: {"id": r["id"], "raw_item": _index_or_null(r.get("fixture_raw", {}).get("sequence"), 1)})
        .to_list()
    )


def _collection_parameter(rows: Rows) -> list[Any]:
    return (
        OracleQuery(rows)
        .where(lambda r: _index_or_null(_logical_taxonomy(r.get("tags")), 0) == "group-1")
        .order_by(lambda r: r["source_index"])
        .select(lambda r: r["id"])
        .take(8)
        .to_list()
    )


def _collection_cli_integration(rows: Rows) -> list[Any]:
    return (
        OracleQuery(rows)
        .where(lambda r: _index_or_null(_logical_taxonomy(r.get("tags")), 0) == "group-1")
        .order_by(lambda r: r["source_index"])
        .select(
            lambda r: {
                "id": r["id"],
                "tags": _logical_taxonomy(r.get("tags")),
                "first_tag": _index_or_null(_logical_taxonomy(r.get("tags")), 0),
                "raw_item": _index_or_null(r.get("fixture_raw", {}).get("sequence"), 1),
            }
        )
        .take(5)
        .to_list()
    )


def _structured_member_or_null(value: Any, *members: str) -> Any:
    """Apply yt-sql's NULL-propagating structured member semantics independently."""
    current = value
    for member in members:
        if not isinstance(current, dict):
            return None
        current = current.get(member)
    return current


def _raw_structured_members(rows: Rows) -> list[Any]:
    def projected(row: dict[str, Any]) -> dict[str, Any]:
        fixture = row.get("fixture_raw")
        record = _structured_member_or_null(fixture, "record")
        records = _structured_member_or_null(fixture, "records")
        second = _index_or_null(records, 1)
        return {
            "id": row["id"],
            "provider_id": _structured_member_or_null(record, "provider_id"),
            "label": _structured_member_or_null(record, "label"),
            "nested_height": _structured_member_or_null(record, "dimensions", "height"),
            "second_provider": _structured_member_or_null(second, "provider_id"),
            "second_height": _structured_member_or_null(second, "height"),
        }

    return (
        OracleQuery(rows)
        .where(lambda r: int(r["source_index"]) <= 12)
        .order_by(lambda r: r["source_index"])
        .select(projected)
        .to_list()
    )


def _raw_structured_member_predicate(rows: Rows) -> list[Any]:
    return (
        OracleQuery(rows)
        .where(
            lambda r: (
                _structured_member_or_null(_structured_member_or_null(r.get("fixture_raw"), "record"), "provider_id")
                == "provider-1"
            )
        )
        .order_by(lambda r: r["source_index"])
        .select(lambda r: r["id"])
        .take(8)
        .to_list()
    )


LANGUAGE_FEATURES = frozenset(
    {
        "boolean.and",
        "boolean.bare",
        "date.relative_ago",
        "from.identifier",
        "from.quoted_source",
        "limit.underscore",
        "offset.underscore",
        "order.default_asc",
        "projection.coalesce_fallback",
        "scalar.random_seeded",
        "projection.field",
        "string.double_quote",
        "string.doubled_quote",
        "temporal.localised",
        "temporal.unit_baktun",
        "temporal.unit_decade",
        "temporal.infinity_between",
        "temporal.infinity_negative",
        "temporal.infinity_positive",
        "temporal.now_fixed",
        "temporal.today_calendar",
        "temporal.today_fixed",
        "text.unquoted_literal",
        "value.number.negative",
        "boolean.not",
        "boolean.or",
        "boolean.parentheses",
        "boolean.precedence",
        "collection.index",
        "collection.null",
        "collection.bounds",
        "collection.raw",
        "collection.output",
        "collection.parameter",
        "collection.quantifier.any",
        "collection.quantifier.all",
        "collection.cardinality",
        "collection.count",
        "collection.filter",
        "collection.map",
        "collection.scope.nested",
        "collection.scope.outer",
        "collection.three_valued",
        "collection.empty",
        "collection.null_element",
        "collection.composition",
        "collection.raw_dynamic",
        "collection.structured",
        "structured.member",
        "structured.member.indexed",
        "structured.member.nested",
        "structured.member.null",
        "structured.member.raw_dynamic",
        "comparison.eq",
        "comparison.ge",
        "comparison.gt",
        "comparison.le",
        "comparison.lt",
        "comparison.ne",
        "comparison.ne_alt",
        "date.compact",
        "date.dot",
        "date.iso",
        "date.local_dmy",
        "date.local_mdy",
        "date.named",
        "date.slash",
        "datetime.offset",
        "datetime.zulu",
        "distinct",
        "duration.clock_hms",
        "duration.clock_ms",
        "duration.compound",
        "duration.decimal",
        "duration.localised",
        "duration.short_alias",
        "field.alias",
        "from.handle",
        "cte.non_recursive",
        "cte.chained",
        "cte.logical_schema",
        "set.union",
        "set.union_all",
        "set.global_order_limit",
        "in",
        "in.not",
        "is.false",
        "is.not_false",
        "is.not_null",
        "is.not_true",
        "is.not_unknown",
        "is.null",
        "is.predicate_unknown",
        "is.true",
        "is.unknown",
        "limit",
        "natural.above",
        "natural.at_least",
        "natural.at_most",
        "natural.below",
        "natural.equal_to",
        "natural.equals",
        "natural.greater_than",
        "natural.less_than",
        "natural.more_than",
        "natural.over",
        "natural.under",
        "null.three_valued",
        "offset",
        "offset.without_limit",
        "order.alias",
        "order.asc",
        "order.desc",
        "order.mixed",
        "order.multi",
        "order.null_last",
        "order.stable_tie",
        "output.auto_multi",
        "output.auto_single",
        "output.csv",
        "output.ids",
        "output.jsonl",
        "output.lines",
        "output.tsv",
        "output.urls",
        "parameter.binding",
        "predicate.between",
        "predicate.not_between",
        "projection.alias",
        "projection.coalesce",
        "projection.default_id",
        "projection.length",
        "projection.lower",
        "projection.raw",
        "projection.star",
        "projection.upper",
        "scalar.arithmetic.add",
        "scalar.arithmetic.divide",
        "scalar.arithmetic.multiply",
        "scalar.arithmetic.parentheses",
        "scalar.function_nested",
        "scalar.char",
        "scalar.concat",
        "scalar.nullif",
        "scalar.greatest",
        "scalar.least",
        "scalar.constant_fold",
        "scalar.case",
        "scalar.case.null_fallthrough",
        "scalar.case.no_else",
        "scalar.case.nested_result",
        "scalar.case.order",
        "order.expression",
        "order.expression_alias",
        "string.case_sensitive",
        "text.contain",
        "text.contains",
        "text.does_not_contain",
        "text.does_not_match",
        "text.match",
        "text.matches",
        "text.like",
        "text.ilike",
        "text.not_like",
        "text.not_ilike",
        "text.like.escape",
        "text.like.single",
        "text.not_contains",
        "text.not_matches",
        "value.count_b",
        "value.count_decimal_suffix",
        "value.count_k",
        "value.count_m",
        "value.count_underscore",
        "value.integer.hex",
        "value.integer.octal",
        "value.integer.binary",
        "scalar.mixed_base",
        "value.enum_case_insensitive",
        "unicode.normalisation_sensitive",
        "unicode.codepoint_length",
        "unicode.casefold_contains",
        "unicode.ilike_case",
        "unicode.like_codepoint",
        "unicode.case_mapping",
        "unicode.regex",
        "unicode.ordering",
        "aggregate.count_star",
        "aggregate.count_expression",
        "aggregate.sum",
        "aggregate.avg",
        "aggregate.min",
        "aggregate.max",
        "aggregate.group_by",
        "aggregate.having",
        "aggregate.filter",
        "aggregate.empty_input",
    }
)


CASES = (
    ConformanceCase(
        "source_order_limit",
        "SELECT id FROM @yt_sql_fixture LIMIT 10",
        _source_order,
        features=("from.handle", "limit", "output.lines"),
    ),
    ConformanceCase(
        "chronological_same_day_subsort",
        "SELECT id FROM @yt_sql_fixture WHERE upload_date BETWEEN 2026-08-01 AND 2026-08-31 AND duration < 1h ORDER BY upload_date ASC, release_timestamp ASC",
        _chronological,
        features=("predicate.between", "comparison.lt", "order.asc", "order.multi"),
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
        features=("comparison.ge", "order.null_last", "output.jsonl"),
    ),
    ConformanceCase(
        "distinct_projection",
        "SELECT DISTINCT title FROM @yt_sql_fixture WHERE title IN ('Duplicate', 'Case Test', 'case test') ORDER BY source_index ASC",
        _distinct_titles,
        ("title",),
        features=("distinct", "in"),
    ),
    ConformanceCase(
        "offset_limit",
        "SELECT id FROM @yt_sql_fixture WHERE view_count IS NOT NULL ORDER BY view_count DESC LIMIT 5 OFFSET 3",
        _offset_limit,
        features=("is.not_null", "order.desc", "offset"),
    ),
    ConformanceCase(
        "contains_case_insensitive",
        "SELECT id, title FROM @yt_sql_fixture WHERE title CONTAINS 'mars' ORDER BY upload_date ASC",
        _contains,
        ("id", "title"),
        "tsv",
        features=("text.contains", "output.tsv"),
    ),
    ConformanceCase(
        "matches_regex",
        "SELECT id, title FROM @yt_sql_fixture WHERE title MATCHES '^Mars|MARS' ORDER BY source_index ASC",
        _matches,
        ("id", "title"),
        "jsonl",
        features=("text.matches",),
    ),
    ConformanceCase(
        "like_prefix",
        "SELECT id, title FROM @yt_sql_fixture WHERE title LIKE 'Mars%' ORDER BY source_index ASC",
        _like_prefix,
        ("id", "title"),
        "jsonl",
        features=("text.like",),
    ),
    ConformanceCase(
        "ilike_contains",
        "SELECT id FROM @yt_sql_fixture WHERE title ILIKE '%mars%' ORDER BY source_index ASC",
        _ilike_contains,
        features=("text.ilike",),
    ),
    ConformanceCase(
        "not_like",
        "SELECT id FROM @yt_sql_fixture WHERE title NOT LIKE 'Mars%' AND title IS NOT NULL ORDER BY source_index ASC",
        _ids_where(
            lambda r: r["title"] is not None and not str(r["title"]).startswith("Mars"),
            order=(("source_index", False),),
        ),
        features=("text.not_like",),
    ),
    ConformanceCase(
        "not_ilike",
        "SELECT id FROM @yt_sql_fixture WHERE title NOT ILIKE '%mars%' AND title IS NOT NULL ORDER BY source_index ASC",
        _ids_where(
            lambda r: r["title"] is not None and "mars" not in str(r["title"]).casefold(),
            order=(("source_index", False),),
        ),
        features=("text.not_ilike",),
    ),
    ConformanceCase(
        "like_single_wildcard",
        "SELECT id FROM @yt_sql_fixture WHERE title LIKE 'Mars_mission' ORDER BY source_index ASC",
        _like_single,
        features=("text.like.single",),
    ),
    ConformanceCase(
        "like_escaped_percent",
        "SELECT id FROM @yt_sql_fixture WHERE title LIKE '100\\%' ORDER BY source_index ASC",
        _ids_where(lambda r: r["title"] == "100%", order=(("source_index", False),)),
        features=("text.like.escape",),
    ),
    ConformanceCase(
        "null_and_boolean_logic",
        "SELECT id FROM @yt_sql_fixture WHERE (view_count IS NULL OR view_count = 0) AND NOT is_live ORDER BY source_index ASC",
        _null_boolean,
        features=("is.null", "boolean.or", "boolean.and", "boolean.not", "boolean.parentheses"),
    ),
    ConformanceCase(
        "scalar_functions_and_alias_order",
        "SELECT id, LOWER(title) AS folded, LENGTH(title) AS chars, COALESCE(view_count, -1) AS views FROM @yt_sql_fixture WHERE upload_date BETWEEN 2026-08-22 AND 2026-08-24 ORDER BY folded ASC",
        _functions,
        ("id", "folded", "chars", "views"),
        "jsonl",
        features=("projection.lower", "projection.length", "projection.coalesce", "projection.alias", "order.alias"),
    ),
    ConformanceCase(
        "scalar_arithmetic_projection_and_order",
        "SELECT id, duration / 60 AS minutes, (view_count + 10) * 2 AS score FROM @yt_sql_fixture WHERE source_index <= 16 ORDER BY duration / 60 DESC, score ASC",
        _scalar_arithmetic,
        ("id", "minutes", "score"),
        "jsonl",
        features=(
            "scalar.arithmetic.add",
            "scalar.arithmetic.divide",
            "scalar.arithmetic.multiply",
            "scalar.arithmetic.parentheses",
            "order.expression",
            "order.expression_alias",
        ),
    ),
    ConformanceCase(
        "nested_scalar_functions_and_expression_order",
        "SELECT id, COALESCE(view_count + 1, 0) AS adjusted, LENGTH(LOWER(title)) AS chars FROM @yt_sql_fixture WHERE source_index <= 12 ORDER BY adjusted DESC",
        _scalar_nested_functions,
        ("id", "adjusted", "chars"),
        "jsonl",
        features=("scalar.arithmetic.add", "scalar.function_nested", "order.expression_alias"),
    ),
    ConformanceCase(
        "scalar_constant_folding_semantics",
        "SELECT id, 19 * 2 * 100 * 0 AS zero, 1 + 2 * 3 AS precedence, LOWER('ABC') AS lowered, COALESCE(NULL, 17) AS fallback, 1 / 0 AS division_by_zero FROM @yt_sql_fixture WHERE source_index <= 5 ORDER BY source_index ASC",
        _scalar_constant_folding,
        ("id", "zero", "precedence", "lowered", "fallback", "division_by_zero"),
        "jsonl",
        features=("scalar.constant_fold",),
    ),
    ConformanceCase(
        "bound_parameters",
        "SELECT id FROM @yt_sql_fixture WHERE upload_date >= :start AND duration < :maximum ORDER BY upload_date ASC, release_timestamp ASC LIMIT 6",
        _bound_parameters,
        params=("start=2026-08-20", "maximum=30m"),
        features=("parameter.binding",),
        execution="cli",
    ),
    ConformanceCase(
        "collection_index_null_and_bounds",
        "SELECT id, tags[0] AS first_tag, tags[99] AS missing_tag, tags[NULL] AS null_index FROM @yt_sql_fixture WHERE source_index <= 12 ORDER BY source_index ASC",
        _collection_index_projection,
        ("id", "first_tag", "missing_tag", "null_index"),
        "jsonl",
        features=("collection.index", "collection.null", "collection.bounds"),
    ),
    ConformanceCase(
        "collection_json_array_output",
        "SELECT id, tags FROM @yt_sql_fixture WHERE source_index <= 6 ORDER BY source_index ASC",
        _collection_output,
        ("id", "tags"),
        "jsonl",
        features=("collection.output",),
    ),
    ConformanceCase(
        "dynamic_raw_collection_index",
        "SELECT id, raw.fixture_raw.sequence[1] AS raw_item FROM @yt_sql_fixture WHERE source_index <= 12 ORDER BY source_index ASC",
        _raw_collection_index,
        ("id", "raw_item"),
        "jsonl",
        features=("collection.raw",),
    ),
    ConformanceCase(
        "collection_index_with_bound_parameter",
        "SELECT id FROM @yt_sql_fixture WHERE tags[0] = :needle ORDER BY source_index ASC LIMIT 8",
        _collection_parameter,
        params=("needle=group-1",),
        features=("collection.parameter", "parameter.binding"),
        execution="cli",
    ),
    ConformanceCase(
        "collection_cli_integration",
        "SELECT id, tags, tags[0] AS first_tag, raw.fixture_raw.sequence[1] AS raw_item FROM @yt_sql_fixture WHERE tags[0] = :needle ORDER BY source_index ASC LIMIT 5",
        _collection_cli_integration,
        ("id", "tags", "first_tag", "raw_item"),
        "jsonl",
        params=("needle=group-1",),
        features=(
            "collection.index",
            "collection.raw",
            "collection.output",
            "collection.parameter",
            "parameter.binding",
        ),
        execution="cli",
    ),
    ConformanceCase(
        "collection_query_semantics",
        "SELECT id, CARDINALITY(tags) AS cardinality, COUNT(tags AS tag WHERE tag != 'skip') AS kept_count, FILTER(tags AS tag WHERE tag != 'skip') AS kept, MAP(tags AS tag SELECT UPPER(tag)) AS upper FROM @yt_sql_fixture WHERE source_index <= 12 ORDER BY source_index ASC",
        _collection_query_semantics,
        ("id", "cardinality", "kept_count", "kept", "upper"),
        "jsonl",
        features=(
            "collection.cardinality",
            "collection.count",
            "collection.filter",
            "collection.map",
            "collection.three_valued",
            "collection.empty",
            "collection.null_element",
        ),
    ),
    ConformanceCase(
        "collection_any_predicate",
        "SELECT id FROM @yt_sql_fixture WHERE ANY(tags AS tag WHERE tag = 'group-1') ORDER BY source_index ASC LIMIT 12",
        _collection_any_group_1,
        features=("collection.quantifier.any", "collection.three_valued", "collection.empty"),
    ),
    ConformanceCase(
        "collection_not_any_predicate",
        "SELECT id FROM @yt_sql_fixture WHERE NOT ANY(tags AS tag WHERE tag = 'group-1') ORDER BY source_index ASC LIMIT 12",
        _collection_not_any_group_1,
        features=("collection.quantifier.any", "collection.three_valued", "collection.empty"),
    ),
    ConformanceCase(
        "collection_all_predicate",
        "SELECT id FROM @yt_sql_fixture WHERE ALL(tags AS tag WHERE tag IS NOT NULL) ORDER BY source_index ASC LIMIT 12",
        _collection_all_known,
        features=(
            "collection.quantifier.all",
            "collection.three_valued",
            "collection.empty",
            "collection.null_element",
        ),
    ),
    ConformanceCase(
        "collection_filter_map_composition",
        "SELECT id, MAP(FILTER(tags AS tag WHERE tag != 'skip') AS kept SELECT UPPER(kept)) AS kept_upper FROM @yt_sql_fixture WHERE source_index <= 12 ORDER BY source_index ASC",
        _collection_filter_map_composition,
        ("id", "kept_upper"),
        "jsonl",
        features=("collection.filter", "collection.map", "collection.composition"),
        execution="cli",
    ),
    ConformanceCase(
        "structured_collection_count",
        "SELECT id, COUNT(formats AS format WHERE format.height >= 700) AS tall_formats FROM @yt_sql_fixture WHERE source_index <= 18 ORDER BY source_index ASC",
        _structured_collection_count,
        ("id", "tall_formats"),
        "jsonl",
        features=("collection.count", "collection.structured", "structured.member"),
    ),
    ConformanceCase(
        "dynamic_raw_filter_map",
        "SELECT id, MAP(FILTER(raw.fixture_raw.sequence AS item WHERE item != 'skip') AS kept SELECT UPPER(kept)) AS raw_upper FROM @yt_sql_fixture WHERE source_index <= 12 ORDER BY source_index ASC",
        _dynamic_raw_filter_map,
        ("id", "raw_upper"),
        "jsonl",
        features=(
            "collection.filter",
            "collection.map",
            "collection.composition",
            "collection.raw_dynamic",
        ),
    ),
    ConformanceCase(
        "nested_collection_scope_outer_reference",
        "SELECT id FROM @yt_sql_fixture WHERE ANY(raw.fixture_raw.sequence AS raw_item WHERE ANY(tags AS tag WHERE tag = raw_item)) ORDER BY source_index ASC LIMIT 8",
        _nested_collection_scope,
        features=(
            "collection.quantifier.any",
            "collection.scope.nested",
            "collection.scope.outer",
            "collection.raw_dynamic",
        ),
    ),
    ConformanceCase(
        "dynamic_raw_structured_members",
        "SELECT id, (raw.fixture_raw.record).provider_id AS provider_id, (raw.fixture_raw.record).label AS label, (raw.fixture_raw.record).dimensions.height AS nested_height, raw.fixture_raw.records[1].provider_id AS second_provider, raw.fixture_raw.records[1].height AS second_height FROM @yt_sql_fixture WHERE source_index <= 12 ORDER BY source_index ASC",
        _raw_structured_members,
        ("id", "provider_id", "label", "nested_height", "second_provider", "second_height"),
        "jsonl",
        features=(
            "structured.member",
            "structured.member.indexed",
            "structured.member.nested",
            "structured.member.null",
            "structured.member.raw_dynamic",
        ),
    ),
    ConformanceCase(
        "dynamic_raw_structured_member_predicate",
        "SELECT id FROM @yt_sql_fixture WHERE (raw.fixture_raw.record).provider_id = 'provider-1' ORDER BY source_index ASC LIMIT 8",
        _raw_structured_member_predicate,
        features=("structured.member", "structured.member.raw_dynamic"),
        execution="cli",
    ),
    ConformanceCase(
        "count_suffix_and_enum_case",
        "SELECT id, view_count, availability FROM @yt_sql_fixture WHERE view_count >= 1m AND availability = 'PUBLIC' ORDER BY view_count DESC, id ASC",
        _count_enum,
        ("id", "view_count", "availability"),
        "csv",
        features=("value.count_m", "value.enum_case_insensitive", "output.csv"),
    ),
    ConformanceCase(
        "raw_dynamic_field",
        "SELECT id, raw.fixture_group AS bucket FROM @yt_sql_fixture WHERE raw.fixture_group IN (1, 3) ORDER BY raw.fixture_group ASC, source_index ASC LIMIT 8",
        _raw_dynamic,
        ("id", "bucket"),
        "tsv",
        features=("projection.raw",),
    ),
    # Comparison operators and their natural-language aliases.
    ConformanceCase(
        "comparison_equal",
        "SELECT id FROM @yt_sql_fixture WHERE view_count = 42 ORDER BY source_index ASC",
        _ids_where(lambda r: r["view_count"] is not None and int(r["view_count"]) == 42),
        features=("comparison.eq",),
    ),
    ConformanceCase(
        "comparison_not_equal",
        "SELECT id FROM @yt_sql_fixture WHERE view_count != 42 AND source_index <= 36 ORDER BY source_index ASC",
        _ids_where(
            lambda r: r["view_count"] is not None and int(r["view_count"]) != 42 and int(r["source_index"]) <= 36
        ),
        features=("comparison.ne",),
    ),
    ConformanceCase(
        "comparison_not_equal_angle",
        "SELECT id FROM @yt_sql_fixture WHERE view_count <> 42 AND source_index <= 36 ORDER BY source_index ASC",
        _ids_where(
            lambda r: r["view_count"] is not None and int(r["view_count"]) != 42 and int(r["source_index"]) <= 36
        ),
        features=("comparison.ne_alt",),
    ),
    ConformanceCase(
        "comparison_less_than",
        "SELECT id FROM @yt_sql_fixture WHERE duration < 60s ORDER BY source_index ASC",
        _ids_where(lambda r: r["duration"] is not None and int(r["duration"]) < 60),
        features=("comparison.lt",),
    ),
    ConformanceCase(
        "comparison_less_or_equal",
        "SELECT id FROM @yt_sql_fixture WHERE duration <= 60s ORDER BY source_index ASC",
        _ids_where(lambda r: r["duration"] is not None and int(r["duration"]) <= 60),
        features=("comparison.le",),
    ),
    ConformanceCase(
        "comparison_greater_than",
        "SELECT id FROM @yt_sql_fixture WHERE view_count > 1m ORDER BY source_index ASC LIMIT 12",
        _ids_where(lambda r: r["view_count"] is not None and int(r["view_count"]) > 1_000_000, take=12),
        features=("comparison.gt",),
    ),
    ConformanceCase(
        "comparison_greater_or_equal",
        "SELECT id FROM @yt_sql_fixture WHERE view_count >= 1m ORDER BY source_index ASC LIMIT 12",
        _ids_where(lambda r: r["view_count"] is not None and int(r["view_count"]) >= 1_000_000, take=12),
        features=("comparison.ge",),
    ),
    ConformanceCase(
        "natural_at_least",
        "SELECT id FROM @yt_sql_fixture WHERE view_count AT LEAST 1m ORDER BY source_index ASC LIMIT 8",
        _ids_where(lambda r: r["view_count"] is not None and int(r["view_count"]) >= 1_000_000, take=8),
        features=("natural.at_least",),
    ),
    ConformanceCase(
        "natural_at_most",
        "SELECT id FROM @yt_sql_fixture WHERE view_count AT MOST 100 ORDER BY source_index ASC",
        _ids_where(lambda r: r["view_count"] is not None and int(r["view_count"]) <= 100),
        features=("natural.at_most",),
    ),
    ConformanceCase(
        "natural_greater_than",
        "SELECT id FROM @yt_sql_fixture WHERE view_count GREATER THAN 1m ORDER BY source_index ASC LIMIT 8",
        _ids_where(lambda r: r["view_count"] is not None and int(r["view_count"]) > 1_000_000, take=8),
        features=("natural.greater_than",),
    ),
    ConformanceCase(
        "natural_more_than",
        "SELECT id FROM @yt_sql_fixture WHERE view_count MORE THAN 1m ORDER BY source_index ASC LIMIT 8",
        _ids_where(lambda r: r["view_count"] is not None and int(r["view_count"]) > 1_000_000, take=8),
        features=("natural.more_than",),
    ),
    ConformanceCase(
        "natural_less_than",
        "SELECT id FROM @yt_sql_fixture WHERE view_count LESS THAN 100 ORDER BY source_index ASC",
        _ids_where(lambda r: r["view_count"] is not None and int(r["view_count"]) < 100),
        features=("natural.less_than",),
    ),
    ConformanceCase(
        "natural_equal_to",
        "SELECT id FROM @yt_sql_fixture WHERE view_count EQUAL TO 42 ORDER BY source_index ASC",
        _ids_where(lambda r: r["view_count"] is not None and int(r["view_count"]) == 42),
        features=("natural.equal_to",),
    ),
    ConformanceCase(
        "natural_over",
        "SELECT id FROM @yt_sql_fixture WHERE view_count OVER 1m ORDER BY source_index ASC LIMIT 8",
        _ids_where(lambda r: r["view_count"] is not None and int(r["view_count"]) > 1_000_000, take=8),
        features=("natural.over",),
    ),
    ConformanceCase(
        "natural_above",
        "SELECT id FROM @yt_sql_fixture WHERE view_count ABOVE 1m ORDER BY source_index ASC LIMIT 8",
        _ids_where(lambda r: r["view_count"] is not None and int(r["view_count"]) > 1_000_000, take=8),
        features=("natural.above",),
    ),
    ConformanceCase(
        "natural_under",
        "SELECT id FROM @yt_sql_fixture WHERE view_count UNDER 100 ORDER BY source_index ASC",
        _ids_where(lambda r: r["view_count"] is not None and int(r["view_count"]) < 100),
        features=("natural.under",),
    ),
    ConformanceCase(
        "natural_below",
        "SELECT id FROM @yt_sql_fixture WHERE view_count BELOW 100 ORDER BY source_index ASC",
        _ids_where(lambda r: r["view_count"] is not None and int(r["view_count"]) < 100),
        features=("natural.below",),
    ),
    ConformanceCase(
        "natural_equals",
        "SELECT id FROM @yt_sql_fixture WHERE view_count EQUALS 42 ORDER BY source_index ASC",
        _ids_where(lambda r: r["view_count"] is not None and int(r["view_count"]) == 42),
        features=("natural.equals",),
    ),
    # Set, range, NULL, Boolean and text predicates.
    ConformanceCase(
        "not_between_inclusive_inverse",
        "SELECT id FROM @yt_sql_fixture WHERE duration NOT BETWEEN 59s AND 61s ORDER BY source_index ASC LIMIT 12",
        _ids_where(lambda r: r["duration"] is not None and not (59 <= int(r["duration"]) <= 61), take=12),
        features=("predicate.not_between",),
    ),
    ConformanceCase(
        "not_in",
        "SELECT id FROM @yt_sql_fixture WHERE availability NOT IN ('PRIVATE', 'subscriber_only') AND source_index <= 36 ORDER BY source_index ASC",
        _ids_where(
            lambda r: (
                r["availability"] is not None
                and str(r["availability"]).casefold() not in {"private", "subscriber_only"}
                and int(r["source_index"]) <= 36
            )
        ),
        features=("in.not",),
    ),
    ConformanceCase(
        "is_not_null",
        "SELECT id FROM @yt_sql_fixture WHERE upload_date IS NOT NULL AND source_index <= 36 ORDER BY source_index ASC",
        _ids_where(lambda r: r["upload_date"] is not None and int(r["source_index"]) <= 36),
        features=("is.not_null",),
    ),
    ConformanceCase(
        "is_true",
        "SELECT id FROM @yt_sql_fixture WHERE is_live IS TRUE ORDER BY source_index ASC",
        _ids_where(lambda r: r["is_live"] is True),
        features=("is.true",),
    ),
    ConformanceCase(
        "is_false",
        "SELECT id FROM @yt_sql_fixture WHERE is_live IS FALSE AND source_index <= 36 ORDER BY source_index ASC",
        _ids_where(lambda r: r["is_live"] is False and int(r["source_index"]) <= 36),
        features=("is.false",),
    ),
    ConformanceCase(
        "is_not_true",
        "SELECT id FROM @yt_sql_fixture WHERE is_live IS NOT TRUE AND source_index <= 36 ORDER BY source_index ASC",
        _ids_where(lambda r: r["is_live"] is not True and int(r["source_index"]) <= 36),
        features=("is.not_true",),
    ),
    ConformanceCase(
        "is_not_false",
        "SELECT id FROM @yt_sql_fixture WHERE is_live IS NOT FALSE ORDER BY source_index ASC",
        _ids_where(lambda r: r["is_live"] is not False),
        features=("is.not_false",),
    ),
    ConformanceCase(
        "is_unknown",
        "SELECT id FROM @yt_sql_fixture WHERE is_live IS UNKNOWN ORDER BY source_index ASC",
        _ids_where(lambda r: r["is_live"] is None),
        features=("is.unknown",),
    ),
    ConformanceCase(
        "is_not_unknown",
        "SELECT id FROM @yt_sql_fixture WHERE is_live IS NOT UNKNOWN ORDER BY source_index ASC",
        _ids_where(lambda r: r["is_live"] is not None),
        features=("is.not_unknown",),
    ),
    ConformanceCase(
        "predicate_is_unknown",
        "SELECT id FROM @yt_sql_fixture WHERE (view_count > 1000) IS UNKNOWN ORDER BY source_index ASC",
        _ids_where(lambda r: r["view_count"] is None),
        features=("is.predicate_unknown",),
    ),
    ConformanceCase(
        "contain_singular",
        "SELECT id FROM @yt_sql_fixture WHERE title CONTAIN 'mars' ORDER BY source_index ASC LIMIT 10",
        _ids_where(lambda r: r["title"] is not None and "mars" in str(r["title"]).casefold(), take=10),
        features=("text.contain",),
    ),
    ConformanceCase(
        "not_contains",
        "SELECT id FROM @yt_sql_fixture WHERE title NOT CONTAINS 'mars' AND source_index <= 20 ORDER BY source_index ASC",
        _ids_where(
            lambda r: (
                r["title"] is not None and "mars" not in str(r["title"]).casefold() and int(r["source_index"]) <= 20
            )
        ),
        features=("text.not_contains",),
    ),
    ConformanceCase(
        "does_not_contain",
        "SELECT id FROM @yt_sql_fixture WHERE title DOES NOT CONTAIN 'mars' AND source_index <= 20 ORDER BY source_index ASC",
        _ids_where(
            lambda r: (
                r["title"] is not None and "mars" not in str(r["title"]).casefold() and int(r["source_index"]) <= 20
            )
        ),
        features=("text.does_not_contain",),
    ),
    ConformanceCase(
        "match_singular",
        "SELECT id FROM @yt_sql_fixture WHERE title MATCH '^Mars' ORDER BY source_index ASC LIMIT 10",
        _ids_where(lambda r: r["title"] is not None and re.search(r"^Mars", str(r["title"])) is not None, take=10),
        features=("text.match",),
    ),
    ConformanceCase(
        "not_matches",
        "SELECT id FROM @yt_sql_fixture WHERE title NOT MATCHES '^Mars' AND source_index <= 20 ORDER BY source_index ASC",
        _ids_where(
            lambda r: (
                r["title"] is not None and re.search(r"^Mars", str(r["title"])) is None and int(r["source_index"]) <= 20
            )
        ),
        features=("text.not_matches",),
    ),
    ConformanceCase(
        "does_not_match",
        "SELECT id FROM @yt_sql_fixture WHERE title DOES NOT MATCH '^Mars' AND source_index <= 20 ORDER BY source_index ASC",
        _ids_where(
            lambda r: (
                r["title"] is not None and re.search(r"^Mars", str(r["title"])) is None and int(r["source_index"]) <= 20
            )
        ),
        features=("text.does_not_match",),
    ),
    ConformanceCase(
        "boolean_precedence",
        "SELECT id FROM @yt_sql_fixture WHERE view_count = 0 OR view_count = 42 AND duration = 20m ORDER BY source_index ASC",
        _ids_where(
            lambda r: (
                (r["view_count"] is not None and int(r["view_count"]) == 0)
                or (
                    r["view_count"] is not None
                    and int(r["view_count"]) == 42
                    and r["duration"] is not None
                    and int(r["duration"]) == 1200
                )
            )
        ),
        features=("boolean.precedence",),
    ),
    ConformanceCase(
        "parentheses_override_precedence",
        "SELECT id FROM @yt_sql_fixture WHERE (view_count = 0 OR view_count = 42) AND duration = 20m ORDER BY source_index ASC",
        _ids_where(
            lambda r: (
                r["duration"] is not None
                and int(r["duration"]) == 1200
                and r["view_count"] is not None
                and int(r["view_count"]) in {0, 42}
            )
        ),
        features=("boolean.parentheses",),
    ),
    ConformanceCase(
        "double_not_boolean",
        "SELECT id FROM @yt_sql_fixture WHERE NOT NOT is_live ORDER BY source_index ASC",
        _ids_where(lambda r: r["is_live"] is True),
        features=("boolean.not",),
    ),
    ConformanceCase(
        "string_equality_is_case_sensitive",
        "SELECT id FROM @yt_sql_fixture WHERE title = 'Case Test' ORDER BY source_index ASC",
        _ids_where(lambda r: r["title"] == "Case Test"),
        features=("string.case_sensitive",),
    ),
    ConformanceCase(
        "ordinary_null_comparison_is_unknown",
        "SELECT id FROM @yt_sql_fixture WHERE view_count != 0 AND source_index <= 36 ORDER BY source_index ASC",
        _ids_where(
            lambda r: r["view_count"] is not None and int(r["view_count"]) != 0 and int(r["source_index"]) <= 36
        ),
        features=("null.three_valued",),
    ),
    # Count and duration literal forms.
    ConformanceCase(
        "count_underscore",
        "SELECT id FROM @yt_sql_fixture WHERE view_count >= 1_000_000 ORDER BY source_index ASC LIMIT 8",
        _ids_where(lambda r: r["view_count"] is not None and int(r["view_count"]) >= 1_000_000, take=8),
        features=("value.count_underscore",),
    ),
    ConformanceCase(
        "hex_integer_count",
        "SELECT id FROM @yt_sql_fixture WHERE view_count >= 0xF4240 ORDER BY source_index ASC LIMIT 8",
        _ids_where(lambda r: r["view_count"] is not None and int(r["view_count"]) >= 1_000_000, take=8),
        features=("value.integer.hex",),
    ),
    ConformanceCase(
        "octal_integer_count",
        "SELECT id FROM @yt_sql_fixture WHERE view_count >= 0o3641100 ORDER BY source_index ASC LIMIT 8",
        _ids_where(lambda r: r["view_count"] is not None and int(r["view_count"]) >= 1_000_000, take=8),
        features=("value.integer.octal",),
    ),
    ConformanceCase(
        "binary_integer_count",
        "SELECT id FROM @yt_sql_fixture WHERE view_count >= 0b11110100001001000000 ORDER BY source_index ASC LIMIT 8",
        _ids_where(lambda r: r["view_count"] is not None and int(r["view_count"]) >= 1_000_000, take=8),
        features=("value.integer.binary",),
    ),
    ConformanceCase(
        "mixed_base_scalar_expression",
        "SELECT 0x10 + 0o10 + 0b10 + 10 AS value FROM @yt_sql_fixture ORDER BY source_index ASC LIMIT 1",
        _mixed_base_projection,
        ("value",),
        features=("scalar.mixed_base", "scalar.arithmetic.add"),
    ),
    ConformanceCase(
        "count_k_suffix",
        "SELECT id FROM @yt_sql_fixture WHERE view_count >= 999k AND view_count < 1m ORDER BY source_index ASC",
        _ids_where(lambda r: r["view_count"] is not None and 999_000 <= int(r["view_count"]) < 1_000_000),
        features=("value.count_k",),
    ),
    ConformanceCase(
        "count_decimal_suffix",
        "SELECT id FROM @yt_sql_fixture WHERE view_count >= 1.5m ORDER BY source_index ASC LIMIT 8",
        _ids_where(lambda r: r["view_count"] is not None and int(r["view_count"]) >= 1_500_000, take=8),
        features=("value.count_decimal_suffix",),
    ),
    ConformanceCase(
        "count_b_suffix",
        "SELECT id FROM @yt_sql_fixture WHERE view_count >= 1b ORDER BY source_index ASC",
        _ids_where(lambda r: r["view_count"] is not None and int(r["view_count"]) >= 1_000_000_000),
        features=("value.count_b",),
    ),
    ConformanceCase(
        "duration_clock_minutes_seconds",
        "SELECT id FROM @yt_sql_fixture WHERE duration = 1:00 ORDER BY source_index ASC",
        _ids_where(lambda r: r["duration"] is not None and int(r["duration"]) == 60),
        features=("duration.clock_ms",),
    ),
    ConformanceCase(
        "duration_clock_hours_minutes_seconds",
        "SELECT id FROM @yt_sql_fixture WHERE duration = 1:00:00 ORDER BY source_index ASC",
        _ids_where(lambda r: r["duration"] is not None and int(r["duration"]) == 3600),
        features=("duration.clock_hms",),
    ),
    ConformanceCase(
        "duration_compound",
        "SELECT id FROM @yt_sql_fixture WHERE duration < 1h30m ORDER BY source_index ASC LIMIT 16",
        _ids_where(lambda r: r["duration"] is not None and int(r["duration"]) < 5400, take=16),
        features=("duration.compound",),
    ),
    ConformanceCase(
        "duration_decimal",
        "SELECT id FROM @yt_sql_fixture WHERE duration < 1.5h ORDER BY source_index ASC LIMIT 16",
        _ids_where(lambda r: r["duration"] is not None and int(r["duration"]) < 5400, take=16),
        features=("duration.decimal",),
    ),
    ConformanceCase(
        "duration_welsh_localised",
        "SELECT id FROM @yt_sql_fixture WHERE duration < 2awr ORDER BY source_index ASC LIMIT 16",
        _ids_where(lambda r: r["duration"] is not None and int(r["duration"]) < 7200, take=16),
        features=("duration.localised",),
    ),
    ConformanceCase(
        "duration_shared_short_alias",
        "SELECT id FROM @yt_sql_fixture WHERE duration < 1d ORDER BY source_index ASC LIMIT 20",
        _ids_where(lambda r: r["duration"] is not None and int(r["duration"]) < 86_400, take=20),
        features=("duration.short_alias",),
    ),
    # Date and timestamp literal forms.
    ConformanceCase(
        "date_iso",
        "SELECT id FROM @yt_sql_fixture WHERE upload_date = 2026-08-31 ORDER BY release_timestamp ASC",
        _ids_where(lambda r: r["upload_date"] == "20260831", order=(("release_timestamp", False),)),
        features=("date.iso",),
    ),
    ConformanceCase(
        "date_compact",
        "SELECT id FROM @yt_sql_fixture WHERE upload_date = 20260831 ORDER BY release_timestamp ASC",
        _ids_where(lambda r: r["upload_date"] == "20260831", order=(("release_timestamp", False),)),
        features=("date.compact",),
    ),
    ConformanceCase(
        "date_slash",
        "SELECT id FROM @yt_sql_fixture WHERE upload_date = 2026/08/31 ORDER BY release_timestamp ASC",
        _ids_where(lambda r: r["upload_date"] == "20260831", order=(("release_timestamp", False),)),
        features=("date.slash",),
    ),
    ConformanceCase(
        "date_dot",
        "SELECT id FROM @yt_sql_fixture WHERE upload_date = 2026.08.31 ORDER BY release_timestamp ASC",
        _ids_where(lambda r: r["upload_date"] == "20260831", order=(("release_timestamp", False),)),
        features=("date.dot",),
    ),
    ConformanceCase(
        "date_local_dmy",
        "SELECT id FROM @yt_sql_fixture WHERE upload_date = 31/08/2026 ORDER BY release_timestamp ASC",
        _ids_where(lambda r: r["upload_date"] == "20260831", order=(("release_timestamp", False),)),
        features=("date.local_dmy",),
    ),
    ConformanceCase(
        "date_local_mdy",
        "SELECT id FROM @yt_sql_fixture WHERE upload_date = 08/31/2026 ORDER BY release_timestamp ASC",
        _ids_where(lambda r: r["upload_date"] == "20260831", order=(("release_timestamp", False),)),
        cli_args=("--date-format", "mdy"),
        features=("date.local_mdy",),
    ),
    ConformanceCase(
        "date_named",
        "SELECT id FROM @yt_sql_fixture WHERE upload_date = '31 August 2026' ORDER BY release_timestamp ASC",
        _ids_where(lambda r: r["upload_date"] == "20260831", order=(("release_timestamp", False),)),
        features=("date.named",),
    ),
    ConformanceCase(
        "datetime_zulu",
        "SELECT id FROM @yt_sql_fixture WHERE release_timestamp = 2026-08-31T20:30:00Z ORDER BY source_index ASC",
        _ids_where(
            lambda r: r["release_timestamp"] == int(datetime(2026, 8, 31, 20, 30, tzinfo=timezone.utc).timestamp())
        ),
        features=("datetime.zulu",),
    ),
    ConformanceCase(
        "datetime_offset",
        "SELECT id FROM @yt_sql_fixture WHERE release_timestamp = 2026-08-31T22:30:00+02:00 ORDER BY source_index ASC",
        _ids_where(
            lambda r: r["release_timestamp"] == int(datetime(2026, 8, 31, 20, 30, tzinfo=timezone.utc).timestamp())
        ),
        features=("datetime.offset",),
    ),
    # Ordering, projection aliases, functions and output formats.
    ConformanceCase(
        "descending_nulls_last",
        "SELECT id FROM @yt_sql_fixture WHERE source_index <= 36 ORDER BY release_timestamp DESC",
        _ids_where(lambda r: int(r["source_index"]) <= 36, order=(("release_timestamp", True),)),
        features=("order.desc", "order.null_last"),
    ),
    ConformanceCase(
        "mixed_direction_order",
        "SELECT id FROM @yt_sql_fixture WHERE source_index <= 12 ORDER BY upload_date DESC, release_timestamp ASC",
        _ids_where(lambda r: int(r["source_index"]) <= 12, order=(("upload_date", True), ("release_timestamp", False))),
        features=("order.mixed", "order.multi"),
    ),
    ConformanceCase(
        "stable_order_tie",
        "SELECT id FROM @yt_sql_fixture WHERE view_count = 42 ORDER BY view_count ASC",
        _ids_where(
            lambda r: r["view_count"] is not None and int(r["view_count"]) == 42, order=(("view_count", False),)
        ),
        features=("order.stable_tie",),
    ),
    ConformanceCase(
        "offset_without_limit",
        "SELECT id FROM @yt_sql_fixture WHERE source_index <= 10 ORDER BY source_index ASC OFFSET 3",
        _ids_where(lambda r: int(r["source_index"]) <= 10, skip=3),
        features=("offset.without_limit",),
    ),
    ConformanceCase(
        "default_projection_id",
        "FROM @yt_sql_fixture WHERE source_index <= 3 ORDER BY source_index ASC",
        _ids_where(lambda r: int(r["source_index"]) <= 3),
        features=("projection.default_id",),
    ),
    ConformanceCase(
        "field_aliases",
        "SELECT id, views, date, url FROM @yt_sql_fixture WHERE source_index <= 3 ORDER BY source_index ASC",
        _project_where(
            lambda r: int(r["source_index"]) <= 3,
            lambda r: {
                "id": r["id"],
                "views": r["view_count"],
                "date": None
                if r["upload_date"] is None
                else f"{str(r['upload_date'])[0:4]}-{str(r['upload_date'])[4:6]}-{str(r['upload_date'])[6:8]}",
                "url": r["webpage_url"],
            },
        ),
        ("id", "views", "date", "url"),
        "jsonl",
        features=("field.alias",),
    ),
    ConformanceCase(
        "upper_projection",
        "SELECT id, UPPER(title) AS shouted FROM @yt_sql_fixture WHERE source_index <= 4 ORDER BY source_index ASC",
        _project_where(
            lambda r: int(r["source_index"]) <= 4,
            lambda r: {"id": r["id"], "shouted": None if r["title"] is None else str(r["title"]).upper()},
        ),
        ("id", "shouted"),
        "jsonl",
        features=("projection.upper",),
    ),
    ConformanceCase(
        "coalesce_multiple_arguments",
        "SELECT id, COALESCE(fixture_nullable, title, 'fallback') AS chosen FROM @yt_sql_fixture WHERE source_index <= 6 ORDER BY source_index ASC",
        _project_where(
            lambda r: int(r["source_index"]) <= 6,
            lambda r: {
                "id": r["id"],
                "chosen": r["fixture_nullable"]
                if r["fixture_nullable"] is not None
                else r["title"]
                if r["title"] is not None
                else "fallback",
            },
        ),
        ("id", "chosen"),
        "jsonl",
        features=("projection.coalesce",),
    ),
    ConformanceCase(
        "distinct_null_collapse",
        "SELECT DISTINCT fixture_nullable FROM @yt_sql_fixture WHERE source_index <= 20 ORDER BY source_index ASC",
        _project_where(lambda r: int(r["source_index"]) <= 20, lambda r: r["fixture_nullable"], distinct=True),
        ("fixture_nullable",),
        "lines",
        features=("distinct",),
    ),
    ConformanceCase(
        "auto_single_output",
        "SELECT title FROM @yt_sql_fixture WHERE source_index <= 3 ORDER BY source_index ASC",
        _project_where(lambda r: int(r["source_index"]) <= 3, lambda r: r["title"]),
        ("title",),
        "auto",
        features=("output.auto_single",),
    ),
    ConformanceCase(
        "auto_multiple_output",
        "SELECT id, title FROM @yt_sql_fixture WHERE source_index <= 3 ORDER BY source_index ASC",
        _project_where(lambda r: int(r["source_index"]) <= 3, lambda r: {"id": r["id"], "title": r["title"]}),
        ("id", "title"),
        "auto",
        features=("output.auto_multi",),
    ),
    ConformanceCase(
        "legacy_ids_output",
        "FROM @yt_sql_fixture WHERE source_index <= 3 ORDER BY source_index ASC",
        _ids_where(lambda r: int(r["source_index"]) <= 3),
        ("id",),
        "ids",
        features=("output.ids",),
    ),
    ConformanceCase(
        "legacy_urls_output",
        "FROM @yt_sql_fixture WHERE source_index <= 3 ORDER BY source_index ASC",
        _ids_where(lambda r: int(r["source_index"]) <= 3),
        ("id",),
        "urls",
        features=("output.urls",),
    ),
    # Additional syntax-shape and temporal cases ensure the dataset actually exercises
    # the supported surface rather than merely containing the tokens in other queries.
    ConformanceCase(
        "coalesce_negative_fallback_is_numeric",
        "SELECT id, COALESCE(view_count, -1) AS views FROM @yt_sql_fixture WHERE id = 'vid006'",
        _project_where(
            lambda r: r["id"] == "vid006",
            lambda r: {"id": r["id"], "views": r["view_count"] if r["view_count"] is not None else -1},
        ),
        ("id", "views"),
        "jsonl",
        features=("projection.coalesce_fallback", "value.number.negative"),
    ),
    ConformanceCase(
        "bare_boolean_predicate",
        "SELECT id FROM @yt_sql_fixture WHERE is_live ORDER BY source_index ASC",
        _ids_where(lambda r: r["is_live"] is True),
        features=("boolean.bare",),
    ),
    ConformanceCase(
        "default_ascending_order",
        "SELECT id FROM @yt_sql_fixture WHERE source_index <= 5 ORDER BY source_index",
        _ids_where(lambda r: int(r["source_index"]) <= 5),
        features=("order.default_asc",),
    ),
    ConformanceCase(
        "limit_with_underscores",
        "SELECT id FROM @yt_sql_fixture ORDER BY source_index LIMIT 1_0",
        _ids_where(lambda r: True, take=10),
        features=("limit.underscore",),
    ),
    ConformanceCase(
        "offset_with_underscores",
        "SELECT id FROM @yt_sql_fixture WHERE source_index <= 8 ORDER BY source_index OFFSET 0_3",
        _ids_where(lambda r: int(r["source_index"]) <= 8, skip=3),
        features=("offset.underscore",),
    ),
    ConformanceCase(
        "select_star_contract",
        "SELECT * FROM @yt_sql_fixture WHERE id = 'vid001'",
        _select_star_projection,
        SELECT_STAR_COLUMNS,
        "jsonl",
        features=("projection.star",),
    ),
    ConformanceCase(
        "ordinary_field_projection",
        "SELECT title FROM @yt_sql_fixture WHERE source_index <= 3 ORDER BY source_index",
        _project_where(lambda r: int(r["source_index"]) <= 3, lambda r: r["title"]),
        ("title",),
        "lines",
        features=("projection.field",),
    ),
    ConformanceCase(
        "bare_identifier_source",
        "SELECT id FROM yt_sql_fixture WHERE source_index <= 2 ORDER BY source_index",
        _ids_where(lambda r: int(r["source_index"]) <= 2),
        features=("from.identifier",),
    ),
    ConformanceCase(
        "quoted_source",
        "SELECT id FROM 'https://fixture.invalid/source' WHERE source_index <= 2 ORDER BY source_index",
        _ids_where(lambda r: int(r["source_index"]) <= 2),
        features=("from.quoted_source",),
    ),
    ConformanceCase(
        "doubled_quote_string_literal",
        "SELECT id FROM @yt_sql_fixture WHERE title = 'O''Brien on Mars' ORDER BY source_index",
        _ids_where(lambda r: r["title"] == "O'Brien on Mars"),
        features=("string.doubled_quote",),
    ),
    ConformanceCase(
        "double_quoted_string_literal",
        'SELECT id FROM @yt_sql_fixture WHERE title = "Case Test" ORDER BY source_index',
        _ids_where(lambda r: r["title"] == "Case Test"),
        features=("string.double_quote",),
    ),
    ConformanceCase(
        "unquoted_text_literal",
        "SELECT id FROM @yt_sql_fixture WHERE title CONTAINS Mars ORDER BY source_index LIMIT 8",
        _ids_where(lambda r: r["title"] is not None and "mars" in str(r["title"]).casefold(), take=8),
        features=("text.unquoted_literal",),
    ),
    ConformanceCase(
        "today_fixed_relative",
        "SELECT id FROM @yt_sql_fixture WHERE upload_date >= TODAY()-3day ORDER BY upload_date ASC, release_timestamp ASC",
        _ids_where(
            lambda r: r["upload_date"] is not None and str(r["upload_date"]) >= "20260829",
            order=(("upload_date", False), ("release_timestamp", False)),
        ),
        features=("temporal.today_fixed",),
    ),
    ConformanceCase(
        "today_calendar_relative",
        "SELECT id FROM @yt_sql_fixture WHERE upload_date >= TODAY()-1month ORDER BY upload_date ASC, release_timestamp ASC",
        _ids_where(
            lambda r: r["upload_date"] is not None and str(r["upload_date"]) >= "20260801",
            order=(("upload_date", False), ("release_timestamp", False)),
        ),
        features=("temporal.today_calendar",),
    ),
    ConformanceCase(
        "today_welsh_relative",
        "SELECT id FROM @yt_sql_fixture WHERE upload_date >= TODAY()-3dydd ORDER BY upload_date ASC, release_timestamp ASC",
        _ids_where(
            lambda r: r["upload_date"] is not None and str(r["upload_date"]) >= "20260829",
            order=(("upload_date", False), ("release_timestamp", False)),
        ),
        features=("temporal.localised",),
    ),
    ConformanceCase(
        "positive_temporal_infinity",
        "SELECT id FROM @yt_sql_fixture WHERE upload_date < INFINITY() ORDER BY source_index",
        _ids_where(lambda r: r["upload_date"] is not None, order=(("source_index", False),)),
        features=("temporal.infinity_positive",),
    ),
    ConformanceCase(
        "negative_temporal_infinity",
        "SELECT id FROM @yt_sql_fixture WHERE upload_date > -INFINITY() ORDER BY source_index",
        _ids_where(lambda r: r["upload_date"] is not None, order=(("source_index", False),)),
        features=("temporal.infinity_negative",),
    ),
    ConformanceCase(
        "bounded_by_temporal_infinities",
        "SELECT id FROM @yt_sql_fixture WHERE upload_date BETWEEN -INFINITY() AND INFINITY() ORDER BY source_index",
        _ids_where(lambda r: r["upload_date"] is not None, order=(("source_index", False),)),
        features=("temporal.infinity_between",),
    ),
    ConformanceCase(
        "today_decade_relative",
        "SELECT id FROM @yt_sql_fixture WHERE upload_date >= TODAY()-1decade ORDER BY source_index",
        _ids_where(lambda r: r["upload_date"] is not None, order=(("source_index", False),)),
        features=("temporal.unit_decade",),
    ),
    ConformanceCase(
        "today_baktun_relative",
        "SELECT id FROM @yt_sql_fixture WHERE upload_date >= TODAY()-1baktun ORDER BY source_index",
        _ids_where(lambda r: r["upload_date"] is not None, order=(("source_index", False),)),
        features=("temporal.unit_baktun",),
    ),
    ConformanceCase(
        "relative_date_ago",
        "SELECT id FROM @yt_sql_fixture WHERE upload_date >= '3 days ago' ORDER BY upload_date ASC, release_timestamp ASC",
        _ids_where(
            lambda r: r["upload_date"] is not None and str(r["upload_date"]) >= "20260829",
            order=(("upload_date", False), ("release_timestamp", False)),
        ),
        features=("date.relative_ago",),
    ),
    ConformanceCase(
        "now_fixed_relative",
        "SELECT id FROM @yt_sql_fixture WHERE release_timestamp >= NOW()-36h ORDER BY release_timestamp ASC",
        _ids_where(
            lambda r: (
                r["release_timestamp"] is not None
                and int(r["release_timestamp"]) >= int(datetime(2026, 8, 31, 0, 0, tzinfo=timezone.utc).timestamp())
            ),
            order=(("release_timestamp", False),),
        ),
        features=("temporal.now_fixed",),
    ),
    ConformanceCase(
        "case_bucket_projection",
        "SELECT id, CASE WHEN duration < 10m THEN 'short' WHEN duration < 1h THEN 'medium' ELSE 'long' END AS bucket FROM @yt_sql_fixture WHERE source_index <= 20 ORDER BY source_index",
        _case_bucket,
        ("id", "bucket"),
        "jsonl",
        features=("scalar.case",),
    ),
    ConformanceCase(
        "case_null_and_ordered_fallthrough",
        "SELECT id, CASE WHEN view_count IS NULL THEN 'missing' WHEN view_count >= 1m THEN 'popular' ELSE 'ordinary' END AS state FROM @yt_sql_fixture WHERE source_index <= 24 ORDER BY source_index",
        _case_null_fallthrough,
        ("id", "state"),
        "jsonl",
        features=("scalar.case.null_fallthrough",),
    ),
    ConformanceCase(
        "case_without_else_returns_null",
        "SELECT id, CASE WHEN duration < 10m THEN 1 END AS flag FROM @yt_sql_fixture WHERE source_index <= 16 ORDER BY source_index",
        _case_without_else,
        ("id", "flag"),
        "jsonl",
        features=("scalar.case.no_else",),
    ),
    ConformanceCase(
        "case_nested_scalar_results",
        "SELECT id, CASE WHEN view_count IS NULL THEN LENGTH(LOWER(title)) ELSE (view_count + 2) * 3 END AS score FROM @yt_sql_fixture WHERE source_index <= 16 ORDER BY source_index",
        _case_nested_result,
        ("id", "score"),
        "jsonl",
        features=("scalar.case.nested_result",),
    ),
    ConformanceCase(
        "case_direct_ordering",
        "SELECT id FROM @yt_sql_fixture WHERE source_index <= 20 ORDER BY CASE WHEN duration < 10m THEN 1 WHEN duration < 1h THEN 2 ELSE 3 END, source_index",
        _case_ordering,
        features=("scalar.case.order",),
    ),
    ConformanceCase(
        "nullif_scalar_semantics",
        "SELECT id, NULLIF('é','é') AS same, NULLIF('é','é') AS distinct, NULLIF(title,NULL) AS null_second FROM @yt_sql_fixture WHERE source_index <= 6 ORDER BY source_index",
        _nullif_projection,
        ("id", "same", "distinct", "null_second"),
        "jsonl",
        features=("scalar.nullif",),
    ),
    ConformanceCase(
        "greatest_scalar_semantics",
        "SELECT id, GREATEST(0x10,0o40,0b11) AS numeric, GREATEST('é','é','ß') AS unicode FROM @yt_sql_fixture WHERE source_index <= 6 ORDER BY source_index",
        _greatest_projection,
        ("id", "numeric", "unicode"),
        "jsonl",
        features=("scalar.greatest",),
    ),
    ConformanceCase(
        "least_scalar_semantics",
        "SELECT id, LEAST(10,0x20,0b11) AS numeric, LEAST('β','α','Ω') AS unicode FROM @yt_sql_fixture WHERE source_index <= 6 ORDER BY source_index",
        _least_projection,
        ("id", "numeric", "unicode"),
        "jsonl",
        features=("scalar.least",),
    ),
    ConformanceCase(
        "concat_text_projection",
        "SELECT CONCAT(id, ' # ', title) AS annotated FROM @yt_sql_fixture WHERE source_index <= 4 ORDER BY source_index",
        _concat_projection,
        ("annotated",),
        "lines",
        features=("scalar.concat",),
    ),
    ConformanceCase(
        "char_unicode_projection",
        "SELECT id, CHAR(65,946,128512) AS chars, CHAR(101,769) AS decomposed FROM @yt_sql_fixture WHERE source_index <= 4 ORDER BY source_index",
        _char_projection,
        ("id", "chars", "decomposed"),
        "jsonl",
        features=("scalar.char",),
    ),
    ConformanceCase(
        "unicode_exact_normalisation_sensitive",
        "SELECT id, title FROM @yt_sql_fixture WHERE title IN ('Café composed é', 'Café decomposed é') ORDER BY source_index",
        _unicode_exact_normalisation,
        ("id", "title"),
        "jsonl",
        features=("unicode.normalisation_sensitive",),
    ),
    ConformanceCase(
        "unicode_codepoint_length",
        "SELECT id, LENGTH(title) AS chars FROM @yt_sql_fixture WHERE id IN ('vid037','vid038','vid040','vid041','vid042','vid043','vid056','vid059','vid060') ORDER BY source_index",
        _unicode_lengths,
        ("id", "chars"),
        "jsonl",
        features=("unicode.codepoint_length",),
    ),
    ConformanceCase(
        "unicode_contains_casefold",
        "SELECT id FROM @yt_sql_fixture WHERE title CONTAINS 'strasse' ORDER BY source_index",
        _unicode_contains_casefold,
        features=("unicode.casefold_contains",),
    ),
    ConformanceCase(
        "unicode_like_one_codepoint",
        "SELECT id FROM @yt_sql_fixture WHERE title LIKE 'Emoji _' ORDER BY source_index",
        _unicode_like_single_codepoint,
        features=("unicode.like_codepoint",),
    ),
    ConformanceCase(
        "unicode_ilike_special_case_equivalence",
        "SELECT id FROM @yt_sql_fixture WHERE id IN ('vid045','vid047','vid048') AND (title ILIKE '%i%' OR title ILIKE '%s%' OR title ILIKE '%k%') ORDER BY source_index",
        _unicode_ilike_specials,
        features=("unicode.ilike_case",),
    ),
    ConformanceCase(
        "unicode_lower_upper",
        "SELECT id, LOWER(title) AS lowered, UPPER(title) AS uppered FROM @yt_sql_fixture WHERE id IN ('vid044','vid045','vid046','vid047','vid048') ORDER BY source_index",
        _unicode_case_functions,
        ("id", "lowered", "uppered"),
        "jsonl",
        features=("unicode.case_mapping",),
    ),
    ConformanceCase(
        "unicode_regex_scripts",
        "SELECT id FROM @yt_sql_fixture WHERE title MATCHES '東京|مرحبا|שלום' ORDER BY source_index",
        _unicode_regex_scripts,
        features=("unicode.regex",),
    ),
    ConformanceCase(
        "unicode_codepoint_ordering",
        "SELECT id FROM @yt_sql_fixture WHERE id IN ('vid044','vid045','vid046','vid047','vid048','vid049','vid050','vid051') ORDER BY title ASC",
        _unicode_codepoint_order,
        features=("unicode.ordering",),
    ),
    ConformanceCase(
        "seeded_random_projection",
        "SELECT id, RANDOM(0xC0FFEE) AS shuffle_key FROM @yt_sql_fixture WHERE source_index <= 8 ORDER BY id",
        _seeded_random,
        ("id", "shuffle_key"),
        "jsonl",
        features=("scalar.random_seeded",),
    ),
    ConformanceCase(
        "aggregate_global_semantics",
        "SELECT COUNT(*) AS rows, COUNT(view_count) AS known_views, SUM(view_count) AS total_views, AVG(view_count) AS mean_views, MIN(title) AS first_title, MAX(title) AS last_title FROM @yt_sql_fixture",
        _aggregate_global,
        ("rows", "known_views", "total_views", "mean_views", "first_title", "last_title"),
        "jsonl",
        features=(
            "aggregate.count_star",
            "aggregate.count_expression",
            "aggregate.sum",
            "aggregate.avg",
            "aggregate.min",
            "aggregate.max",
        ),
    ),
    ConformanceCase(
        "aggregate_group_by_having_unicode",
        "SELECT title, COUNT(*) AS n FROM @yt_sql_fixture GROUP BY title HAVING n > 1 ORDER BY n DESC",
        _aggregate_grouped_unicode,
        ("title", "n"),
        "jsonl",
        features=("aggregate.group_by", "aggregate.having"),
    ),
    ConformanceCase(
        "aggregate_filter_semantics",
        "SELECT COUNT(*) FILTER (WHERE duration < 10m) AS short, SUM(view_count) FILTER (WHERE duration < 10m) AS short_views FROM @yt_sql_fixture",
        _aggregate_filter,
        ("short", "short_views"),
        "jsonl",
        features=("aggregate.filter",),
    ),
    ConformanceCase(
        "aggregate_empty_input",
        "SELECT COUNT(*) AS n, SUM(view_count) AS total FROM @yt_sql_fixture WHERE id = '__missing__'",
        _aggregate_empty,
        ("n", "total"),
        "jsonl",
        features=("aggregate.empty_input",),
    ),
    ConformanceCase(
        "cte_chained_logical_schema",
        "WITH short AS (SELECT id, title, duration / 60 AS minutes FROM @yt_sql_fixture WHERE duration < 1h), mars AS (SELECT id, minutes FROM short WHERE title ILIKE '%mars%') SELECT id, minutes FROM mars ORDER BY minutes DESC LIMIT 7",
        _cte_chained_projection,
        ("id", "minutes"),
        "jsonl",
        features=("cte.non_recursive", "cte.chained", "cte.logical_schema"),
    ),
    ConformanceCase(
        "union_distinct_same_source",
        "SELECT id FROM @yt_sql_fixture WHERE fixture_group IN (1, 2) UNION SELECT id FROM @yt_sql_fixture WHERE fixture_group IN (2, 3) ORDER BY id LIMIT 12",
        _union_distinct,
        features=("set.union", "set.global_order_limit"),
    ),
    ConformanceCase(
        "union_all_duplicate_preservation",
        "SELECT id FROM @yt_sql_fixture WHERE fixture_group = 1 UNION ALL SELECT id FROM @yt_sql_fixture WHERE fixture_group = 1 ORDER BY id LIMIT 12",
        _union_all,
        features=("set.union_all",),
    ),
    ConformanceCase(
        "convoluted_existing_language",
        "SELECT DISTINCT id, LOWER(title) AS folded FROM @yt_sql_fixture WHERE ((duration BETWEEN 10m AND 1h AND (title CONTAINS 'mars' OR view_count >= 1m)) OR (view_count IS NULL AND title IS NOT NULL)) AND upload_date IS NOT NULL ORDER BY upload_date DESC, release_timestamp ASC LIMIT 9 OFFSET 1",
        _convoluted,
        ("id", "folded"),
        "jsonl",
    ),
)
