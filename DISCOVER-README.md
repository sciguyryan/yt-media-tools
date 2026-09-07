# yt-discover

### Running the test suite

The repository includes `pytest.ini`, which makes `yt_discover_tests/` the canonical test tree, adds the project root to Python import resolution, and excludes the separate `yt_downloader_tests/` tree and legacy test copies from normal discovery. Run the complete suite from the repository root with:

```bash
python -m pytest
```

Run only the yt-sql conformance suite with:

```bash
python -m pytest yt_discover_tests/test_conformance.py
```

Dataset generation is automatic and visible during conformance runs. `yt_discover_tests/conformance/README.md` documents profile selection, reproducibility, oracle independence, and manual torture-test generation.


## v0.18.0 yt-sql oracle and scalable conformance architecture

Version 0.18.0 completes the Phase 5.5A testing architecture before analytical syntax expansion. Normal test runs no longer depend on checked-in generated datasets or pre-curated semantic answers. Instead, pytest lazily generates deterministic ephemeral datasets, seeds real yt-discover SQLite caches, executes independently authored Python oracle pipelines, executes the equivalent yt-sql through the real CLI, compares the complete serialised outputs, and lets pytest clean the temporary data afterwards.

The generator defines four centrally sized profiles:

```text
small       36 records
normal   1,000 records
large   10,000 records
huge   100,000 records
```

Routine pytest coverage uses only the `small` and `normal` profiles. The `large` and `huge` profiles remain available for deliberate manual stress, scalability and performance runs, but are disabled in the default automated suite. Tests can also request an arbitrary exact size and alternate deterministic seed.

The generator's reproducibility identity is the generator version, seed, and requested size. For the same version and seed, every smaller dataset is an exact prefix of every larger dataset. This makes scale-dependent failures reproducible without silently changing the earlier records. Generated payloads include a SHA-256 digest of the logical record sequence.

For manual inspection, reproduction, torture tests, or future benchmarking, generate one profile or an exact size explicitly:

```bash
python yt_discover_tests/conformance/generate_dataset.py \
  --profile large \
  --output-dir /tmp/yt-sql-data

python yt_discover_tests/conformance/generate_dataset.py \
  --size 250000 \
  --seed 31415926 \
  --output-dir /tmp/yt-sql-data
```

Running the generator with neither `--profile` nor `--size` and supplying `--output-dir` generates all four standard profiles. Normal pytest use requires no manual generation.

The semantic authority is `yt_discover_tests/conformance/oracle.py`, a deliberately simple LINQ-style collection pipeline. Test authors write each yt-sql query and its Python oracle independently. The oracle does not parse yt-sql, consume the production AST, or import the production query parser, planner, evaluator, metadata normaliser, schema, or output implementation. Its operators such as `where`, `select`, `distinct`, `order_by`, `then_by`, `skip`, and `take` describe the intended algorithm directly over generated records.

This means conformance expectations are algorithmic rather than pre-curated snapshots. The same query/oracle pair can run unchanged against small, normal, large, huge, an arbitrary exact size, or a different deterministic seed. Static output-format unit tests remain useful elsewhere, but semantic yt-sql correctness no longer depends on committed expected-result files.

The generated records remain extractor-like rather than relying on YouTube ID shapes. The current end-to-end cache source is necessarily resolved through the existing YouTube source adapter, but the generator and oracle are intentionally structured so later extractor/service agnosticism does not require replacing the semantic testing model.

Phase 5.5B must add independently authored oracle cases for every substantive new language construct, including boundary and cross-feature interactions, before that syntax is accepted.

## v0.16.0 query-language maturity

Version 0.16.0 implements Phase 5: D9 `DISTINCT`, D10 `OFFSET`, D11 a small scalar-function library, D13 query parameters, and D14 machine-readable query provenance. The existing acquisition, cache, frontier, offline, explain, and output behaviour remains compatible.

