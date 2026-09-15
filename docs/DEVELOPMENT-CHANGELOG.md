# Development changelog

This file records meaningful changes during active development. It is not release history. When a dot release is completed and accepted, relevant entries are reconciled into the root `CHANGELOG.md` and the completed development section is cleared or advanced for the next work item.

## Downloader 1.19.x - Unreleased

- [feature] Add `--remove-completed-rows` for annotated file-backed queues whose first whitespace-delimited field is the download target.
- [maintenance] Preserve the exact-line semantics of `--remove-completed-ids` while sharing archive reconciliation and queue reporting with annotated-row removal.
- [test] Add deterministic annotated-row parsing, atomic removal, archive reconciliation and command-planning coverage.

## Discover 0.29.x - Unreleased

- [maintenance] Replace frozen-dataclass evaluation contexts with a compact slots-based read-only representation to reduce hot-path construction and collection-binding overhead without changing evaluator semantics.
- [test] Verify evaluation-context public state remains read-only alongside existing lexical binding and evaluator coverage.
- [maintenance] Keep compatibility coercion at the public expression-evaluator boundary so recursive scalar and Boolean evaluation stays on the normalised explicit-context fast path.
- [test] Preserve explicit evaluation-context semantics while preparing the evaluator hot path for direct Phase 5 performance comparison.
- [maintenance] Introduce an explicit expression evaluation context that owns the current metadata record and lexical collection-element bindings.
- [maintenance] Route recursive scalar and Boolean evaluation through immutable child contexts while preserving the established evaluator entry points and yt-sql semantics.
- [test] Add focused coverage for context immutability, lexical collection binding distance and direct scalar and Boolean evaluation through explicit contexts.
- [maintenance] Introduce explicit semantic relation scope, field ownership and logical row identity foundations without changing the current single-relation query grammar.
- [maintenance] Route query-body source and CTE schema selection through relation bindings so future relational resolution does not depend on anonymous schema selection.
- [test] Add focused coverage for relation identity, CTE binding, field ownership, ambiguity and logical row identity.

- [maintenance] Batch source-scoped detailed metadata cache reads into bounded set-oriented SQLite queries instead of issuing one query per candidate ID.
- [test] Add deterministic cache batching coverage, including source isolation, bounded query counts and malformed or missing records.
- [maintenance] Reuse one top-level query property analysis across metadata, LIMIT and cost planning instead of deriving the same semantic facts repeatedly.
- [maintenance] Reuse expression-property results within one query analysis for projection, ordering and predicate derivations.
- [test] Add focused planning-analysis reuse coverage while preserving the existing public planning helper behaviour.
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
