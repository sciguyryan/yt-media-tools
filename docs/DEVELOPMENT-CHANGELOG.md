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

### Structured member access - Phase 4

- Evaluate resolved structured member expressions against metadata dictionaries while preserving the semantic type boundary established by resolution.
- Propagate SQL NULL from nullable structured bases and missing runtime members, including nested member chains and indexed structured elements.
- Support structure-preserving function results such as `COALESCE` during runtime member evaluation.
- Reject arbitrary Python objects and non-dictionary runtime values at the evaluator boundary rather than using attribute access or generic mapping protocols.
- Extend focused runtime coverage across direct, nested, indexed, function-valued, dynamic, NULL and predicate member access.

### Structured member access - Phase 5

- Define closed yt-sql member schemas for first-class format, chapter and thumbnail records without mirroring arbitrary backend dictionaries.
- Type format members for identifiers, dimensions, codecs, rates, sizes, language and related stable metadata, with extractor-dependent values remaining nullable.
- Type chapter title and temporal bounds plus thumbnail identity, URL and dimensions as nullable structured members.
- Preserve the existing unknown logical ordering contract for structured collections, so declaring members does not make positional indexing valid.
- Keep dynamic `raw.*` structured collection elements opaque and separate from the stable first-class metadata schemas.
- Add focused schema and explain coverage for declared members, NULLability, backend-specific exclusions, raw opacity and unchanged ordering semantics.

### Structured member access - Phase 6

- Add precise structured member acquisition requirements that preserve the physical root field, nested member path and direct indexed-access context.
- Propagate structured member requirements through query properties, metadata requirement planning, source-boundary unioning and physical acquisition requests without treating member access as whole-structure consumption.
- Add explicit source capability declarations for exact structured member acquisition while keeping all current adapters conservative by default.
- Permit member-specific acquisition only when the selected adapter proves exact member semantics and, for indexed member access, exact positional acquisition semantics as well.
- Fall back to exact indexed containing-record acquisition or full containing-structure acquisition whenever member-level equivalence cannot be proven, and never partially acquire a dynamically indexed member path.
- Add focused acquisition-planning coverage for nested member requirements, indexed/member composition, whole-structure conflicts, current-backend fallback and capability-gated precise acquisition.

### Structured member access - Phase 7

- Infer conservative dynamic member schemas for genuinely structured `raw.*` dictionaries and ordered raw record collections.
- Support postfix member access through direct raw records, indexed raw structured collections and recursively nested dynamic structures while preserving SQL NULL propagation.
- Expose only string-keyed members whose observed runtime values have one compatible yt-sql shape, treating missing members as nullable and omitting incompatible members from the dynamic schema.
- Preserve opaque structured typing when provider records cannot be described safely, including non-string-keyed shapes, rather than coercing uncertain values into ordinary scalars.
- Keep whole raw structured values non-selectable so dynamic member inference does not weaken the existing structured-value boundary.
- Add focused coverage for direct, indexed, nested, nullable, incompatible, opaque and predicate dynamic raw member access.

### Structured member access - Phase 8

- Extend the deterministic conformance generator to version 5 with dynamic raw structured records, nested records, nullable members and ordered raw record sequences.
- Add independent-oracle conformance cases for direct, nested and indexed structured member access, NULL propagation, predicate use, optimiser equivalence, canonical formatting and offline CLI execution.
- Expand the yt-sql reference with structured value semantics, closed first-class metadata schemas, dynamic raw inference boundaries, member-access examples and acquisition fallback rules.
- Expand Discover usage and durable test-coverage documentation for structured member access without changing the root release changelog or Discover version.
