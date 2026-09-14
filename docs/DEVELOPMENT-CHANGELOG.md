# Development changelog

This file records meaningful changes during active development. It is not release history. When a dot release is completed and accepted, relevant entries are reconciled into the root `CHANGELOG.md` and the completed development section is cleared or advanced for the next work item.

## Discover 0.29.x - Unreleased

### Collection querying beyond indexing - Phase 1

- Add a syntax-neutral lexical scope model for collection elements that preserves exact element types and supports deterministic nested outer-scope addressing.
- Define collection-level and element-level NULLability as distinct semantic concerns without changing collection ordering contracts.
- Define existential and universal collection predicate reduction using exact SQL three-valued logic, including NULL collections, nullable predicate results and empty-collection identities.
- Keep user-facing binding syntax deliberately undecided so later parser work can lower into the semantic scope model without changing its contracts.