`SELECT DISTINCT` removes duplicate projected rows. Deduplication is based on the selected scalar values after deterministic ordering, so when several source records produce the same projection the first record in the requested order is retained. `OFFSET` is a non-negative row offset applied after filtering, ordering, and `DISTINCT`, and before `LIMIT`:

```bash
yt-discover.py "SELECT DISTINCT title FROM @example ORDER BY upload_date DESC LIMIT 25 OFFSET 50"
```

The first scalar-function library is intentionally small. `LOWER(field)`, `UPPER(field)`, `LENGTH(field)`, and `COALESCE(field, fallback, ...)` are supported in `SELECT`. Give a computed value an alias to use it in `ORDER BY`:

```bash
yt-discover.py "SELECT id, LOWER(title) AS folded FROM @example ORDER BY folded ASC"
yt-discover.py "SELECT COALESCE(title, 'Untitled') AS title FROM @example"
```

Functions are currently projection expressions rather than a general arithmetic/expression language. Function predicates and nested function expressions are deliberately deferred rather than being implemented with ambiguous coercion rules.

Repeatable `--param NAME=VALUE` bindings replace `:NAME` placeholders outside quoted strings. Values are safely quoted first and then interpreted by the existing field-aware literal resolver, so dates, durations, counts, Booleans, timestamps, and strings retain the same query typing rules:

```bash
yt-discover.py \
  --param start=2026-08-01 \
  --param maximum=1h \
  "SELECT id FROM @whatdamath WHERE upload_date >= :start AND duration < :maximum"
```

Every supplied parameter must be used and every placeholder must be bound. Duplicate parameter names are rejected case-insensitively. Placeholders inside quoted SQL strings are literal text and are not expanded.

`--provenance FILE` writes a JSON sidecar describing the submitted and resolved query, parameter bindings, source, execution plan/backend, cache outcome, temporal context, and result counts. It is intended for reproducibility and audit trails rather than replacing `--report`:

```bash
yt-discover.py \
  --offline \
  --provenance ./runs/anton-query.json \
  "SELECT DISTINCT id FROM @whatdamath WHERE duration < 1h"
```

Use `--provenance -` only when normal query rows are redirected elsewhere, so provenance JSON cannot silently contaminate a pipeline.

`DISTINCT` and non-zero `OFFSET` conservatively disable Phase 4 LIMIT-aware detailed-acquisition termination for now. Their row-shaping semantics are exact, but the early-termination proof has not yet been extended to them.

`yt-discover.py` is a media-metadata discovery tool built around yt-dlp, with optional YouTube.js channel enumeration. Its SQL-inspired query language is named yt-sql. It can query channel or playlist metadata, filter and order records locally, project selected fields, and emit shell-friendly or structured output.

The default remains deliberately simple: if `SELECT` is omitted, the query behaves as `SELECT id`, so the output can still be piped directly into `run-downloader.py -`.

Run either command for the detailed reference:

```bash
yt-discover.py --help
yt-discover.py --examples
```

Both include extensive practical examples covering sources, filtering, dates, projection, nested metadata, output formats, diagnostics, verbose operation, and piping.

## v0.15.0 LIMIT-aware execution optimisation

Version 0.15.0 implements Phase 4 and D5 with a deliberately proof-based first form of LIMIT-aware acquisition termination. When a query has `LIMIT`, preserves source order by omitting `ORDER BY`, and uses only statically known fields, yt-discover acquires detailed metadata in source-order batches and stops once the requested number of authoritative matches has been observed. Later source rows cannot displace those matches from the first N results, so the optimisation is exact rather than heuristic.

```bash
./yt-discover.py --tab videos \
  "SELECT id FROM @whatdamath WHERE duration < 1h LIMIT 25" -v
```

Queries with an explicit `ORDER BY` remain exhaustive in this release because a later row may still outrank an earlier match. Dynamic `raw.*` fields are also excluded from early termination because their types are resolved only after detailed metadata exists. Archive exclusion disables the optimisation because archived rows are removed after acquisition and could otherwise cause an unsafe early stop. Offline queries do not need the optimisation because they perform no network metadata acquisition.

