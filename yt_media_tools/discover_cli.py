"""Command-line parsing and query preparation for yt-discover.

This module contains only the CLI-facing interpretation that existed in the
0.26.6 application script. Query parsing and semantic behaviour remain owned by
the query engine.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from yt_media_tools.cache import default_cache_path
from yt_media_tools.discover_constants import DEFAULT_ARCHIVE_FILE, PROGRAM_VERSION
from yt_media_tools.query import (
    Binary,
    Field,
    IsNull,
    Literal,
    OrderTerm,
    Query,
    merge_queries,
    parse_query,
    parse_where,
)
from yt_media_tools.sources import TAB_SUFFIXES


EXAMPLES = r"""
Examples:

  Complete yt-sql queries
  -----------------------------
  The canonical form can contain WITH, SELECT, DISTINCT, FROM, WHERE, GROUP BY,
  HAVING, UNION/UNION ALL, ORDER BY, LIMIT, and OFFSET:
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

  SELECT * expands deterministically to the scalar fields available in the resolved
  schema. Use --fields or --schema when you need to inspect the available metadata.

  Compose reusable logical relations with non-recursive CTEs:
    yt-discover.py "WITH short AS (SELECT id, title FROM @example WHERE duration < 1h) SELECT id FROM short WHERE title ILIKE '%mars%'"

  Combine compatible result sets. UNION removes duplicate logical rows; UNION ALL
  preserves them:
    yt-discover.py "SELECT id, title FROM @channel_a UNION ALL SELECT id, title FROM @channel_b ORDER BY title"

  yt-dlp-supported non-YouTube collection URLs can participate in set composition
  when source classification is automatic:
    yt-discover.py "SELECT id, title FROM @channel_a UNION ALL SELECT id, title FROM 'https://www.twitch.tv/example/videos'"

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

  LIMIT can stop acquisition early when source order is the final result order. Queries decided entirely from authoritative lightweight metadata may stop source enumeration; queries needing detailed metadata may stop detailed extraction after enough final matches:
    yt-discover.py "SELECT id FROM @example LIMIT 25" -v
    yt-discover.py "SELECT id FROM @example WHERE duration < 1h LIMIT 25" -v

  OFFSET raises the proof target to OFFSET + LIMIT. yt-dlp positional item ranges are not treated as final-row limits because unavailable source entries may be skipped.

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

  If cookies.txt exists beside yt-discover.py, it is supplied to yt-dlp automatically.
  Override that optional default with an explicit cookie file when needed:
    yt-discover.py --cookies /path/to/cookies.txt @example --where "duration < 1h"

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
        help="yt-sql query with optional SELECT DISTINCT, FROM, WHERE, GROUP BY, HAVING, ORDER BY, LIMIT, and OFFSET clauses",
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
    compatibility.add_argument(
        "--cookies",
        type=Path,
        metavar="FILE",
        help="use cookies from FILE; if omitted, cookies.txt beside yt-discover.py is used when present",
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
            predicate=predicate if shortcut.predicate is None else Binary("AND", shortcut.predicate, predicate),
            order_by=shortcut.order_by,
            limit=shortcut.limit,
            source=shortcut.source,
            select=shortcut.select,
            from_source=shortcut.from_source,
            distinct=shortcut.distinct,
            offset=shortcut.offset,
            group_by=shortcut.group_by,
            having=shortcut.having,
        )

    if query.order_by and shortcut.order_by:
        raise ValueError("ORDER BY in --where/--query cannot be combined with --sort/--rev")
    if query.limit is not None and shortcut.limit is not None:
        raise ValueError("LIMIT in --where/--query cannot be combined with --limit")
    return merge_queries(query, shortcut)
