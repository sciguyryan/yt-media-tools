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

The `schema_version` value is the cache schema authority. A newly created cache is labelled `3`. Existing versions 1, 2 and 3 are accepted by the current opener. A non-integer version or any other integer fails closed.

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

`put_many()` accepts only records whose top-level `id` is a non-empty string. It serialises the complete record as compact UTF-8 JSON and assigns one UTC `fetched_at` to every accepted record in that call. Upserting the same `(source_url, video_id)` replaces both the timestamp and the complete JSON document.

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

A record is fresh only when every field required by the query is within its maximum age. For a `raw.*` requirement, freshness additionally requires every named dictionary segment to exist in the cached raw object. The value at the end of the path may itself be `null`; path presence, not truthiness, is what this check establishes.

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

## `raw.*` is cache-visible state

The complete decoded yt-dlp object is not merely an implementation backup. yt-sql can address nested backend values through `raw.*`, and cache freshness explicitly understands those paths. Consequently the raw JSON contains a mixture of query-visible state and backend material that no accepted query may care about.

Issue #126 should preserve that distinction in its fixtures. Deciding which raw material receives a v4 representation belongs to the later `raw.*` compatibility work, not to this historical audit.

## What this commit does not decide

This audit intentionally stops short of declaring every SQLite-readable row combination valid or invalid. The next fixture work needs to turn the implementation facts above into a machine-testable validity boundary.

In particular, we still need to classify malformed timestamps/JSON, disagreement between a row `video_id` and its JSON `id`, negative or inconsistent counters, duplicate/non-contiguous source indexes, cross-table source-kind disagreement and frontier/order disagreement. Some of those states are impossible through the public writer API but physically possible because v3 did not encode the rule in SQLite.

That is exactly why the fixture work follows the audit rather than preceding it.