`--explain` and JSON explain now state whether LIMIT-aware acquisition is eligible and why. `--explain-analyze` and `--report` record whether detailed acquisition actually stopped early, how many source-order batches ran, and how many candidates were examined. When acquisition stops after LIMIT is satisfied, result statistics explicitly mark the observed match count as a lower bound rather than pretending the unexamined tail has been counted.

The batch size is intentionally conservative and implementation-defined. LIMIT therefore bounds detailed acquisition work without promising exactly N metadata requests. Source enumeration and the D8 frontier remain independent: a query may avoid most detailed extraction even when the source itself still requires a complete or frontier-confirming lightweight scan.

## v0.14.0 incremental source frontier and safe append

Version 0.14.0 implements Phase 3. Eligible normal online queries against a channel `videos` tab can now reuse a trusted persisted source ordering as an incremental frontier. yt-discover enumerates the newest-first flat feed until five consecutive previously known IDs confirm overlap, then merges the newly observed prefix with the trusted historical ordering instead of walking the entire channel again. If overlap is not confirmed before the feed ends, yt-discover treats that as uncertainty, completes the enumeration, and rebuilds the trusted ordering from the full observation. Explicit `--acquisition full` continues to force complete enumeration.

The frontier is separate from detailed-metadata coverage. An inaccessible or members-only video can therefore remain part of the trusted source ordering without falsely claiming that detailed metadata for it is cached. Trusted source ordering is replaced transactionally after a complete observation so entries that have disappeared do not survive as phantom frontier members. The SQLite schema is now version 3; version 1 and 2 caches migrate automatically where their persisted ordering can be validated conservatively.

Phase 3 also adds native persistent ID-list output:

```bash
./yt-discover.py --tab videos \
  "SELECT id FROM @whatdamath WHERE duration < 1h ORDER BY upload_date ASC, release_timestamp ASC" \
  --append ./ids/ids-anton
```

`--append FILE` is intentionally ID-specific. It preserves the existing UTF-8 file, appends only IDs that are not already present, and updates the file atomically using a temporary file and `os.replace()`. Existing duplicates already present in the file are left untouched; new duplicates are not added. Plain shell `>>` remains supported for ordinary append semantics. `-v` reports existing IDs, query results already present, and newly appended IDs.

The first D8 implementation uses yt-dlp's lazy flat feed for frontier overlap. The optional YouTube.js backend remains available for bounded-date enumeration as before. `--explain`, `--explain-analyze`, JSON explain output, and `--report` now describe frontier eligibility and actual frontier outcomes.

## v0.13.0 cache-native querying and execution analysis

Version 0.13.0 implements Phase 2. The persistent cache can now be queried directly with `--offline`, which guarantees that yt-discover will not contact YouTube or refresh stale metadata. Offline mode uses the detailed records already stored for the resolved source. If the most recent recorded source coverage is incomplete or unknown, yt-discover says so explicitly on standard error rather than pretending the cached subset is the whole current source. Required fields that have exceeded their normal freshness policy are also reported as stale, but their cached values are still used because offline mode forbids refreshes.

```bash
./yt-discover.py --offline --tab videos \
  "SELECT id, title, upload_date FROM @whatdamath WHERE duration < 1h ORDER BY upload_date ASC, release_timestamp ASC"
```

A cache-only query fails clearly when there are no cached detailed records for the requested source. Source order observations are now persisted separately so offline queries can preserve the most recently observed source order when no explicit `ORDER BY` is supplied. This is still not a D8 frontier and does not remove the need for online source enumeration during normal runs.

`--explain` now has a machine-readable form:

```bash
./yt-discover.py --tab videos --explain-format json --explain \
  "SELECT id FROM @whatdamath WHERE upload_date >= 2026-08-01 AND duration < 1h LIMIT 25"
```

