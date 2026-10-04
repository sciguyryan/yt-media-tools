# yt-discover cache v3 contract

This document freezes the cache-v3 contract as implemented by Discover 0.29.17. It is a historical description for migration work, not a proposal for cache v4 and not an invitation to tidy v3 before migrating it.

The distinction matters. Cache v3 has a small SQLite schema and rather more meaning in the Python code around it. A database can satisfy SQLite's column and primary-key constraints while containing combinations that the `MetadataCache` API would never write. Later migration code needs to know both layers instead of quietly treating "SQLite opened it" as the whole validity rule.

This is the first pass over that contract. Issue #126 will add immutable valid and invalid historical fixtures in later commits.

## Opening a v3 cache

`MetadataCache.open()` creates the parent directory, opens SQLite and enables foreign-key enforcement, WAL journal mode and `synchronous=NORMAL`. v3 itself defines no foreign keys, so `PRAGMA foreign_keys = ON` does not add relationships between the cache tables.

`cache_meta` is created first:

```text
cache_meta(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
```

The `schema_version` value is the cache schema authority. A newly created cache is labelled `3`. The current opener recognises existing versions 1, 2 and 3. A non-integer version or any other integer fails closed.

Opening versions 1 or 2 is an in-place migration to v3. Missing current tables and indexes are created. The migration may seed `source_frontiers`, but only for a source whose positive `source_observations.observed_entries` exactly equals the number of persisted `source_entries`. Its head is the lowest `source_index`, its verification time is inherited from the observation and `overlap_confirmations` starts at zero. This cardinality check is intentional: a partial historical ordering is not promoted into a trusted frontier. The schema version is then changed to 3.

## Detailed metadata

The authoritative detailed cache table is:

```text
metadata_records(
    source_url TEXT NOT NULL,
    video_id TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    PRIMARY KEY (source_url, video_id)
)
```

with an additional index on `video_id`.

Identity in this table is source scoped. The same media ID seen through two source URLs is two independent rows and may contain two complete copies of the same extractor response.

`put_many()` writes only records whose top-level `id` is a non-empty string. It serialises the complete record as compact UTF-8 JSON and assigns one UTC `fetched_at` to every record written in that call. Upserting the same `(source_url, video_id)` replaces both the timestamp and the complete JSON document.

There is no SQL constraint requiring the JSON document's `id` to equal the row's `video_id`. The cache API creates that relationship by deriving `video_id` from `record['id']`. This is an example of an API invariant that later structural-validity work needs to make explicit.

Reads are deliberately tolerant of some bad physical rows. A detailed row is ignored by `get_many()`/`source_records()` if `fetched_at` cannot be parsed, `raw_json` cannot be decoded, or the decoded JSON is not an object. A timezone-naive parseable timestamp is interpreted as UTC. This tolerance does not by itself make an undecodable row a valid v3 state; issue #126 still needs to classify such rows when it defines structural validity.

### Freshness

There is one acquisition timestamp for the complete detailed record. Field-aware freshness is derived from that timestamp rather than stored independently.

The v3 defaults are:

| Field | Maximum age |
| --- | --- |
| `id`, `upload_date`, `release_timestamp`, `timestamp`, `channel_id`, `uploader_id` | 3650 days |
| `duration`, `webpage_url` | 30 days |
| `title`, `uploader`, `channel` | 7 days |
| `modified_timestamp` | 1 day |
| `view_count`, `like_count`, `comment_count`, `channel_follower_count` | 6 hours |
| `availability`, `live_status`, `is_live`, `was_live` | 1 hour |
| other/dynamic fields | 1 day |

The aliases `views`, `likes`, `comments`, `date` and `url` share the policy of their canonical fields.

A record is fresh only when every field required by the query is within its maximum age. Historically, a `raw.*` requirement additionally required every named dictionary segment to exist in the cached raw object. The value at the end of the path could itself be `null`; path presence, not truthiness, was what this check established. Issue #142 removed that unused language surface before release, but the rule remains part of the frozen v3 behavioural record.

When one required field is stale, normal online acquisition refreshes the complete authoritative yt-dlp record rather than updating one field in isolation. Offline mode can still use stale cached values because it forbids network refresh and reports that limitation separately.

## Source observations and ordering

v3 stores source knowledge separately from detailed metadata. None of these tables has a foreign key to `metadata_records` or to another source-state table.

An observation is telemetry, not a completeness claim:

```text
source_observations(
    source_url TEXT PRIMARY KEY,
    source_kind TEXT NOT NULL,
    last_observed_at TEXT NOT NULL,
    observed_entries INTEGER NOT NULL DEFAULT 0
)
```

`record_source_observation()` replaces the current observation for a source. Recording an observation alone does not create a frontier.

A trusted complete newest-first ordering is stored in:

```text
source_entries(
    source_url TEXT NOT NULL,
    video_id TEXT NOT NULL,
    source_index INTEGER NOT NULL,
    observed_at TEXT NOT NULL,
    PRIMARY KEY (source_url, video_id)
)
```

with an index on `(source_url, source_index)`.

`record_source_entries()` deletes the previous ordering for that source and replaces it transactionally. It numbers non-empty IDs from one in caller order. Its API contract is stronger than the SQL schema: callers are required to use it only for a complete trusted source view, not a bounded or otherwise partial scan. Replacement is intentional so media absent from a later complete view cannot survive as phantom members.

