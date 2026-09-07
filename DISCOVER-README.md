# YouTube discovery

`yt-discover.py` is a companion to the downloader for finding video IDs from a YouTube channel or playlist.

It uses `yt-dlp` by default to enumerate the source, applies the requested filters and prints matching video IDs one per line. An experimental YouTube.js source backend is also available when Node.js and `youtubei.js` are installed. The output can be redirected to a file or piped into the downloader.

## Basic use

Print all IDs found in a source:

```bash
./yt-discover.py CHANNEL_OR_PLAYLIST_URL
```

Filter by upload date:

```bash
./yt-discover.py CHANNEL_URL --after 2024-01-01
./yt-discover.py CHANNEL_URL --before 2024-12-31
./yt-discover.py CHANNEL_URL --after 2024-01-01 --before 2024-12-31
```

Filter titles using a case-insensitive substring or regular expression:

```bash
./yt-discover.py CHANNEL_URL --title interview
./yt-discover.py CHANNEL_URL --title-regex 'interview|discussion'
```

Uploader, duration and live-status filters can be combined:

```bash
./yt-discover.py CHANNEL_URL --uploader example --min-duration 600
./yt-discover.py CHANNEL_URL --max-duration 300 --live no
```

Sort and limit the matching entries:

```bash
./yt-discover.py CHANNEL_URL --sort date --reverse --limit 20
./yt-discover.py CHANNEL_URL --sort title --limit 50
```

All supplied filters are combined. For example:

```bash
./yt-discover.py CHANNEL_URL --after 2024-01-01 --title interview --min-duration 900 --live no --sort date --reverse --limit 25
```

This is becoming cumbersome for complicated searches, but each option can still be useful on its own.

## YT-SQL expressions

The experimental filter expression now has a name: YT-SQL.

YT-SQL is still only a filter language at this stage. It does not yet provide complete query statements, projections, ordering clauses or limits.

For example:

```bash
./yt-discover.py CHANNEL_URL --where 'title contains "interview" and duration >= 900'
```

Boolean expressions can now use `and`, `or`, `not` and parentheses:

```bash
./yt-discover.py CHANNEL_URL --where '(title contains "interview" or title contains "discussion") and not live = true'
```

The current language supports:

- `title contains VALUE`
- `uploader contains VALUE`
- `duration =`, `!=`, `<`, `<=`, `>` and `>=`
- `date =`, `!=`, `<`, `<=`, `>` and `>=`
- `live = true` and `live = false`
- `and`
- `or`
- `not`
- parentheses

Existing command-line filters still work and are combined with YT-SQL expressions.

This first named YT-SQL parser is intentionally small. `and` and `or` currently have the same precedence and are evaluated from left to right, so parentheses should be used when mixing them.

## Complete YT-SQL queries

YT-SQL can now be supplied as a complete query statement with `--query`.

The simplest query is:

```bash
./yt-discover.py CHANNEL_URL --query 'select id'
```

Filtering can be included with `where`:

```bash
./yt-discover.py CHANNEL_URL --query 'select id where title contains "interview" and duration >= 900'
```

Multiple fields are printed as tab-separated values:

```bash
./yt-discover.py CHANNEL_URL --query 'select id, title, duration where duration >= 600'
```

Queries can also order and limit results:

```bash
./yt-discover.py CHANNEL_URL --query 'select id, title order by date desc limit 20'
```

Supported selected fields are `id`, `title`, `uploader`, `duration`, `date` and `live`.

The older `--where` expression option remains available for ID-only output. `--where` and `--query` cannot be used together.

## Richer YT-SQL predicates

YT-SQL now supports several predicates that previously required dedicated command-line options or could not be expressed at all:

```bash
./yt-discover.py CHANNEL_URL --query 'select id, title where duration between 600 and 1800'
./yt-discover.py CHANNEL_URL --query 'select id where title matches "interview|discussion"'
./yt-discover.py CHANNEL_URL --query 'select id where uploader in ("example", "another")'
./yt-discover.py CHANNEL_URL --query 'select id where date is not null'
```

`BETWEEN`, `IN`, `IS NULL`, `IS NOT NULL`, `CONTAINS` and `MATCHES` can be combined with the existing Boolean operators.

## Source backends

Discover now has an experimental second source backend.