B1 `EXPLAIN ANALYZE` is available as `--explain-analyze`. It executes the query but suppresses normal result rows, then reports the plan and actual execution outcome, including enumeration, lightweight rejection, detailed candidates, cache reuse, query-result statistics and timings. Use `--explain-format json` for structured output.

```bash
./yt-discover.py --tab videos --explain-analyze \
  "SELECT id FROM @whatdamath WHERE upload_date >= 2026-08-01 AND duration < 1h LIMIT 25"

./yt-discover.py --offline --tab videos --explain-format json --explain-analyze \
  "SELECT id FROM @whatdamath WHERE duration < 1h ORDER BY upload_date ASC"
```

The SQLite schema is now version 2. Existing version 1 Phase 1 caches are migrated in place by creating the new source-order and coverage tables, while unsupported schema versions still fail closed. `--report` has also gained offline/cache coverage and timing information.

## v0.12.1 inaccessible-only detailed refresh fix

Version 0.12.1 fixes a Phase 1 cache-refresh edge case where yt-dlp could return status 1 after every requested stale or missing video proved inaccessible, even though yt-discover had already classified those per-video failures correctly. Fully accounted-for per-video YouTube failures are now retained as skips and query execution continues. Unexplained or extractor-wide yt-dlp failures remain fatal.

## v0.12.0 persistent metadata cache

Version 0.12.0 introduces the Phase 1 persistent SQLite metadata cache. Normal channel-video queries still enumerate the current source because the D8 incremental frontier is deliberately not active yet, but yt-discover now checks source-scoped cached detailed metadata before asking yt-dlp to re-extract a known video. Fresh cache hits are reused; missing or stale records are refreshed and written back transactionally.

Freshness is field-aware. Stable identity and publication fields can be reused for much longer than mutable counters or availability state. If any field required by the current query has exceeded its freshness policy, yt-discover refreshes that video's complete authoritative yt-dlp record. Dynamic `raw.*` paths are only treated as cache hits when the path was actually present in the cached record.

The default cache follows the XDG cache convention and normally lives at `~/.cache/yt-discover/metadata.sqlite3`. Override it or disable it per run:

```bash
./yt-discover.py --cache /path/to/metadata.sqlite3 --tab videos \
  "SELECT id FROM @whatdamath WHERE duration < 1h"

./yt-discover.py --no-cache --tab videos \
  "SELECT id FROM @whatdamath WHERE duration < 1h"
```

The cache schema is explicitly versioned. Version 1 caches migrate automatically to the current schema, while unsupported schema versions fail closed. Source observations are recorded for future D8 work, but v0.12.0 does not treat them as a trusted frontier or completeness guarantee. This means stale cache state can cost extra work, but cannot cause yt-discover to silently skip new uploads.

`--report` now includes cache hits, misses, stale entries, refreshes, and writes. `--explain` documents the cache-first detailed-metadata plan and explicitly states that source completeness is still established online.

## v0.11.0 capability-aware planning and explain output

Version 0.11.0 introduces an explicit acquisition capability model. yt-discover now distinguishes metadata that is exact, approximate, or unavailable at the YouTube.js, yt-dlp flat, and yt-dlp detailed stages. `--explain` exposes those capabilities together with the planned acquisition strategy, optimisation paths that are active or available, reasons an optimisation cannot be used, and the estimated acquisition cost.

Bounded channel scans now use a general conservative lightweight predicate evaluator. It may reject a candidate before detailed yt-dlp extraction when exact lightweight values or conservative upload-date uncertainty intervals prove that the complete `WHERE` expression is false. This includes safe upper-date pruning as well as the existing lower-bound rejection. Unknown or ambiguous values are always retained for authoritative detailed evaluation.

`--warn-source-size` now rejects negative values and reports observed source work when the threshold is actually reached. Explicit `--acquisition full` no longer produces the generic warning that no automatic optimisation was found. Acquisition reports include detailed-candidate counts and the configured source-size warning threshold.

For example:

```bash
./yt-discover.py --tab videos --explain \
  "SELECT id FROM @whatdamath WHERE upload_date BETWEEN 2026-04-01 AND 2026-06-30 AND duration < 1h LIMIT 25"
```

