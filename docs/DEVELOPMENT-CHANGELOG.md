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
