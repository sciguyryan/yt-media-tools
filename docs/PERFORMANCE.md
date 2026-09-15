# Performance testing and regression policy

This document defines the performance-testing strategy for yt-discover and yt-sql. It describes the execution surfaces that should be measured, the reasons for measuring them, the methodology used to obtain comparable results, and the guidance used when deciding whether an observed performance change is acceptable.

Performance testing complements functional, conformance and differential testing. Functional correctness remains the primary requirement: a faster implementation is not an improvement if it changes observable yt-sql semantics, weakens acquisition correctness, changes deterministic behaviour where determinism is promised, or otherwise violates an established language or execution invariant.

The benchmark suite is intended to remain useful as the implementation evolves. It should therefore measure stable architectural and behavioural surfaces rather than being coupled unnecessarily to one implementation.

## Objectives

Performance testing has several related objectives:

- Establish reproducible performance characteristics for important yt-sql and yt-discover execution paths.
- Detect material time, throughput, allocation and memory regressions introduced by implementation changes.
- Detect adverse changes in algorithmic scaling that may not be obvious from small workloads.
- Provide evidence that an optimisation improves the workload it is intended to improve.
- Demonstrate that behaviour-preserving refactors remain reasonably performance-neutral unless a documented trade-off is justified.
- Allow parser, resolver, evaluator, optimiser, planner, cache and related architectural alternatives to be compared empirically.
- Preserve historical baselines so cumulative regressions cannot be hidden by a sequence of individually small changes.

Performance results are evidence rather than an automatic substitute for engineering judgement. Statistical timing measurements are affected by the execution environment, while the significance of a regression depends on the frequency and importance of the affected operation.

## Benchmark principles

Canonical benchmarks must be deterministic in the work they perform. Given the same benchmark version, dataset-generator version, seed, workload size and relevant configuration, a benchmark should exercise the same logical input and operations.

Network performance is excluded from canonical benchmarks. Remote yt-dlp acquisition depends on network conditions, remote service behaviour, throttling, extractor changes and other factors outside the implementation being measured. Acquisition-related benchmarks should use deterministic local data, controlled test doubles or other reproducible boundaries where the purpose is to measure yt-discover rather than the network or a remote service.

Timing and memory-allocation measurements should normally be collected separately. Instrumentation such as `tracemalloc` can materially affect execution time and must not contaminate canonical timing results.

Benchmarks must not weaken or bypass normal semantics merely to obtain a more favourable result. Optimised and unoptimised execution must remain observationally equivalent wherever the optimisation strategy requires equivalence.

## Measured surfaces

The benchmark suite should cover the principal execution stages that can materially affect yt-sql and yt-discover performance.

### Parsing

Parser benchmarks measure query parsing time, throughput and memory behaviour across simple queries, representative real queries, complex expressions, deeply nested expressions, large compound queries and parser-torture inputs.

Parser performance matters because every textual yt-sql query passes through this stage. Parser benchmarks are also required when evaluating alternative parser architectures so architectural decisions can be based on measured cost rather than implementation preference alone.

### Semantic resolution

Resolution benchmarks measure the cost of resolving fields, types, scopes, structured access, collection bindings, CTEs, compound queries and other semantic structures.

Resolution is measured separately from parsing so changes to semantic modelling can be evaluated independently and so increasing language complexity does not conceal unexpectedly expensive resolution behaviour.

### Query and expression analysis

Analysis benchmarks measure property derivation such as required fields, aggregate characteristics, volatility, type information, metadata requirements and other information derived from resolved expressions and queries.

These benchmarks are particularly important where several planner or optimiser stages require overlapping information. They help identify repeated traversal, redundant derivation and changes in the scaling behaviour of semantic analysis.

### Optimisation

Optimiser benchmarks measure the cost of transforming resolved queries and expressions, including predicate simplification, scalar constant folding, temporal reasoning, requirement analysis, collection expressions, CTEs and compound queries.

Optimisation must remain conservative and semantics-preserving. Performance improvements produced by the optimiser should therefore be considered alongside the cost of performing the optimisation itself and the differential tests that establish observational equivalence.

### Planning

Planning benchmarks measure metadata-requirement planning, source-boundary planning, physical acquisition planning and other planner work that can be exercised without depending on uncontrolled remote acquisition.

These benchmarks help identify repeated analysis or requirement construction and provide a baseline for future relational and multi-backend planning work.

