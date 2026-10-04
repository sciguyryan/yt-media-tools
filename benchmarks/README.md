# yt-discover performance benchmarks

The benchmark suite measures deterministic local yt-sql and yt-discover execution paths. Statistical timing benchmarks use `pytest-benchmark`; Python allocation measurements use `tracemalloc` in separate tests so allocation instrumentation does not contaminate timing results. See `docs/PERFORMANCE.md` for the benchmark and regression policy.

Install the benchmark dependency alongside the normal test tooling:

```bash
python -m pip install -r requirements-benchmark.txt
```

`benchmark.py` is the public entry point for the suite. With no benchmark names it runs the normal timing suite and excludes the heavier scaling and memory workloads:

```bash
python benchmark.py
```

List the available groups and stable benchmark names with:

```bash
python benchmark.py --list
python benchmark.py --list --verbose
```

Run a complete group, several groups or an individual benchmark by name:

```bash
python benchmark.py parser
python benchmark.py parser analysis optimiser
python benchmark.py parser.simple
python benchmark.py cache.lookup.1000
```

Run the entire registered suite, including scaling, memory and stress benchmarks, with:

```bash
python benchmark.py --all
```

Save a named pytest-benchmark timing baseline and optional JSON result with:

```bash
python benchmark.py --save-baseline discover-baseline --benchmark-json benchmark-results.json
```

The baseline options apply to statistical timing benchmarks. Memory benchmarks remain separately instrumented because allocation tracing would distort canonical timing results. Timing comparisons are advisory and must be interpreted according to `docs/PERFORMANCE.md`; shared CI timing is not an acceptance gate.

Compare the current timing results with a saved baseline through the same entry point:

```bash
python benchmark.py --compare discover-baseline
```

The default console output is a compact terminal-width-aware Rich table using Unicode box drawing and restrained colour. Use `--ascii` for ASCII borders, `--no-colour` to disable colour, and `--verbose` for additional timing statistics. The complete pytest-benchmark data remains available through saved baselines and `--benchmark-json`.

CI uses the same public entry point with `python benchmark.py --smoke`. This verifies the normal benchmark machinery with minimal timing rounds without treating shared-runner timings as performance evidence.

Benchmark JSON and local `.benchmarks/` storage are generated artefacts and must not be committed as canonical source. Release or programme baselines should be retained explicitly as benchmark artefacts when required rather than being silently replaced by later runs.

## Relational reconciliation

The `relational` group covers deterministic in-memory JOIN execution across one-to-one, one-to-many, no-match and highly asymmetric relation sizes, together with compound equality and SEMI execution. Individual surfaces use stable names such as `relational.join.one_to_one`, `relational.join.compound_equality`, `relational.join.semi` and `relational.planning.join_acquisition`.

Run the complete relational group with:

```bash
python benchmark.py relational
```

## Cache-v4 reconciliation measurements

Issue #135 uses `benchmarks/cache_v4_reconciliation.py` for deterministic cache-shape and physical-storage measurements that do not belong in the statistical timing suite. The harness generates controlled source overlap, representative registered scalar and collection metadata, and machine-readable SQLite page, freelist, table and index measurements. Its `small`, `normal`, `large` and `huge` profiles are deterministic; `--media-count` supports an exact local size. Large and huge profiles are opt-in and are not part of routine pytest or CI.

Run the normal profile without retaining its generated database:

```bash
python benchmarks/cache_v4_reconciliation.py --profile normal --json cache-v4-normal.json
```

Retain a generated database for independent inspection with:

```bash
python benchmarks/cache_v4_reconciliation.py --profile large --database /tmp/cache-v4-large.sqlite3 --json /tmp/cache-v4-large.json
```

Use `--sources` and `--overlap-percent` to measure repeated-media deduplication under different source shapes. Benchmark JSON and generated databases are local measurement artefacts and must not be treated as canonical source files.

### Migration reconciliation

`benchmarks/cache_v4_migration_reconciliation.py` exercises the production v3-to-v4 migration against deterministic shapes derived from the permanent historical v3 fixture. It records the composition-aware preflight estimate, total migration time, structured phase timings, the largest destination size observed at migration stage boundaries, final page and freelist usage, and the size after an observational `VACUUM`. The source hash is recorded before and after migration so benchmark runs also prove source immutability.

Run the normal migration profile with:

```bash
python benchmarks/cache_v4_migration_reconciliation.py --profile normal --output /tmp/cache-v4-migration-normal.json
```

Use `--additional-records` for an exact deterministic metadata-record count. `--keep-database` retains the compacted generated v4 destination for independent inspection. The benchmark never changes production migration compaction behaviour: its `VACUUM` runs only against the generated benchmark destination after the real migration has completed, so Part 2 can measure reclaimable space before deciding whether production migration should prevent churn or compact explicitly.

The `large` and `huge` profiles remain opt-in local workloads and are excluded from routine pytest and CI. Compare `preflight_required_bytes` with `peak_observed_file_bytes` when evaluating disk-space safety, and compare `before_compaction.freelist_bytes` with `after_compaction.file_bytes` when evaluating transient migration churn. Stage-boundary peak measurement is deliberately conservative in what it claims: it observes sizes when structured migration events are emitted rather than sampling the database continuously.

### Migration churn attribution

Part 3 extends the migration reconciliation output with `stage_storage`, recording SQLite file, live-page and freelist measurements at structured migration boundaries. Measurements on the deterministic profiles showed that the former copy-then-drop strategy accumulated reclaimable space when the copied v3 runtime tables were removed. Population and deferred-index construction were not the source of the persistent freelist.

The production v3-to-v4 transition therefore now creates a fresh v4 destination and reads the protected v3 source separately. Historical source-state rows and detailed metadata are copied semantically into the v4 representation rather than copying legacy SQLite pages into the destination and dropping them later. The destination retains the established schema-v3/incomplete marker until target certification and finalisation, preserving restart-only and cut-over safety semantics.

The migration benchmark continues to run an observational `VACUUM` after migration. With the fresh-destination strategy, final freelist usage should be zero; any remaining file-size difference after `VACUUM` is SQLite page-layout compaction rather than legacy-table reclamation. This evidence does not justify adding production `VACUUM` behaviour.
