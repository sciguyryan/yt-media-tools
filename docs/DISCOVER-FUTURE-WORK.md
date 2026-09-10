# Discover future work

## Purpose

Discover 0.26.6 "No Loose Ends" is the accepted hardened baseline for the next stage of yt-sql development. The language is now broad enough that future additions should be chosen because they make media discovery more expressive, predictable or efficient, not simply because another SQL dialect happens to support them.

The next programme should borrow selectively from SQL, LINQ and yt-dlp's own data model. SQL provides a strong vocabulary for scalar expressions, grouping, set composition and analytical queries. LINQ is particularly interesting where Discover is dealing with an ordered, lazily acquired sequence rather than a conventional database table. yt-dlp exposes source and format metadata that can support queries ordinary SQL engines would never need to express.

This roadmap is intentionally ambitious. It records the features we currently want, but the phases are ordered by architectural dependency. A later phase may be refined after experience with earlier work. No phase should be treated as permission to weaken existing semantics merely to make a new feature easier to implement.

## Working rules

Every phase must leave Discover in a releasable state. New syntax and functions require complete parser, semantic, execution and formatting coverage, including malformed forms and interactions with existing language features. Optimiser changes require differential testing against unoptimised execution and must remain deterministic and idempotent. NULL and three-valued logic, Unicode behaviour, temporal semantics, source/facet identity, ordering and volatile functions remain conservative boundaries for optimisation.

Documentation is part of implementation. `DISCOVER-README.md`, `YT-SQL.md`, `YT-SQL-OPTIMISATION.md`, `YT-SQL-TEST-COVERAGE.md`, `TODO.md` where appropriate, and `CHANGELOG.md` must be updated in the same release when their contracts change. Permanent documentation should describe current behaviour rather than narrating development phases.

The deterministic conformance corpus remains the semantic authority for routine testing. Small and normal generated datasets remain suitable for normal tests. Large and huge datasets remain explicit scale/stress work and must not make routine CI slow.

General relational composition is no longer rejected categorically. The dedicated 0.30.x roadmap evaluates selected JOIN forms where independently acquired media relations create compelling Discover use cases, particularly SEMI and ANTI joins. SQL completeness remains a non-goal, and unsupported relational forms should remain unsupported unless concrete media-query value justifies them.

## Phase 1 - comparison and ordering completion

Complete two small but important gaps in the existing expression and ordering model:

- `NULLS FIRST` and `NULLS LAST` on individual `ORDER BY` terms.
- `IS DISTINCT FROM` and `IS NOT DISTINCT FROM` as NULL-safe comparisons.

The release must document both explicit and default NULL ordering. Tests should cover scalar and temporal values, aliases, CTEs, set composition, aggregation, malformed placement and stable ordering. The optimiser may reason more strongly about NULL-safe comparison only where equivalence is proven.

## Phase 2 - text and Unicode functions

Expand the deterministic text function family with functions that are useful against titles, descriptions, uploader names and other extractor metadata:

- `CODEPOINT()` as the natural inverse of `CHAR()`.
- `TRIM()`, `LTRIM()` and `RTRIM()`.
- `SUBSTRING()`, `LEFT()` and `RIGHT()`.
- `REPLACE()` and `REVERSE()`.
- `STARTS_WITH()` and `ENDS_WITH()`.
- `POSITION()`.

The Unicode contract must be explicit for every operation. Discover must not introduce implicit normalisation. Indexing, slicing, reversal and code-point conversion need deterministic definitions consistent with the existing code-point-oriented language semantics. The Unicode torture corpus should grow with this phase, including combining sequences, supplementary-plane characters, emoji/ZWJ sequences, variation selectors, unusual whitespace and composed/decomposed text.

## Phase 3 - numeric functions

Complete the practical scalar arithmetic surface with:

- `ABS()` and `SIGN()`.
- `ROUND()`, `FLOOR()` and `CEIL()`.
- `SQRT()` and `POWER()`.
- `LOG()`, `LOG10()` and `EXP()`.
- `CLAMP()`.

Tests must cover integers and floats, NULL propagation, domain errors, signed zero and other floating-point cases where observable serialisation can differ. Deterministic literal expressions may be constant-folded, but symbolic rewrites must continue to respect NULL and IEEE-754 behaviour. Trigonometric functions are not currently a priority and should be added only if a useful media-discovery case appears.

## Phase 4 - temporal extraction

Add deterministic extraction functions before attempting more complicated temporal arithmetic:

