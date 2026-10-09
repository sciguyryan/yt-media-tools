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

## Parser benchmarks

The `parser` group covers simple, complex, collection-heavy and derived-relation workloads for the production hand-written parser.

Run the parser workloads with:

```bash
python benchmark.py parser
```

The `parser.lexing.*` targets measure tokenisation separately from the existing `parser.*` full-parse targets using the same four inputs. Compare the two stages before attributing parser time to regular expressions. Python caches compiled regex patterns, so explicit `re.compile()` changes require measured end-to-end benefits rather than compilation microbenchmarks alone.

Parser scaling is kept out of the normal timing suite. The `scaling` group covers accepted scalar-parenthesis depths 1, 32 and 128 together with corresponding unmatched-parenthesis rejection paths. Stable names begin with `parser.nested.*` and `parser.malformed_nested.*`. For example:

```bash
python benchmark.py parser.nested.depth_32 \
  parser.malformed_nested.depth_32
```

The `memory` group also exposes depth-1 and depth-32 parser measurements through `memory.parser.reference.nested.*`. These report peak Python allocations traced by `tracemalloc`.

The completed Lark and Tree-sitter comparison, including its local measurements and final decision, remains recorded in `docs/YT-SQL-PARSER-MIGRATION.md` and repository history.

## Cache-v4 reconciliation

The cache-v4 benchmark tools are retained as reproducible engineering evidence rather than as a release diary. They use deterministic profiles so storage and timing changes can be compared without depending on a developer's real cache.

`cache_v4_reconciliation.py` builds v4 databases directly and reports logical population, repeated-media deduplication, SQLite allocation and table/index storage. `cache_v4_migration_reconciliation.py` derives historical v3 shapes from the permanent fixture and measures the real v3-to-v4 path, including preflight sizing, phase timings, peak destination size, certification time and final storage. `cache_v4_runtime_reconciliation.py` exercises provider precedence, freshness fallback, retention and explicit compaction.

The standard profiles are `small`, `normal`, `large` and `huge`. Small and normal are suitable for quick comparisons; large and huge are opt-in local workloads and stay outside routine CI. Exact-size overrides are available where a benchmark supports them.

Typical runs are:

```bash
python benchmarks/cache_v4_reconciliation.py --profile normal
python benchmarks/cache_v4_migration_reconciliation.py --profile normal
python benchmarks/cache_v4_runtime_reconciliation.py --profile normal
```

Machine-readable JSON can be written with `--output` where supported. Migration benchmarking also preserves a source hash before and after the run so the benchmark itself verifies that the historical source remained unchanged.

Interpret storage numbers with SQLite's allocation model in mind. Deleting rows may create reusable pages without reducing the main file. WAL may contain committed pages that are not yet reflected in the main database size. The runtime benchmark therefore distinguishes WAL allocation from main-database freelist space, while explicit compaction checkpoints WAL where applicable and vacuums only when reusable main-database pages exist.

The issue #135 measurements established three useful baselines. Fresh-destination migration avoids the old copy-and-drop freelist growth; the current 500-row migration transaction bound and deferred source-entry index did not show a material reason to change; and provider resolution remained stable enough that a separate resolution cache would add semantic risk without measured benefit. These are measured implementation choices, not promises about every future workload, so the benchmark tools remain available for retuning.
