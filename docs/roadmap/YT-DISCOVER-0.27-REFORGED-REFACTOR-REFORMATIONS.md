# yt-discover 0.27.x - Reforged Refactor Reformations

## Purpose

The 0.27.x series restructures Discover before further optimiser and
language expansion. It must preserve the externally observable behaviour
of the accepted 0.26.6 baseline while breaking the current monolithic
implementation into explicit architectural components that can support
acquisition-aware optimisation, richer media metadata and future yt-sql
syntax without accumulating more complexity in `yt-discover.py` or
`yt_media_tools/query.py`.

No 0.27.x phase should intentionally add yt-sql syntax, change query
semantics, change source/facet interpretation, or alter existing
acquisition behaviour except where a bug is independently identified and
fixed with dedicated regression coverage.

## Design principles

-   Keep `yt-discover.py` as a thin executable entry point rather than
    an application framework.
-   Separate parsing, semantic resolution, optimisation, acquisition
    planning and execution.
-   Preserve current types and semantics during extraction wherever
    viable instead of combining refactoring with redesign.
-   Keep source/facet identity, cache/frontier behaviour and provenance
    explicit.
-   Keep extractor-specific behaviour behind source and capability
    abstractions.
-   Preserve SQL-like three-valued NULL logic, temporal infinity, exact
    Unicode behaviour, deterministic ordering and RANDOM semantics.
-   Add automated tests for every deterministic architectural seam that
    can be exercised without external network access.
-   Preserve routine CI speed. Large and huge generated datasets remain
    explicit stress tools rather than routine CI inputs.

## 0.27.0 - Application Shell Extraction

**Status:** Complete.

The executable is now a thin bootstrap into dedicated Discover application
modules. CLI parsing/query preparation, explain/analyse presentation,
acquisition/cache orchestration, output/provenance helpers, shared application
constants and top-level application execution are separated without intentional
query or acquisition semantic changes.

### Scope

Reduce `yt-discover.py` to a small executable layer responsible for
process start-up, dependency wiring and exit status only.

Extract coherent responsibilities into dedicated modules, including:

-   CLI argument parser construction;
-   CLI-specific validation;
-   parameter parsing and binding;
-   query text preparation;
-   explain/analyse command orchestration;
-   acquisition orchestration;
-   cache/frontier coordination;
-   provenance construction and output;
-   append/output-file handling where currently owned by the script;
-   top-level application execution.

### Required behaviour preservation

-   Existing command-line options retain their spelling, defaults and
    precedence.
-   Existing stdout and stderr boundaries remain unchanged.
-   Existing exit codes remain unchanged.
-   No query is reparsed or semantically interpreted by the CLI layer
    beyond existing CLI responsibilities.
-   `--help`, `--examples`, no-argument behaviour and machine-readable
    modes retain their established contracts.
-   The existing harmless no-argument easter egg remains unchanged.

### Testing

-   CLI snapshot or equivalent behavioural tests for representative
    success and failure paths.
-   Exit-status regression coverage.
-   stdout/stderr separation tests.
-   Parameter-binding regression tests.
-   Tests proving extracted modules are used by the executable rather
    than duplicated logic remaining in `yt-discover.py`.

### Completion criterion

`yt-discover.py` is a small application shell and no longer owns
substantial query, acquisition, provenance or formatting logic.

## 0.27.1 - Query Model Extraction

### Scope

Extract the core syntactic and resolved query data structures from
`yt_media_tools/query.py` into stable internal modules.

Separate at least:

-   source-position/span structures;
-   parsed AST nodes;
-   resolved expression nodes;
-   resolved query/relation nodes;
-   type descriptors;
-   temporal values and infinity sentinels;
-   common scalar value helpers;
-   semantic identity/equality helpers used by optimiser logic.

### Constraints

-   Preserve existing object semantics and field names where practical.
-   Avoid broad renaming purely for aesthetic reasons.
-   Preserve canonical formatting behaviour.
-   Keep source positions available for deterministic diagnostics.
-   Do not add a serialised AST or compiled-query format in this phase.

### Testing

-   Existing parser/resolver tests must continue to exercise the
    extracted structures.
-   Equality and semantic-identity regression tests for expressions,
    CASE, aggregates and composed queries.
-   Tests confirming source positions do not affect semantic equivalence
    where the current optimiser intentionally ignores them.

## 0.27.2 - Parser and Formatter Separation

### Scope

Separate text parsing from canonical query formatting.

Parser responsibilities should include:

-   lexical/token handling;
-   expression parsing;
-   SELECT query parsing;
-   CTE parsing;
-   set-operation parsing;
-   source/facet parsing;
-   aggregate/window-ready grammar extension points without implementing
    new syntax;
-   deterministic syntax diagnostics.

Formatter responsibilities should include:

-   canonical rendering of parsed/resolved queries as appropriate;
-   stable keyword and whitespace rules;
-   canonical literal formatting;
-   canonical source/facet formatting;
-   preservation of semantic round-trip behaviour.

### Required invariants

-   Parse-format-parse stability remains corpus-wide.
-   Unicode input is not normalised implicitly.
-   Error locations remain deterministic.
-   Unsupported syntax remains unsupported rather than accidentally
    accepted by parser reorganisation.

### Testing

-   Complete canonical conformance corpus round-trip.
-   Hostile whitespace and nested-expression torture tests.
-   Malformed CTE/UNION/source/facet cases.
-   Unicode delimiter/lookalike and line-separator coverage.