- `YEAR()`.
- `MONTH()`.
- `DAY()`.
- `HOUR()`.
- `MINUTE()`.
- `SECOND()`.
- `DAY_OF_WEEK()`.
- `DAY_OF_YEAR()`.

The phase must define behaviour for date-only values, timestamps, NULLs and typed temporal infinity. Any timezone assumptions must be explicit. Grouping and ordering by extracted values should receive direct conformance coverage.

## Phase 5 - aggregate completion

Extend the existing aggregate model with:

- aggregate `DISTINCT` arguments, beginning with `COUNT(DISTINCT ...)`, `SUM(DISTINCT ...)` and `AVG(DISTINCT ...)`;
- `COUNT_IF(predicate)`;
- `BOOL_AND(predicate)`;
- `BOOL_OR(predicate)`.

`BOOL_AND` and `BOOL_OR` provide a SQL-shaped equivalent to LINQ-style `All` and `Any` over groups without introducing general subquery quantifiers. Empty groups, all-NULL groups, mixed TRUE/FALSE/UNKNOWN inputs, `FILTER`, aliases, HAVING, CTEs and set composition all need explicit semantics and tests.

Whether `DISTINCT` is accepted on `MIN()` and `MAX()` should be a deliberate language decision rather than an accidental parser consequence.

## Phase 6 - set completion

Extend the existing positional set-composition architecture with:

- `INTERSECT`.
- `EXCEPT`.

The first implementation should use distinct set semantics. `INTERSECT ALL` and `EXCEPT ALL` can wait until a real multiset use case justifies their extra cardinality rules.

Coverage should include duplicate rows, NULLs, Unicode, independently acquired sources, same-source cross-facet composition, CTE branches, aggregates, schema reconciliation and global ordering/OFFSET/LIMIT behaviour.

## Phase 7 - keyed selection with DISTINCT ON

Add `DISTINCT ON (...)` as a first-class solution for selecting one representative row per key, for example the newest or most-viewed item per uploader.

Discover should favour deterministic semantics over permissive compatibility with another dialect. Where row selection depends on ordering, insufficient or ambiguous ordering should be rejected rather than allowing an arbitrary representative to win. Parser and execution tests should deliberately exercise ties, NULL keys, aliases, multiple keys, Unicode keys, CTEs and set-composed input.

This feature provides much of the practical value of LINQ's `DistinctBy` and some common "top row per group" use cases without requiring window functions yet.

## Phase 8 - format-aware querying

Introduce a yt-dlp-native query surface for the formats available before download. This should be treated as a new metadata capability tier rather than flattening one arbitrary selected format into ordinary item metadata.

The initial model should avoid general arrays or lambdas and instead provide a contained format predicate language such as:

```sql
HAS_FORMAT(height >= 2160 AND fps >= 60 AND vcodec = 'av01')
```

The initial family should include:

- `HAS_FORMAT(predicate)`.
- `COUNT_FORMATS(predicate)`.
- `FORMAT_MAX(field)`.
- `FORMAT_MIN(field)`.

Candidate format fields include `format_id`, `ext`, `width`, `height`, `resolution`, `fps`, `aspect_ratio`, `vcodec`, `acodec`, `container`, `protocol`, `dynamic_range`, `tbr`, `vbr`, `abr`, `asr`, `audio_channels`, `filesize`, `filesize_approx`, `language` and `format_note` where yt-dlp exposes them.

Format availability is extractor-dependent. Missing metadata must not be confused with a negative capability result. The planner and explain output must distinguish lightweight listing metadata from detailed per-item extraction required by format predicates.

## Phase 9 - richer format analysis and acquisition planning

Build on the format model only after Phase 8 is stable. Investigate additional format aggregates where they have clear semantics, richer codec/audio/HDR queries, and planner optimisations that can avoid unnecessary work.

`HAS_FORMAT(...)` should be able to short-circuit after the first proven match. Other rewrites, such as relating `COUNT_FORMATS(predicate) >= 1` to existence, should be implemented only after NULL/missing-data and capability semantics make the equivalence exact.

Avoid convenience functions such as `HAS_AV1()` or `HAS_HDR()` unless they genuinely improve the language. `HAS_FORMAT(vcodec = 'av01')` is preferable to a growing catalogue of aliases when the generic form is already clear.

## Phase 10 - regular-expression transformations

Add transformation capability rather than another spelling of the existing regex predicate:

- `REGEXP_EXTRACT()`.
- `REGEXP_REPLACE()`.

