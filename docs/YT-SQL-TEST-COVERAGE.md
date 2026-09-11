# yt-sql test coverage

This document records the major yt-sql language and execution surfaces that must remain covered. It is the durable test-completeness inventory used when reviewing regressions and future language changes.

## Coverage standard

A language feature is not considered thoroughly covered merely because its happy path parses. Where applicable, coverage should include parsing, semantic resolution, execution, formatting round-trips, malformed input, NULL behaviour, Unicode behaviour, optimiser differential equivalence, composition through CTEs and set operations, and observable CLI behaviour.

Optimiser tests must compare the complete observable result of optimised and unoptimised execution. The routine conformance corpus also enforces optimiser idempotence across every directly resolved semantic case and canonical parse-format-parse stability across every directly parsed case. Parameter binding remains a CLI-boundary contract with dedicated tests before parsing.

## Grammar and scalar expressions

Current dedicated coverage includes SELECT projection, aliases, SELECT *, arithmetic and precedence, parenthesised expressions, CASE, LOWER, UPPER, LENGTH, COALESCE, NULLIF, GREATEST, LEAST, CHAR, RANDOM, decimal and non-decimal integer literals, query parameters, and malformed scalar-function calls.

Torture coverage additionally combines deeply parenthesised scalar and Boolean expressions, hostile whitespace, CASE with nested functions and mixed-base literals, malformed CASE boundaries, malformed function argument lists, and parse-format-parse stability.

## Predicates and three-valued logic

Current dedicated coverage includes comparisons, BETWEEN, IN, IS NULL, Boolean IS forms, CONTAINS, MATCHES, LIKE, ILIKE, negated forms, AND, OR and NOT. Unicode-sensitive LIKE/ILIKE and normalisation distinctions have dedicated tests.

Torture coverage combines duplicate IN members, nested NOT, NULL-sensitive predicates, exact LIKE optimisation paths, Boolean precedence, malformed BETWEEN/IN/LIKE forms, and deterministic failures at clause boundaries.

## Temporal and numeric semantics

Current coverage includes durations, multilingual units, relative dates, date/timestamp type distinctions, temporal infinity, malformed dates and timestamps, duration boundaries, decimal separators that are intentionally unsupported, numeric underscores, hexadecimal, octal and binary literals.

Torture coverage keeps temporal and numeric values embedded inside larger Boolean/scalar expressions so parser and resolver interactions are exercised rather than only isolated literal parsing.

## Aggregation

Current coverage includes COUNT(*), COUNT(expr), SUM, AVG, MIN, MAX, GROUP BY, HAVING, aggregate FILTER, NULL elimination, grouping of NULL keys, aggregate aliases, invalid nesting, type checking and aggregate UNION branches. HAVING optimiser coverage includes semantic duplicate-term removal, double-negation elimination, differential execution and idempotence.

Static relation coverage includes WHERE predicates that are impossible under SQL filtering semantics, constant TRUE/FALSE HAVING conditions, capability-proven TRUE filters, per-branch UNION elimination, shared-source field pruning after an empty branch is removed from physical requirements, and explain consistency for skipped acquisition. These tests keep scalar UNKNOWN semantics separate from the relational question of whether a row can ever survive.

Physical acquisition-plan coverage checks identity-only enumeration, authoritative lightweight fields, ordinary complete metadata, nested formats/subtitles/chapters/thumbnails metadata, open-ended raw metadata, independent UNION source plans, empty-boundary plans, yt-dlp stage lowering, and human/JSON explain output. The tests assert the semantic stage model separately from the backend mapping so future adapters can honour finer-grained stages without changing the query contract.

Torture coverage chains filtered CTE materialisation into grouping, HAVING and outer ordering, and also aggregates a cross-facet UNION-derived relation containing scalar CASE expressions and seeded RANDOM projection.

## CTE and set composition

Current coverage includes declaration-order CTE scoping, CTE schema export, SELECT * from CTEs, recursive/forward-reference rejection, UNION, UNION ALL, left-associative mixed set boundaries, heterogeneous schemas, global ordering/slicing, Unicode-sensitive deduplication and aggregate branches.

Torture coverage uses multiple CTE stages, UNION ALL inside a CTE, outer aggregation over the materialised relation, facet-distinct physical requests, Unicode values, mixed-base arithmetic and optimiser differential execution in one query.

## Source and facet identity

Current coverage includes source classification, capability discovery, OF facets, --tab compatibility, unsupported capability diagnostics, same-source cross-facet acquisition identity, per-facet schemas, cache/frontier separation, provenance and seeded RANDOM identity.

The cross-facet torture query deliberately uses two facets of one physical source through UNION ALL before further CTE materialisation and aggregation.

## Ordering, DISTINCT and slicing

Current coverage includes aliases in ORDER BY, deterministic ties, DISTINCT, OFFSET, LIMIT, global set-operation ordering, early acquisition termination and OFFSET + LIMIT planning. RANDOM ordering has dedicated volatile and seeded coverage.

Torture coverage combines computed aliases, multiple ORDER BY keys, LIMIT/OFFSET and large nested predicates, with optimiser differential equivalence checked after resolution.

## Unicode

The deterministic fixture includes composed and decomposed forms, combining marks, emoji and ZWJ sequences, the Welsh flag tag sequence, variation selectors, Greek sigma forms, Turkish I variants, German sharp s, Kelvin sign, CJK, Arabic, Hebrew, RTL marks, unusual whitespace, line separators, fullwidth wildcard lookalikes and zero-width joiners/non-joiners.

No implicit Unicode normalisation is permitted. Torture composition retains Unicode strings through facets, LIKE/ILIKE, UNION materialisation and grouping.

## Malformed and hostile input

The negative suite covers missing clauses, invalid literals, malformed predicates, unsupported functions, invalid types, malformed CTEs and invalid source/facet forms. The torture suite extends this with hostile whitespace, excessive parentheses, malformed repeated clauses, broken UNION boundaries, malformed aggregate FILTER, incomplete LIKE escaping and invalid Unicode scalar construction.

Diagnostics tested by the suite must remain deterministic. Parser failures should not turn into internal exceptions merely because the surrounding query is deeply nested or composition-heavy.

## Stress and scale coverage

Large and huge generated profiles are reserved for explicit stress and performance testing rather than routine CI. The routine suite should continue to cover every language and execution surface listed above, including negative, composition and optimiser-differential cases.
