# yt-discover performance benchmarks

The benchmark suite measures deterministic local yt-sql and yt-discover execution paths. Statistical timing benchmarks use `pytest-benchmark`; Python allocation measurements use `tracemalloc` in separate tests so allocation instrumentation does not contaminate timing results. See `docs/PERFORMANCE.md` for the benchmark and regression policy.

Install the benchmark dependency alongside the normal test tooling:

```bash
python -m pip install pytest pytest-benchmark
```

Run the routine statistical benchmark set with:

```bash
python -m pytest benchmarks/test_query_pipeline_benchmarks.py --benchmark-only
```

Save a named baseline and full JSON result with:

```bash
python -m pytest benchmarks/test_query_pipeline_benchmarks.py --benchmark-only --benchmark-save=discover-baseline --benchmark-json=benchmark-results.json
```

Compare a later run with a saved result using `--benchmark-compare` or the `pytest-benchmark compare` command. Timing comparisons are advisory and must be interpreted according to `docs/PERFORMANCE.md`; shared CI timing is not an acceptance gate.

Scaling benchmarks are opt-in:

```bash
python -m pytest benchmarks/test_scaling_benchmarks.py -m scale --benchmark-only
```

Python allocation benchmarks are also opt-in and intentionally do not use the timing fixture:

```bash
python -m pytest benchmarks/test_memory_benchmarks.py -m memory
```

Benchmark JSON and local `.benchmarks/` storage are generated artefacts and must not be committed as canonical source. Release or programme baselines should be retained explicitly as benchmark artefacts when required rather than being silently replaced by later runs.
