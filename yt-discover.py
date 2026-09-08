#!/usr/bin/env python3
"""Discover and query YouTube channel or playlist metadata using yt-dlp."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from time import perf_counter
from pathlib import Path

from yt_media_tools.archive import exclude_archive, read_archive_ids
from yt_media_tools.cache import CacheStats, MetadataCache, SourceCoverage, default_cache_path
from yt_media_tools.capabilities import capabilities_for_fields, safely_reject_lightweight
from yt_media_tools.dates import DateContext
from yt_media_tools.metadata import normalise_record
from yt_media_tools.planner import (
    AcquisitionPlan,
    assess_cost,
    plan_acquisition,
    plan_limit_termination,
    required_query_fields,
)
from yt_media_tools.optimizer import optimise_query
from yt_media_tools.output import append_unique_ids, write_records
from yt_media_tools.report import RunReport, write_report
from yt_media_tools.tools import ToolRegistry, ToolStatus, check_tools, format_tool_check
from yt_media_tools.youtubejs import (
    YouTubeJsError,
    enumerate_until_date_boundary as enumerate_youtubejs_until_date_boundary,
)
from yt_media_tools.query import (
    Binary,
    Field,
    IsNull,
    Literal,
    OrderTerm,
    Query,
    QuerySyntaxError,
    SelectTerm,
    apply_query,
    format_query,
    explain_expression,
    merge_queries,
    parse_query,
    parse_where,
    resolve_query,
)
from yt_media_tools.schema import QuerySchema
from yt_media_tools.sources import TAB_SUFFIXES, SourceSpec, resolve_source
from yt_media_tools.ytdlp import (
    AcquisitionStats,
    EnumerationStats,
    YtDlpError,
    build_lazy_flat_command,
    build_metadata_command,
    build_video_metadata_command,
    enumerate_all_flat,
    enumerate_until_date_boundary,
    enumerate_until_known_overlap,
    load_metadata,
    shell_join,
)


PROGRAM_VERSION = "0.23.6"

DEFAULT_ENUMERATION_PROGRESS_INTERVAL = 100
VERBOSE_ENUMERATION_PROGRESS_INTERVAL = 25
DEFAULT_ARCHIVE_FILE = Path("/mnt/storage/Storage/Scripts/archive.txt")
FRONTIER_OVERLAP_CONFIRMATIONS = 5

EXAMPLES = r"""
Examples:

  Complete yt-sql queries
  -----------------------------
  The canonical form can contain SELECT, DISTINCT, FROM, WHERE, ORDER BY, LIMIT, and OFFSET:
    yt-discover.py "FROM @example WHERE upload_date BETWEEN 2026-04-01 AND TODAY()"

  Omitted SELECT means SELECT id, preserving pipe-friendly video ID output:
    yt-discover.py "FROM @example WHERE upload_date >= 2026-04-01" | yt-download.py -

  Safely maintain a persistent ID list, appending only IDs not already present:
    yt-discover.py --tab videos "SELECT id FROM @example WHERE duration < 1h ORDER BY upload_date ASC, release_timestamp ASC" --append ./ids/example

  Plain shell append remains available when deduplication is not required:
    yt-discover.py "FROM @example WHERE upload_date >= TODAY()-7d" >> ./ids/example

  Select one metadata field. One selected field is printed one value per line:
    yt-discover.py "SELECT title FROM @example ORDER BY upload_date DESC"

  Select several fields. Multiple fields default to JSON Lines:
    yt-discover.py "SELECT id, title, upload_date, duration, views FROM @example WHERE upload_date >= 2026-01-01 ORDER BY upload_date DESC"

  Rename a selected output field with AS:
    yt-discover.py "SELECT title, view_count AS views FROM @example ORDER BY views DESC LIMIT 25"

  Remove duplicate projected rows and page deterministically with OFFSET:
    yt-discover.py "SELECT DISTINCT title FROM @example ORDER BY upload_date DESC LIMIT 25 OFFSET 50"

  Use scalar expressions, nested functions, and computed ordering:
    yt-discover.py "SELECT id, duration / 60 AS minutes FROM @example ORDER BY minutes DESC"
    yt-discover.py "SELECT id, (view_count + 10) * 2 AS score FROM @example ORDER BY score + 1 DESC"
    yt-discover.py "SELECT id, LENGTH(LOWER(title)) AS characters FROM @example ORDER BY characters DESC"
    yt-discover.py "SELECT COALESCE(title, 'Untitled') AS title FROM @example"

  Bind reusable typed values without editing the query text:
    yt-discover.py --param start=2026-08-01 --param maximum=1h "SELECT id FROM @example WHERE upload_date >= :start AND duration < :maximum"

  Write machine-readable provenance alongside normal query output:
    yt-discover.py --provenance ./query-provenance.json "SELECT id FROM @example WHERE duration < 1h"

  Query a playlist using the same language:
    yt-discover.py "SELECT playlist_index, id, title, duration FROM PLxxxxxxxxxxxxxxxxxxxxxx ORDER BY playlist_index ASC"

  Quote full URLs in FROM:
    yt-discover.py "SELECT id, title FROM 'https://www.youtube.com/playlist?list=PLxxxxxxxxxxxxxxxxxxxxxx'"

  SELECT * is deliberately unsupported because yt-dlp metadata is dynamic. Use
  --fields or --schema to discover scalar fields, then name the fields you need.

  Source shorthand and compatibility
  ----------------------------------
  The established positional-source interface remains supported:
    yt-discover.py @example --where "duration < 45m AND views >= 5k"
    yt-discover.py PLxxxxxxxxxxxxxxxxxxxxxx --query "WHERE duration >= 30m ORDER BY playlist_index ASC"

  A bare name is a channel handle; channel IDs and playlist IDs are detected:
    yt-discover.py example
    yt-discover.py UCxxxxxxxxxxxxxxxxxxxxxx
    yt-discover.py PLxxxxxxxxxxxxxxxxxxxxxx

  Force unusual source interpretation when necessary:
    yt-discover.py --source-type playlist SOME_PLAYLIST_ID
    yt-discover.py --source-type channel SOME_CHANNEL_NAME

  Channel tabs remain acquisition options:
    yt-discover.py @example --tab videos
    yt-discover.py @example --tab shorts
    yt-discover.py @example --tab live

  Filtering and Boolean logic
  ---------------------------
  Combine predicates with AND, OR, NOT, and parentheses:
    yt-discover.py "FROM @example WHERE (duration < 10m OR duration > 2h) AND views >= 100k AND NOT title CONTAINS 'trailer'"

  Test missing metadata explicitly:
    yt-discover.py "FROM @example WHERE duration IS NOT NULL AND duration < 45m"

  IN, BETWEEN, and their negated forms are supported:
    yt-discover.py "FROM @example WHERE live_status IN ('not_live', 'was_live')"
    yt-discover.py "FROM @example WHERE duration NOT BETWEEN 30m AND 2h"
    yt-discover.py "FROM @example WHERE live_status NOT IN ('is_live', 'is_upcoming')"

  Text search and regular expressions:
    yt-discover.py "FROM @example WHERE title CONTAINS 'documentary'"
    yt-discover.py "FROM @example WHERE title NOT CONTAINS 'trailer'"
    yt-discover.py "FROM @example WHERE title MATCHES '^Episode [0-9]+'"

  Dates and timestamps
  --------------------
  ISO dates are preferred and portable:
    yt-discover.py "FROM @example WHERE upload_date >= 2024-01-01"

  Compact yt-dlp dates, local numeric dates, and named dates are accepted:
    yt-discover.py @example --where "upload_date >= 20240101"
    yt-discover.py @example --where "upload_date >= 31/01/2024"
    yt-discover.py @example --date-format mdy --where "upload_date >= 01/31/2024"
    yt-discover.py @example --where "upload_date >= 1 January 2024"

  Relative dates remain available in readable form:
    yt-discover.py @example --where "upload_date >= 6 months ago"
    yt-discover.py @example --where "upload_date BETWEEN 1 year ago AND today"

  TODAY() is a typed local calendar date:
    yt-discover.py "FROM @example WHERE upload_date BETWEEN TODAY()-1yr AND TODAY()"
    yt-discover.py "FROM @example WHERE upload_date >= TODAY()-6mo"
    yt-discover.py "FROM @example WHERE upload_date < TODAY()+1w"

  NOW() is a typed timestamp:
    yt-discover.py "FROM @example WHERE release_timestamp >= NOW()-48h"
    yt-discover.py "FROM @example WHERE release_timestamp BETWEEN NOW()-1yr AND NOW()"

  TODAY() and NOW() are captured once per query run. Date fields require TODAY();
  timestamp fields require NOW(). Timestamp literals may include timezone offsets:
    yt-discover.py @example --where "release_timestamp >= 2024-01-01T18:30:00Z"

  Human values
  ------------
  Durations accept compact, clock, and worded forms:
    yt-discover.py @example --where "duration BETWEEN 10m AND 2h"
    yt-discover.py @example --where "duration >= 1h30m"
    yt-discover.py @example --where "duration >= 90 minutes"
    yt-discover.py @example --where "duration >= 01:30:00"

  Counts accept separators and magnitude suffixes:
    yt-discover.py @example --where "views >= 10k"
    yt-discover.py @example --where "views >= 1.5m"
    yt-discover.py @example --where "view_count >= 1_000_000"

  Dynamic and nested metadata
  ---------------------------
  Any scalar top-level yt-dlp JSON field can become queryable and selectable:
    yt-discover.py "SELECT id, channel_follower_count FROM @example WHERE channel_follower_count >= 100k"

  Friendly aliases include:
    views       -> view_count
    likes       -> like_count
    comments    -> comment_count
    date        -> upload_date
    url         -> webpage_url

  Select or filter scalar nested raw yt-dlp data with dotted paths:
    yt-discover.py "SELECT id, raw.some_object.some_value AS score FROM @example WHERE raw.some_object.some_value >= 10"

  Objects and arrays are intentionally not assigned scalar semantics. Select a
  scalar child path instead.

  Discover available fields from real metadata:
    yt-discover.py @example --items 1 --fields
    yt-discover.py @example --items 1 --schema

  Ordering, reversal, and limits
  -----------------------------
  ORDER BY supports multiple fields and stable source-order tie-breaking:
    yt-discover.py "SELECT id, title, views FROM @example WHERE views >= 10k ORDER BY upload_date DESC, views DESC LIMIT 100"

  Missing ORDER BY values are always placed last. BETWEEN is inclusive.

  LIMIT can stop detailed metadata acquisition early when source order is the final
  result order. This is exact for queries without ORDER BY:
    yt-discover.py "SELECT id FROM @example WHERE duration < 1h LIMIT 25" -v

  An explicit ORDER BY may require later rows to be considered, so those LIMIT queries
  remain exhaustive unless a future planner rule can prove an ordering-specific shortcut:
    yt-discover.py "SELECT id FROM @example WHERE duration < 1h ORDER BY upload_date DESC LIMIT 25" -v

  Existing shortcuts remain available:
    yt-discover.py @example --sort newest
    yt-discover.py @example --sort oldest
    yt-discover.py PLxxxxxxxxxxxxxxxxxxxxxx --rev
    yt-discover.py @example --limit 100

  Output and files
  ----------------
  Automatic output uses lines for one selected field and JSONL for several:
    yt-discover.py "SELECT title FROM @example"
    yt-discover.py "SELECT id, title, views FROM @example"

  Request structured formats explicitly:
    yt-discover.py "SELECT id, title, upload_date, views FROM @example" --format jsonl
    yt-discover.py "SELECT id, title, upload_date, views FROM @example" --format csv > videos.csv
    yt-discover.py "SELECT id, title, upload_date, views FROM @example" --format tsv > videos.tsv

  --format lines requires exactly one selected field:
    yt-discover.py "SELECT url FROM @example WHERE views >= 100k" --format lines

  Legacy output shortcuts remain when SELECT is omitted:
    yt-discover.py @example --format ids
    yt-discover.py @example --format urls

  Write output directly to a file:
    yt-discover.py "SELECT id, title, views FROM @example" --format csv --output videos.csv

  Persistent metadata cache
  -------------------------
  Detailed yt-dlp metadata is cached by source and video ID. Fresh fields are reused
  after source enumeration; stale or missing required fields are refreshed:
    yt-discover.py --tab videos "FROM @example WHERE duration < 1h" -v

  Override the XDG-compatible SQLite cache location:
    yt-discover.py --cache ./metadata.sqlite3 --tab videos "FROM @example WHERE views >= 100k"

  Disable cache reads and writes for a diagnostic or clean acquisition run:
    yt-discover.py --no-cache --tab videos "FROM @example WHERE upload_date >= TODAY()-30d"

  Eligible channel-video queries may reuse the trusted persisted source ordering as an
  incremental frontier. If overlap cannot be confirmed, yt-discover completes source
  enumeration and rebuilds the trusted ordering before continuing.

  Tool checks and acquisition backends
  ------------------------------------
  Check required and optional tools before contacting YouTube:
    yt-discover.py --check-tools

  Automatic mode prefers YouTube.js for bounded channel enumeration when it is
  installed locally, then uses yt-dlp for authoritative detailed extraction:
    yt-discover.py --tab videos "FROM @example WHERE upload_date >= TODAY()-6mo" --backend auto -v

  Force the zero-extra-dependency yt-dlp enumeration backend:
    yt-discover.py --tab videos "FROM @example WHERE upload_date >= TODAY()-6mo" --backend ytdlp

  Require YouTube.js. This fails clearly rather than silently falling back if the
  optional backend is unavailable or fails at runtime:
    yt-discover.py --tab videos "FROM @example WHERE upload_date >= TODAY()-6mo" --backend youtubejs

  With --backend auto, missing or failed YouTube.js enumeration is announced on
  stderr and yt-dlp bounded enumeration is used as the fallback. Full acquisition
  and detailed candidate extraction always use yt-dlp.

  Acquisition controls
  --------------------
  Let the query planner bound a newest-first channel videos scan by date:
    yt-discover.py --tab videos "FROM @example WHERE upload_date BETWEEN 2026-04-01 AND TODAY()" -v

  In automatic mode, eligible date-bounded channel video queries first use yt-dlp's
  lazy flat-playlist enumeration with approximate dates. Enumeration terminates only
  after a conservative safety boundary is confirmed, then full metadata is acquired
  for the candidate IDs and the original WHERE is evaluated authoritatively.

  Force the previous exhaustive acquisition behaviour when desired:
    yt-discover.py --tab videos "FROM @example WHERE upload_date >= 2026-04-01" --acquisition full

  Automatic bounded acquisition is deliberately conservative. It currently applies
  only to the channel videos tab when the WHERE expression logically implies a lower
  upload_date bound. Playlist ordering, --tab all, shorts/live tabs, and unsafe OR/NOT
  predicates fall back to exhaustive acquisition.

  Restrict entries before full metadata extraction using yt-dlp playlist syntax:
    yt-discover.py @example --items 1:100 --where "views >= 5k"

  Exclude IDs already present in the downloader archive:
    yt-discover.py @example --exclude-archive --where "upload_date >= 2024-01-01"

  Keep expert yt-dlp acquisition prefilters where useful:
    yt-discover.py @example --after 20240101 --match-filter "duration > 600"

  Cache-native and offline queries
  --------------------------------
  Query cached detailed metadata without contacting YouTube or refreshing stale fields:
    yt-discover.py --offline --tab videos "SELECT id, title FROM @example WHERE duration < 1h ORDER BY upload_date ASC"

  Offline mode reports incomplete/unknown source coverage and stale required fields explicitly.
  It never silently treats cached rows as a complete current source.

  Query validation and diagnostics
  --------------------------------
  Validate a complete query without contacting YouTube:
    yt-discover.py --check-query "SELECT id, title FROM @example WHERE duration BETWEEN 10m AND 2h ORDER BY views DESC"

  Explain what a complete query means without contacting YouTube:
    yt-discover.py --explain "SELECT id FROM @example WHERE upload_date BETWEEN TODAY()-1yr AND TODAY() ORDER BY upload_date ASC"

  Explain aliases, temporal values, ordering, limits, and expected output:
    yt-discover.py --explain "SELECT id, views AS popularity FROM @example WHERE upload_date >= TODAY()-6mo ORDER BY popularity DESC LIMIT 25"

  Explain field capabilities and optimisation paths for a bounded query:
    yt-discover.py --tab videos --explain "SELECT id FROM @example WHERE upload_date BETWEEN 2026-04-01 AND 2026-06-30 AND duration < 1h LIMIT 25"

  Emit the planned explanation as machine-readable JSON:
    yt-discover.py --tab videos --explain-format json --explain "SELECT id FROM @example WHERE upload_date >= 2026-08-01 AND duration < 1h LIMIT 25"

  Execute the query but suppress normal rows and show what actually happened:
    yt-discover.py --tab videos --explain-analyze "SELECT id FROM @example WHERE upload_date >= 2026-08-01 AND duration < 1h LIMIT 25"

  Analyse a cache-only execution without contacting YouTube:
    yt-discover.py --offline --tab videos --explain-analyze "SELECT id FROM @example WHERE duration < 1h ORDER BY upload_date ASC"

  The explanation identifies active bounded enumeration, lightweight rejection,
  safe upper-date pruning, backend opportunities, detailed-only fields, and
  optimisation paths, including whether LIMIT-aware detailed acquisition can terminate safely.

  Inspect source resolution, yt-dlp command, and parsed query:
    yt-discover.py "SELECT id, title FROM @example WHERE duration < 45m" --dry-run

  Show concise live acquisition progress on stderr while keeping stdout pipe-safe:
    yt-discover.py -v "FROM @example WHERE upload_date >= TODAY()-30d" | yt-download.py -

  Show every successfully acquired entry as well as skipped/inaccessible entries:
    yt-discover.py -vv "FROM @example WHERE upload_date >= TODAY()-30d"

  -v reports periodic acquisition counts and important skips. -vv additionally reports
  every available entry. Both modes keep query-result stdout clean for pipelines.

  Print a post-run acquisition/query report to the console (stderr by default):
    yt-discover.py "FROM @example WHERE upload_date >= TODAY()-30d" --report

  Write the report to a file while keeping result output separate:
    yt-discover.py "SELECT id, title FROM @example" --report acquisition-report.txt

  Explicitly place the report on stdout when no pipeline-safe separation is required:
    yt-discover.py "FROM @example" --report -

  Reports include videos attempted/observed, metadata available, inaccessible/skipped
  entries by category, archive exclusions, WHERE matches, LIMIT effects, and emitted rows.

  Show this full example reference:
    yt-discover.py --examples