The explanation shows why the date range can bound enumeration and prune provably out-of-range candidates, while `duration` still requires authoritative detailed metadata.

## v0.10.0 YouTube.js compatibility fix

The YouTube.js backend now consumes its parser-backed `feed.videos` collection as an iterable rather than requiring a native JavaScript array. This is important with current YouTube.js releases, where channel video feeds are exposed through `ObservedArray` and may include newer `LockupView` video nodes. If a channel advertises a Videos tab but YouTube.js yields no parseable video entries, `--backend auto` treats that as a backend failure and falls back to yt-dlp instead of silently returning an empty result.


## Linux installation and external tools

yt-discover requires Python 3 and yt-dlp. YouTube.js is optional and is used only to improve bounded channel enumeration when it is available. Full metadata extraction remains yt-dlp-based.

Check the current installation without contacting YouTube:

```bash
./yt-discover.py --check-tools
```

A healthy installation with the optional backend available will report Python-side access to yt-dlp, Node.js, and YouTube.js. If YouTube.js is unavailable, normal `--backend auto` runs can fall back to yt-dlp and will announce that fallback on standard error when the query would otherwise use the optional backend.

### Required: yt-dlp

Install yt-dlp using the method appropriate to the Linux distribution. A common isolated Python installation is:

```bash
python3 -m pip install --user -U yt-dlp
```

Alternatively, use the official yt-dlp binary or a distribution package, provided `yt-dlp` is available in `PATH`. Verify it with:

```bash
yt-dlp --version
```

### Optional: Node.js and YouTube.js

YouTube.js is an optional InnerTube client used for continuation-driven channel enumeration. It does not require a YouTube Data API key. Install a current Node.js release using the Linux distribution, NodeSource, `nvm`, or another trusted Node.js installation method, then verify:

```bash
node --version
npm --version
```

Install YouTube.js locally in the extracted yt-discover directory so Node module resolution is deterministic:

```bash
cd /path/to/yt-discover
npm install youtubei.js@latest
./yt-discover.py --check-tools
```

The local installation creates `node_modules/` beside `yt-discover.py`. It is deliberately optional and is not bundled in the release archive. YouTube.js currently documents installation through `npm install youtubei.js@latest`; because it talks to YouTube's internal InnerTube interface, it may occasionally require updates when YouTube changes its responses.

Backend selection is explicit:

```bash
# Prefer YouTube.js bounded enumeration when available, otherwise fall back to yt-dlp.
./yt-discover.py --backend auto --tab videos "FROM @channel WHERE upload_date >= TODAY()-6mo"

# Never use YouTube.js.
./yt-discover.py --backend ytdlp --tab videos "FROM @channel WHERE upload_date >= TODAY()-6mo"

# Require YouTube.js. Missing tools or runtime enumeration failures are fatal.
./yt-discover.py --backend youtubejs --tab videos "FROM @channel WHERE upload_date >= TODAY()-6mo"
```

`--backend` controls the optional bounded enumeration stage. Full source acquisition and authoritative detailed metadata extraction continue to use yt-dlp.

## Complete queries

A complete query may contain `SELECT`, `FROM`, `WHERE`, `ORDER BY`, and `LIMIT`:

```bash
yt-discover.py "SELECT id, title, upload_date, views FROM @channel WHERE upload_date >= 2026-04-01 ORDER BY upload_date DESC LIMIT 100"
```

`SELECT` is optional. This query:

```bash
yt-discover.py "FROM @channel WHERE upload_date BETWEEN 2026-04-01 AND TODAY()"
```

is equivalent to selecting only `id`, so it remains ideal for pipelines:

```bash
yt-discover.py "FROM @channel WHERE upload_date BETWEEN 2026-04-01 AND TODAY()" \
| run-downloader.py -
```

The established source-plus-options interface is retained:

