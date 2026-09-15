# Development changelog

This file records meaningful changes during active development. It is not release history. When a dot release is completed and accepted, relevant entries are reconciled into the root `CHANGELOG.md` and the completed development section is cleared or advanced for the next work item.

## Discover 0.29.x - Unreleased

- [feature] Add typed variadic `CONCAT()` scalar expressions with NULL propagation, constant folding and deterministic conformance coverage.
- [docs] Document `CONCAT()` semantics and optimisation behaviour for constructed textual projections.
- [cli] Add compact Rich benchmark result and baseline-comparison tables with stable benchmark names, Unicode presentation, ASCII and no-colour fallbacks, and terminal-width-aware rendering.
- [cli] Add `benchmark.py --compare` baseline lookup and actionable benchmark-dependency diagnostics while retaining pytest-benchmark as the measurement engine.
- [docs] Document the benchmark presentation, comparison and fallback conventions.
- [maintenance] Add shared yt-sql AST child discovery and depth-first traversal infrastructure, and use it for structural randomness discovery.
- [test] Add focused traversal tests covering stable child order, query traversal, semantic boundaries and scoped/case expressions.
- [test] Add the Phase 0 deterministic performance benchmark foundation using pytest-benchmark for statistical timing and separate tracemalloc allocation measurements.
- [test] Add parser, resolution, analysis, optimiser, scalar and collection evaluation, offline execution and scaling benchmark workloads based on deterministic generated data.
- [cli] Add a single `benchmark.py` entry point with named benchmark and group selection, `--list`, `--smoke` and `--all` execution.
- [docs] Add the performance testing and regression policy covering benchmark methodology, required execution, immutable baselines, CI boundaries and acceptance guidance.
