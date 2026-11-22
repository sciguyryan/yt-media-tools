# TODO

Working lists of outstanding work. Completed work is recorded in the changelogs and durable design documents rather than here. Each language item carries the contract constraints it must satisfy; every increment still follows the established pipeline of design decisions, Python implementation, Rust parity, portable conformance cases and certification.

# Downloader TODO

- Define a versioned machine-readable execution-request schema backed by Downloader's typed policy and planning model.
- Investigate reliable structured per-target outcomes from yt-dlp without parsing human-readable output.
- Add manifest-driven retry only after structured outcome semantics are reliable.
- Define a simple versioned Discover-to-Downloader interchange format.
- Revisit language preference and filesize policy when extractor semantics can be specified conservatively.
- Investigate authoritative associated-artefact path reporting for run manifests.
- Evaluate property-based, mutation and focused fuzz testing where they materially improve deterministic coverage.
- Evaluate optional external-tool integrations only where they add clear utility behind an existing typed policy boundary.
- Consider the low-impact `El Psy Kongroo` easter egg only if it cannot affect scripting, help, errors or machine-readable output.
- Investigate optional playback-aware rate limiting that derives an approximate download rate from the actually selected media formats, applies configurable headroom for variable bitrate and network jitter, degrades gracefully when reliable bitrate information is unavailable, and exposes the calculation through planning and explain output. Keep existing download-speed behaviour unchanged by default; the goal is considerate bandwidth and server-load behaviour resembling ordinary real-time playback.

# Discover language TODO

Ordered by intended sequence. The first item is the next planned increment.

## Window functions

- Add `RANK()` and `DENSE_RANK()` on the existing window foundation. Ties follow the established no-implicit-tie-breaker contract: rows with equal window-ordering keys receive no guaranteed relative ranks, and conformance cases must fully distinguish ordering keys where repeatable output matters. Partitions restart independently; the deferred post-grouping window stage reserved in `WINDOW-DESIGN.md` may enable with this or a later increment.
- Add `LAG()`, `LEAD()`, `FIRST_VALUE()` and `LAST_VALUE()` with a design note covering row-relative access, default values, partition boundaries and NULL defaults. Frame syntax stays out until a concrete need appears.
- Consider aggregate windows such as `COUNT(...) OVER (...)` only after the row-relative functions settle. Frame-sensitive behaviour must have an explicit restricted contract or remain rejected; defaults must never be inherited accidentally from another SQL dialect.
- Add `QUALIFY` last among the window work, once enough window functions exist to justify filtering their results without a CTE. Its execution stage and alias visibility must be explicit, and equivalent CTE forms should be compared where semantics permit.

## Text and Unicode functions

- Add `CODEPOINT()` as the natural inverse of `CHAR()`; `TRIM()`, `LTRIM()` and `RTRIM()`; `SUBSTRING()`, `LEFT()` and `RIGHT()`; `REPLACE()` and `REVERSE()`; `STARTS_WITH()` and `ENDS_WITH()`; and `STRPOS(haystack, needle)`.
- `STRPOS` returns the one-based code-point index of the first occurrence, `0` when the substring does not occur, and NULL only when an operand is NULL. Matching is exact code-point comparison without case folding; case-insensitive search remains `CONTAINS` and `ILIKE` territory. The spelling deliberately replaces the earlier text-position `POSITION()` idea, which now collides with the final-result `POSITION()`.
- Every operation needs an explicit Unicode contract consistent with the code-point-oriented language semantics. No implicit normalisation. Indexing, slicing and reversal are code-point based, matching `LENGTH()`. The Unicode torture corpus grows with this phase, including combining sequences, supplementary-plane characters, emoji and ZWJ sequences, variation selectors, unusual whitespace and composed/decomposed text.

## Numeric functions

- Add `ABS()`, `SIGN()`, `ROUND()`, `FLOOR()`, `CEIL()`, `SQRT()`, `POWER()`, `LOG()`, `LOG10()`, `EXP()` and `CLAMP()`.
- Tests must cover integers and floats, NULL propagation, domain errors and signed zero, plus any case where observable serialisation can differ. Deterministic literal expressions may be constant-folded, but symbolic rewrites must continue to respect NULL and IEEE-754 behaviour. Trigonometric functions wait for a real media-discovery use case.

## Temporal extraction

- Add `YEAR()`, `MONTH()`, `DAY()`, `HOUR()`, `MINUTE()`, `SECOND()`, `DAY_OF_WEEK()` and `DAY_OF_YEAR()`.
- Behaviour must be defined for date-only values, timestamps, NULLs and typed temporal infinity, with explicit timezone assumptions. Grouping and ordering by extracted values receive direct conformance coverage. Temporal arithmetic waits until extraction has settled.

## Aggregate completion

- Add aggregate `DISTINCT` arguments, beginning with `COUNT(DISTINCT ...)`, `SUM(DISTINCT ...)` and `AVG(DISTINCT ...)`; `COUNT_IF(predicate)`; `BOOL_AND(predicate)`; and `BOOL_OR(predicate)`.
- Empty groups, all-NULL groups, mixed TRUE/FALSE/UNKNOWN inputs, `FILTER`, aliases, HAVING, CTEs and set composition all need explicit semantics and tests. Whether `DISTINCT` is accepted on `MIN()` and `MAX()` is a deliberate language decision rather than an accidental parser consequence.

## Ordered aggregates

- Revisit aggregates that bring ordering or output-size concerns, led by `STRING_AGG()`, potentially with an explicit aggregate-local ordering form later. Driven by real discovery and reporting use cases rather than copying a database function catalogue.

## Regular-expression transformations

