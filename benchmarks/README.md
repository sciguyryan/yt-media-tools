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

## Parser comparison

The `parser` group contains matching simple, complex, collection-heavy and derived-relation workloads for the production hand-written parser and the experimental Lark parser. The experimental Lark surfaces use stable `parser.lark.*` names and remain advisory until parser migration is decided.

Run both parser implementations with:

```bash
python benchmark.py parser
```

The optional Tree-sitter feasibility package adds matching `parser.tree_sitter.*` surfaces, including `parser.tree_sitter.derived` for grammar revision 2. These measure raw parsing, including UTF-8 encoding at the Python boundary, but exclude query-model construction that has not yet been implemented. Build the committed generated source and run the directly comparable targets with:

```bash
python -m pip install tree-sitter==0.26.0
python -m pip install --no-deps experiments/tree-sitter-yt-sql
python benchmark.py parser.simple parser.complex parser.collection parser.derived \
  parser.tree_sitter.simple parser.tree_sitter.complex \
  parser.tree_sitter.collection parser.tree_sitter.derived
```

An environment without the optional binding skips the Tree-sitter benchmark cases. Raw feasibility timings are evidence about whether continued implementation is worthwhile, not evidence of end-to-end parser parity.

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
