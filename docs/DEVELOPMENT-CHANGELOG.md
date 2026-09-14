# Development changelog

This file records meaningful changes during active development. It is not release history. When a dot release is completed and accepted, relevant entries are reconciled into the root `CHANGELOG.md` and the completed development section is cleared or advanced for the next work item.

## Discover 0.29.x - Unreleased

### Collection querying beyond indexing - Phase 1

- Add a syntax-neutral lexical scope model for collection elements that preserves exact element types and supports deterministic nested outer-scope addressing.
- Define collection-level and element-level NULLability as distinct semantic concerns without changing collection ordering contracts.
- Define existential and universal collection predicate reduction using exact SQL three-valued logic, including NULL collections, nullable predicate results and empty-collection identities.
- Keep user-facing binding syntax deliberately undecided so later parser work can lower into the semantic scope model without changing its contracts.

### Collection querying beyond indexing - Phase 2

- Add contained `ANY(collection AS binding WHERE predicate)` and `ALL(...)` syntax for collection predicates without introducing a general lambda language.
- Add explicit syntax-level collection predicate and lexically bound element-reference nodes with deterministic scope-distance tracking.
- Resolve binding references lexically during parsing, including nested outer references and innermost shadowing, while preserving ordinary row-field lookup for unbound identifiers.
- Support structured-member and postfix expression composition from bound collection elements without changing established bare dotted field-path parsing.
- Add canonical formatting, round-trip coverage and deterministic malformed-binding diagnostics for collection predicate syntax.

### Collection querying beyond indexing - Phase 3

- Resolve `ANY` and `ALL` collection operands against the yt-sql type model and retain exact bound element types through lexical scopes.
- Evaluate existential and universal predicates with the Phase 1 SQL three-valued reducers, including NULL collections, nullable elements, UNKNOWN predicate results and empty-collection identities.
- Support nested quantifiers, outer element references, ordinary outer-row fields and structured member access during runtime collection predicate evaluation.
- Carry collection predicates through semantic identity and expression-property analysis so required source fields remain visible to acquisition planning while bound elements remain local values.
- Reject non-collection quantifier operands deterministically without introducing count, filtering or projection semantics.

### Collection querying beyond indexing - Phase 4

- Add `CARDINALITY(collection)` for total collection size, counting NULL elements while preserving NULL collections as SQL NULL.
- Add scoped `COUNT(collection AS binding WHERE predicate)` without changing established aggregate `COUNT(expr)` or `COUNT(*)` semantics.
- Count only TRUE element-predicate results so FALSE and UNKNOWN remain excluded unless the predicate explicitly tests for NULL.
- Propagate exact integer result NULLability from the collection operand and preserve empty collections as a deterministic zero count.
- Integrate collection counts with lexical binding, semantic identity, optimiser traversal and expression-property analysis so source requirements remain accurate.
- Add focused coverage for NULL and empty collections, nullable elements, outer-row references, aggregate-count compatibility, canonical formatting and deterministic invalid-operand diagnostics.

### Collection querying beyond indexing - Phase 5

- Add `FILTER(collection AS binding WHERE predicate)` as a collection-valued scoped expression using the established lexical element-binding model.
- Preserve the input collection's exact element type, top-level NULLability and logical ordering contract in the filtered result.
- Keep only elements whose predicate evaluates to TRUE, excluding FALSE and UNKNOWN while allowing explicit NULL predicates to retain nullable elements.
- Preserve SQL NULL for NULL collections and return an empty collection for empty inputs without manufacturing ordering guarantees.
- Integrate filtered collections with semantic identity, optimiser traversal and expression-property analysis so source requirements and outer-row references remain visible.
- Add focused coverage for order preservation, NULL and empty collections, nullable elements, structured/nested predicates, postfix indexing, canonical formatting and deterministic invalid operands.

### Collection querying beyond indexing - Phase 6

- Add MAP collection projection using the established lexical element-binding model.
- Derive projected collection element types from the projection expression while preserving source collection NULLability and logical ordering.
- Support scalar, structured and nested collection projection results, including composition with FILTER and nested collection scopes.
- Keep MAP contextual and preserve conservative positional-indexing rules after projection.
- Add focused coverage for exact projected results, NULL and empty collections, nested scopes, ordering, typing, formatting, optimiser traversal and invalid operands.

### Collection querying beyond indexing - Phase 7

- Add explicit collection-query acquisition requirements for `ANY`, `ALL`, `CARDINALITY`, scoped `COUNT`, `FILTER` and `MAP`, rooted at their physical metadata collection.
- Record outer-row dependencies separately from bound element references so correlated collection expressions cannot be mistaken for self-contained backend operations.
- Propagate collection-query requirements through query properties, metadata requirements, source-boundary unioning and physical acquisition requests.
- Add operation-specific exact collection-query capability declarations as a strong adapter contract covering yt-sql NULL handling, three-valued predicates, ordering and result typing.
- Permit collection-query pushdown only when every required operation for the collection is explicitly exact and uncorrelated, otherwise acquire the complete containing collection for exact local evaluation.
- Preserve current adapter behaviour by advertising no collection-query pushdown capabilities by default.
- Add focused acquisition-planning coverage for operation requirements, composed FILTER/MAP pipelines, current-backend fallback, capability-gated pushdown, correlated expressions and whole-collection conflicts.

### Collection querying beyond indexing - Phase 8

- Extend the deterministic conformance generator to version 6 with empty collections, nullable elements, explicit filter anchors, declared structured format collections and dynamic raw sequences for nested scope coverage.
- Add independent-oracle conformance cases for `ANY`, `ALL`, `CARDINALITY`, scoped `COUNT`, exact `FILTER` and `MAP` results, FILTER/MAP composition, structured collections, dynamic raw collections and nested outer binding references.
- Exercise collection-query semantics through canonical formatting, optimiser equivalence and real offline CLI execution while preserving focused evaluator truth-table coverage for exact TRUE, FALSE and UNKNOWN quantifier results.
- Document lexical binding, three-valued semantics, NULL and empty collection behaviour, filtering and projection typing/order preservation, and conservative acquisition pushdown requirements.
- Reconcile Discover usage, optimisation, test-coverage and conformance architecture documentation with the implemented collection-query language.
