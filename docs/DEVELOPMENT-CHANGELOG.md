# Development changelog

This file records meaningful changes during active development. It is not release history. When a dot release is completed and accepted, relevant entries are reconciled into the root `CHANGELOG.md` and the completed development section is cleared or advanced for the next work item.

## Discover 0.29.x - Unreleased

### Structured member access - Phase 1

- Add first-class structured type metadata with opaque, declared and dynamic schema shapes.
- Add named structured member contracts with independent member and top-level NULLability.
- Preserve `QueryType.scalar("structured")` as the existing opaque structured-value boundary while enabling declared schemas for later member access.
- Add deterministic member type lookup and nullable-base result propagation without introducing new query syntax or runtime member evaluation.
- Add focused type-model coverage for declared, dynamic, opaque, nested and collection-composed structured values.

### Structured member access - Phase 2

- Add a dedicated postfix structured-member AST node without introducing semantic member resolution or runtime evaluation.
- Parse `.member` after indexed, function-valued and parenthesised scalar expressions, including chained and interleaved indexing/member postfix operations.
- Preserve established bare dotted field paths such as `raw.extra.score` while adding explicit postfix member syntax for structured-producing expressions.
- Extend canonical scalar formatting and parse-format-parse coverage for structured member expressions.
- Add deterministic diagnostics for missing or malformed postfix member names.