```bash
yt-discover.py @channel --where "duration < 45m AND views >= 5k"
yt-discover.py PLxxxxxxxxxxxxxxxxxxxxxx --query "WHERE duration >= 30m ORDER BY playlist_index ASC"
```

## SELECT projection

Select one scalar field to receive one value per line by default:

```bash
yt-discover.py "SELECT title FROM @channel ORDER BY upload_date DESC"
```

Select multiple fields to receive JSON Lines by default:

```bash
yt-discover.py "SELECT id, title, upload_date, duration, views FROM @channel"
```

Output aliases use `AS`:

```bash
yt-discover.py "SELECT title, view_count AS views FROM @channel"
```

Explicit aliases may also be referenced by `ORDER BY`:

```bash
yt-discover.py "SELECT id, raw.extra.score AS score FROM @channel ORDER BY score DESC"
```

`SELECT *` is intentionally unsupported. yt-dlp metadata is dynamic, so an implicit star has no stable, honest meaning. Use `--fields` or `--schema` to inspect available scalar fields, then select the fields you actually need.

## FROM sources

`FROM` accepts channel handles, channel IDs, playlist IDs, bare channel names, and quoted URLs:

```text
FROM @channel
FROM UCxxxxxxxxxxxxxxxxxxxxxx
FROM PLxxxxxxxxxxxxxxxxxxxxxx
FROM channel-name
FROM 'https://www.youtube.com/playlist?list=PLxxxxxxxxxxxxxxxxxxxxxx'
```

Automatic source classification remains deterministic. `--source-type channel|playlist` is available as an override for unusual identifiers. Channel-only `--tab all|videos|shorts|live` behaviour is retained and is rejected for playlists rather than silently ignored.

## WHERE predicates

Supported predicates include:

```text
=  !=  <>  <  <=  >  >=
BETWEEN ... AND ...
NOT BETWEEN ... AND ...
IN (...)
NOT IN (...)
IS NULL
IS NOT NULL
IS TRUE
IS FALSE
CONTAINS
NOT CONTAINS
MATCHES
NOT MATCHES
AND
OR
NOT
(...)
```

Examples:

```text
WHERE duration BETWEEN 10m AND 2h
WHERE views >= 100k AND NOT title CONTAINS 'trailer'
WHERE live_status IN ('not_live', 'was_live')
WHERE duration IS NOT NULL AND duration < 45m
```

`CONTAINS` is case-insensitive. Ordinary string equality is case-sensitive except for known enum-like fields such as `live_status` and `availability`, which compare case-insensitively. `MATCHES` uses the regular expression as written.

## Human-readable values

Durations accept forms such as:

```text
30s
10m
2h
1h30m
90 minutes
01:30:00
```

Counts accept separators and suffixes:

```text
1_000
1,000
10k
1.5m
2b
```

Literal interpretation is type-aware. For example, `5m` means five minutes against `duration` and five million against a count field.

## Dates and timestamps

ISO dates are preferred:

```text
2026-04-01
```

Compact yt-dlp dates, local numeric dates, named dates, and readable relative dates are also supported:

```text
20260401
31/01/2026
1 January 2026
6 months ago
1 year ago
```

`--date-format dmy|mdy|ymd` controls ambiguous local numeric dates. ISO remains universally accepted.

`TODAY()` is a typed local calendar date:

```text
upload_date BETWEEN TODAY()-1yr AND TODAY()
upload_date >= TODAY()-6mo
```

`NOW()` is a typed timestamp:

```text
release_timestamp >= NOW()-48h
release_timestamp BETWEEN NOW()-1yr AND NOW()
```

`TODAY()` and `NOW()` are captured once per query run. Date fields require date values, and timestamp fields require timestamp values, avoiding hidden midnight or timezone coercions.

## Dynamic and nested metadata

Top-level scalar yt-dlp JSON fields become queryable and selectable dynamically. Known fields receive stronger semantic types, and friendly aliases include:

```text
views     -> view_count
likes     -> like_count
comments  -> comment_count
date      -> upload_date
url       -> webpage_url
```

