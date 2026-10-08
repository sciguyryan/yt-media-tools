# SQLite maintenance policy (#157)

The shared maintenance module provides SQLite measurement, policy validation, bounded post-operation incremental vacuuming, explicit full vacuum, WAL checkpointing and statistics optimisation for Discover and Downloader.

The optional user policy is `~/.config/yt-media-tools/database-maintenance.toml` on XDG-compatible systems, or under an absolute `XDG_CONFIG_HOME` when configured. The module exposes `default_config_path()` so platform-specific integration can be completed alongside the application CLI integration. An absent default policy uses conservative provisional values. An explicitly supplied missing policy, malformed TOML, unknown keys, unsupported version or automatic full vacuum setting fails validation.

The accepted strategy is post-operation hybrid maintenance, with bounded incremental vacuuming where supported and full vacuum requiring a distinct manual administrative action. No automatic full vacuum is supported. The default threshold values and page budget remain provisional until representative production-shaped benchmarking supports calibration.

Example configuration:

```toml
schema_version = 1

[maintenance]
enabled = true
trigger = "post-operation"
strategy = "hybrid"

[maintenance.incremental]
enabled = true
max_pages_per_run = 4096
max_duration_seconds = 2

[maintenance.full]
automatic = false

[databases.collection_state]
min_reclaimable_mib = 32
min_free_ratio = 0.25

[databases.metadata_cache]
min_reclaimable_mib = 512
min_free_ratio = 0.30
```

The `inspect_database()` and `dry_run()` APIs open existing SQLite files read-only and never create or modify them. Measurements include SQLite page count, free-list pages, page size, vacuum mode, main-file size and WAL-file size. The free-list estimate is not a guarantee of filesystem space reclaimed. A positive dry-run decision describes *potential* eligibility based on measurements only, not permission to execute: cross-process idleness, locking, disk-space and runtime budgets have not yet been evaluated. Existing databases in `NONE` or `FULL` vacuum modes are not converted automatically.

The dry-run API reports storage eligibility only; it does not establish that the database is idle or that maintenance will obtain the required locks.

## Part 2: bounded post-operation incremental vacuum

`incremental_maintenance()` now performs an opportunistic, database-scoped maintenance pass. It checks eligibility under a non-blocking advisory maintenance lock, opens only an existing database, and uses zero SQLite busy timeout. Contention defers maintenance rather than delaying user work. Each incremental vacuum statement requests one page, with the configured page and elapsed-time budgets checked between statements. SQLite may take longer than the elapsed-time budget to complete an individual statement; the budget is not a hard execution deadline.

Downloader invokes this pass after collection processing, completion reconciliation and any run-manifest output, outside the collection-specific lock. The original download exit status remains authoritative. New collection-state databases select `auto_vacuum=INCREMENTAL` before creating application tables. Existing collection-state databases retain their existing mode and are not converted automatically. Discover also invokes the shared maintenance engine after its main operation, using the resolved cache path.

The advisory lock serialises cooperating maintenance processes, not all SQLite clients. SQLite's own locking prevents conflicting writes, and a busy database causes deferral. Automatic full vacuum and existing-database conversion are not supported. WAL checkpointing and statistics optimisation are available as explicit shared operations.

## Part 3: explicit full vacuum and shared compaction

Discover's existing `--cache-compact` command retains its explicit semantics and now invokes the shared `manual_full_vacuum()` implementation. `cache_compaction.py` is a compatibility import surface only; there is no second compaction engine. The shared executor uses the same database-scoped advisory lock as incremental maintenance, refuses active transactions, uses a zero SQLite busy timeout, checks available disk space conservatively before a full rebuild, and attempts a TRUNCATE checkpoint for WAL databases. Full vacuum is never invoked by the automatic post-operation path. Existing SQLite vacuum modes are preserved without implicit conversion.

`checkpoint_wal()` and `optimise_statistics()` are separate shared operations. Checkpointing is skipped for non-WAL databases, and `PRAGMA optimize` is delegated to the installed SQLite library. Automatic scheduling for WAL checkpointing and statistics optimisation remains outside the current implementation. Preflight estimates are conservative but cannot guarantee against external disk consumption or every SQLite temporary-file configuration. Full vacuum is not time-bounded. Existing callers of `cache_compaction.compact_cache()` continue to use the shared implementation through a compatibility alias.

## Part 4: Discover lifecycle integration and measurement

Discover now evaluates bounded incremental maintenance after the main invocation has returned, including unsuccessful runs where a metadata cache was successfully opened. The resolved cache path is captured at the actual cache-open boundary, so the maintenance hook does not repeat managed-cache discovery, migrations or explicit-file resolution. Early commands that do not open the cache, including cache status and manual compaction, do not schedule automatic maintenance. The original invocation status remains authoritative; maintenance deferral is advisory.

Freshly initialised v4 metadata caches select `auto_vacuum=INCREMENTAL` before schema creation. Existing databases, including migrated databases, retain their previous vacuum mode. Explicit `--cache-compact` remains the manual full-vacuum interface and continues to use the single shared implementation. `cache_compaction.py` remains a compatibility import rather than a second executor. Downloader continues to reclaim only after collection work is complete.

A deterministic, disposable SQLite reclamation microbenchmark is available as `PYTHONPATH=. python benchmarks/sqlite_maintenance.py --rows 10000`. It reports initial and final file size, free pages, reclaimed pages and elapsed time. This is a synthetic page-reclamation benchmark, not a representative measurement of Discover's provider-heavy metadata schema or production concurrency. The 32 MiB collection-state and 512 MiB metadata-cache thresholds remain conservative provisional values pending real-world workload measurements; no performance claim or threshold calibration is inferred from the microbenchmark alone.

The current shared status and dry-run API remains programmatic. Discover's existing `--cache-status` retains its established JSON and text contracts; the separate policy eligibility fields have not been added to those formats. WAL checkpoint and statistics optimisation helpers remain explicit rather than automatically scheduled. The maintenance lock serialises cooperating maintenance workers, while SQLite itself governs conflicts with unrelated readers and writers. No hard elapsed-time guarantee exists inside a SQLite statement.