## 0.27.3 - Resolver and Evaluator Separation

### Scope

Separate semantic resolution from local execution.

Resolver responsibilities should include:

-   field lookup and dynamic-field resolution;
-   source/facet schema resolution;
-   type checking;
-   scalar/aggregate function resolution;
-   parameter binding semantics;
-   aggregate validity;
-   CTE scope and schema export;
-   set-operation schema reconciliation;
-   ORDER BY alias/ordinal semantics where currently supported;
-   validation of RANDOM and temporal semantics.

Evaluator responsibilities should include:

-   scalar expression evaluation;
-   three-valued Boolean logic;
-   filtering;
-   projection;
-   grouping/aggregation;
-   HAVING;
-   DISTINCT;
-   sorting;
-   OFFSET/LIMIT;
-   CTE materialisation;
-   UNION/UNION ALL execution.

### Constraints

The resolver must not perform network acquisition. The evaluator must
not reinterpret raw query text.

### Testing

-   Resolver-only negative tests for invalid types, invalid aggregate
    nesting and invalid dynamic fields.
-   Evaluator tests using already-resolved queries and deterministic
    fixture rows.
-   Optimised versus unoptimised evaluation must remain identical.

## 0.27.4 - Source, Facet and Capability Architecture

### Scope

Consolidate the current source/facet architecture into an explicit model
that future optimiser phases can query without relying on
extractor-specific conditionals scattered through the application.

The model should represent:

-   physical source identity;
-   logical source/facet identity;
-   source classification;
-   extractor family/adapter identity;
-   supported logical facets;
-   per-facet logical schema;
-   stable field availability declarations;
-   cache/frontier identity;
-   provenance identity;
-   acquisition capabilities.

### Capability groundwork

Without yet using it for new optimisation, define capability vocabulary
capable of representing facts such as:

-   field structurally unsupported;
-   field logically supported and nullable;
-   field normally available from enumeration;
-   field may require per-entry metadata;
-   source exposes a trustworthy order relevant to a logical field;
-   source supports a stable collection/facet;
-   source can cheaply enumerate identities before deeper metadata.

The capability model must describe what Discover can rely on, not what
yt-dlp happens to do in one observed run.

### yt-dlp boundary

Where yt-dlp provides stable extractor metadata or flags that can be
translated into Discover capabilities, perform translation inside the
adapter layer. Do not leak raw extractor implementation details into
yt-sql semantics.

### Testing

-   Deterministic source classification.
-   YouTube channel/facet capability fixtures.
-   Generic yt-dlp extractor fixtures.
-   Unsupported-facet failures.
-   Cross-facet cache/provenance isolation.
-   Incompatible dynamic-field kind detection.

## 0.27.5 - Planner and Optimiser Boundaries

### Scope

Define an explicit pipeline:

``` text
query text
  -> parser
  -> semantic resolver
  -> semantic property analysis
  -> logical optimiser
  -> acquisition planner
  -> acquisition/extractor adapters
  -> local evaluator
  -> output
```

The property-analysis stage may initially expose only the information
already required by current optimisation. Full expansion is reserved for
0.28.0.

### Architectural rules

-   The optimiser consumes resolved semantic structures.
-   The acquisition planner consumes semantic requirements and source
    capabilities.
-   Extractor adapters receive a physical acquisition request rather
    than a raw query.
-   Local execution consumes acquired logical rows rather than yt-dlp
    dictionaries where practical.
-   Explain output reads plan information rather than reconstructing it
    independently.

### Existing optimisation migration

Move current constant folding, redundant-bound elimination, early LIMIT
logic and related optimisation decisions behind the new
optimiser/planner interfaces without changing their semantics.

### Testing

-   Current optimiser differential suite.
-   Planner snapshot/structural tests for representative queries.
-   Tests that CLI options do not directly alter semantic optimiser
    nodes except through typed policy inputs.

## 0.27.6 - Reforged Reconciliation

### Scope

Perform a dedicated no-new-features audit of the refactored application.

### Required review areas

-   CLI parity;
-   parser parity;
-   formatter parity;
-   resolver parity;
-   evaluator parity;
-   optimiser parity;
-   cache/frontier parity;
-   provenance parity;
-   source/facet identity;
-   generic extractor handling;
-   dynamic fields;
-   aggregates and FILTER;
-   CTEs;
-   UNION/UNION ALL;
-   DISTINCT;
-   OFFSET/LIMIT;
-   RANDOM;
-   temporal values and infinity;
-   Unicode;
-   deterministic diagnostics.

### Cleanup

-   Remove dead transitional imports and aliases.
-   Remove duplicate implementations left behind by extraction.
-   Remove stale compatibility paths that are no longer reachable and
    are not part of supported behaviour.
-   Update architecture documentation to reflect the actual module
    boundaries.
-   Keep README focused on user-visible behaviour rather than internal
    refactoring.

### Exit criterion

0.27.x is complete only when the refactored implementation is observably
equivalent to the accepted 0.26.6 behaviour except for separately
documented bug fixes backed by regression tests.

## Roadmap maintenance

This file is a living programme document. As each sub-phase is
completed, mark it complete and reconcile the description with durable
implemented behaviour. Keep transient local-acceptance notes out of
committed product documentation. During an active version series,
structural cleanup may be deferred until the series closes, at which
point stale notes, duplicated TODOs and obsolete transitional wording
should be removed.

The canonical location for these programme documents is `docs/roadmap/`.
