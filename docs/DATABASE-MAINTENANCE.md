# SQLite maintenance policy (#157)

Part 1 establishes a shared read-only policy and measurement foundation for Downloader's collection-state database and Discover's metadata cache. It does not schedule, execute or coordinate vacuuming, WAL checkpointing or statistics optimisation. Those behaviours are reserved for later parts of #157.

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

Parts 2 through 4 will introduce safe coordination and incremental execution, explicit manual full vacuum and ancillary maintenance, then application integration and measured default calibration.