- Add `REGEXP_EXTRACT()` and `REGEXP_REPLACE()` as transformation capability, not another spelling of the regex predicate. Document the regex engine, capture behaviour, invalid-pattern errors and Unicode semantics. `REGEXP_EXTRACT_ALL()` waits until a justified list/collection value type exists.

## Introspection and conversion

- Consider `TYPEOF()` for heterogeneous extractor metadata, and conversion functions or `CAST` only where real data demonstrates a need. Discover prefers explicit type errors over loose implicit coercion, and synonyms such as `NVL`, `IFNULL` or `IIF` stay out while `COALESCE`, `NULLIF` and `CASE` express the same concepts clearly.

## Ordering completion

- Add explicit `NULLS FIRST` and `NULLS LAST` on individual `ORDER BY` terms, documented alongside the fixed default placement (NULLs last in both directions). Cover scalar and temporal values, aliases, CTEs, set composition, aggregation, malformed placement and stable ordering.

## Set completion

- Add `INTERSECT` and `EXCEPT` with distinct set semantics first. `INTERSECT ALL` and `EXCEPT ALL` wait for a real multiset use case. Coverage includes duplicate rows, NULLs, Unicode, independently acquired sources, same-source cross-facet composition, CTE branches, aggregates, schema reconciliation and global ordering/OFFSET/LIMIT behaviour.

## Keyed selection

- Add `DISTINCT ON (...)` for selecting one deterministic representative row per key. Where row selection depends on ordering, insufficient or ambiguous ordering is rejected rather than allowing an arbitrary representative to win. Ties, NULL keys, aliases, multiple keys, Unicode keys, CTEs and set-composed input receive deliberate parser and execution coverage.

## Format-aware querying

- Introduce a yt-dlp-native capability tier for the formats available before download, built around a contained format predicate language such as `HAS_FORMAT(height >= 2160 AND fps >= 60)` rather than general arrays or lambdas, with `COUNT_FORMATS(predicate)`, `FORMAT_MAX(field)` and `FORMAT_MIN(field)` following the same shape.
- Format availability is extractor-dependent: missing metadata must not be confused with a negative capability result, and the planner and explain output must distinguish lightweight listing metadata from the detailed per-item extraction format predicates require. Avoid convenience aliases such as `HAS_AV1()` when the generic form is already clear. Richer format analysis, codec/HDR queries and existence short-circuits build only after the first tier is stable, and only when NULL/missing-data and capability semantics make each rewrite exact.

## Temporal arithmetic and bucketing

- After temporal extraction has settled, consider `DATE_ADD()`, `DATE_SUB()`, `DATE_DIFF()` and a truncation or bucketing form that composes naturally with the existing duration/unit system. Units, date-versus-timestamp behaviour, overflow and infinity behaviour and timezone assumptions must be settled in a design note before grammar or implementation is committed.

## Ordered-sequence semantics

- Investigate LINQ-inspired `TAKE WHILE` and `SKIP WHILE` as genuinely different from `WHERE`: they terminate or skip an ordered input sequence at its first boundary rather than filtering every row. The main attraction is acquisition planning on sources with a trustworthy monotonic order. The design must state whether the operators observe authoritative source order or a later query ordering stage, preferring source-sequence semantics so the acquisition value survives. Weakly ordered sources need clear diagnostics rather than accidental assumptions.

## Sampling

- Investigate query sampling and acquisition sampling as different operations. Discover must not claim a statistically representative sample of an extractor's full population when it has only examined an ordered prefix. Acquisition-level sampling remains a later optimisation and research problem.

## Hardening and language review

- After the outstanding language work settles, repeat the hardening model that produced the 0.26.6 baseline: remove dead and stale code, audit compatibility paths, audit every optimiser surface, reconcile the language-feature and test-coverage inventories, expand parser/semantic/optimiser torture cases across interacting subsystems, run property/mutation/fuzzing work where it adds confidence, benchmark important execution paths and reconcile all documentation with implemented behaviour.
- Only after hardening should the language reopen for a broad survey against PostgreSQL, SQLite, DuckDB, BigQuery, ClickHouse, LINQ, jq-like transformations, yt-dlp's current metadata surface and real accumulated queries. Every addition still justifies itself against Discover's own model.

# Testing and tooling investigations

- Investigate a Hypothesis-based property programme before the next major grammar expansion. Strong properties include parse-format stability chains, optimiser idempotence, optimised/unoptimised equivalence, production-versus-reference evaluation and generated typed ASTs. It complements, never replaces, the deterministic conformance corpus.
- Evaluate a maintained Python mutation-testing tool (`mutmut` as the leading candidate) for explicit hardening runs around comparison boundaries, Boolean logic, NULL behaviour, optimiser guards, ordering and planning. Full runs sit alongside scale/stress and release work, not routine CI.
- Evaluate coverage-guided fuzzing (Atheris or equivalent) for hostile parser input: arbitrary input must parse or fail through deterministic documented errors, never crash.
- Use branch coverage as a diagnostic for unexercised semantic and failure paths, not a vanity percentage.
- Extend the repeatable benchmark programme to new language stages as they arrive, preferring comparative regression information over brittle absolute timing gates.
- Investigate formalising the independent-oracle approach into a deliberately simple reference evaluator for suitable yt-sql subsets.
- Continue the YouTube.js/InnerTube investigation as an optional enrichment provider behind the source/capability planner; a query must not change meaning because a different provider supplied the data.
- Evaluate Rust implementation or selective Rust acceleration as an evidence-driven design investigation, preserving yt-sql semantics, deterministic behaviour, diagnostics and the conformance contract exactly. The Python implementation remains authoritative unless evidence justifies the cost.
