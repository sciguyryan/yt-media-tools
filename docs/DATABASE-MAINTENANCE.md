# SQLite maintenance policy (#157)

Part 1 established a shared read-only policy and measurement foundation for Downloader's collection-state database and Discover's metadata cache. Part 2 adds bounded post-operation incremental vacuuming for Downloader. WAL checkpointing and statistics optimisation remain reserved for later parts of #157.

The optional user policy is `~/.config/yt-media-tools/database-maintenance.toml` on XDG-compatible systems, or under an absolute `XDG_CONFIG_HOME` when configured. The module exposes `default_config_path()` so platform-specific integration can be completed alongside the application CLI integration. An absent default policy uses conservative provisional values. An explicitly supplied missing policy, malformed TOML, unknown keys, unsupported version or automatic full vacuum setting fails validation.

The accepted strategy is post-operation hybrid maintenance, with bounded incremental vacuuming where supported and full vacuum requiring a distinct manual administrative action. No automatic full vacuum is supported. The default threshold values and page budget are provisional until Part 4 benchmarking.

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

Parts 3 and 4 will add explicit manual full vacuum and ancillary maintenance, then complete integration and measured default calibration.

## Part 2: bounded post-operation incremental vacuum

`incremental_maintenance()` now performs an opportunistic, database-scoped maintenance pass. It checks eligibility under a non-blocking advisory maintenance lock, opens only an existing database, and uses zero SQLite busy timeout. Contention defers maintenance rather than delaying user work. Each incremental vacuum statement requests one page, with the configured page and elapsed-time budgets checked between statements. SQLite may take longer than the elapsed-time budget to complete an individual statement; the budget is not a hard execution deadline.

Downloader invokes this pass after collection processing, completion reconciliation and any run-manifest output, outside the collection-specific lock. The original download exit status remains authoritative. New collection-state databases select `auto_vacuum=INCREMENTAL` before creating application tables. Existing collection-state databases retain their existing mode and are not converted automatically. Discover's metadata cache can use the shared maintenance engine, but its invocation-level integration and new-database mode policy remain for Part 4, after the existing managed-cache lifecycle is audited.

The advisory lock serialises cooperating maintenance processes, not all SQLite clients. SQLite's own locking prevents conflicting writes, and a busy database causes deferral. Automatic full vacuum, WAL checkpointing, statistics optimisation and existing-database conversion are not implemented in Part 2.