The original yt-dlp JSON is retained internally, so nested scalar object paths can be used through `raw.*`:

```text
raw.some_object.some_value >= 10
```

They may also be selected:

```text
SELECT id, raw.some_object.some_value AS score
```

Objects and arrays themselves are deliberately not given invented scalar semantics. Collection functions remain reserved until a real use case justifies them.

Use introspection to inspect actual metadata:

```bash
yt-discover.py @channel --items 1 --fields
yt-discover.py @channel --items 1 --schema
```

## Ordering and limiting

`ORDER BY` supports multiple fields and independent directions:

```text
ORDER BY upload_date DESC, views DESC
```

Explicit `SELECT ... AS ...` aliases may be used by `ORDER BY`. Missing ordering values are placed last for both directions. Stable sorting preserves acquisition order as the final implicit tie-breaker.

`source_index` exposes acquisition order explicitly. `playlist_index` remains available for playlist sources.

Existing shortcuts remain available:

```text
--sort newest
--sort oldest
--rev
--limit 100
```

## Output formats

The default `--format auto` chooses:

- one selected scalar field: one value per line
- multiple selected fields: JSON Lines

Explicit formats are:

```text
auto
lines
jsonl
csv
tsv
```

CSV and TSV include a header row using the selected output names:

```bash
yt-discover.py "SELECT id, title, upload_date, views FROM @channel" --format csv > videos.csv
```

`--format lines` requires exactly one selected field.

The legacy `--format ids` and `--format urls` shortcuts remain supported only when `SELECT` is omitted. This prevents an explicit projection from being silently overridden.

## Validation and diagnostics

Validate grammar without contacting YouTube:

```bash
yt-discover.py --check-query "SELECT id, title FROM @channel WHERE duration BETWEEN 10m AND 2h ORDER BY views DESC"
```

Dynamic field existence and type validation occur after metadata acquisition because yt-dlp fields can vary by source and extractor.

Use `--explain` to describe the semantics of a complete query without contacting YouTube:

```bash
yt-discover.py --explain "SELECT id FROM @channel WHERE upload_date BETWEEN TODAY()-1yr AND TODAY() ORDER BY upload_date ASC"
```

The explanation reports source classification, projection and aliases, the interpreted filter, ordering, limit, default serialisation, and the single captured values of `TODAY()` and `NOW()`. Known fields are type-checked immediately. Dynamic yt-dlp fields are explicitly marked as requiring post-acquisition validation rather than being guessed.

Use `--dry-run` to inspect source resolution, the yt-dlp command, and the parsed query without running yt-dlp:

```bash
yt-discover.py "SELECT id, title FROM @channel WHERE duration < 45m" --dry-run
```

Use `-v` or `--verbose` for concise runtime progress. Verbose messages are written exclusively to standard error, preserving standard output for pipelines:

```bash
yt-discover.py -v "FROM @channel WHERE upload_date >= TODAY()-30d" \
| run-downloader.py -
```

Verbose mode reports source resolution, the yt-dlp command, acquisition progress and record count, schema construction, archive exclusions, query selection, ordering and limits, the selected output format, destination, and emitted row count. Normal operation remains quiet and machine-friendly.

## Acquisition controls

Existing acquisition controls remain available, including `--items`, `--date`, `--after`, `--before`, `--match-filter`, `--exclude-live`, `--exclude-upcoming`, and downloader-archive exclusion. These are kept separate from the local query language where they represent yt-dlp acquisition policy rather than metadata query semantics.

## Live progress and acquisition reports

Long channel or playlist scans can take time because yt-discover acquires full metadata before applying operations such as ORDER BY. Use `-v` for periodic acquisition counts and important inaccessible/skipped entries on standard error. Use `-vv` to additionally report every successfully acquired entry. Query results remain on standard output, so both modes are safe in pipelines.

