# YT-SQL

YT-SQL is the experimental query language used by `yt-discover.py`.

At version 0.4.0 it is only a boolean filter expression supplied through `--where`. It is not yet a complete SQL-like statement language.

## Example

```bash
./yt-discover.py CHANNEL_URL --where '(title contains "interview" or title contains "discussion") and duration >= 900'
```

## Supported fields

- `title`
- `uploader`
- `duration`
- `date`
- `live`

## Boolean operators

- `and`
- `or`
- `not`

Parentheses can be used for grouping.

At this stage, `and` and `or` have equal precedence and are evaluated from left to right. Use parentheses when mixing them if the intended grouping matters.

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