### Scalar evaluation

Scalar evaluation benchmarks measure execution time and throughput over deterministic records for representative arithmetic, comparison, Boolean, function, temporal, structured-value and other scalar expressions.

Because scalar evaluation may occur once or many times per candidate row, relatively small per-evaluation regressions can become material on large datasets. Workloads should therefore include both microbenchmarks and realistic multi-row evaluation.

### Collection evaluation

Collection benchmarks measure operations including `ANY`, `ALL`, `CARDINALITY`, scoped `COUNT`, `FILTER` and `MAP`, together with nested and composed collection expressions.

Measurements should include execution time, throughput and allocation behaviour. Workloads should vary collection cardinality and pipeline depth so temporary materialisation, repeated traversal and lexical-binding costs can be observed rather than inferred.

### Cache access

Cache benchmarks measure lookup and update paths independently of remote acquisition. Workloads should include individual keys and increasingly large known sets of candidate IDs, together with representative cached, stale and absent records.

Where possible, deterministic structural measurements such as the number of SQLite operations should accompany timing measurements. A bounded set-oriented cache operation is a stronger regression property than a timing threshold alone.

### End-to-end offline execution

End-to-end benchmarks exercise representative queries through the relevant parser, resolver, optimiser, planner and local evaluation stages using deterministic data without uncontrolled network acquisition.

These workloads provide a useful complement to isolated benchmarks. Microbenchmarks can identify the source of a change, while end-to-end workloads show whether that change is material to realistic execution.

### Formatting and explain output

Formatting and explain benchmarks should cover sufficiently complex queries and plans to detect material scaling or allocation regressions. These surfaces are lower priority than query execution but remain useful when their implementation changes substantially.

External Graphviz process start-up or renderer performance should not be treated as a canonical measure of yt-sql planner performance. Structural explain generation and deterministic serialisation can be measured independently of an external renderer.

## Workload scaling

A single workload size is insufficient for identifying algorithmic regressions. Benchmarks should therefore exercise several deterministic scales appropriate to the surface being measured.

Dataset-oriented benchmarks should reuse deterministic generated data where this provides representative inputs. Existing conformance profiles may be used where appropriate, while benchmark-specific profiles may be introduced where different scaling characteristics are required. Dataset generation must remain deterministic for a given generator version, seed and requested size.

Expression-oriented benchmarks should vary both width and depth. Collection benchmarks should vary collection cardinality and composition depth. Cache benchmarks should vary requested key counts. Other benchmark families should expose the dimension most likely to reveal their expected complexity.

Large and stress workloads are valuable for detecting scaling problems but should not make ordinary test or CI execution unnecessarily slow.

## Timing methodology

Canonical timing results must not be based on a single execution.

Statistical timing benchmarks use `pytest-benchmark`, which provides calibrated rounds, benchmark statistics, saved comparisons and JSON output. Benchmark-specific configuration should prefer the library's established measurement facilities over project-specific timing loops.

Each timing benchmark should perform appropriate warm-up work before collecting multiple measured iterations. The benchmark result should retain enough information to distinguish a stable change from ordinary execution noise.

The primary comparison statistic should normally be the median. Results should also retain useful supporting statistics such as the minimum, upper percentile, dispersion, iteration count and throughput where meaningful.

Very short operations require particular care because scheduling, timer resolution and interpreter effects can dominate the measured work. Such operations should normally be repeated within each measured iteration so the timed interval is sufficiently large to be meaningful.

Benchmark comparisons should consider both relative and absolute changes. Large percentage changes in operations whose absolute duration remains negligible must not automatically be treated as material regressions.

## Memory methodology

Memory is a first-class performance characteristic rather than a secondary timing metric.

Targeted Python allocation benchmarks may use `tracemalloc` to measure peak traced memory and allocation behaviour. These measurements must be collected separately from canonical timing measurements because allocation tracing changes runtime performance.

Representative end-to-end workloads may additionally measure process-level peak memory where a sufficiently stable platform mechanism is available. Process memory and Python allocation measurements answer different questions and should not be presented as interchangeable values.

Memory benchmarks should pay particular attention to behaviour that scales with rows, expression depth, collection cardinality, intermediate collection materialisation and planning structures.

## Environment metadata

Benchmark results must record enough environmental information to make later comparisons meaningful. This should include, where available:

