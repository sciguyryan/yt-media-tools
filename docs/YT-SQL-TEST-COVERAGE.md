# yt-sql test coverage

This document records the major yt-sql language and execution surfaces that must remain covered. It is the durable test-completeness inventory used when reviewing regressions and future language changes.

## Coverage standard

A language feature is not considered thoroughly covered merely because its happy path parses. Where applicable, coverage should include parsing, semantic resolution, execution, formatting round-trips, malformed input, NULL behaviour, Unicode behaviour, optimiser differential equivalence, composition through CTEs and set operations, and observable CLI behaviour.

Optimiser tests must compare the complete observable result of optimised and unoptimised execution. The routine conformance corpus also enforces optimiser idempotence across every directly resolved semantic case and canonical parse-format-parse stability across every directly parsed case. Parameter binding remains a CLI-boundary contract with dedicated tests before parsing.

## Grammar and scalar expressions

Current dedicated coverage includes SELECT projection, aliases, SELECT *, arithmetic and precedence, parenthesised expressions, CASE, LOWER, UPPER, LENGTH, COALESCE, CONCAT, NULLIF, GREATEST, LEAST, CHAR, RANDOM, decimal and non-decimal integer literals, query parameters, and malformed scalar-function calls.

Torture coverage additionally combines deeply parenthesised scalar and Boolean expressions, hostile whitespace, CASE with nested functions and mixed-base literals, malformed CASE boundaries, malformed function argument lists, and parse-format-parse stability.

## Typed collections and indexing

Current dedicated coverage includes collection type descriptors, element NULLability, stable versus unknown ordering, postfix parsing and chaining, canonical formatting, resolver type checks, zero-based evaluation, NULL and out-of-range results, integer and negative-index diagnostics, collection-valued functions and parentheses, raw ordered sequences, structured-value regression boundaries, scalar WHERE comparisons, `IS NULL`, output serialisation, explain metadata and acquisition-stage planning.

The deterministic conformance generator includes first-class taxonomy collections and backend-specific raw ordered sequences. Independent oracle cases cover logical ordering, direct indexing, NULL collections, NULL indexes, out-of-range access, JSON array output, raw indexing and CLI parameter binding against indexed results. Routine conformance continues to compare optimised and unoptimised execution and enforce canonical parse-format-parse stability for directly parsed collection cases.

Acquisition tests require whole-collection fallback unless an explicit backend capability proves that partial indexed acquisition is semantically identical to local indexing of the complete yt-sql logical collection. Unknown backend ordering must never become a positional language guarantee.

## Collection querying beyond indexing

Dedicated coverage now includes lexical collection-element scopes, nested outer references and shadowing, exact existential/universal three-valued truth tables, NULL and empty collections, nullable elements, `CARDINALITY`, scoped `COUNT`, `FILTER`, `MAP`, structured members, raw ordered collections, exact filtered/projected outputs, ordering-contract preservation, optimiser traversal, canonical formatting and deterministic invalid-operand diagnostics. Aggregate `COUNT` and aggregate `FILTER (WHERE ...)` have explicit regression checks so the new scoped forms remain semantically distinct.

The deterministic conformance generator version 6 adds empty collections, nullable collection elements, explicit filtered-value anchors, structured format collections and dynamic raw sequences suitable for nested collection scopes. Independent oracle cases cover `ANY`, `ALL`, empty-versus-NULL quantifier behaviour, cardinality, scoped count, exact filtering, projection, FILTER/MAP composition, structured member predicates, dynamic raw collection pipelines, nested bindings with outer references, optimiser equivalence, canonical parse-format-parse stability and real offline CLI execution. The oracle expresses these operations directly over ordinary Python lists and dictionaries without importing production collection semantics, resolver or evaluator code.

Acquisition-planning coverage records each collection operation separately, tracks correlated outer-row dependencies, requires every composed operation to have an explicit exact backend capability before pushdown, and verifies whole-collection fallback for current adapters. Synthetic exact-capability tests prove the optimisation path without changing default backend behaviour.

## Structured values and member access

Current dedicated coverage includes opaque, declared and dynamic structured type shapes, member NULLability, postfix parsing and chaining, distinction from legacy dotted field paths, canonical formatting, direct/nested/indexed/function-valued resolution, deterministic unknown-member and invalid-operand diagnostics, runtime dictionary-only evaluation, SQL NULL propagation, predicate participation, closed format/chapter/thumbnail schemas, dynamic raw schema inference, incompatible-shape rejection and acquisition requirement propagation.

Structured acquisition tests separately cover exact member capability, indexed-member capability composition, dynamic-index rejection, indexed-record fallback and complete containing-structure fallback. Current adapters are expected to remain on the conservative fallback path unless they explicitly prove stronger semantics.

The deterministic conformance generator version 5 adds compatible dynamic raw structured records, nested structured members and ordered raw record sequences. Independent oracle cases cover direct member access, nested member access, indexed record members, missing and NULL members, predicate use, optimiser equivalence, canonical formatting and real offline CLI execution. The oracle expresses member lookup and NULL propagation directly over ordinary Python dictionaries and does not import the production type, schema, resolver or evaluator implementation.

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

Cost/selectivity heuristic coverage checks safe AND-term reordering, stable ordering for equal-ranked terms, detailed-stage deferral behind cheap authoritative filters, very-high cost classification for dynamic raw metadata, zero-cost empty relations, consistency with the established planner cost classes, and human/JSON explain observability. Residual and unsafe predicate forms remain covered by the staged-predicate differential and NULL-semantics suites.

Explain-presentation coverage checks explicit schema versioning, deterministic decision/graph construction, semantic ANSI colour that can be disabled completely, `NO_COLOR`, automatic Unicode/ASCII fallback, deterministic Graphviz DOT generation, human plan-overview integration, and JSON output free from ANSI escape sequences. Graphviz SVG generation is exercised separately as an optional-tool smoke check rather than making the external renderer a prerequisite for the ordinary Python test suite.

0.28 differential reconciliation adds a cross-surface semantic corpus that executes deterministic resolved queries before and after optimisation and requires identical complete results plus optimiser idempotence. The corpus covers NULL and three-valued logic, Unicode, temporal infinity and relative dates, alternate-base numeric forms, CASE/scalar expressions, aggregate FILTER, GROUP BY/HAVING, CTEs, UNION/UNION ALL, heterogeneous source schemas, source/facet identity, DISTINCT, LIMIT/OFFSET and seeded RANDOM. It also checks canonical format/parse stability, repeated deterministic syntax errors, generated equivalent Boolean transformations and a mutation-style sensitivity matrix for representative unsafe rewrites. Volatile RANDOM is tested structurally rather than through repeated result equality.

Acquisition torture coverage checks empty-branch skipping, ordering barriers to LIMIT termination, detailed-stage termination, bounded temporal frontiers, deferred expensive metadata, independent cross-facet boundaries, CTE physical-requirement pruning, same-source requirement reconciliation, dynamic raw metadata and volatile random ordering. Existing semantic-property tests remain the authority for distinguishing structurally unavailable metadata from not-yet-acquired metadata, and the 0.28.13 corpus repeats that invariant at the reconciliation boundary.

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
