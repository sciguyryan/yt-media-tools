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


def _char_projection(rows: Rows) -> list[Any]:
    return (
        OracleQuery(rows)
        .where(lambda r: int(r["source_index"]) <= 4)
        .order_by(lambda r: r["source_index"])
        .select(lambda r: {"id": r["id"], "chars": "Aβ😀", "decomposed": "e\u0301"})
        .to_list()
    )


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
        "in",
        "in.not",
        "is.false",
        "is.not_false",
        "is.not_null",
        "is.not_true",
        "is.null",
        "is.true",
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
        "projection.upper",
        "scalar.arithmetic.add",
        "scalar.arithmetic.divide",
        "scalar.arithmetic.multiply",
        "scalar.arithmetic.parentheses",
        "scalar.function_nested",
        "scalar.char",
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
        "value.count_comma",
        "value.count_decimal_suffix",
        "value.count_k",
        "value.count_m",
        "value.count_underscore",
        "value.enum_case_insensitive",
        "unicode.normalisation_sensitive",
        "unicode.codepoint_length",
        "unicode.casefold_contains",
        "unicode.ilike_case",
        "unicode.like_codepoint",
        "unicode.case_mapping",
        "unicode.regex",
        "unicode.ordering",
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
        "count_comma",
        "SELECT id FROM @yt_sql_fixture WHERE view_count >= 1,000,000 ORDER BY source_index ASC LIMIT 8",
        _ids_where(lambda r: r["view_count"] is not None and int(r["view_count"]) >= 1_000_000, take=8),
        features=("value.count_comma",),
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
        "convoluted_existing_language",
        "SELECT DISTINCT id, LOWER(title) AS folded FROM @yt_sql_fixture WHERE ((duration BETWEEN 10m AND 1h AND (title CONTAINS 'mars' OR view_count >= 1m)) OR (view_count IS NULL AND title IS NOT NULL)) AND upload_date IS NOT NULL ORDER BY upload_date DESC, release_timestamp ASC LIMIT 9 OFFSET 1",
        _convoluted,
        ("id", "folded"),
        "jsonl",
    ),
)