Use `--report` to print a post-run acquisition/query report to standard error. Use `--report FILE` to write the report to a UTF-8 text file, or `--report -` to explicitly place it on standard output. Reports include the number of videos attempted or observed, metadata records available, inaccessible/skipped videos by recognised category, archive exclusions, records evaluated by WHERE, matches before LIMIT, and rows emitted. If yt-dlp emits errors that cannot be associated with a specific video ID, the attempted total is labelled as a minimum rather than presented as exact.

Examples:

```bash
yt-discover.py -v "FROM @example WHERE upload_date >= TODAY()-30d" | run-downloader.py -

yt-discover.py -vv "FROM @example ORDER BY upload_date ASC"

yt-discover.py "FROM @example WHERE views >= 10k" --report

yt-discover.py "SELECT id, title FROM @example" --report acquisition-report.txt
```

## Query-planned bounded acquisition

Version 0.11.0 can avoid walking an entire large channel in an important class of queries. When `--acquisition auto` is used, the source is a channel `videos` tab, and the `WHERE` expression logically implies a lower `upload_date` bound, yt-discover performs continuation-driven lightweight enumeration first. In `--backend auto`, YouTube.js is preferred when installed; otherwise yt-dlp lazy flat enumeration is used. Both lightweight backends expose approximate or relative publication timing rather than authoritative full-video metadata, so yt-discover keeps a generous safety margin and requires several consecutive entries beyond that margin before stopping pagination. YouTube.js relative dates receive an additional uncertainty allowance before an entry may count as safely old. It then performs full yt-dlp extraction only for the candidate video IDs that were actually enumerated, and evaluates the original query against authoritative metadata. If YouTube.js is unavailable or fails during an `auto` run, yt-discover prints a fallback notice to standard error and retries bounded enumeration with yt-dlp. Explicit `--backend youtubejs` is strict and does not fall back.

For example:

```bash
./yt-discover.py --tab videos \
  "SELECT id FROM @whatdamath WHERE upload_date BETWEEN 2026-04-01 AND TODAY() ORDER BY upload_date ASC" \
  -v --report
```

Use `--acquisition full` to force exhaustive acquisition. Use `--backend ytdlp` to disable the optional YouTube.js enumerator while retaining bounded planning where eligible. Automatic bounded acquisition intentionally falls back to full acquisition for playlists, `--tab all`, shorts/live tabs, predicates whose OR/NOT structure cannot prove a universal lower date bound, and runs that already contain explicit yt-dlp acquisition prefilters. This keeps the optimisation separate from query correctness.


## Acquisition cost assessment and large-source warnings

Version 0.11.0 assesses the likely acquisition cost before contacting YouTube. The planner distinguishes bounded scans from queries for which no safe early-termination strategy can be proved. With `-v`, the selected cost class and its reason are printed to stderr.

When a query has no safe source boundary and appears to require detailed metadata, yt-discover prints a non-interactive warning before automatic full acquisition. Explicit `--acquisition full` suppresses that warning because the exhaustive plan was requested deliberately. `--warn-source-size COUNT` reports when observed acquisition work actually reaches the configured threshold; `--warn-source-size 0` disables threshold notices.

Bounded scans also perform conservative lightweight candidate rejection. Relative publication dates carry uncertainty intervals, while IDs and titles are exact at supported lightweight stages. An enumerated video is skipped before yt-dlp detail extraction only when the complete `WHERE` expression can be proved false from those capabilities. This supports both lower and upper upload-date pruning and exact ID/title predicates. Ambiguous, unavailable, or otherwise uncertain cases are retained. The authoritative `WHERE` expression is still evaluated against full yt-dlp metadata.

The acquisition report records the cost estimate, its reason, observed enumeration counts, detailed-candidate count, and how many lightweight candidates were safely rejected before detailed extraction.

Examples:

```bash
./yt-discover.py --tab videos \
  "FROM @example WHERE upload_date >= TODAY()-6mo" -v --report
```

```bash
./yt-discover.py \
  "FROM @example WHERE raw.some_field = 'value'" \
  --warn-source-size 1000 -v
```
