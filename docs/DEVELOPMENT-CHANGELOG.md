# Development changelog

This file records meaningful changes during active development. It is not release history. When a dot release is completed and accepted, relevant entries are reconciled into the root `CHANGELOG.md` and the completed development section is cleared or advanced for the next work item.

## Discover 0.29.x - Issue #2 typed collections and indexing

### Phase 1 - Typed collection semantics

- Added first-class collection types with declared element types, element NULLability, top-level NULLability and explicit ordering contracts.
- Established zero-based indexing semantics, NULL/out-of-range behaviour and conservative positional-order requirements.

### Phase 2 - Postfix indexing syntax

- Added postfix `[index]` parsing, AST representation and canonical formatting.
- Allowed indexing to compose with parenthesised and function-valued expressions without changing existing precedence unexpectedly.

### Phase 3 - Semantic resolution and evaluation

- Resolved index expressions against collection-valued operands and enforced integer, non-negative index requirements.
- Added runtime indexing with SQL NULL propagation and out-of-range NULL results.
- Integrated index nodes with semantic, optimiser and field-requirement traversal.

### Phase 4 - Collection fields and backend capabilities

- Modelled tags, categories, formats, chapters and thumbnails as typed collections.
- Defined backend-independent lexical ordering for tags and categories while leaving structured collection order unknown.
- Published collection type and ordering contracts through source capabilities and collection-specific acquisition stages.

### Phase 5 - Indexed acquisition planning

- Preserved direct indexed access as a precise metadata requirement separate from whole-collection use.
- Allowed partial indexed acquisition only behind explicit exact-capability proof, with conservative full-collection fallback otherwise.
- Carried indexed requirements through source-boundary, physical planning and explain output.

### Phase 6 - Dynamic raw collection indexing

- Allowed ordered `raw.*` list and tuple values to be indexed, including nested collections and arrays of opaque structured records.
- Kept raw sequence ordering backend-specific rather than promoting it into first-class yt-sql logical ordering.
- Rejected mappings, sets, scalar values and inconsistent dynamic shapes conservatively and deterministically.
- Preserved raw indexed requirements for planning while retaining local full-collection evaluation unless exact backend capability is proven.
- Preserved the existing prohibition on directly selecting opaque structured raw values; indexing does not promote arrays of records into selectable structured values.

### Phase 7 - Collection output and explain

- Serialised collection values as JSON arrays, including stable JSON array syntax for single-field line output.
- Exposed collection type, element type, logical ordering and positional-indexing capability in human and machine-readable explain output.
- Kept acquisition details tied to the physical plan, including whether exact indexed acquisition is available or full collection acquisition is required.

### Phase 8 - Conformance, integration and documentation

- Extended the deterministic conformance generator with typed taxonomy collections and backend-specific raw ordered sequences, advancing the generator contract to version 4.
- Added independent oracle coverage for direct indexing, NULL and out-of-range behaviour, collection JSON output, raw indexing and CLI parameter binding against indexed expressions.
- Reconciled WHERE parsing, resolution and evaluation so indexed scalar expressions can participate in comparisons and `IS NULL` predicates without weakening existing field-specific predicate semantics.
- Restored the established `Expected a field name.` diagnostic for empty WHERE and aggregate FILTER predicates after general scalar predicate integration.
- Preserved the scalar-only `SELECT *` contract by excluding dynamically inferred collection fields from star expansion.
- Added parser, resolver, evaluator and parameter-binding regression tests for indexed WHERE expressions and parenthesised collection operands.
- Expanded the yt-sql reference, test-coverage inventory, conformance documentation and CLI examples for collection indexing, ordering, output and acquisition semantics.