The normal backend remains `yt-dlp`:

```bash
./yt-discover.py CHANNEL_URL --source-backend yt-dlp
```

YouTube.js can be selected explicitly when Node.js and `youtubei.js` are available:

```bash
./yt-discover.py CHANNEL_URL --source-backend youtubejs
```

Backend availability can be inspected without enumerating a source:

```bash
./yt-discover.py --list-backends
```

The YouTube.js backend is experimental in this version. It assumes a fairly simple response shape from `youtubei.js` and is expected to need compatibility work as more channel and playlist forms are exercised.

## Metadata cache

Discover now keeps source enumeration metadata in a local SQLite cache by default. The cache reduces repeated source enumeration while keeping the query and normalisation layers independent from storage.

The default cache file is `discover-cache.sqlite3` beside the script. Use `--cache PATH` to select another database, `--cache-max-age SECONDS` to change freshness, `--refresh` to ignore an existing cached source, or `--no-cache` to disable persistent caching.

The initial cache schema stores raw source entries together with source order and fetch time. Cache schema compatibility is checked explicitly.

`--refresh-details` asks Discover to enrich incomplete cached entries without re-enumerating the whole source. Detailed refresh is best-effort: deleted, private or otherwise inaccessible videos are left with their existing cached metadata while refresh continues for the remaining entries.

The cache can now act as an execution source in its own right. `--offline` requires cached metadata and prevents live source access. Stale cached metadata is accepted in offline mode because no network refresh is permitted.

```bash
./yt-discover.py CHANNEL_URL --offline --query 'select id, title where duration >= 600'
```

Use `--cache-status` to report whether the cached source is fresh or stale, how many entries it contains, its age, and the backend that originally populated it. `--explain` now reports whether execution is cache-native or live.

Cache schema version 2 records source-level acquisition metadata. Existing schema version 1 databases are migrated in place.

## Query planning

Discover can now choose a source backend according to the fields required by a query.

The default backend mode is `auto`. A backend can still be forced explicitly with `--source-backend`.

Use `--explain` to inspect the selected backend and metadata coverage:

```bash
./yt-discover.py CHANNEL_URL --query 'select id, duration where live = false' --explain
```

The first capability model distinguishes metadata as `exact`, `approximate` or `unavailable`. Planning prefers an available backend with fewer unavailable fields and then stronger metadata coverage.

This is an early planner. Capability declarations describe what the backend integration expects to provide rather than guaranteeing that every individual source contains every field.

## Acquisition and metadata normalisation

Discover now separates source enumeration from query evaluation.

`yt_sources.py` is responsible for asking yt-dlp to enumerate a source. The resulting extractor metadata is then converted by `yt_metadata.py` into a smaller internal record containing the fields YT-SQL currently understands.

This keeps YT-SQL independent from yt-dlp-specific field names and provides one place to handle missing or inconsistent metadata.

## Metadata limitations

The discovery script relies on metadata available from `yt-dlp --flat-playlist`. Entries with missing metadata cannot satisfy filters that require that field. For example, an entry without an upload date cannot match `--after` or `--before`, and an entry without duration cannot match a duration range.

## Downloader integration

Save discovered IDs for later:

```bash
./yt-discover.py CHANNEL_URL --title interview > ids.txt
./yt-download.py
```

Or pass them through standard input:

```bash
./yt-discover.py CHANNEL_URL --title interview | ./yt-download.py -
```

## Options

Run the built-in help for the complete option list:

```bash
./yt-discover.py --help
```

## Licence

This project is distributed under the GNU Lesser General Public License version 2.1. See `LICENSE` for the licence text.

## Incremental source refresh

Discover can now extend an existing newest-first cached source without replacing its known tail:

```bash
./yt-discover.py CHANNEL_URL --incremental
```

The refresh observes the source again and looks for the first video ID already present in the cached ordering. Only entries before that confirmed overlap are appended to the cache. Duplicate IDs in the newly observed prefix are ignored.

If no overlap with the cached source can be confirmed, Discover refuses the incremental update rather than guessing that two independent observations belong to one continuous ordering. Use `--refresh` when a complete replacement is intended.

Cache schema version 3 records the current source head and the number of successful overlap confirmations. Existing version 2 caches are migrated in place.
