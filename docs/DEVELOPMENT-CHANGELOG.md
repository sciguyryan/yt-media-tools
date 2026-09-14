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

### Structured member access - Phase 3

- Resolve postfix member access against declared and known dynamic structured-value schemas while preserving opaque structured values as inaccessible until a member schema exists.
- Propagate declared member types and nullable structured bases through resolved member expressions, including nested member chains and indexed structured elements.
- Preserve structured types through `COALESCE` and `NULLIF` where compatible so function-valued structured expressions can participate in member access.
- Reject non-structured operands and unknown structured members with deterministic semantic diagnostics while keeping bare dotted fields semantically distinct from postfix member access.
- Extend semantic identity, aggregate/random traversal, optimiser traversal and expression-property analysis to recognise resolved structured member expressions without adding runtime evaluation.
- Add focused semantic-resolution coverage for direct, nested, indexed, function-valued, dynamic, opaque, invalid and dotted-field cases.