The regex engine, capture behaviour, invalid-pattern errors and Unicode semantics must be documented. `REGEXP_EXTRACT_ALL()` should wait unless or until Discover has a justified list/collection value type.

## Phase 11 - temporal arithmetic and bucketing

After temporal extraction has settled, add a coherent temporal arithmetic family. Current candidates are:

- `DATE_ADD()`.
- `DATE_SUB()`.
- `DATE_DIFF()`.
- `DATE_TRUNC()` or a less stringly typed equivalent that composes naturally with yt-sql's existing duration/unit system.

The design should settle units, date-versus-timestamp behaviour, overflow/infinity behaviour and timezone assumptions before grammar or implementation is committed.

## Phase 12 - ordered-sequence semantics

Investigate and, if the semantics remain useful and predictable, add LINQ-inspired sequence operators:

- `TAKE WHILE`.
- `SKIP WHILE`.

These are deliberately not aliases for `WHERE`. `TAKE WHILE` terminates an ordered input sequence at the first non-match, while `SKIP WHILE` discards an initial matching prefix and then continues normally.

The main attraction is acquisition planning: on a source with a trustworthy monotonic order, `TAKE WHILE` may permit Discover to stop asking the extractor for more records. The design must explicitly state whether the operators observe authoritative source order or a later query ordering stage. The initial preference is source-sequence semantics so the feature can retain its acquisition value.

Unsupported or weakly ordered source cases need clear diagnostics rather than accidental assumptions.

## Phase 13 - sampling

Add deterministic logical result sampling, building on the stable row identity already used by seeded `RANDOM()`.

A candidate surface is conceptually:

```sql
SAMPLE 100 SEED 31415926
```

The exact grammar should be selected only after its interaction with CTEs, set composition, ordering, DISTINCT, OFFSET/LIMIT and seeded randomness is understood.

Result sampling and acquisition sampling are different operations. Discover must not claim a statistically representative sample of an extractor's full population when it has only examined an ordered prefix. Acquisition-level sampling should remain a later optimisation/research problem.

## Phase 14 - window-function foundation

Introduce the first window execution stage with:

- `OVER`.
- `PARTITION BY`.
- window-local `ORDER BY`.
- `ROW_NUMBER()`.
- `RANK()`.
- `DENSE_RANK()`.

This is a major architectural phase. Window evaluation order, aliases, partition identity, NULL ordering, ties, CTE/set-composed input and interaction with ordinary `ORDER BY` must be specified before optimisation work begins.

Do not attempt the entire SQL window specification in one release. Window frames can remain unsupported until a concrete need appears.

## Phase 15 - advanced windows

Once the window foundation is proven, add:

- `LAG()` and `LEAD()`.
- `FIRST_VALUE()` and `LAST_VALUE()`.
- aggregate windows such as `COUNT(...) OVER (...)`, `SUM(...) OVER (...)` and `AVG(...) OVER (...)`.

Frame-sensitive behaviour should either have an explicit restricted contract or remain rejected until frame syntax is implemented. Defaults must never be inherited accidentally from another SQL dialect.

## Phase 16 - QUALIFY

Add `QUALIFY` after window functions exist so users can filter window results without introducing a CTE solely for that purpose.

Its execution stage and alias visibility must be explicit. Tests should compare equivalent CTE and `QUALIFY` forms where semantics permit.

## Phase 17 - richer ordered aggregates

Revisit aggregates that are useful but bring additional ordering or output-size concerns. The leading candidate is `STRING_AGG()`, potentially with an explicit aggregate-local ordering form later.

This phase should be driven by real discovery/reporting use cases rather than an attempt to copy an entire database function catalogue.

## Phase 18 - introspection and conversion

Consider `TYPEOF()` for heterogeneous extractor metadata and add conversion functions or `CAST` only where real data demonstrates a need.

Discover should continue to prefer explicit type errors over loose implicit coercion. Synonyms such as `NVL`, `IFNULL` or `IIF` should not be added when `COALESCE`, `NULLIF` and `CASE` already express the same concepts clearly.

## Phase 19 - full hardening and reconciliation

Stop adding syntax and repeat the hardening model that produced the 0.26.6 baseline:

1. remove dead and stale code;
2. audit compatibility paths;
3. audit every optimiser surface for safe improvements and unsafe tempting rewrites;
4. reconcile the language-feature and test-coverage inventories;
5. expand parser, semantic and optimiser torture cases;
6. run property, mutation and fuzzing work where it adds confidence;
7. benchmark important execution paths and investigate regressions;
8. reconcile all permanent documentation with implemented behaviour.

