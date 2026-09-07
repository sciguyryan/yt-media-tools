# YT-SQL

YT-SQL is the query language used by `yt-discover.py`.

Version 0.7.0 expands the language with richer predicates while keeping the existing statement form.

## Query form

```text
SELECT fields
[WHERE expression]
[ORDER BY field [ASC|DESC]]
[LIMIT number]
```

Keywords are case-insensitive.

## Fields

- `id`
- `title`
- `uploader`
- `duration`
- `date`
- `live`

## Predicates

General comparisons are available with:

- `=`
- `!=`
- `<`
- `<=`
- `>`
- `>=`

Additional predicates are:

- `BETWEEN value AND value`
- `IN (value, value, ...)`
- `IS NULL`
- `IS NOT NULL`
- `CONTAINS value`
- `MATCHES value`

`CONTAINS` and `MATCHES` apply to text fields. `MATCHES` uses a case-insensitive regular expression.

## Boolean expressions

Expressions support:

- `and`
- `or`
- `not`
- parentheses

`and` and `or` still have equal precedence and are evaluated from left to right. Use parentheses when mixing them if grouping matters.

## Examples

```bash
./yt-discover.py CHANNEL_URL --query 'select id, title where duration between 600 and 1800'
./yt-discover.py CHANNEL_URL --query 'select id where title matches "interview|discussion"'
./yt-discover.py CHANNEL_URL --query 'select id where uploader in ("example", "another")'
./yt-discover.py CHANNEL_URL --query 'select id where date is not null'
```

## NULL behaviour

Missing metadata can be tested explicitly with `IS NULL` and `IS NOT NULL`.

In this version, ordinary inequality comparisons treat a missing value as unequal to a non-NULL value. This behaviour is retained for compatibility with the first implementation and may be revised as YT-SQL semantics become more formal.

## Metadata model

YT-SQL now evaluates a normalised internal metadata record rather than raw yt-dlp entries. Source acquisition and extractor-specific field handling are kept outside the query module.

YT-SQL remains backend-independent. Both yt-dlp and the experimental YouTube.js path are normalised before query evaluation.

## Query planning

Discover now inspects the fields required by a YT-SQL query before choosing an acquisition backend. `--explain` reports the selected backend and whether required metadata is expected to be exact, approximate or unavailable.

Capability planning is separate from YT-SQL evaluation. Missing metadata can still occur for individual videos even when a backend normally provides a field.
