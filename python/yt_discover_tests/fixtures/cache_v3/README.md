# Canonical cache-v3 fixture

`canonical-valid-v3.sqlite3` is an immutable historical fixture for the cache-v3 migration contract. It was created with the Discover 0.29.17 `MetadataCache` writer API during issue #126. Do not regenerate it from a later cache implementation. If the fixture ever needs to change, add a new explicitly versioned fixture and explain why.

The database is intentionally small, but it is not meant to look tidy. Each awkward record exists because it preserves a v3 distinction that later migration code must not flatten.

## What is in it

`https://www.youtube.com/@fixture/videos` is a complete three-entry source. It has an observation, trusted newest-first entries, complete coverage, a frontier and three detailed metadata records. Its metadata includes Unicode, empty collections and strings, false Boolean and numeric values, SQL-relevant JSON `null` values, historical nested backend values and a fake format URL representing baggage that v3 retains inside `raw_json` but v4 does not preserve generically.

`shared-video` also appears under `https://www.youtube.com/@fixture/shorts`. The two detailed rows intentionally disagree on title, duration, view count, nested raw data and acquisition time. That is valid v3: detailed identity is `(source_url, video_id)`, not media identity alone.

`https://example.invalid/enumeration-only` has only a source observation. It has no source entries, coverage, frontier or detailed metadata. v3 can know that a source was observed without claiming a trusted ordering or cached details.

`https://example.invalid/partial` records an incomplete four-entry observation and coverage snapshot when only one detailed row is cached. A second detailed row is then acquired without rewriting coverage. Its stored `cached_entries` therefore remains `1` while the current detailed-row count is `2`. This is deliberate. v3 coverage stores a historical snapshot, not a live count.

## Things deliberately absent

This fixture predates the explicit validity-boundary tests and therefore keeps the questionable cases out of the canonical database itself. Part 3 classifies them with isolated mutations instead.

Malformed timestamps or metadata JSON, broken source ordering and a frontier that disagrees with its stored ordering are outside the structural contract. Row/JSON ID disagreement and negative counters remain structurally valid because v3 never established the stronger constraints that would make them invalid. Keeping those decisions in mutation tests avoids making the canonical fixture itself harder to read.

SHA-256: `d0d28d5c1f57d2b75026608999cfd398a4abd7e825cbac078ec86529c1012ae5`

## Semantic migration oracle

`canonical-valid-v3.oracle.json` records the fixture's source-side semantic facts without specifying a cache-v4 storage layout. `ORACLE.md` explains the boundary. The oracle is checked independently against this SQLite database so later migration work can rely on it without turning a proposed v4 representation into historical v3 truth.

## Permanent v4 migration expectation

`canonical-valid-v4-expected.json` is an independently authored semantic expectation for the v3-to-v4 transition. It deliberately describes stable identities and values rather than copying SQLite surrogate IDs or serialising the migration implementation's output. The historical migration suite compares the migrated database with this expectation so implementation and oracle cannot silently share the same transformation logic.

The permanent suite also mutates copies of the accepted v3 fixture into states the frozen v3 contract rejects, exercises interruption and restart-only behaviour after destination work has occurred, and audits the permanent JSON Lines migration log for historical payload material and representative sensitive values. These cases are regression evidence for the historical transition and should remain after v4 becomes the ordinary runtime schema.