The table does not declare `source_index` unique within a source, positive, or contiguous. Those properties arise from the writer. Later validity work should not infer stronger historical SQL constraints than v3 actually had.

## Coverage is a recorded snapshot

Coverage is stored independently:

```text
source_coverage(
    source_url TEXT PRIMARY KEY,
    source_kind TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    observed_entries INTEGER NOT NULL,
    cached_entries INTEGER NOT NULL,
    complete INTEGER NOT NULL,
    reason TEXT NOT NULL
)
```

`record_source_coverage()` calculates `cached_entries` from the number of detailed `metadata_records` for the source at the moment coverage is recorded. It stores `complete` as 0 or 1 and keeps the caller's human-readable reason.

`cached_entries` is therefore historical snapshot data. It is not recomputed when detailed rows later change. Migration must not reinterpret it as a live count.

The application records complete coverage only after paths that establish a complete source observation with detailed metadata for every relevant observed entry. Bounded, filtered, enumeration-only or otherwise incomplete acquisition records incomplete coverage with an explanatory reason.

## A frontier is stronger than an observation

The incremental frontier is:

```text
source_frontiers(
    source_url TEXT PRIMARY KEY,
    source_kind TEXT NOT NULL,
    verified_at TEXT NOT NULL,
    known_entries INTEGER NOT NULL,
    head_video_id TEXT NOT NULL,
    overlap_confirmations INTEGER NOT NULL
)
```

`record_source_frontier()` receives a trusted newest-first ID sequence. An empty sequence removes the frontier. Otherwise `known_entries` is the number of non-empty IDs supplied and `head_video_id` is the first one. The frontier record does not itself store the rest of the ordering; `source_entries` carries that separately.

The normal application writes source entries and a frontier together only when it has established a complete source ordering under the current acquisition rules. A plain source observation never implies a frontier. This distinction also explains the conservative v1/v2 migration rule described above.

Again, SQLite does not enforce cross-table agreement. A frontier row can physically exist without matching source entries or an observation. Whether such combinations are structurally valid v3 is a contract question for the fixture/validity phases of issue #126, not something to repair silently in this audit commit.

## Specialised providers are not persisted here

The v3 persistent detailed cache is an authoritative yt-dlp JSON cache. Specialised YouTube.js and ytmusicapi acquisitions may supply exact scalar metadata to a query, but those specialised results are not written as independent persistent provider observations in v3.

That absence is part of the historical contract. A v3 migration cannot recover provider-owned observations that v3 never stored.

## `raw.*` was cache-visible v3 state

At the time this historical contract was frozen, the complete decoded yt-dlp object was not merely an implementation backup. yt-sql could address nested backend values through `raw.*`, and cache freshness understood those paths. Consequently the raw JSON mixed then-query-visible state with backend material that had no established query use.

The fixtures preserve that distinction as historical evidence. The later compatibility work initially retained unresolved material conservatively, but issue #142 resolved the pre-release language decision by removing unused `raw.*` support. The final v4 migration reconstructs supported registered facts and deliberately discards arbitrary unregistered remainder.

## Structural validity boundary

The historical validator used by issue #126 is intentionally narrower than a new runtime cache checker. It exists in the test suite so later migration work has a stable source contract without changing normal v3 opening behaviour.

A structurally valid v3 database has the v3 table/column and required-index shape, one `schema_version=3` authority row, parseable stored timestamps and detailed metadata whose `raw_json` decodes to a JSON object. A stored source ordering uses one contiguous one-based `source_index` sequence. Where a frontier exists, it summarises that stored ordering: the ordering exists, `known_entries` is its cardinality and `head_video_id` is its first entry.

The boundary is deliberately not stricter than the historical representation earns. In particular, v3 never constrained counters to non-negative values and never required a row's `video_id` to equal the top-level `id` inside `raw_json`. The validator therefore does not reject those states. Coverage counts remain historical snapshots and are not checked against current metadata counts. Observations are telemetry and need not imply entries, coverage or a frontier.

Invalid test cases are produced as isolated mutations of the canonical fixture. Each mutation is expected to break one named invariant, which makes the reason for rejection reviewable instead of hiding it in an opaque collection of damaged databases.

## Migration oracle

The canonical valid fixture has a versioned semantic companion at `yt_discover_tests/fixtures/cache_v3/canonical-valid-v3.oracle.json`. It freezes the source-side facts later migration code must account for without describing an expected v4 database.

That separation is deliberate. Issue #126 can state that source-scoped detailed identity, acquisition times, source observations, trusted ordering, historical coverage snapshots and frontier state have established v3 meaning. It cannot yet state which v4 table, provider row or entity relationship should represent them. Those choices belong to the v4 registry and storage work.

The oracle records that nested raw paths were query-visible in v3 while the same stored JSON contained backend material with no established query use. Known examples remain visible as historical evidence, but the final pre-release decision is now explicit: issue #142 removed `raw.*`, supported registered facts migrate, and arbitrary unregistered remainder has no v4 representation. Specialised YouTube.js and ytmusicapi observations are separately recorded as unrecoverable because v3 never persisted them.

Tests derive the corresponding facts directly from the immutable SQLite fixture and compare them with the JSON oracle. A later cache change therefore cannot quietly rewrite either the historical fixture or the story told about it. The oracle has its own format version so an incompatible change to the oracle itself must be deliberate.
