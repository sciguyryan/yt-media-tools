# YouTube discovery

`yt-discover.py` is a companion to the downloader for finding video IDs from a YouTube channel or playlist.

It uses `yt-dlp` to enumerate the source, applies the requested filters and prints matching video IDs one per line. The output can be redirected to a file or piped into the downloader.

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
