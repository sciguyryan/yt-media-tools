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