- yt-discover version or source revision;
- benchmark-suite version;
- dataset-generator version;
- dataset seed and workload size;
- Python implementation and version;
- operating system and architecture;
- processor information;
- relevant dependency versions;
- benchmark configuration and iteration counts.

Results from materially different environments should not be treated as directly interchangeable without considering the environmental difference.

## Benchmark entry point

The benchmark suite is exposed through the repository-level `benchmark.py` entry point. Benchmark implementation modules are internal organisation rather than part of the developer interface. The entry point accepts stable individual benchmark names and broader benchmark groups, lists the registered suite, and provides a single `--all` option for explicitly running every registered timing, scaling, memory and stress workload. Running it without names executes the normal practical suite and excludes the heavier opt-in workloads.

CI and developer documentation should use this entry point rather than depending on the internal pytest module layout. Statistical timing continues to be provided by `pytest-benchmark`; the entry point is a command dispatcher and must not duplicate the timing, calibration or statistical machinery supplied by the benchmarking library.

Human-readable timing results should be presented by the benchmark entry point as compact terminal-width-aware tables rather than exposing the wide internal pytest-benchmark table as the normal developer interface. Unicode box drawing and restrained colour may improve scanability where supported, but textual assessments and numeric values must carry the complete meaning. An ASCII border mode and a no-colour mode must remain available. Comparison output should prioritise the stable benchmark identifier, baseline median, current median, percentage change and regression-policy assessment; additional statistics remain available in verbose or machine-readable output.

Saved baseline comparison should be available directly through `benchmark.py --compare`, so developers and CI tooling do not need to depend on pytest-benchmark storage paths or internal test node names. The presentation layer may classify median changes using the regression guidance below, but those classifications remain advisory and do not replace repeat measurements, absolute-cost judgement or scaling analysis.

## Machine-readable results

The benchmark runner should support a stable machine-readable result format in addition to human-readable console output.

Machine-readable results should contain stable benchmark identifiers, measurements, supporting statistics, workload parameters and environmental metadata. This allows results to be retained as baseline artefacts, compared automatically, analysed historically and visualised without parsing human-oriented console text.

Benchmark identifiers should describe stable measured surfaces rather than incidental implementation details. Examples include `parser.simple`, `analysis.deep_expression`, `evaluation.scalar.large`, `evaluation.collection.filter_map`, `planning.metadata.large`, `cache.lookup.1000` and `end_to_end.offline.normal`.

## Baselines

Performance comparisons should distinguish between a release baseline and an immediately preceding development baseline.

The release baseline is an immutable set of benchmark results captured from the release or other agreed starting point before a programme of implementation work begins. It provides the principal measure of cumulative performance change.

A previous-phase or previous-change baseline may additionally be retained during development. This makes it easier to identify the particular change that introduced a regression or improvement.

A new result must not silently replace the release baseline merely because development has progressed. When a new release becomes the basis for subsequent work, its benchmark results may become the release baseline for that later programme while older baselines remain historical evidence.

## Regression guidance

Performance acceptance is evidence-based. The following ranges provide default guidance for sufficiently stable timing benchmarks rather than absolute pass or fail thresholds.

| Reproducible Slowdown | Default Interpretation | Expected Response |
| --- | --- | --- |
| 0-5% | Effectively neutral or likely measurement noise | Record the result. No further action is normally required unless the change is consistently reproducible or affects an unusually hot path. |
| More than 5% up to 10% | Small potential regression | Repeat the relevant benchmarks and inspect consistency, absolute cost and affected workload. |
| More than 10% up to 20% | Material regression | Investigate and understand the cause before accepting the change. |
| More than 20% up to 50% | Significant regression | Normally unacceptable without a compelling and documented engineering justification. |
| More than 50% | Severe regression | Treat as a blocker except in exceptional circumstances supported by clear evidence. |

Percentage thresholds should not be applied mechanically to extremely short operations. The benchmark comparison should consider a minimum meaningful absolute difference where percentage changes would otherwise exaggerate negligible costs.

A regression below a numerical threshold can still be important when it affects a very hot operation or changes scaling behaviour. Conversely, a measurable regression may be acceptable when it affects an infrequent operation and enables a justified improvement in correctness, maintainability or architecture.

## Memory regression guidance

Memory changes should be assessed using similar evidence-based ranges.