The torture corpus should deliberately combine format predicates, set composition, keyed selection, aggregates, windows, QUALIFY, Unicode, temporal expressions, NULL semantics and seeded randomness. The purpose is not to produce an impressive query for its own sake, but to force independent language subsystems to interact under deterministic expectations.

## Phase 20 - language and ecosystem review

Only after the preceding programme is hardened should the language reopen for another broad survey. Revisit PostgreSQL, SQLite, DuckDB, BigQuery, ClickHouse, LINQ, jq-like transformation ideas, yt-dlp's current metadata surface and the real queries accumulated during use.

Additional syntax should still have to justify itself against Discover's own model. Recursive CTEs, DDL, DML, transactions, stored procedures, database schemas and JOINs remain outside the intended language.

## Tooling and external integration investigations

The development programme should also investigate tools that can improve correctness, confidence or acquisition capability. Adoption is not mandatory merely because a tool appears here. Each should be used where it solves a real problem without weakening portability or making routine development unnecessarily heavy.

### Hypothesis

Property-based testing is a compelling candidate and should be evaluated before the next major grammar expansion. Particularly strong properties include:

- parse -> format -> parse -> format stability;
- optimiser idempotence;
- optimised versus unoptimised semantic equivalence;
- production evaluator versus an independent reference evaluator;
- generated typed ASTs that remain valid across formatting and parsing.

Hypothesis should complement, not replace, deterministic golden conformance and hand-authored torture tests.

### Mutation testing

Evaluate a maintained Python mutation-testing tool, currently with `mutmut` as a leading candidate, for explicit hardening runs. Mutation testing is especially valuable around comparison boundaries, Boolean logic, NULL behaviour, optimiser guards, ordering and source/facet planning.

A full mutation run should not be added to routine CI if its cost is disproportionate. It belongs naturally alongside explicit scale/stress and release-hardening work.

### Coverage-guided fuzzing

Evaluate Atheris or an equivalent maintained Python fuzzing approach for hostile parser input. The core invariant is that arbitrary input must either parse successfully or fail through deterministic documented syntax/semantic errors, never through an unexpected crash.

This is lower priority than property-based semantic testing but valuable as a parser-hardening layer.

### Branch coverage

Use branch coverage as a diagnostic rather than a vanity target. It should help identify unexercised semantic and failure paths, especially after adding new language stages. A raw percentage is not a substitute for meaningful conformance tests.

### Benchmarks and profiling

Create repeatable benchmarks for parsing, formatting, resolution, optimisation, execution, aggregation, set composition and source planning. Extend them to format predicates and window execution when those features arrive.

Use the deterministic dataset generator for reproducible workloads. Prefer comparative regression information over brittle absolute timing gates.

### Independent reference evaluation

Investigate formalising the existing independent-oracle approach into a deliberately simple reference evaluator for suitable subsets of yt-sql. It should favour obvious correctness over optimisation. Property-generated resolved expressions could then be evaluated by both the production engine and reference evaluator.

### YouTube.js and InnerTube

Continue to investigate YouTube.js as an optional YouTube-specific acquisition or enrichment provider, not as a replacement for yt-dlp and not as a mandatory runtime dependency.

The investigation should compare channel/video enumeration, continuation behaviour, search, detailed metadata, formats, live metadata, captions, chapters, playlists, comments and other useful InnerTube surfaces. The main architectural question is whether an optional provider can satisfy some capability requests more cheaply or completely than yt-dlp while preserving identical yt-sql semantics.

Provider choice belongs behind the source/capability planner. A query must not change meaning because a different provider supplied the data. Extractor agnosticism remains a core design goal.

### Third-party SQL parsers

Do not adopt a third-party SQL parser as yt-sql's grammar authority. Other parsers and dialects remain useful design references, but yt-sql now has enough deliberate non-standard behaviour that forcing it through a general SQL parser would work against the language rather than simplify it.

## Features deliberately outside the roadmap

The following are not planned unless the project's purpose changes substantially:

- JOINs of any kind;
- recursive CTEs;
- DDL or DML;
- transactions;
- stored procedures;
- database schemas;
- user-defined SQL functions;
- gratuitous aliases for existing functions/operators;
- loose implicit type conversion;
- a general list/array/lambda language without a demonstrated need.

The aim is not to implement SQL. The aim is to take the parts of SQL and LINQ that fit an extractor-backed discovery language, combine them with the metadata yt-dlp can expose, and keep the resulting language small enough that its semantics can still be stated and tested precisely.