Query language summary:

  Clauses:
    [SELECT <field> [AS <name>] [, ...]]
    [FROM <source>]
    [WHERE <expression>]
    [ORDER BY <field> [ASC|DESC] [, ...]]
    [LIMIT <positive integer>]
    [OFFSET <non-negative integer>]

  Omitted SELECT means SELECT id. A complete positional query normally uses FROM;
  the older positional SOURCE plus --where/--query form remains supported.

  Predicates:
    =  !=  <>  <  <=  >  >=
    BETWEEN ... AND ...
    NOT BETWEEN ... AND ...
    IN (...)
    NOT IN (...)
    IS NULL / IS NOT NULL
    IS TRUE / IS FALSE
    CONTAINS / NOT CONTAINS
    MATCHES / NOT MATCHES
    LIKE / NOT LIKE
    ILIKE / NOT ILIKE
    AND / OR / NOT
    parentheses

  Readable comparison aliases retained for convenience:
    at least, at most, greater than, more than, less than,
    over, above, under, below, equals, equal to

  Serialisation formats:
    auto, lines, jsonl, csv, tsv
    ids and urls remain legacy shortcuts when SELECT is omitted
""".strip()


def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def non_negative_int(value: str) -> int:
    """Return a non-negative integer or raise an argparse type error."""
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a non-negative integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("expected a non-negative integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Discover full YouTube video metadata from a channel or playlist, query it locally, "
            "and emit video IDs by default."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EXAMPLES,
    )
    parser.add_argument(
        "source",
        nargs="?",
        metavar="SOURCE_OR_QUERY",
        help="source identifier/URL, or a complete SELECT/FROM query",
    )
    parser.add_argument(
        "--source-type",
        choices=("auto", "channel", "playlist"),
        default="auto",
        help="override automatic source classification (default: auto)",
    )
    parser.add_argument(
        "--tab",
        choices=tuple(TAB_SUFFIXES),
        default="all",
        help="channel tab to inspect; invalid for playlist sources (default: all)",
    )

    query_group = parser.add_mutually_exclusive_group()
    query_group.add_argument(
        "--where", metavar="EXPRESSION", help="yt-sql predicate, optionally followed by ORDER BY/LIMIT/OFFSET"
    )
    query_group.add_argument(
        "--query",
        metavar="QUERY",
        help="yt-sql query with optional SELECT DISTINCT, FROM, WHERE, ORDER BY, LIMIT, and OFFSET clauses",
    )
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="bind :NAME query parameters as typed field literals; repeatable",
    )

    compatibility = parser.add_argument_group("query compatibility and acquisition prefilters")
    compatibility.add_argument(
        "--filter",
        action="append",
        default=[],
        metavar="EXPRESSION",
        help="additional readable predicate; repeatable and ANDed with the main query",
    )
    compatibility.add_argument("--date", metavar="DATE", help="yt-dlp acquisition prefilter for an exact date")
    compatibility.add_argument(
        "--after", metavar="DATE", help="yt-dlp acquisition prefilter for videos on or after DATE"
    )
    compatibility.add_argument(
        "--before", metavar="DATE", help="yt-dlp acquisition prefilter for videos on or before DATE"
    )
    compatibility.add_argument(
        "--match-filter",
        action="append",
        default=[],
        metavar="FILTER",
        help="expert yt-dlp acquisition filter; may be supplied more than once",
    )
    compatibility.add_argument(
        "--backend",
        choices=("auto", "youtubejs", "ytdlp"),
        default="auto",
        help="choose the bounded channel enumeration backend; full/detailed extraction remains yt-dlp (default: auto)",
    )
    compatibility.add_argument(
        "--acquisition",
        choices=("auto", "full"),
        default="auto",
        help="choose query-planned acquisition or force exhaustive yt-dlp extraction (default: auto)",
    )

    selection = parser.add_argument_group("selection and ordering")
    selection.add_argument("--sort", choices=("newest", "oldest"), help="shortcut for ORDER BY upload_date DESC or ASC")
    selection.add_argument("--rev", "--reverse", action="store_true", help="reverse acquired source order before LIMIT")
    selection.add_argument("--limit", type=positive_int, metavar="COUNT", help="shortcut for LIMIT COUNT")
    selection.add_argument(
        "--warn-source-size",
        type=non_negative_int,
        default=500,
        metavar="COUNT",
        help="warn when an unbounded source scan reaches COUNT observed entries where possible; 0 disables (default: 500)",
    )
    selection.add_argument(
        "--items", metavar="ITEM_SPEC", help="restrict source extraction using yt-dlp playlist item syntax"
    )
    selection.add_argument("--exclude-live", action="store_true", help="shortcut for NOT is_live")
    selection.add_argument("--exclude-upcoming", action="store_true", help="shortcut for live_status != 'is_upcoming'")
    selection.add_argument(
        "--exclude-archive", action="store_true", help=f"exclude IDs already present in {DEFAULT_ARCHIVE_FILE}"
    )
    selection.add_argument(
        "--archive",
        type=Path,
        default=DEFAULT_ARCHIVE_FILE,
        metavar="FILE",
        help="archive file used by --exclude-archive",
    )
    selection.add_argument(
        "--date-format",
        choices=("dmy", "mdy", "ymd"),
        default="dmy",
        help="interpret ambiguous local numeric query dates (default: dmy; ISO is always accepted)",
    )

    cache_group = parser.add_argument_group("persistent metadata cache")
    cache_group.add_argument(
        "--cache",
        type=Path,
        default=default_cache_path(),
        metavar="FILE",
        help="SQLite metadata cache (default: XDG cache directory or ~/.cache/yt-discover/metadata.sqlite3)",
    )
    cache_group.add_argument(
        "--no-cache",
        action="store_true",
        help="disable metadata-cache reads and writes for this run",
    )
    cache_group.add_argument(
        "--offline",
        action="store_true",
        help="query only cached metadata; never contact YouTube or refresh stale fields",
    )

    introspection = parser.add_argument_group("introspection and validation")
    introspection_mode = introspection.add_mutually_exclusive_group()
    introspection_mode.add_argument(
        "--fields", action="store_true", help="acquire metadata, list queryable top-level fields and aliases, then exit"
    )
    introspection_mode.add_argument(
        "--schema", action="store_true", help="like --fields, also listing scalar nested raw.* paths"
    )
    introspection.add_argument(
        "--check-query", metavar="QUERY", help="check query grammar without acquiring metadata, then exit"
    )
    introspection_mode.add_argument(
        "--explain", metavar="QUERY", help="explain a complete query without contacting YouTube, then exit"
    )
    introspection_mode.add_argument(
        "--explain-analyze",
        metavar="QUERY",
        help="execute a complete query and report the actual plan/outcome without emitting query rows",
    )
    introspection_mode.add_argument(
        "--check-tools",
        action="store_true",
        help="check required and optional acquisition tools without contacting YouTube, then exit",
    )
    introspection.add_argument(
        "--explain-format",
        choices=("text", "json"),
        default="text",
        help="format for --explain and --explain-analyze (default: text)",
    )

    output = parser.add_argument_group("output")
    output.add_argument(
        "--format",
        choices=("auto", "lines", "jsonl", "csv", "tsv", "ids", "urls"),
        default="auto",
        help="serialisation format; auto uses lines for one SELECT field and JSONL for multiple fields",
    )
    output_dest = output.add_mutually_exclusive_group()
    output_dest.add_argument(
        "-o", "--output", type=Path, metavar="FILE", help="write output to FILE instead of standard output"
    )
    output_dest.add_argument(
        "--append", type=Path, metavar="FILE", help="atomically append only new video IDs not already present in FILE"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print resolved source, yt-dlp command, and parsed query without running yt-dlp",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="report live progress to stderr; repeat as -vv for per-entry acquisition detail",
    )
    parser.add_argument(
        "--report",
        nargs="?",
        const="stderr",
        metavar="FILE",
        help="print an acquisition/query report to stderr, or write it to FILE; use --report - for stdout",
    )
    parser.add_argument(
        "--provenance", metavar="FILE", help="write machine-readable JSON query provenance to FILE; use - for stdout"
    )
    parser.add_argument(
        "--examples",
        action="store_true",
        help="show the full practical example and query-language reference, then exit",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {PROGRAM_VERSION}")
    return parser


def looks_like_complete_query(value: str | None) -> bool:
    if value is None:
        return False
    first = value.lstrip().split(None, 1)[0].upper() if value.strip() else ""
    return first in {"SELECT", "FROM"}


def _parse_parameters(values: list[str]) -> dict[str, str]:
    """Parse repeatable NAME=VALUE bindings with case-insensitive names."""
    result: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise ValueError(f"--param requires NAME=VALUE, got {item!r}")
        name, value = item.split("=", 1)
        name = name.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ValueError(f"invalid parameter name {name!r}")
        key = name.casefold()
        if key in result:
            raise ValueError(f"duplicate query parameter {name!r}")
        result[key] = value
    return result


def bind_query_parameters(text: str, parameters: dict[str, str]) -> str:
    """Replace :name placeholders outside quoted SQL strings with safely quoted literals."""
    out: list[str] = []
    used: set[str] = set()
    i = 0
    quote: str | None = None
    while i < len(text):
        ch = text[i]
        if quote is not None:
            out.append(ch)
            if ch == quote:
                if i + 1 < len(text) and text[i + 1] == quote:
                    out.append(text[i + 1])
                    i += 2
                    continue
                quote = None
            elif ch == "\\" and i + 1 < len(text):
                out.append(text[i + 1])
                i += 2
                continue
            i += 1
            continue
        if ch in {"'", '"'}:
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == ":" and i + 1 < len(text) and (text[i + 1].isalpha() or text[i + 1] == "_"):
            j = i + 2
            while j < len(text) and (text[j].isalnum() or text[j] == "_"):
                j += 1
            name = text[i + 1 : j]
            key = name.casefold()
            if key not in parameters:
                raise ValueError(f"missing value for query parameter :{name}")
            value = parameters[key].replace("'", "''")
            out.append(f"'{value}'")
            used.add(key)
            i = j
            continue
        out.append(ch)
        i += 1
    unused = sorted(set(parameters) - used)
    if unused:
        raise ValueError("unused query parameter(s): " + ", ".join(unused))
    return "".join(out)


def parse_user_query(args: argparse.Namespace, inline_query: str | None = None) -> Query:
    parameters = _parse_parameters(args.param)
    if inline_query is not None:
        if args.query or args.where:
            raise ValueError("a positional complete query cannot be combined with --query or --where")
        query = parse_query(bind_query_parameters(inline_query, parameters))
    elif args.query:
        query = parse_query(bind_query_parameters(args.query, parameters))
    elif args.where:
        query = parse_where(bind_query_parameters(args.where, parameters))
    else:
        query = Query()

    for expression in args.filter:
        extra = parse_where(expression)
        if extra.order_by or extra.limit is not None or extra.offset or extra.distinct:
            raise ValueError(
                "--filter accepts predicates only; use --where or --query for DISTINCT/ORDER BY/LIMIT/OFFSET"
            )
        query = merge_queries(query, extra)

    if args.rev and args.sort is not None:
        raise ValueError("--rev/--reverse cannot be combined with --sort")

    shortcut = Query()
    if args.sort is not None:
        shortcut = Query(order_by=(OrderTerm("upload_date", descending=(args.sort == "newest")),))
    elif args.rev:
        shortcut = Query(order_by=(OrderTerm("source_index", descending=True),))

    if args.limit is not None:
        shortcut = Query(
            shortcut.predicate, shortcut.order_by, args.limit, shortcut.source, shortcut.select, shortcut.from_source
        )

    predicates = []
    if args.exclude_live:
        predicates.append(
            Binary(
                "OR",
                IsNull(Field("is_live")),
                Binary("=", Field("is_live"), Literal(False, "FALSE")),
            )
        )
    if args.exclude_upcoming:
        predicates.append(
            Binary(
                "OR",
                IsNull(Field("live_status")),
                Binary("!=", Field("live_status"), Literal("is_upcoming", "'is_upcoming'", quoted=True)),
            )
        )

    for predicate in predicates:
        shortcut = Query(
            predicate if shortcut.predicate is None else Binary("AND", shortcut.predicate, predicate),
            shortcut.order_by,
            shortcut.limit,
            shortcut.source,
            shortcut.select,
            shortcut.from_source,
            shortcut.distinct,
            shortcut.offset,
        )

    if query.order_by and shortcut.order_by:
        raise ValueError("ORDER BY in --where/--query cannot be combined with --sort/--rev")
    if query.limit is not None and shortcut.limit is not None:
        raise ValueError("LIMIT in --where/--query cannot be combined with --limit")
    return merge_queries(query, shortcut)


def print_schema(schema: QuerySchema, *, include_raw: bool) -> None:
    print("Field\tType\tNullable\tNotes")
    for info in schema.available_fields():
        notes = []
        if info.alias_of:
            notes.append(f"alias for {info.alias_of}")
        elif info.dynamic:
            notes.append("dynamic yt-dlp scalar")
        print(f"{info.name}\t{info.kind}\t{'yes' if info.nullable else 'no'}\t{'; '.join(notes)}")
    if include_raw:
        for info in schema.raw_scalar_paths():
            print(f"{info.name}\t{info.kind}\t{'yes' if info.nullable else 'no'}\traw nested scalar")


def _verbose(level: int, message: str, *, minimum: int = 1) -> None:
    """Write operational progress to stderr without contaminating pipeline output."""
    if level >= minimum:
        print(f"[yt-discover] {message}", file=sys.stderr, flush=True)


def _acquisition_progress(level: int):
    """Create a yt-dlp progress callback for concise (-v) or detailed (-vv) telemetry."""

    def callback(event: str, stats: AcquisitionStats, detail: str | None) -> None:
        if event == "available":
            if level >= 2:
                _verbose(level, f"Available entry {stats.available}: {detail}", minimum=2)
            elif level >= 1 and (stats.available == 1 or stats.available % 10 == 0):
                _verbose(level, f"Acquired {stats.available} available entries; {stats.skipped} skipped so far.")
        elif event == "skipped":
            _verbose(level, f"Skipped inaccessible entry: {detail}.")

    return callback


def _enumeration_progress(level: int, *, context: str, warn_threshold: int = 0):
    """Create pipe-safe progress reporting for potentially lengthy source enumeration."""
    interval = (
        1
        if level >= 2
        else VERBOSE_ENUMERATION_PROGRESS_INTERVAL
        if level >= 1
        else DEFAULT_ENUMERATION_PROGRESS_INTERVAL
    )
    large_warning_emitted = False

    def callback(event: str, stats: AcquisitionStats, detail: str | None) -> None:
        nonlocal large_warning_emitted
        if event != "enumerated":
            return
        count = stats.available
        if warn_threshold and not large_warning_emitted and count >= warn_threshold:
            print(
                f"yt-discover: large-source warning: {context} has already observed {count} items and is still enumerating "
                f"(configured warning threshold: {warn_threshold}).",
                file=sys.stderr,
                flush=True,
            )
            large_warning_emitted = True
        if count == 1 and level >= 1:
            _verbose(level, f"{context}: observed first source item.")
        elif count and count % interval == 0:
            if level >= 1:
                _verbose(level, f"{context}: enumerated {count} source items so far.")
            else:
                print(
                    f"yt-discover: {context}: enumerated {count} source items so far.",
                    file=sys.stderr,
                    flush=True,
                )

    return callback


def _effective_output_format(output_format: str, selected_count: int, *, explicit_select: bool) -> str:
    if output_format == "auto":
        return "lines" if selected_count == 1 else "jsonl"
    if output_format == "ids":
        return "lines (legacy ids shortcut)"
    if output_format == "urls":
        return "lines (legacy urls shortcut)"
    return output_format


def explain_user_query(query_text: str, *, source_type: str, tab: str, date_format: str, offline: bool = False) -> str:
    """Explain query semantics, field capabilities, and safe acquisition optimisations."""
    query = parse_query(query_text)
    if query.from_source is None:
        raise ValueError("--explain requires a complete query containing FROM <source>")
    source = resolve_source(query.from_source, source_type=source_type, tab=tab)
    dates = DateContext(date_order=date_format)
    schema = QuerySchema(())

    lines = [
        "Query explanation",
        "",
        "Source",
        f"  Type: {source.kind}",
        f"  Input: {query.from_source}",
        f"  Resolved URL: {source.canonical_url}",
    ]
    if source.kind == "channel":
        lines.append(f"  Tab: {tab}")

    # Resolve using the known schema. Dynamic fields cannot be validated without metadata,
    # so explain their parsed form while making the deferred validation explicit.
    try:
        resolved = resolve_query(query, schema, dates)
        dynamic_deferred = False
    except QuerySyntaxError as exc:
        message = exc.message
        if message.startswith("Unknown field "):
            resolved = None
            dynamic_deferred = True
        else:
            raise

    optimisation = optimise_query(resolved) if resolved is not None else None

    lines.extend(["", "Projection"])
    if resolved is not None:
        for term in resolved.select:
            original = next(
                (
                    item
                    for item in (query.select or (SelectTerm("id"),))
                    if (item.alias or item.field) == term.output_name
                ),
                None,
            )
            detail = f"  {term.output_name}: {term.field} ({term.kind or 'unknown'})"
            if original is not None and original.field.casefold() != term.field.casefold():
                detail += f" [resolved from {original.field}]"
            lines.append(detail)
    else:
        for term in query.select or (SelectTerm("id"),):
            lines.append(f"  {term.output_name}: {term.field}")

    lines.extend(["", "Filter"])
    if query.predicate is None:
        lines.append("  None. All acquired entries qualify.")
    elif resolved is not None:
        lines.append(f"  {explain_expression(resolved.predicate)}")
    else:
        lines.append(f"  {format_query(Query(predicate=query.predicate))}")

    lines.extend(["", "Predicate optimiser"])
    if optimisation is None:
        lines.append("  Deferred until dynamic metadata fields can be resolved.")
    elif optimisation.changed:
        lines.append(f"  Applied {len(optimisation.decisions)} semantics-preserving rewrite(s):")
        for decision in optimisation.decisions:
            lines.append(f"  [{decision.rule}] {decision.before} -> {decision.after}")
        if optimisation.query.predicate is not None:
            lines.append(f"  Optimised filter: {explain_expression(optimisation.query.predicate)}")
        else:
            lines.append("  Rewrites apply to predicates embedded in scalar expressions.")
    else:
        lines.append("  No semantics-preserving query rewrite was applicable.")

    lines.extend(["", "Ordering"])
    if resolved is not None and resolved.order_by:
        for term in resolved.order_by:
            lines.append(f"  {term.field} {'descending' if term.descending else 'ascending'}; NULL values last")
    elif query.order_by:
        for term in query.order_by:
            lines.append(f"  {term.field} {'descending' if term.descending else 'ascending'}; NULL values last")
    else:
        lines.append("  Source order is preserved.")

    lines.extend(
        [
            "",
            "Row shaping",
            f"  DISTINCT: {'yes' if query.distinct else 'no'}",
            f"  OFFSET: {query.offset}",
            f"  LIMIT: {query.limit if query.limit is not None else 'None'}",
        ]
    )

    required = required_query_fields(query)
    lines.extend(["", "Required fields"])
    for capability in capabilities_for_fields(required):
        lines.append(
            f"  {capability.field}: YouTube.js={capability.youtubejs}; "
            f"yt-dlp-flat={capability.ytdlp_flat}; yt-dlp-detailed={capability.ytdlp_detailed}"
        )

    plan = plan_acquisition(query, source_kind=source.kind, tab=tab, dates=dates)
    if offline:
        plan = AcquisitionPlan("offline-cache", "offline mode uses cached detailed metadata only")
        cost_class, cost_reason = "local", "no network acquisition is permitted; only cached records are evaluated"
    else:
        cost_class, cost_reason = assess_cost(query, plan)
    lines.extend(
        [
            "",
            "Acquisition plan",
            f"  Strategy: {plan.mode}",
            f"  Reason: {plan.reason}",
        ]
    )
    if plan.targeted:
        lines.append(f"  Safe lower upload-date boundary: {plan.lower_date_bound.isoformat()}")
        lines.append(f"  Conservative enumeration stop threshold: {plan.stop_before.isoformat()}")
        lines.append(f"  Boundary confirmations required: {plan.confirmation_entries}")

    lines.extend(["", "Optimisation paths"])
    if offline:
        lines.extend(
            [
                "  [active] Cache-only execution",
                "           Source enumeration and detailed metadata refresh are disabled.",
                "  [inactive] Network acquisition optimisations",
                "             Bounded enumeration and backend selection do not run in offline mode.",
            ]
        )
    elif plan.targeted:
        lines.extend(
            [
                "  [active] Bounded channel enumeration",
                "           The newest-first videos feed can stop after the conservative date boundary is confirmed.",
                "  [available] YouTube.js lightweight enumeration",
                "              Used automatically when installed and --backend permits it; yt-dlp flat enumeration is the fallback.",
                "  [active] Conservative lightweight predicate rejection",
                "           Exact ID/title predicates and provable upload-date interval failures may reject candidates before detailed extraction.",
                "  [active] Upper date-bound pruning when provable",
                "           Candidates provably newer than an upper upload-date condition are also rejected before detailed extraction.",
            ]
        )
    else:
        lines.extend(
            [
                "  [unavailable] Bounded channel enumeration",
                f"                {plan.reason}.",
                "  [conditional] Incremental channel frontier",
                "                Eligible channel /videos full-source queries can stop after conservative overlap with a trusted persisted source ordering.",
                "  [unavailable] Conservative lightweight predicate rejection",
                "                Lightweight rejection is available for entries observed during lightweight enumeration; cached historical entries are evaluated authoritatively.",
            ]
        )
    limit_plan = plan_limit_termination(query)
    if query.limit is None:
        lines.append("  [not applicable] LIMIT-aware acquisition termination: query has no LIMIT.")
    elif offline:
        lines.append(
            "  [inactive] LIMIT-aware acquisition termination: offline execution performs no metadata acquisition."
        )
    elif limit_plan.eligible:
        lines.extend(
            [
                "  [active] LIMIT-aware acquisition termination",
                f"           {limit_plan.reason}.",
                "           Detailed metadata is acquired in source-order batches and may stop once LIMIT authoritative matches exist.",
            ]
        )
    else:
        lines.extend(
            [
                "  [unavailable] LIMIT-aware acquisition termination",
                f"                {limit_plan.reason}.",
            ]
        )

    lines.extend(
        [
            "",
            "Cache plan",
            *(
                [
                    "  Offline execution: query cached detailed metadata only.",
                    "  Missing records: cannot be acquired.",
                    "  Stale required fields: reported and used without refresh.",
                    "  Source completeness: reported explicitly from persisted coverage state when available.",
                ]
                if offline
                else [
                    "  Normal execution: consult the persistent metadata cache after source enumeration.",
                    "  Fresh required fields: reuse cached yt-dlp metadata.",
                    "  Missing or stale required fields: refresh that video's detailed metadata with yt-dlp.",
                    "  Source completeness: not inferred from cache rows.",
                    "  Incremental frontier: for eligible channel /videos full-source queries, a trusted persisted source ordering may stop enumeration after conservative known-ID overlap.",
                ]
            ),
            "",
            "Detailed metadata",
            f"  Required: {'cached only' if offline else 'yes'}",
            f"  Reason: {'offline mode never refreshes metadata' if offline else 'final WHERE evaluation and selected metadata remain authoritative yt-dlp operations'}.",
            "",
            "Estimated cost",
            f"  {cost_class}",
            f"  {cost_reason}",
        ]
    )

    selected_count = len(query.select) if query.select else 1
    lines.extend(
        [
            "",
            "Output",
            f"  Selected scalar fields: {selected_count}",
            f"  Default serialisation: {'lines' if selected_count == 1 else 'jsonl'}",
        ]
    )
    lines.extend(
        ["", "Temporal context", f"  TODAY() = {dates.today.isoformat()}", f"  NOW() = {dates.local_now.isoformat()}"]
    )
    if dynamic_deferred:
        lines.extend(
            [
                "",
                "Deferred validation",
                "  One or more fields are dynamic yt-dlp metadata fields and can only be type-checked after metadata acquisition.",
            ]
        )
    return "\n".join(lines)


def explain_user_query_json(
    query_text: str, *, source_type: str, tab: str, date_format: str, offline: bool = False
) -> dict[str, object]:
    """Return a machine-readable offline query plan for D16."""
    query = parse_query(query_text)
    if query.from_source is None:
        raise ValueError("--explain requires a complete query containing FROM <source>")
    source = resolve_source(query.from_source, source_type=source_type, tab=tab)
    dates = DateContext(date_order=date_format)
    required = sorted(required_query_fields(query))
    plan = plan_acquisition(query, source_kind=source.kind, tab=tab, dates=dates)
    if offline:
        plan = AcquisitionPlan("offline-cache", "offline mode uses cached detailed metadata only")
        cost_class, cost_reason = "local", "no network acquisition is permitted; only cached records are evaluated"
    else:
        cost_class, cost_reason = assess_cost(query, plan)

    try:
        resolved_for_optimiser = resolve_query(query, QuerySchema(()), dates)
        optimiser_result = optimise_query(resolved_for_optimiser)
        optimiser_payload: dict[str, object] = {
            "status": "active",
            "changed": optimiser_result.changed,
            "rewrites": [
                {"rule": item.rule, "before": item.before, "after": item.after} for item in optimiser_result.decisions
            ],
            "optimised_query": format_query(optimiser_result.query),
        }
    except QuerySyntaxError as exc:
        if not exc.message.startswith("Unknown field "):
            raise
        optimiser_payload = {
            "status": "deferred",
            "changed": None,
            "rewrites": [],
            "reason": "dynamic metadata fields require post-acquisition type resolution",
        }

    return {
        "kind": "yt-discover-explain",
        "version": PROGRAM_VERSION,
        "query": format_query(query),
        "row_shaping": {"distinct": query.distinct, "offset": query.offset, "limit": query.limit},
        "predicate_optimiser": optimiser_payload,
        "source": {
            "type": source.kind,
            "input": query.from_source,
            "url": source.canonical_url,
            "tab": tab if source.kind == "channel" else None,
        },
        "required_fields": [
            {
                "field": capability.field,
                "youtubejs": capability.youtubejs,
                "ytdlp_flat": capability.ytdlp_flat,
                "ytdlp_detailed": capability.ytdlp_detailed,
            }
            for capability in capabilities_for_fields(required)
        ],
        "acquisition": {
            "strategy": plan.mode,
            "reason": plan.reason,
            "lower_upload_date": plan.lower_date_bound.isoformat() if plan.lower_date_bound else None,
            "stop_before": plan.stop_before.isoformat() if plan.stop_before else None,
            "boundary_confirmations": plan.confirmation_entries if plan.targeted else None,
        },
        "cache": {
            "mode": "offline-cache-only" if offline else "cache-first-after-source-enumeration",
            "offline_supported": True,
            "source_completeness_inferred_from_rows": False,
        },
        "limit_aware_termination": {
            "applicable": query.limit is not None,
            "implemented": True,
            "eligible": (False if offline else plan_limit_termination(query).eligible),
            "reason": (
                "offline execution performs no metadata acquisition"
                if offline
                else plan_limit_termination(query).reason
            ),
            "scope": "source-order detailed metadata acquisition",
        },
        "cost": {"class": cost_class, "reason": cost_reason},
        "temporal_context": {
            "today": dates.today.isoformat(),
            "now": dates.local_now.isoformat(),
        },
    }


def _format_coverage_warning(coverage: SourceCoverage | None, cached_count: int) -> str:
    """Describe offline source coverage without overstating completeness."""
    if coverage is None:
        return f"source completeness is unknown; querying {cached_count} cached detailed record(s) only"
    if coverage.complete:
        return (
            f"last recorded source coverage was complete at {coverage.observed_at.isoformat()} "
            f"({coverage.cached_entries}/{coverage.observed_entries} detailed records cached)"
        )
    return (
        f"source coverage is incomplete: {coverage.reason}; querying {cached_count} cached detailed record(s) only "
        f"(last observation {coverage.observed_at.isoformat()})"
    )


def _explain_analyze_payload(
    *,
    query: Query,
    source: SourceSpec,
    plan: AcquisitionPlan,
    requested_backend: str,
    selected_backend: str,
    fallback_reason: str,
    enumeration: EnumerationStats | None,
    acquisition: AcquisitionStats,
    cache: CacheStats,
    cache_enabled: bool,
    offline: bool,
    coverage: SourceCoverage | None,
    lightweight_rejected: int,
    detailed_candidates: int | None,
    query_input: int,
    matched_before_limit: int,
    emitted: int,
    acquisition_seconds: float,
    query_seconds: float,
    total_seconds: float,
    frontier_attempted: bool = False,
    frontier_confirmed: bool = False,
    frontier_new_entries: int = 0,
    limit_termination_eligible: bool = False,
    limit_terminated: bool = False,
    limit_batches: int = 0,
    limit_candidates_examined: int = 0,
) -> dict[str, object]:
    """Build machine-readable actual execution telemetry for B1/D16."""
    return {
        "kind": "yt-discover-explain-analyze",
        "version": PROGRAM_VERSION,
        "query": format_query(query),
        "row_shaping": {"distinct": query.distinct, "offset": query.offset, "limit": query.limit},
        "source": {"type": source.kind, "url": source.canonical_url},
        "plan": {"strategy": plan.mode, "reason": plan.reason},
        "actual": {
            "offline": offline,
            "requested_backend": requested_backend,
            "selected_backend": selected_backend,
            "fallback_reason": fallback_reason or None,
            "enumerated": enumeration.enumerated if enumeration is not None else 0,
            "enumeration_stopped_early": enumeration.stopped_early if enumeration is not None else False,
            "frontier": {
                "attempted": frontier_attempted,
                "confirmed": frontier_confirmed,
                "new_source_entries": frontier_new_entries,
                "full_enumeration_avoided": frontier_confirmed,
            },
            "limit_termination": {
                "eligible": limit_termination_eligible,
                "terminated_early": limit_terminated,
                "batches": limit_batches,
                "candidates_examined": limit_candidates_examined,
            },
            "lightweight_rejected": lightweight_rejected,
            "detailed_candidates": detailed_candidates,
            "metadata_available": acquisition.available,
            "metadata_skipped": acquisition.skipped,
            "cache": {
                "enabled": cache_enabled,
                "examined": cache.examined,
                "fresh_hits": cache.hits,
                "stale": cache.stale,
                "misses": cache.misses,
                "refreshed": cache.refreshed,
                "written": cache.written,
            },
            "coverage": None
            if coverage is None
            else {
                "complete": coverage.complete,
                "observed_at": coverage.observed_at.isoformat(),
                "observed_entries": coverage.observed_entries,
                "cached_entries": coverage.cached_entries,
                "reason": coverage.reason,
            },
            "query_input": query_input,
            "matched_before_limit": matched_before_limit,
            "emitted": emitted,
        },
        "timing_seconds": {
            "acquisition_or_cache": acquisition_seconds,
            "query": query_seconds,
            "total": total_seconds,
        },
    }


def _format_explain_analyze_text(payload: dict[str, object]) -> str:
    actual = payload["actual"]
    timing = payload["timing_seconds"]
    assert isinstance(actual, dict)
    assert isinstance(timing, dict)
    cache = actual["cache"]
    assert isinstance(cache, dict)
    lines = [
        "EXPLAIN ANALYZE",
        "",
        "Plan",
        f"  Strategy: {payload['plan']['strategy']}",
        f"  Reason: {payload['plan']['reason']}",
        "",
        "Actual execution",
        f"  Offline: {'yes' if actual['offline'] else 'no'}",
        f"  Backend: {actual['selected_backend']} (requested: {actual['requested_backend']})",
        f"  Entries enumerated: {actual['enumerated']}",
        f"  Enumeration stopped early: {'yes' if actual['enumeration_stopped_early'] else 'no'}",
        f"  Lightweight candidates rejected: {actual['lightweight_rejected']}",
        f"  Detailed candidates: {actual['detailed_candidates'] if actual['detailed_candidates'] is not None else 'n/a'}",
        f"  Metadata available from refresh: {actual['metadata_available']}",
        f"  Inaccessible/skipped during refresh: {actual['metadata_skipped']}",
        "",
        "Incremental frontier",
        f"  Attempted: {'yes' if actual['frontier']['attempted'] else 'no'}",
        f"  Overlap confirmed: {'yes' if actual['frontier']['confirmed'] else 'no'}",
        f"  New source entries: {actual['frontier']['new_source_entries']}",
        f"  Full enumeration avoided: {'yes' if actual['frontier']['full_enumeration_avoided'] else 'no'}",
        "",
        "LIMIT-aware acquisition",
        f"  Eligible: {'yes' if actual['limit_termination']['eligible'] else 'no'}",
        f"  Detailed acquisition stopped early: {'yes' if actual['limit_termination']['terminated_early'] else 'no'}",
        f"  Batches: {actual['limit_termination']['batches']}",
        f"  Candidates examined: {actual['limit_termination']['candidates_examined']}",
        "",
        "Cache outcome",
        f"  Records examined: {cache['examined']}",
        f"  Fresh hits: {cache['fresh_hits']}",
        f"  Stale entries: {cache['stale']}",
        f"  Misses: {cache['misses']}",
        f"  Refreshed: {cache['refreshed']}",
        f"  Written: {cache['written']}",
        "",
        "Result statistics",
        f"  DISTINCT: {'yes' if payload['row_shaping']['distinct'] else 'no'}",
        f"  OFFSET: {payload['row_shaping']['offset']}",
        f"  LIMIT: {payload['row_shaping']['limit'] if payload['row_shaping']['limit'] is not None else 'None'}",
        f"  Records evaluated by WHERE: {actual['query_input']}",
        f"  Matched before LIMIT: {actual['matched_before_limit']}"
        + (
            " (at least; acquisition stopped after LIMIT was satisfied)"
            if actual["limit_termination"]["terminated_early"]
            else ""
        ),
        f"  Rows that would be emitted: {actual['emitted']}",
        "",
        "Timing",
        f"  Acquisition/cache phase: {timing['acquisition_or_cache']:.3f}s",
        f"  Query evaluation: {timing['query']:.3f}s",
        f"  Total: {timing['total']:.3f}s",
    ]
    if actual.get("fallback_reason"):
        lines.insert(8, f"  Fallback: {actual['fallback_reason']}")
    coverage = actual.get("coverage")
    if isinstance(coverage, dict):
        lines.extend(
            [
                "",
                "Source coverage",
                f"  Complete at last observation: {'yes' if coverage['complete'] else 'no'}",
                f"  Observed at: {coverage['observed_at']}",
                f"  Cached/observed records: {coverage['cached_entries']}/{coverage['observed_entries']}",
                f"  Reason: {coverage['reason']}",
            ]
        )
    else:
        lines.extend(["", "Source coverage", "  Unknown"])
    return "\n".join(lines)


def _cached_or_refresh_metadata(
    *,
    cache: MetadataCache | None,
    source_url: str,
    video_ids: list[str],
    required_fields: set[str],
    verbose: int,
) -> tuple[list[dict], AcquisitionStats, CacheStats]:
    """Reuse fresh source-scoped cache rows and refresh only stale or missing videos."""
    cached_by_id: dict[str, dict] = {}
    refresh_ids: list[str] = []
    hits = stale = misses = 0
    cache_fields = {field for field in required_fields if field.casefold() != "source_index"}

    for video_id in video_ids:
        if cache is None:
            refresh_ids.append(video_id)
            continue
        item = cache.get(source_url, video_id)
        if item is None:
            misses += 1
            refresh_ids.append(video_id)
        elif cache.is_fresh(item, cache_fields):
            hits += 1
            cached_by_id[video_id] = item.record
        else:
            stale += 1
            refresh_ids.append(video_id)

    fetched_records: list[dict] = []
    acquisition_stats = AcquisitionStats()
    if refresh_ids:
        command = build_video_metadata_command(refresh_ids)
        _verbose(verbose, f"Refreshing detailed metadata for {len(refresh_ids)} cache-miss/stale videos...")
        if verbose >= 2:
            _verbose(verbose, f"Candidate yt-dlp command: {shell_join(command)}")
        fetched_records, acquisition_stats = load_metadata(
            command,
            progress=_acquisition_progress(verbose) if verbose else None,
        )

    fetched_by_id = {
        record.get("id"): record for record in fetched_records if isinstance(record.get("id"), str) and record.get("id")
    }
    written = cache.put_many(source_url, fetched_records) if cache is not None else 0
    records: list[dict] = []
    for video_id in video_ids:
        record = fetched_by_id.get(video_id) or cached_by_id.get(video_id)
        if record is not None:
            records.append(record)
    return (
        records,
        acquisition_stats,
        CacheStats(
            examined=len(video_ids) if cache is not None else 0,
            hits=hits,
            stale=stale,
            misses=misses,
            refreshed=len(fetched_records),
            written=written,
        ),
    )


def _merge_acquisition_stats(total: AcquisitionStats, part: AcquisitionStats) -> None:
    """Merge one detailed-extraction batch into aggregate telemetry."""
    total.available += part.available
    total.error_lines += part.error_lines
    total.identified_error_lines += part.identified_error_lines
    for video_id, category in part.skipped_by_id.items():
        total.record_skip(video_id, category)


def _merge_cache_stats(total: CacheStats, part: CacheStats) -> CacheStats:
    """Return aggregate cache telemetry for repeated LIMIT-aware batches."""
    return CacheStats(
        examined=total.examined + part.examined,
        hits=total.hits + part.hits,
        stale=total.stale + part.stale,
        misses=total.misses + part.misses,
        refreshed=total.refreshed + part.refreshed,
        written=total.written + part.written,
    )


def _limit_aware_cached_acquire(
    *,
    cache: MetadataCache | None,
    source_url: str,
    video_ids: list[str],
    query: Query,
    dates: DateContext,
    required_fields: set[str],
    verbose: int,
    batch_size: int = 25,
) -> tuple[list[dict], AcquisitionStats, CacheStats, bool, int, int]:
    """Acquire source-order candidates in batches until LIMIT authoritative matches exist.

    The planner calls this only when source order is the final result order and all query
    fields have statically known types. Later source rows therefore cannot displace an
    already observed matching row from the first LIMIT results.
    """
    assert query.limit is not None
    raw_records: list[dict] = []
    acquisition = AcquisitionStats()
    cache_stats = CacheStats()
    matched = 0
    batches = 0
    examined_candidates = 0

    for start in range(0, len(video_ids), batch_size):
        batch_ids = video_ids[start : start + batch_size]
        if not batch_ids:
            break
        batches += 1
        batch_raw, batch_acquisition, batch_cache = _cached_or_refresh_metadata(
            cache=cache,
            source_url=source_url,
            video_ids=batch_ids,
            required_fields=required_fields,
            verbose=verbose,
        )
        _merge_acquisition_stats(acquisition, batch_acquisition)
        cache_stats = _merge_cache_stats(cache_stats, batch_cache)
        raw_records.extend(batch_raw)
        examined_candidates += len(batch_ids)

        batch_records = [normalise_record(record) for record in batch_raw]
        try:
            resolved = resolve_query(query, QuerySchema(batch_records), dates)
        except QuerySyntaxError:
            # Eligibility excludes dynamic fields, so a semantic failure here should be
            # reproduced later by the normal authoritative resolution path.
            continue
        predicate_only = Query(predicate=resolved.predicate)
        matched += len(apply_query(batch_records, predicate_only))
        if matched >= query.limit:
            return raw_records, acquisition, cache_stats, True, batches, examined_candidates

    return raw_records, acquisition, cache_stats, False, batches, examined_candidates


def _write_provenance(destination: str, payload: dict[str, object]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if destination == "-":
        sys.stdout.write(text)
        return
    path = Path(destination).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.examples:
        print(EXAMPLES)
        return 0

    if args.check_query is not None:
        try:
            checked = parse_query(bind_query_parameters(args.check_query, _parse_parameters(args.param)))
        except QuerySyntaxError as exc:
            parser.error(exc.format())
        except ValueError as exc:
            parser.error(str(exc))
        print(format_query(checked))
        print("Syntax is valid. Dynamic field and type validation occurs after metadata acquisition.")
        return 0

    if args.explain is not None:
        try:
            if args.explain_format == "json":
                print(
                    json.dumps(
                        explain_user_query_json(
                            bind_query_parameters(args.explain, _parse_parameters(args.param)),
                            source_type=args.source_type,
                            tab=args.tab,
                            date_format=args.date_format,
                            offline=args.offline,
                        ),
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                )
            else:
                print(
                    explain_user_query(
                        bind_query_parameters(args.explain, _parse_parameters(args.param)),
                        source_type=args.source_type,
                        tab=args.tab,
                        date_format=args.date_format,
                        offline=args.offline,
                    )
                )
        except QuerySyntaxError as exc:
            parser.error(exc.format())
        except ValueError as exc:
            parser.error(str(exc))
        return 0

    explain_analyze = args.explain_analyze is not None
    if explain_analyze:
        if args.source is not None or args.query or args.where:
            parser.error("--explain-analyze cannot be combined with SOURCE_OR_QUERY, --query, or --where")
        args.source = args.explain_analyze

    if args.offline and args.no_cache:
        parser.error("--offline requires the metadata cache and cannot be combined with --no-cache")
    if args.offline and (
        args.date or args.after or args.before or args.items or any(item.strip() for item in args.match_filter)
    ):
        parser.error(
            "--offline cannot use yt-dlp acquisition prefilters such as --date/--after/--before/--items/--match-filter"
        )
    if args.append is not None and explain_analyze:
        parser.error("--append cannot be combined with --explain-analyze")
    if args.append is not None and args.format not in {"auto", "lines", "ids"}:
        parser.error("--append supports ID line output only; omit --format or use --format lines/ids")
    if args.provenance == "-" and not explain_analyze and args.output is None and args.append is None:
        parser.error(
            "--provenance - would mix JSON provenance with query rows on stdout; use a file or redirect query output with -o/--append"
        )

    effective_argv = sys.argv[1:] if argv is None else argv
    if not effective_argv:
        print("El Psy Kongroo.", file=sys.stderr)
        parser.error(
            "SOURCE_OR_QUERY is required unless --examples, --check-query, --explain, --explain-analyze, --check-tools, or --version is used"
        )

    total_started = perf_counter()
    project_root = Path(__file__).resolve().parent
    if args.offline and not args.check_tools:
        tools = ToolRegistry(
            ytdlp=ToolStatus("yt-dlp", True, False, detail="not checked in offline mode"),
            node=ToolStatus("Node.js", False, False, detail="not checked in offline mode"),
            youtubejs=ToolStatus("YouTube.js", False, False, detail="not checked in offline mode"),
        )
    else:
        tools = check_tools(project_root)

    if args.check_tools:
        print(format_tool_check(tools))
        return 0 if tools.ytdlp.available else 1

    if args.source is None and not args.query:
        parser.error(
            "SOURCE_OR_QUERY is required unless --examples, --check-query, --explain, --explain-analyze, --check-tools, or --version is used"
        )

    if args.archive != DEFAULT_ARCHIVE_FILE and not args.exclude_archive:
        parser.error("--archive is only meaningful together with --exclude-archive")
    if args.date and (args.after or args.before):
        parser.error("--date cannot be combined with --after or --before")

    inline_query = args.source if looks_like_complete_query(args.source) else None
    positional_source = None if inline_query is not None else args.source

    try:
        query = parse_user_query(args, inline_query)
        if query.from_source is not None and positional_source is not None:
            raise ValueError("source is specified both positionally and by FROM")
        source_value = query.from_source or positional_source
        if source_value is None:
            raise ValueError("query has no source; add FROM <source> or provide SOURCE_OR_QUERY positionally")
        source: SourceSpec = resolve_source(source_value, source_type=args.source_type, tab=args.tab)
    except QuerySyntaxError as exc:
        parser.error(exc.format())
    except ValueError as exc:
        parser.error(str(exc))

    if not tools.ytdlp.available and not args.dry_run and not args.offline:
        parser.error(f"required tool yt-dlp is unavailable: {tools.ytdlp.detail}. Run --check-tools for details")
    if args.backend == "youtubejs" and not tools.youtubejs_available and not args.offline:
        parser.error(
            f"requested backend 'youtubejs' is unavailable: {tools.youtubejs.detail}. Run --check-tools for details"
        )

    if args.verbose and not args.offline:
        _verbose(True, "Checked acquisition tools before contacting YouTube.")
        _verbose(True, f"yt-dlp: {tools.ytdlp.version if tools.ytdlp.available else 'unavailable'}.")
        _verbose(True, f"Node.js: {tools.node.version if tools.node.available else 'unavailable'}.")
        _verbose(True, f"YouTube.js: {tools.youtubejs.version if tools.youtubejs_available else 'unavailable'}.")

    _verbose(args.verbose, f"Resolved source as {source.kind}: {source.canonical_url}")

    date_context = DateContext(date_order=args.date_format)
    plan: AcquisitionPlan = plan_acquisition(query, source_kind=source.kind, tab=args.tab, dates=date_context)
    explicit_prefilters = bool(
        args.items or args.date or args.after or args.before or any(item.strip() for item in args.match_filter)
    )
    if args.offline:
        plan = AcquisitionPlan("offline-cache", "offline mode uses cached detailed metadata only")
    elif args.acquisition == "full":
        plan = AcquisitionPlan("full", "exhaustive acquisition was requested with --acquisition full")
    elif explicit_prefilters and plan.targeted:
        plan = AcquisitionPlan(
            "full",
            "explicit yt-dlp acquisition prefilters are present; automatic bounded planning is disabled",
        )

    limit_plan = plan_limit_termination(query)
    if args.exclude_archive and limit_plan.eligible:
        limit_plan = type(limit_plan)(
            False,
            "archive exclusion is applied after acquisition, so early LIMIT termination cannot prove the first N surviving rows",
            limit_plan.limit,
        )
    if args.offline and limit_plan.eligible:
        limit_plan = type(limit_plan)(
            False,
            "offline execution already has a finite cached record set and performs no metadata acquisition",
            limit_plan.limit,
        )

    if args.offline:
        cost_class, cost_reason = "local", "no network acquisition is permitted; only cached records are evaluated"
    else:
        cost_class, cost_reason = assess_cost(query, plan)
    if not args.offline and not args.dry_run and args.acquisition != "full" and cost_class == "very-high":
        print(
            "yt-discover: warning: this query may require complete source enumeration and substantial metadata acquisition; "
            "no safe source boundary is available. Add a lower upload_date bound when that matches the intended query.",
            file=sys.stderr,
            flush=True,
        )
    if args.verbose:
        _verbose(True, f"Acquisition cost estimate: {cost_class} ({cost_reason}).")

    requested_backend = args.backend
    selected_backend = "cache" if args.offline else "ytdlp"
    fallback_reason = ""
    if plan.targeted:
        if args.backend == "youtubejs":
            selected_backend = "youtubejs"
        elif args.backend == "auto" and tools.youtubejs_available:
            selected_backend = "youtubejs"
        else:
            selected_backend = "ytdlp"
            if args.backend == "auto" and not tools.youtubejs_available:
                fallback_reason = tools.youtubejs.detail or "YouTube.js is unavailable"
                print(
                    f"yt-discover: optional YouTube.js backend unavailable; using yt-dlp bounded enumeration ({fallback_reason}).",
                    file=sys.stderr,
                )

    command = build_metadata_command(
        source.canonical_url,
        playlist_items=args.items,
        date=args.date,
        date_after=args.after,
        date_before=args.before,
        match_filters=tuple(item for item in args.match_filter if item.strip()),
    )

    if args.verbose:
        _verbose(True, f"Acquisition plan: {plan.mode} ({plan.reason}).")
        if args.offline:
            _verbose(True, "Execution source: persistent metadata cache only; network acquisition is disabled.")
        elif plan.targeted:
            _verbose(True, f"Enumeration backend: {selected_backend} (requested: {requested_backend}).")
            if fallback_reason:
                _verbose(True, f"Fallback reason: {fallback_reason}.")
            _verbose(True, f"Query lower upload-date bound: {plan.lower_date_bound.isoformat()}.")
            _verbose(
                True,
                f"Conservative flat-scan stop threshold: {plan.stop_before.isoformat()} after {plan.confirmation_entries} consecutive older entries.",
            )
        else:
            _verbose(True, f"yt-dlp command: {shell_join(command)}")
        _verbose(True, f"Parsed query: {format_query(query)}")

    if args.dry_run:
        print(f"source: {source.kind} -> {source.canonical_url}")
        print(f"acquisition: {plan.mode} -> {plan.reason}")
        if args.offline:
            print(f"cache: {args.cache.expanduser()}")
            print("network: disabled")
        elif plan.targeted:
            print(f"backend: requested={requested_backend} selected={selected_backend}")
            if fallback_reason:
                print(f"fallback: {fallback_reason}")
            flat_command = build_lazy_flat_command(source.canonical_url)
            if selected_backend == "youtubejs":
                print("enumeration: YouTube.js continuation-driven channel videos feed")
            else:
                print(f"enumeration: {shell_join(flat_command)}")
            print(
                f"boundary: lower={plan.lower_date_bound.isoformat()} stop-before={plan.stop_before.isoformat()} confirmations={plan.confirmation_entries}"
            )
            print("detail extraction: candidate video IDs from the bounded enumeration pass")
        elif not args.offline:
            print(f"yt-dlp: {shell_join(command)}")
        print(f"query:  {format_query(query)}")
        print("note: dynamic fields and typed literals are resolved after metadata acquisition")
        return 0

    if args.exclude_archive and not args.archive.expanduser().is_file():
        parser.error(f"archive file not found: {args.archive.expanduser()}")

    metadata_cache: MetadataCache | None = None
    if not args.no_cache:
        metadata_cache = MetadataCache(args.cache)
        try:
            metadata_cache.open()
        except (OSError, RuntimeError) as exc:
            print(f"Error: could not open metadata cache {args.cache.expanduser()}: {exc}", file=sys.stderr)
            return 1
        _verbose(args.verbose, f"Metadata cache: {args.cache.expanduser()}.")
    else:
        _verbose(args.verbose, "Metadata cache disabled for this run.")

    enumeration_stats: EnumerationStats | None = None
    cache_stats = CacheStats()
    lightweight_rejected = 0
    detailed_candidates: int | None = None
    offline_coverage: SourceCoverage | None = None
    observed_ids_for_cache: list[str] = []
    frontier_attempted = False
    frontier_confirmed = False
    frontier_new_entries = 0
    limit_terminated = False
    limit_batches = 0
    limit_candidates_examined = 0
    acquisition_started = perf_counter()
    if args.offline:
        assert metadata_cache is not None
        cached_items = metadata_cache.source_records(source.canonical_url)
        if not cached_items:
            print(
                f"Error: offline cache has no detailed metadata for {source.canonical_url}.",
                file=sys.stderr,
            )
            metadata_cache.close()
            return 1
        required_fields = {field for field in required_query_fields(query) if field.casefold() != "source_index"}
        fresh = sum(1 for item in cached_items if metadata_cache.is_fresh(item, required_fields))
        stale = len(cached_items) - fresh
        raw_records = [item.record for item in cached_items]
        cache_stats = CacheStats(examined=len(cached_items), hits=fresh, stale=stale)
        acquisition_stats = AcquisitionStats()
        detailed_candidates = len(cached_items)
        offline_coverage = metadata_cache.source_coverage(source.canonical_url)
        coverage_message = _format_coverage_warning(offline_coverage, len(cached_items))
        if offline_coverage is None or not offline_coverage.complete:
            print(f"yt-discover: offline warning: {coverage_message}.", file=sys.stderr)
        else:
            _verbose(args.verbose, f"Offline coverage: {coverage_message}.")
        if stale:
            print(
                f"yt-discover: offline warning: {stale} cached record(s) are stale for one or more fields required by this query; stale values will be used without refresh.",
                file=sys.stderr,
            )
        _verbose(
            args.verbose,
            f"Offline query loaded {len(cached_items)} cached detailed records and made no YouTube requests.",
        )
    elif plan.targeted:
        flat_command = build_lazy_flat_command(source.canonical_url)
        _verbose(args.verbose, f"Enumerating lightweight channel metadata lazily with {selected_backend}...")
        try:
            if selected_backend == "youtubejs":
                flat_entries, enumeration_stats = enumerate_youtubejs_until_date_boundary(
                    project_root,
                    source.canonical_url,
                    stop_before=plan.stop_before,
                    confirmation_entries=plan.confirmation_entries,
                    dates=date_context,
                    progress=_enumeration_progress(
                        args.verbose, context="Bounded YouTube.js enumeration", warn_threshold=args.warn_source_size
                    ),
                )
            else:
                if args.verbose >= 2:
                    _verbose(args.verbose, f"Flat yt-dlp command: {shell_join(flat_command)}")
                flat_entries, enumeration_stats = enumerate_until_date_boundary(
                    flat_command,
                    stop_before=plan.stop_before,
                    confirmation_entries=plan.confirmation_entries,
                    progress=_enumeration_progress(
                        args.verbose, context="Bounded yt-dlp enumeration", warn_threshold=args.warn_source_size
                    ),
                )
        except YouTubeJsError as exc:
            if args.backend == "youtubejs":
                print(f"Error: YouTube.js enumeration failed: {exc}.", file=sys.stderr)
                return 1
            fallback_reason = f"YouTube.js enumeration failed: {exc}"
            selected_backend = "ytdlp"
            print(
                f"yt-discover: YouTube.js enumeration failed; falling back to yt-dlp bounded enumeration ({exc}).",
                file=sys.stderr,
            )
            try:
                flat_entries, enumeration_stats = enumerate_until_date_boundary(
                    flat_command,
                    stop_before=plan.stop_before,
                    confirmation_entries=plan.confirmation_entries,
                    progress=_enumeration_progress(
                        args.verbose, context="Bounded yt-dlp enumeration", warn_threshold=args.warn_source_size
                    ),
                )
            except YtDlpError as fallback_exc:
                print(f"Error: {fallback_exc}.", file=sys.stderr)
                return 1
        except YtDlpError as exc:
            print(f"Error: {exc}.", file=sys.stderr)
            return 1
        candidate_ids = []
        seen_ids = set()
        lightweight_rejected = 0
        for entry in flat_entries:
            video_id = entry.get("id")
            if not (isinstance(video_id, str) and video_id and video_id not in seen_ids):
                continue
            seen_ids.add(video_id)
            observed_ids_for_cache.append(video_id)
            # Lightweight evaluation is deliberately one-sided: a candidate is discarded
            # only when exact values or conservative uncertainty intervals prove that the
            # complete WHERE predicate is false. Unknown or approximate cases are retained.
            if safely_reject_lightweight(query.predicate, entry, date_context):
                lightweight_rejected += 1
                continue
            candidate_ids.append(video_id)
        detailed_candidates = len(candidate_ids)
        _verbose(
            args.verbose,
            f"Lightweight enumeration observed {enumeration_stats.enumerated} entries "
            f"({enumeration_stats.dated} dated, {enumeration_stats.undated} undated); "
            f"{len(candidate_ids)} detailed candidates; {lightweight_rejected} safely rejected before full extraction.",
        )
        if enumeration_stats.stopped_early:
            _verbose(args.verbose, "Stopped channel pagination after the conservative date boundary was confirmed.")
        else:
            _verbose(
                args.verbose,
                "Channel enumeration reached its natural end before the conservative date boundary was confirmed.",
            )
        if candidate_ids:
            try:
                if limit_plan.eligible:
                    (
                        raw_records,
                        acquisition_stats,
                        cache_stats,
                        limit_terminated,
                        limit_batches,
                        limit_candidates_examined,
                    ) = _limit_aware_cached_acquire(
                        cache=metadata_cache,
                        source_url=source.canonical_url,
                        video_ids=candidate_ids,
                        query=query,
                        dates=date_context,
                        required_fields=required_query_fields(query),
                        verbose=args.verbose,
                    )
                else:
                    raw_records, acquisition_stats, cache_stats = _cached_or_refresh_metadata(
                        cache=metadata_cache,
                        source_url=source.canonical_url,
                        video_ids=candidate_ids,
                        required_fields=required_query_fields(query),
                        verbose=args.verbose,
                    )
            except YtDlpError as exc:
                print(f"Error: {exc}.", file=sys.stderr)
                return 1
        else:
            raw_records, acquisition_stats = [], AcquisitionStats()
    else:
        cache_first_full = (
            metadata_cache is not None
            and source.kind == "channel"
            and args.tab == "videos"
            and args.items is None
            and not (args.date or args.after or args.before or any(item.strip() for item in args.match_filter))
        )
        if cache_first_full:
            flat_command = build_lazy_flat_command(source.canonical_url)
            if args.verbose >= 2:
                _verbose(args.verbose, f"Flat yt-dlp command: {shell_join(flat_command)}")
            prior_order = metadata_cache.source_entry_ids(source.canonical_url)
            frontier = metadata_cache.source_frontier(source.canonical_url) if args.acquisition != "full" else None
            if frontier is not None and prior_order:
                frontier_attempted = True
                _verbose(
                    args.verbose,
                    f"Using incremental source frontier with {len(prior_order)} known entries; "
                    f"requiring {FRONTIER_OVERLAP_CONFIRMATIONS} consecutive known IDs before stopping.",
                )
                try:
                    flat_entries, enumeration_stats = enumerate_until_known_overlap(
                        flat_command,
                        known_ids=set(prior_order),
                        confirmation_entries=FRONTIER_OVERLAP_CONFIRMATIONS,
                        progress=_enumeration_progress(
                            args.verbose,
                            context="Incremental frontier enumeration",
                            warn_threshold=args.warn_source_size,
                        ),
                    )
                except YtDlpError as exc:
                    print(f"Error: {exc}.", file=sys.stderr)
                    return 1
            else:
                _verbose(
                    args.verbose,
                    "No trusted incremental frontier is available; enumerating the complete channel videos source.",
                )
                try:
                    flat_entries, enumeration_stats = enumerate_all_flat(
                        flat_command,
                        progress=_enumeration_progress(
                            args.verbose,
                            context="Full channel enumeration",
                            warn_threshold=args.warn_source_size,
                        ),
                    )
                except YtDlpError as exc:
                    print(f"Error: {exc}.", file=sys.stderr)
                    return 1

            current_ids: list[str] = []
            entry_by_id: dict[str, dict] = {}
            seen_ids: set[str] = set()
            for entry in flat_entries:
                video_id = entry.get("id")
                if not (isinstance(video_id, str) and video_id and video_id not in seen_ids):
                    continue
                seen_ids.add(video_id)
                current_ids.append(video_id)
                entry_by_id[video_id] = entry

            if frontier_attempted and enumeration_stats.stopped_on_frontier:
                frontier_confirmed = True
                current_set = set(current_ids)
                frontier_new_entries = sum(1 for video_id in current_ids if video_id not in set(prior_order))
                observed_ids_for_cache = current_ids + [
                    video_id for video_id in prior_order if video_id not in current_set
                ]
                _verbose(
                    args.verbose,
                    f"Incremental frontier confirmed after {enumeration_stats.enumerated} observed entries; "
                    f"{frontier_new_entries} new source entr{'y' if frontier_new_entries == 1 else 'ies'} discovered.",
                )
            else:
                observed_ids_for_cache = current_ids
                if frontier_attempted:
                    _verbose(
                        args.verbose,
                        "Stored frontier overlap was not confirmed before source end; rebuilt the source ordering from a complete enumeration.",
                    )

            candidate_ids = []
            for video_id in observed_ids_for_cache:
                entry = entry_by_id.get(video_id)
                if entry is not None and safely_reject_lightweight(query.predicate, entry, date_context):
                    lightweight_rejected += 1
                    continue
                candidate_ids.append(video_id)
            detailed_candidates = len(candidate_ids)
            try:
                if limit_plan.eligible:
                    (
                        raw_records,
                        acquisition_stats,
                        cache_stats,
                        limit_terminated,
                        limit_batches,
                        limit_candidates_examined,
                    ) = _limit_aware_cached_acquire(
                        cache=metadata_cache,
                        source_url=source.canonical_url,
                        video_ids=candidate_ids,
                        query=query,
                        dates=date_context,
                        required_fields=required_query_fields(query),
                        verbose=args.verbose,
                    )
                else:
                    raw_records, acquisition_stats, cache_stats = _cached_or_refresh_metadata(
                        cache=metadata_cache,
                        source_url=source.canonical_url,
                        video_ids=candidate_ids,
                        required_fields=required_query_fields(query),
                        verbose=args.verbose,
                    )
            except YtDlpError as exc:
                print(f"Error: {exc}.", file=sys.stderr)
                return 1
        else:
            if cost_class == "very-high" and args.acquisition != "full":
                print(
                    "yt-discover: warning: no safe acquisition optimisation was identified for this query; detailed metadata may be required for most or all source entries.",
                    file=sys.stderr,
                )
            _verbose(args.verbose, "Acquiring full video metadata with yt-dlp...")
            if args.verbose:
                _verbose(
                    args.verbose,
                    "Queries requiring ORDER BY/LIMIT are evaluated after acquisition; result output may remain quiet until this phase completes.",
                )
            try:
                raw_records, acquisition_stats = load_metadata(
                    command,
                    progress=_acquisition_progress(args.verbose) if args.verbose else None,
                )
            except YtDlpError as exc:
                print(f"Error: {exc}.", file=sys.stderr)
                return 1
            observed_ids_for_cache = [
                record.get("id") for record in raw_records if isinstance(record.get("id"), str) and record.get("id")
            ]
            if metadata_cache is not None:
                cache_stats = CacheStats(written=metadata_cache.put_many(source.canonical_url, raw_records))

    acquisition_elapsed = perf_counter() - acquisition_started

    if args.offline:
        _verbose(
            args.verbose,
            f"Cache-only acquisition complete: {len(raw_records)} cached detailed records available; 0 YouTube requests.",
        )
    else:
        _verbose(
            args.verbose,
            f"Acquisition complete: {acquisition_stats.available} available, "
            f"{acquisition_stats.skipped} inaccessible/skipped, "
            f"{acquisition_stats.attempted} attempted/observed.",
        )
    if limit_plan.eligible and not args.offline:
        if limit_terminated:
            _verbose(
                args.verbose,
                f"LIMIT-aware detailed acquisition stopped after {limit_candidates_examined} candidate(s) in {limit_batches} batch(es); {query.limit} authoritative match(es) were sufficient in source order.",
            )
        elif limit_batches:
            _verbose(
                args.verbose,
                f"LIMIT-aware detailed acquisition examined all {limit_candidates_examined} candidate(s); fewer than {query.limit} authoritative matches were available.",
            )
    if metadata_cache is not None:
        _verbose(
            args.verbose,
            f"Cache outcome: {cache_stats.hits} fresh hits, {cache_stats.stale} stale, "
            f"{cache_stats.misses} misses, {cache_stats.written} records written.",
        )
        source_order_complete = (
            not args.offline
            and plan.mode == "full"
            and not explicit_prefilters
            and (frontier_confirmed or enumeration_stats is None or not enumeration_stats.stopped_early)
        )
        if source_order_complete and observed_ids_for_cache:
            metadata_cache.record_source_entries(source.canonical_url, observed_ids_for_cache)
            metadata_cache.record_source_frontier(
                source.canonical_url,
                source.kind,
                observed_ids_for_cache,
                overlap_confirmations=(FRONTIER_OVERLAP_CONFIRMATIONS if frontier_confirmed else 0),
            )
        if not args.offline and enumeration_stats is not None:
            metadata_cache.record_source_observation(
                source.canonical_url,
                source.kind,
                len(observed_ids_for_cache) if frontier_confirmed else enumeration_stats.enumerated,
            )
            complete_coverage = (
                plan.mode == "full"
                and (frontier_confirmed or not enumeration_stats.stopped_early)
                and args.items is None
                and lightweight_rejected == 0
                and len(raw_records) == len(observed_ids_for_cache)
            )
            coverage_reason = (
                "complete full-source observation with detailed metadata for every observed entry"
                if complete_coverage
                else (
                    "bounded or filtered observation does not establish complete detailed source coverage"
                    if plan.mode != "full" or lightweight_rejected
                    else "one or more observed source entries lack cached detailed metadata"
                )
            )
            metadata_cache.record_source_coverage(
                source.canonical_url,
                source.kind,
                len(observed_ids_for_cache) if frontier_confirmed else enumeration_stats.enumerated,
                complete=complete_coverage,
                reason=coverage_reason,
            )
        elif not args.offline and observed_ids_for_cache:
            complete_coverage = (
                plan.mode == "full"
                and not explicit_prefilters
                and acquisition_stats.skipped == 0
                and acquisition_stats.attempted == len(raw_records)
            )
            metadata_cache.record_source_coverage(
                source.canonical_url,
                source.kind,
                acquisition_stats.attempted,
                complete=complete_coverage,
                reason=(
                    "complete full-source detailed acquisition"
                    if complete_coverage
                    else "detailed acquisition did not establish complete source coverage"
                ),
            )

    observed_source_work = (
        enumeration_stats.enumerated if enumeration_stats is not None else acquisition_stats.attempted
    )
    if enumeration_stats is None and args.warn_source_size and observed_source_work >= args.warn_source_size:
        print(
            f"yt-discover: warning: observed source work reached {observed_source_work} entries "
            f"(configured warning threshold: {args.warn_source_size}).",
            file=sys.stderr,
        )

    query_started = perf_counter()
    records = []
    for source_index, raw in enumerate(raw_records, start=1):
        record = normalise_record(raw)
        record["source_index"] = source_index
        records.append(record)

    schema = QuerySchema(records)
    _verbose(args.verbose, f"Built query schema from {len(records)} normalised records.")
    if args.fields or args.schema:
        print_schema(schema, include_raw=args.schema)
        return 0

    try:
        resolved_query = resolve_query(
            query,
            schema,
            date_context,
        )
    except QuerySyntaxError as exc:
        parser.error(exc.format())

    optimisation = optimise_query(resolved_query)
    resolved_query = optimisation.query
    if optimisation.changed:
        _verbose(args.verbose, f"Optimiser applied {len(optimisation.decisions)} semantics-preserving rewrite(s).")
        for decision in optimisation.decisions:
            _verbose(args.verbose, f"Optimiser [{decision.rule}]: {decision.before} -> {decision.after}")

    archive_excluded = 0
    if args.exclude_archive:
        try:
            archive_ids = read_archive_ids(args.archive.expanduser())
        except OSError as exc:
            print(f"Error: could not read archive file: {exc}", file=sys.stderr)
            return 1
        before_archive = len(records)
        records = exclude_archive(records, archive_ids)
        archive_excluded = before_archive - len(records)
        _verbose(args.verbose, f"Archive exclusion removed {archive_excluded} entries; {len(records)} remain.")

    before_query = len(records)
    where_only_query = Query(
        resolved_query.predicate,
        resolved_query.order_by,
        None,
        resolved_query.source,
        resolved_query.select,
        resolved_query.from_source,
        False,
        0,
    )
    where_matches = apply_query(records, where_only_query)
    distinct_query = Query(
        resolved_query.predicate,
        resolved_query.order_by,
        None,
        resolved_query.source,
        resolved_query.select,
        resolved_query.from_source,
        resolved_query.distinct,
        0,
    )
    distinct_rows = apply_query(records, distinct_query)
    unlimited_query = Query(
        resolved_query.predicate,
        resolved_query.order_by,
        None,
        resolved_query.source,
        resolved_query.select,
        resolved_query.from_source,
        resolved_query.distinct,
        resolved_query.offset,
    )
    matched_before_limit = apply_query(records, unlimited_query)
    selected = matched_before_limit if resolved_query.limit is None else matched_before_limit[: resolved_query.limit]
    query_elapsed = perf_counter() - query_started
    _verbose(args.verbose, f"WHERE matched {len(where_matches)} of {before_query} entries.")
    if resolved_query.distinct:
        _verbose(
            args.verbose,
            f"DISTINCT reduced {len(where_matches)} matching row(s) to {len(distinct_rows)} projected row(s).",
        )
    if resolved_query.offset:
        _verbose(
            args.verbose,
            f"OFFSET skipped up to the first {resolved_query.offset} matching distinct row(s); {len(matched_before_limit)} remain before LIMIT.",
        )
    if resolved_query.limit is not None:
        _verbose(args.verbose, f"LIMIT reduced output to {len(selected)} entries.")
    if resolved_query.order_by:
        order_desc = ", ".join(
            f"{term.field} {'DESC' if term.descending else 'ASC'}" for term in resolved_query.order_by
        )
        _verbose(args.verbose, f"Applied ordering: {order_desc}.")
    _verbose(
        args.verbose,
        f"Output format: {_effective_output_format(args.format, len(resolved_query.select), explicit_select=bool(query.select))}.",
    )
    if args.append is not None:
        _verbose(args.verbose, f"Appending only new IDs atomically to {args.append.expanduser()}.")
    elif args.output is not None:
        _verbose(args.verbose, f"Writing output to {args.output.expanduser()}.")
    else:
        _verbose(args.verbose, "Writing output to stdout.")

    existing_count: int | None = None
    duplicate_count: int | None = None
    appended_count: int | None = None
    if not explain_analyze:
        try:
            if args.append is not None:
                existing_count, duplicate_count, appended_count = append_unique_ids(
                    selected, resolved_query, args.append
                )
                _verbose(
                    args.verbose,
                    f"Append outcome: {existing_count} existing nonblank IDs, "
                    f"{duplicate_count} query result(s) already present, {appended_count} new ID(s) appended.",
                )
            else:
                write_records(
                    selected,
                    resolved_query,
                    args.format,
                    args.output,
                    explicit_select=bool(query.select),
                )
        except ValueError as exc:
            parser.error(str(exc))
        except OSError as exc:
            print(f"Error: could not write output: {exc}", file=sys.stderr)
            return 1
        if args.append is None:
            _verbose(args.verbose, f"Emitted {len(selected)} row{'s' if len(selected) != 1 else ''}.")
    else:
        _verbose(
            args.verbose,
            f"EXPLAIN ANALYZE suppressed {len(selected)} query row{'s' if len(selected) != 1 else ''} from normal output.",
        )

    total_elapsed = perf_counter() - total_started
    current_coverage = offline_coverage
    if metadata_cache is not None and current_coverage is None:
        current_coverage = metadata_cache.source_coverage(source.canonical_url)

    if args.provenance is not None:
        provenance_payload: dict[str, object] = {
            "kind": "yt-discover-query-provenance",
            "version": PROGRAM_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "query": {
                "canonical_bound": format_query(query),
                "resolved": format_query(resolved_query),
                "parameters": {name: value for name, value in sorted(_parse_parameters(args.param).items())},
                "distinct": resolved_query.distinct,
                "offset": resolved_query.offset,
                "limit": resolved_query.limit,
            },
            "source": {
                "type": source.kind,
                "url": source.canonical_url,
                "tab": args.tab if source.kind == "channel" else None,
            },
            "execution": {
                "offline": args.offline,
                "acquisition_plan": plan.mode,
                "backend": selected_backend,
                "frontier_attempted": frontier_attempted,
                "frontier_confirmed": frontier_confirmed,
                "limit_terminated_early": limit_terminated,
                "normalised_records": len(raw_records),
                "records_evaluated": before_query,
                "where_matched": len(where_matches),
                "distinct_rows": len(distinct_rows),
                "matched_before_limit": len(matched_before_limit),
                "emitted_rows": len(selected),
            },
            "cache": {
                "enabled": metadata_cache is not None,
                "path": str(args.cache.expanduser()) if metadata_cache is not None else None,
                "fresh_hits": cache_stats.hits,
                "stale": cache_stats.stale,
                "misses": cache_stats.misses,
                "refreshed": cache_stats.refreshed,
            },
            "temporal_context": {
                "today": date_context.today.isoformat(),
                "now": date_context.local_now.isoformat(),
            },
        }
        try:
            _write_provenance(args.provenance, provenance_payload)
        except OSError as exc:
            print(f"Error: could not write provenance: {exc}", file=sys.stderr)
            return 1
        if args.provenance != "-":
            _verbose(args.verbose, f"Wrote query provenance to {Path(args.provenance).expanduser()}.")

    if args.report is not None:
        output_format = _effective_output_format(
            args.format, len(resolved_query.select), explicit_select=bool(query.select)
        )
        output_destination = (
            f"append:{args.append.expanduser()}"
            if args.append is not None
            else str(args.output.expanduser())
            if args.output is not None
            else "stdout"
        )
        report = RunReport(
            source_kind=source.kind,
            source_url=source.canonical_url,
            query=format_query(query),
            acquisition=acquisition_stats,
            normalised=len(raw_records),
            archive_excluded=archive_excluded,
            query_input=before_query,
            matched_before_limit=len(matched_before_limit),
            where_matched=len(where_matches),
            distinct_rows=len(distinct_rows),
            emitted=len(selected),
            limit=resolved_query.limit,
            distinct=resolved_query.distinct,
            offset=resolved_query.offset,
            output_format=output_format,
            output_destination=output_destination,
            acquisition_plan=plan.mode,
            acquisition_reason=plan.reason,
            enumeration=enumeration_stats,
            requested_backend=requested_backend,
            selected_backend=selected_backend,
            fallback_reason=fallback_reason,
            tools=tools,
            cost_class=cost_class,
            cost_reason=cost_reason,
            lightweight_rejected=lightweight_rejected,
            detailed_candidates=detailed_candidates,
            source_size_warning_threshold=args.warn_source_size,
            cache_enabled=metadata_cache is not None,
            cache_path=str(args.cache.expanduser()) if metadata_cache is not None else "",
            cache=cache_stats,
            offline=args.offline,
            coverage=current_coverage,
            frontier_attempted=frontier_attempted,
            frontier_confirmed=frontier_confirmed,
            frontier_new_entries=frontier_new_entries,
            limit_termination_eligible=limit_plan.eligible,
            limit_terminated=limit_terminated,
            limit_batches=limit_batches,
            limit_candidates_examined=limit_candidates_examined,
            append_existing=existing_count,
            append_duplicates=duplicate_count,
            append_added=appended_count,
            acquisition_seconds=acquisition_elapsed,
            query_seconds=query_elapsed,
            total_seconds=total_elapsed,
        )
        try:
            write_report(report, args.report)
        except OSError as exc:
            print(f"Error: could not write report: {exc}", file=sys.stderr)
            return 1
        if args.report not in {"stderr", "-"}:
            _verbose(args.verbose, f"Wrote acquisition report to {Path(args.report).expanduser()}.")
    if explain_analyze:
        analysis_payload = _explain_analyze_payload(
            query=query,
            source=source,
            plan=plan,
            requested_backend=requested_backend,
            selected_backend=selected_backend,
            fallback_reason=fallback_reason,
            enumeration=enumeration_stats,
            acquisition=acquisition_stats,
            cache=cache_stats,
            cache_enabled=metadata_cache is not None,
            offline=args.offline,
            coverage=current_coverage,
            lightweight_rejected=lightweight_rejected,
            detailed_candidates=detailed_candidates,
            query_input=before_query,
            matched_before_limit=len(matched_before_limit),
            emitted=len(selected),
            acquisition_seconds=acquisition_elapsed,
            query_seconds=query_elapsed,
            total_seconds=total_elapsed,
            frontier_attempted=frontier_attempted,
            frontier_confirmed=frontier_confirmed,
            frontier_new_entries=frontier_new_entries,
            limit_termination_eligible=limit_plan.eligible,
            limit_terminated=limit_terminated,
            limit_batches=limit_batches,
            limit_candidates_examined=limit_candidates_examined,
        )
        if args.explain_format == "json":
            print(json.dumps(analysis_payload, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(_format_explain_analyze_text(analysis_payload))

    if metadata_cache is not None:
        metadata_cache.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
