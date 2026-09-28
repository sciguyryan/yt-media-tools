# Canonical cache-v3 fixture

`canonical-valid-v3.sqlite3` is an immutable historical fixture for the cache-v3 migration contract. It was created with the accepted Discover 0.29.17 `MetadataCache` writer API during issue #126. Do not regenerate it from a later cache implementation. If the fixture ever needs to change, add a new explicitly versioned fixture and explain why.

The database is intentionally small, but it is not meant to look tidy. Each awkward record exists because it preserves a v3 distinction that later migration code must not flatten.

## What is in it

`https://www.youtube.com/@fixture/videos` is a complete three-entry source. It has an observation, trusted newest-first entries, complete coverage, a frontier and three detailed metadata records. Its metadata includes Unicode, empty collections and strings, false Boolean and numeric values, SQL-relevant JSON `null` values, nested `raw.*` paths and a fake format URL representing backend material that v3 retains inside `raw_json`.

`shared-video` also appears under `https://www.youtube.com/@fixture/shorts`. The two detailed rows intentionally disagree on title, duration, view count, nested raw data and acquisition time. That is valid v3: detailed identity is `(source_url, video_id)`, not media identity alone.

`https://example.invalid/enumeration-only` has only a source observation. It has no source entries, coverage, frontier or detailed metadata. v3 can know that a source was observed without claiming a trusted ordering or cached details.

`https://example.invalid/partial` records an incomplete four-entry observation and coverage snapshot when only one detailed row is cached. A second detailed row is then acquired without rewriting coverage. Its stored `cached_entries` therefore remains `1` while the current detailed-row count is `2`. This is deliberate. v3 coverage stores a historical snapshot, not a live count.

## Things deliberately absent

This fixture does not settle the validity of states that Part 1 left open. It therefore contains no malformed timestamp or JSON, row/JSON ID disagreement, negative counters, duplicate or non-contiguous source indexes, source-kind disagreement, or contradictory frontier/order state.

Those cases belong to the explicit validity-boundary work rather than being smuggled into the canonical valid corpus because SQLite happens to permit them.

SHA-256: `d0d28d5c1f57d2b75026608999cfd398a4abd7e825cbac078ec86529c1012ae5`