| Reproducible Memory Increase | Default Interpretation |
| --- | --- |
| 0-5% | Generally neutral or measurement noise |
| More than 5% up to 10% | Review if reproducible |
| More than 10% up to 20% | Material increase requiring investigation and explanation |
| More than 20% | Normally unacceptable without a documented justification |
| Unbounded or adverse complexity change | Blocker regardless of the percentage observed on a particular dataset |

An implementation that changes memory growth from an appropriate bounded or linear relationship to an unexpectedly worse complexity class must not be accepted merely because the difference is small on the benchmark's smallest dataset.

## Algorithmic and deterministic performance regressions

Where a performance property can be tested deterministically, it should be protected by an ordinary automated test rather than inferred from elapsed time.

Examples include limiting the number of database operations for a batched cache lookup, proving that a short-circuited expression is not evaluated, proving that unnecessary acquisition is not requested, verifying bounded planner work where an explicit invariant exists, or checking that an optimisation avoids work it claims to eliminate.

Deterministic performance invariants may fail ordinary CI. Statistical wall-clock or memory comparisons should not normally fail ordinary CI because shared runners are too variable to provide a trustworthy benchmark environment.

Changes that introduce an adverse algorithmic complexity class, unbounded repeated work, N+1 access pattern or equivalent structural regression should normally be treated as blockers even when current timing measurements happen to remain within an otherwise acceptable percentage range.

## Required benchmark execution

The relevant benchmark suite must be run after implementation changes reasonably capable of affecting execution time, allocation behaviour, peak memory or algorithmic scaling.

This includes changes to:

- parsing, tokenisation or parser architecture;
- semantic resolution and type resolution;
- AST or query-model structure and traversal;
- semantic and query-property analysis;
- optimisation;
- expression or collection evaluation;
- planning or acquisition planning;
- cache and database access;
- row, binding or evaluation-environment representation;
- formatting or explain generation when their execution model changes materially;
- deterministic dataset or conformance infrastructure used by benchmark workloads;
- shared infrastructure on a measured execution path.

Parser replacements or similarly fundamental architectural changes should run the complete applicable benchmark suite rather than only their most obvious benchmark family, because representation and lifetime changes can affect downstream resolution, analysis, planning and memory behaviour.

Documentation-only changes, test expectation corrections and other changes that cannot reasonably affect runtime behaviour do not require benchmark execution.

## Continuous integration

Ordinary CI should continue to prioritise deterministic functional and conformance testing.

Deterministic performance invariants belong in ordinary automated tests where they can be expressed reliably. A small benchmark smoke job verifies that benchmark workloads and result generation remain functional, but statistical timing differences do not gate CI on shared runners.

The full benchmark suite should be run in a suitably controlled local or dedicated environment when required by implementation changes, during significant architectural investigations, and as part of release reconciliation.

A scheduled non-gating benchmark workflow may be considered if a sufficiently stable execution environment becomes available. Its purpose would be historical observation and early warning rather than treating shared-runner timing as a correctness property.

## Interpreting refactors and optimisations

A behaviour-preserving refactor does not need to make execution faster to be successful. Performance within normal measurement variation is an acceptable result when the refactor provides a justified architectural or maintenance benefit.

A material regression introduced by a refactor requires investigation. Acceptance should consider the magnitude and location of the regression, its real execution frequency, memory effects, scaling behaviour and the architectural benefit obtained.

An optimisation should demonstrate a reproducible improvement in the workload it targets. If the expected improvement cannot be measured, the additional implementation complexity should be reconsidered. An optimisation that improves one metric while materially worsening another must be evaluated as a trade-off rather than described simply as an improvement.

Performance improvements must also be checked for accidental reductions in required work, changed query results, weakened acquisition, altered ordering, changed NULL behaviour or any other semantic difference. Faster incorrect execution is a regression.

## Performance and semantic equivalence

yt-sql optimisation is governed by semantic equivalence. Performance work must preserve SQL-like three-valued NULL behaviour, typed values, source and facet identity, deterministic behaviour where promised, acquisition requirements, ordering and every other observable language invariant.

When an optimisation changes query or expression execution, differential tests should compare optimised and deliberately unoptimised behaviour wherever deterministic semantics permit it. Performance evidence supplements those tests and never replaces them.

When semantic equivalence cannot be established safely, the transformation must not be applied regardless of its measured performance benefit.
