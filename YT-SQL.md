# YT-SQL

YT-SQL is the query language used by `yt-discover.py`.

Version 0.5.0 expands the earlier boolean filter expressions into complete query statements.

## Query form

```text
SELECT fields
[WHERE expression]
[ORDER BY field [ASC|DESC]]
[LIMIT number]
```

Keywords are case-insensitive.

## Examples

Print IDs:

```bash
./yt-discover.py CHANNEL_URL --query 'select id'
```

Filter results:

```bash
./yt-discover.py CHANNEL_URL --query 'select id where title contains "interview" and duration >= 900'
```

Select several fields:

```bash
./yt-discover.py CHANNEL_URL --query 'select id, title, duration where duration >= 600'
```

Order and limit results:

```bash
./yt-discover.py CHANNEL_URL --query 'select id, title order by date desc limit 20'
```

When several fields are selected, output is tab-separated.

## Fields

- `id`
- `title`
- `uploader`
- `duration`
- `date`
- `live`

## Boolean expressions

`where` expressions support:

- `and`
- `or`
- `not`
- parentheses

At this stage, `and` and `or` still have equal precedence and are evaluated from left to right. Use parentheses when mixing them if grouping matters.

## Comparisons

`title` and `uploader` support `contains`.

`duration` and `date` support:

- `=`
- `!=`
- `<`
- `<=`
- `>`
- `>=`

`live` supports equality with `true` or `false`.

## Legacy expression mode

The earlier `--where` option remains available for queries that only need ID output:

```bash
./yt-discover.py CHANNEL_URL --where 'duration >= 900'
```

## Implementation

YT-SQL parsing and evaluation now live in a separate `yt_query.py` module rather than inside the command-line script.

`ORDER BY` is applied before `LIMIT`, so limited ordered queries select from the correctly ordered result set.
