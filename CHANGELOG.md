# Changelog

## Downloader 1.12.0 - Queue State

- Add conservative queue outcome accounting for requested, already archived, newly completed and unresolved targets.
- Print a concise queue summary after file-backed completion-removal runs.
- Add `--queue-report FILE` for deterministic machine-readable JSON outcome reports.
- Add `--failed-targets FILE` for atomically generated reusable unresolved-target batch files.
- Preserve unresolved queue entries on failed or interrupted runs and identify interruption explicitly in JSON reports.
- Keep unavailable, skipped and failed classifications deliberately unresolved until the executor can establish those per-target outcomes reliably.
- Add deterministic tests for queue snapshots, outcome classification, interruption and atomic report generation.
- Add simulated end-to-end executor tests proving queue, archive, report and retry-file behaviour for partial failure and interruption.

## Downloader 1.11.0 - Alongside

- Add typed manual/automatic subtitle policy, language and format selection, and independent subtitle embedding.
- Add opt-in thumbnail and info-JSON sidecars plus independent thumbnail embedding.
- Make metadata and chapter embedding explicit typed policy while preserving the established enabled-by-default behaviour.
- Make SponsorBlock policy explicit, preserving remove-all as the built-in default while supporting validated mark/remove categories and complete disabling.
- Expose associated-artefact, metadata, chapter and SponsorBlock decisions through human and JSON explanation.
- Add deterministic tests for historical defaults, explicit disablement, profile precedence, SponsorBlock validation and command compilation.
- Reconcile the shipped parameter-profile example with the 1.10.0 defaults file so it no longer shows removed redundant raw format selectors.

## Downloader 1.10.0 - Selection Rules

- Add declarative hard bounds for minimum/maximum resolution and frame rate, compiled into yt-dlp format filters.
- Add fallback-friendly preferences for video codec, audio codec, frame rate, HDR class and audio channel count using yt-dlp format sorting.
- Add merge-container policy using `--merge-output-format` without silently remuxing or transcoding media.
- Keep raw `-f/--format` selectors authoritative by rejecting combinations with hard declarative format constraints instead of rewriting expert expressions.
- Expose the resolved generated selector, sort order, format bounds, preferences and merge container through human and JSON explanation.
- Remove redundant raw format selectors from the shipped parameter profiles so their effective behaviour continues to inherit Downloader's built-in selector.
- Add deterministic format-policy tests for validation, precedence, selector compilation, sorting, raw-selector authority and explanation output.

## Downloader 1.9.0 - Known Limits

- Expand typed parameter-profile and CLI policy for rate limiting, throttling, fragment concurrency and retry behaviour.
- Add configurable download-archive and temporary paths while preserving the existing built-in defaults.
- Add repeatable retry-sleep and extractor-argument settings with strict JSON typing and explicit CLI precedence.
- Add browser-cookie selection as a first-class authentication source alongside cookie files, automatic cookies and explicit cookie disabling.
- Extend resolved plans and explain output with operational policy, authentication and path decisions, redacting sensitive extractor-argument values from explanation output.
- Keep queue reconciliation bound to the resolved archive path rather than the historical script-local constant.
- Add deterministic coverage for profile validation, precedence, command compilation and explain output.

## Downloader 1.8.0 - Clear Intent

- Separate resolved Downloader configuration from command execution with an explicit immutable download-plan model.
- Add `--explain` and `--explain-json` so effective profiles, policy, authentication, paths, queue behaviour and the final yt-dlp command can be inspected without execution.
- Record whether effective parameter values came from a selected parameter profile or an explicit command-line override.
- Keep `--dry-run` as the exact command-only surface while routing normal execution through the same resolved plan.
- Add deterministic plan-level tests for precedence provenance, command equivalence and human/machine-readable explanation.
- Remove the completed parameter-profile implementation work from the project TODO list.

## Discover 0.26.6 - No Loose Ends

- Complete the cleanup, optimiser and test-completeness reconciliation without adding yt-sql syntax.
- Remove stale release-phase narration and duplicated version claims from current reference documentation, keeping historical sequencing in the changelog.
- Add corpus-wide canonical parse-format-parse stability checks for every directly parsed conformance query.
- Add corpus-wide optimiser idempotence checks for every routine directly resolved semantic case.
- Extend the optimiser with exact duplicate-term and double-negation simplification inside HAVING, preserving three-valued logic and aggregate semantics.
- Extend semantic AST identity to scalar, aggregate and CASE expressions so position metadata cannot prevent safe equivalence checks.
- Reconcile the durable coverage and optimisation references with the implemented source/facet, aggregate and optimiser contracts.
- Give the split GitHub Actions workflows distinct display names while preserving their independent files and jobs.

## Discover 0.26.5 - Pressure Test

- Continue the post-0.26.2 hardening programme without adding or changing yt-sql syntax.
- Add a living yt-sql coverage inventory spanning grammar, semantics, optimiser equivalence, composition, source/facet identity, Unicode, aggregation, malformed input and observable execution behaviour.
- Add deliberate hostile-whitespace and deeply parenthesised parse/format round-trip coverage.
- Add dense scalar/Boolean optimiser differential and idempotence coverage over the deterministic Unicode fixture.
- Add chained CTE, aggregate and HAVING torture coverage.
- Add the first executable Sadness Query combining cross-facet UNION ALL, chained CTEs, Unicode-sensitive predicates, CASE, mixed-base arithmetic, seeded RANDOM and outer aggregation.
- Expand deterministic malformed-input torture coverage across clause boundaries, CTEs, UNION, CASE, aggregate FILTER, RANDOM, CHAR and LIKE escaping.
- Reject empty CTE bodies explicitly instead of allowing them to fall through into an implicit relation during resolution.
- Keep grammar and feature expansion frozen pending final hardening reconciliation.
- Remove stale phase and acceptance narration from long-lived documentation and express current behavioural contracts in present tense.

## Discover 0.26.4 - Measured Cuts

- Complete the dedicated optimiser-audit phase without adding or changing yt-sql syntax.
- Deduplicate literal `IN` members, collapse singleton `IN` and `NOT IN`, and remove provably subsumed same-field membership predicates while preserving NULL/UNKNOWN behaviour.
- Add a direct exact-match execution path for case-sensitive `LIKE` patterns that contain no unescaped wildcard, preserving exact Unicode and escaping semantics without invoking the regular-expression engine.
- Extend proof-based LIMIT-aware acquisition termination to source-order `OFFSET` queries by stopping only after `OFFSET + LIMIT` authoritative matches have been observed.
- Add direct differential and idempotence coverage for membership rewrites, exact-LIKE fast paths and LIMIT-plus-OFFSET planning.
- Audit tempting but unsafe rewrites, including contradiction folding, volatile RANDOM simplification, Unicode case substitutions and symbolic arithmetic identities with observable floating-point edge cases.
- Keep new syntax frozen pending the exhaustive completeness and torture-test phase.

## Discover 0.26.3 - Quiet Sweep

- Begin the post-0.26.2 hardening programme without adding or changing yt-sql syntax.
- Remove unused scalar compatibility wrappers, an unused metadata-output helper, an unused schema helper and an unused unit-registry constructor.
- Remove the stale package-level `__version__` value so `PROGRAM_VERSION` remains the single application version authority.
- Remove the unused legacy source-resolver import from the Discover CLI while preserving the intentional compatibility resolver API and `--tab` behaviour.
- Add the project-local pinned `markdownlint-cli2` development dependency and npm lint script, with `node_modules/**` excluded by the shared Markdown lint configuration.
- Audit production definitions, imports, module-level constants and explicit TODO/FIXME/HACK markers for dead or stale implementation artefacts.
- Preserve behaviour, grammar, source/facet semantics and the split GitHub Actions workflow organisation unchanged.

## Discover 0.26.2 - Crossing Streams

- Remove the temporary same-source cross-facet composition restriction now that each physical source/facet request has an independent execution identity.
- Key per-source query schemas by both physical source and logical facet so heterogeneous metadata cannot leak between branches.
- Tag acquired records with their logical facet and filter UNION/CTE inputs by the complete source/facet identity.
- Keep cache, coverage and frontier state isolated through each facet's independently resolved canonical acquisition URL.
- Include the logical facet in deterministic seeded `RANDOM(seed)` row identity so the same media ID in different facets remains independently reproducible.
- Preserve per-request acquisition counts and facet provenance when one physical source appears through several facets.
- Add same-source cross-facet UNION, UNION ALL, CTE, aggregate, Unicode, schema, seeded-randomness and global LIMIT/OFFSET regression coverage.
- Preserve the split Ruff, pytest and Markdown lint GitHub Actions workflows.
- Complete the planned 0.26.x source/facet series and freeze further syntax work pending the dedicated test-completeness and parser-torture review.

## Discover 0.26.1 - One Path

- Separate physical source classification, logical capability discovery and facet-to-acquisition mapping into explicit source-layer stages.
- Add deterministic `SourceCapabilities` metadata so the query/planner layer can reason about advertised logical facets without knowing extractor URL details.
- Route legacy `--tab` values through the same canonical facet request used by yt-sql `OF`; matching `OF`/`--tab` requests resolve identically and conflicts continue to fail closed.
- Report source adapter names and advertised facets through explain output and provenance.
- Improve unsupported-facet diagnostics by naming the active adapter and the exact facets it advertises.
- Preserve the user's split GitHub Actions workflow files for Ruff, pytest and Markdown linting.
- Keep same-source cross-facet composition disabled until the 0.26.2 identity/composition hardening pass.

## 0.26.0 - OF Origins

### Discover

- Add `FROM <source> OF <facet>` as the extractor-agnostic source collection syntax.
- Route `OF videos`, `OF shorts` and `OF live` through the existing YouTube channel acquisition adapter.
- Preserve bare `FROM <source>` as the default collection and keep `--tab` as a compatibility surface over the same facet model.
- Reject unsupported physical-source facets, conflicting `OF`/`--tab` requests and attempts to apply `OF` to CTE result relations.
- Add deterministic source/facet grammar and capability tests covering CTE and UNION composition.
- Fail closed when one composed query requests multiple facets of the same physical source until cross-facet cache and schema identity are hardened.
- Refresh the TODO roadmap and freeze further syntactic sugar until the post-0.26.2 test-completeness review.

## Discover 0.25.3 - Random Rendezvous

- Add `RANDOM()` for volatile per-execution row ordering and projected synthetic values.
- Add `RANDOM(seed)` with deterministic row-stable values derived from the integer seed and stable logical row identity rather than evaluation order.
- Permit RANDOM in scalar projection and ordering contexts, including aliases, CTEs and UNION-derived relations, while rejecting grouping and HAVING placement and retaining existing predicate grammar restrictions.
- Keep RANDOM calls opaque to constant folding and deterministic scalar rewrites, and preserve complete-result acquisition for explicit random ordering.
- Materialise projected random aliases so the value displayed to the user is the same value used by `ORDER BY` within that execution.
- Add a pinned markdownlint-cli2 GitHub Actions job, enforcing the established MD001 heading-increment and MD012 multiple-blank-line rules across project Markdown.

## Discover 0.25.2 - Composition Crucible

- Harden `UNION` and `UNION ALL` across CTEs, aggregation, global ordering, LIMIT/OFFSET and heterogeneous extractor-shaped logical relations without adding new grammar.
- Add a reusable deterministic multi-source fixture covering channel-like, playlist-like and Twitch-like records, including missing metadata, duplicate logical rows, Unicode normalisation distinctions and deliberately incompatible dynamic field kinds.
- Preserve already-materialised aggregate rows across set-operation boundaries so aggregate UNION branches are not accidentally evaluated a second time.
- Keep execution-only CTE and aggregate row markers internal to the query engine and prevent them from leaking into public query results.
- Record per-source acquired-row counts in provenance for composed acquisitions while retaining the existing single-source provenance fields.
- Strengthen Unicode torture coverage by using the Welsh flag tag sequence and verifying LIKE `_` continues to count Unicode code points rather than displayed grapheme clusters.

## Discover 0.25.1 - Union Uprising

- Add positional `UNION` and `UNION ALL` composition across ordinary queries and non-recursive CTEs.
- Reconcile branch schemas by column position, retain output names from the first branch, promote compatible numeric kinds, and reject incompatible projected types.
- Allow a composed query to acquire multiple physical yt-dlp sources independently before logical reconciliation, preserving source identity internally through normalisation.
- Add per-source schema resolution so heterogeneous extractor metadata is type-checked before set composition rather than collapsed into one mixed acquisition schema.
- Apply global `ORDER BY`, `OFFSET` and `LIMIT` after the complete set expression and disable source-order early LIMIT termination for UNION queries.
- Extend optimiser traversal, physical-field planning, explain output and deterministic heterogeneous-source tests across channel-like, playlist-like and Twitch-like source shapes.
- Run the routine pytest suite automatically in GitHub Actions alongside Ruff while retaining `scale` and `stress` exclusions from normal CI.

## Discover 0.25.0 - Common Ground

- Add non-recursive `WITH` common table expressions with declaration-order scoping and case-insensitive CTE references.
- Materialise each CTE as a logical yt-sql result relation whose exported column names and resolved scalar kinds define the schema visible to later CTEs and the outer query.
- Allow CTEs to contain ordinary filtering, scalar projection, aggregation, `GROUP BY`, `HAVING`, ordering, DISTINCT, LIMIT and OFFSET using the established query semantics.
- Reject recursive CTEs, self-reference, forward references, nested `WITH` clauses and multiple physical extractor sources in this foundation release.
- Resolve the one physical extractor source through CTE chains so outer `FROM cte_name` queries do not mistake a logical relation for an external source.
- Extend optimiser traversal, physical-field planning, deterministic conformance and independent-oracle differential coverage across chained CTE execution.

## Discover 0.24.0 - Aggregate Ascent

- Add `COUNT(*)`, `COUNT(expr)`, `SUM`, `AVG`, `MIN` and `MAX` with SQL-like NULL elimination and deterministic empty-input behaviour.
- Add `GROUP BY` with normalisation-sensitive Unicode grouping and deterministic first-source-occurrence group order when no `ORDER BY` is present.
- Add aggregate-aware `HAVING` comparisons, Boolean composition, NULL tests and references to explicit SELECT aliases.
- Add SQL-style aggregate `FILTER (WHERE ...)`, evaluated over rows that survive the ordinary query `WHERE` predicate.
- Require non-aggregate projected and ordered expressions in aggregate queries to match a `GROUP BY` expression, reject nested aggregates, and keep `SELECT *` out of aggregate queries.
- Prevent limit-aware early acquisition termination for aggregate queries because complete input groups are required before final row shaping.
- Extend deterministic conformance, independent oracle coverage, Unicode grouping/extrema checks, optimiser differential verification and negative aggregate validation.

## Discover 0.23.8 - Schema Star

- Add `SELECT *` with deterministic expansion over canonical built-in scalar fields followed by observed top-level dynamic scalar fields in case-insensitive lexical order.
- Exclude aliases and `raw.*` paths from star expansion so values are not duplicated and extractor-internal metadata is not unexpectedly projected.
- Require `SELECT *` to stand alone rather than mixing it with explicit expressions or aliases.
- Make star expansion participate in ordinary acquisition-cost analysis, `DISTINCT`, output serialisation, provenance and optimiser differential checks after semantic resolution.

## Discover 0.23.7 - Scalar Summit

- Add `NULLIF`, `GREATEST` and `LEAST` as first-class scalar functions in projections, ordering expressions and nested scalar expressions.
- Define `NULLIF(a, b)` to return NULL only when the comparison is TRUE; UNKNOWN comparisons caused by NULL preserve the first argument.
- Require `GREATEST` and `LEAST` to receive at least two compatible scalar arguments and propagate NULL when any argument is NULL.
- Preserve exact, normalisation-sensitive Unicode ordering for textual extrema rather than introducing hidden case folding or normalisation.
- Fold fully literal calls through the existing scalar constant optimiser and verify optimised and unoptimised execution remain observationally equivalent.
- Extend deterministic conformance, arity, type-compatibility, NULL, Unicode and mixed-base numeric coverage for the new scalar functions.

## Discover 0.23.6 - Radix Revelry

- Add hexadecimal, octal and binary integer literals throughout yt-sql scalar and typed numeric value positions.
- Allow mixed-base scalar arithmetic and Unicode `CHAR()` arguments, with all non-decimal forms resolving to ordinary integer values before execution.
- Standardise readable numeric grouping on underscores and retire comma-grouped numeric literals so commas remain unambiguous list and function-argument separators.
- Require underscores to occur between digits and reject malformed base prefixes, invalid base digits, repeated separators and trailing separators.
- Extend scalar constant folding and optimiser differential coverage across mixed-base expressions.
- Add deterministic conformance and negative parser coverage for decimal, hexadecimal, octal and binary literal forms.

## Discover 0.23.5 - Character Forge

- Add `CHAR()` as a first-class scalar function for constructing Unicode text from one or more code-point expressions.
- Define `CHAR()` arguments as Unicode scalar values from 0 through U+10FFFF excluding surrogate code points, with NULL propagation and clear diagnostics for invalid constant arguments.
- Preserve yt-sql's normalisation-sensitive Unicode model so composed and decomposed sequences created with `CHAR()` remain observably distinct.
- Fold fully literal `CHAR()` calls through the existing scalar constant optimiser and verify optimised and unoptimised execution remain equivalent.
- Resolve the existing comma-grouped-number ambiguity inside scalar function calls so function commas are parsed as argument separators without changing grouped-number syntax in ordinary value positions.
- Add Unicode, arity, type, range, surrogate, arithmetic-expression, NULL, nesting and optimiser coverage for `CHAR()`.

## Discover 0.23.4 - Unicode Gauntlet

- Bump the deterministic yt-sql conformance generator to version 3 and expand the small semantic profile from 36 to 60 records so Unicode edge cases are always present in routine testing.
- Add deterministic anchors for composed and decomposed text, combining marks, supplementary-plane characters, emoji and ZWJ sequences, variation selectors, regional indicators, case-mapping edge cases, non-Latin scripts, bidirectional marks, Unicode whitespace and line separators.
- Add Unicode conformance coverage across exact comparison, `CONTAINS`, `MATCHES`, `LIKE`, `ILIKE`, `LOWER`, `UPPER`, `LENGTH`, ordering, projection, JSONL serialisation and scalar constant folding.
- Define yt-sql text as normalisation-sensitive Unicode text: no implicit NFC/NFD conversion is performed, and `LENGTH` counts Unicode code points rather than grapheme clusters.
- Document the deliberate distinction between case-folded `CONTAINS` semantics and Unicode-aware regular-expression case handling used by `ILIKE`.
- Extend optimiser differential requirements so Unicode-sensitive scalar rewrites and text execution paths must remain observationally equivalent before and after optimisation.

## Discover 0.23.3 - Like It or Not

- Add SQL-like `LIKE`, `NOT LIKE`, `ILIKE` and `NOT ILIKE` text predicates with `%` and `_` wildcards.
- Define backslash escaping for literal wildcard and backslash characters, and reject incomplete trailing escapes.
- Preserve SQL-like NULL/UNKNOWN behaviour and support the new predicates in lightweight acquisition rejection where exact metadata is available.
- Compile literal LIKE patterns during semantic resolution and cache compiled forms for repeated row evaluation.
- Extend deterministic conformance, malformed-input and differential optimiser coverage across case sensitivity, negation, escaping, Unicode, newlines and wildcard cardinality.
- Document conservative regex-to-LIKE optimisation candidates while declining rewrites whose anchoring, wildcard cardinality, newline or case semantics are not provably equivalent.

## Discover 0.23.2 - Known Quantities

- Add conservative post-resolution scalar constant folding for fully literal arithmetic, unary expressions and deterministic scalar functions.
- Fold nested constant subexpressions recursively while preserving yt-sql NULL behaviour, including NULL results for division and modulo by zero.
- Keep symbolic field algebra deliberately disabled where equivalence has not been proved, including `field * 0`, and extend differential optimiser coverage around those boundaries.
- Add `YT-SQL-OPTIMISATION.md` as the living per-feature optimisation strategy, documenting current rewrites, deliberately excluded transformations, future candidates and differential verification requirements.
- Record the exploratory compiled-query design direction without committing to an implementation.
- Add `El Psy Kongroo.` as a zero-argument Discover easter egg while retaining the existing required-source error and exit status.

## Discover 0.23.1 - Conditional Currents

- Add searched `CASE WHEN ... THEN ... [ELSE ...] END` as a first-class scalar expression in `SELECT` and `ORDER BY`.
- Preserve SQL-like three-valued condition semantics: only TRUE selects a branch, FALSE and UNKNOWN fall through, and omitted `ELSE` returns NULL.
- Validate CASE result compatibility while allowing NULL-only branches and compatible numeric result types.
- Extend acquisition field analysis through CASE conditions and result expressions.
- Optimise predicates nested inside CASE branches to the same deterministic fixed point as top-level filters, with differential conformance coverage for identical rows and serialised output.
- Add malformed syntax, type, nesting, ordering, NULL, planner and optimiser regression coverage for conditional expressions.

## Discover 0.23.0 - Expression Expanse

- Make scalar expressions first-class in `SELECT` and `ORDER BY` instead of treating projection functions as a special case.
- Add arithmetic operators `+`, `-`, `*`, `/` and `%`, including unary `+` and `-`, SQL-like precedence and parenthesised scalar expressions.
- Allow existing scalar functions to nest and accept scalar expressions as arguments while preserving their established NULL behaviour.
- Allow `ORDER BY` to use scalar expressions directly or reference aliases for computed projections.
- Extend acquisition field analysis and deterministic conformance coverage so nested scalar expressions request every metadata field they depend on.

## Discover 0.22.0 - Optimisation Origins

- Add a dedicated semantics-preserving yt-sql predicate optimiser that runs after typed semantic resolution.
- Normalise negation, remove duplicate Boolean terms, collapse degenerate `BETWEEN` expressions and eliminate subsumed same-field comparison bounds.
- Preserve SQL-like three-valued NULL behaviour exactly across optimiser rewrites rather than replacing UNKNOWN-producing contradictions with Boolean constants.
- Expose deterministic optimiser rewrite decisions through verbose execution and `--explain`, including machine-readable JSON explain output.
- Add differential optimiser tests that execute resolved queries before and after optimisation and require identical truth values, selected rows and serialised output across the routine conformance corpus.

## Discover 0.21.0 - Temporal Horizons

- Add typed `INFINITY()` and `-INFINITY()` bounds for date and timestamp comparisons while preserving SQL-like NULL semantics.
- Extend the data-driven unit registry with decade, century and millennium units.
- Add Maya Long Count units from kin through baktun as recursively resolved fixed-day measures.
- Extend deterministic conformance and query tests for temporal infinity and the new unit definitions.

## Downloader 1.7.0 - Parameter Profiles

- Add versioned JSON parameter profiles selected with `-p/--parameter-profile` and alternate defaults files selected with `-d/--defaults`.
- Ship `best`, `4k`, `1440p` and `playlist` parameter profiles using yt-dlp format selectors directly.
- Add `--list-parameters`, deterministic profile generation, explicit write support and refusal of accidental profile overwrites.
- Add `--overwrite-profile` for deliberate replacement and omit a redundant profile-removal command.
- Preserve command-line precedence over profile settings, including symmetric cookie and playlist overrides.
- Move output-layout profile selection to `-P/--output-profile` while retaining `--profile` as a legacy long-option alias.
- Add `-f/--format` so yt-dlp format selectors can be stored in profiles or overridden directly.

## Discover 0.20.1 - Conformance Corrections

- Fix signed numeric literal resolution so negative values remain numeric after tokenisation, including scalar-function fallbacks such as `COALESCE(view_count, -1)`.
- Add comprehensive deterministic yt-sql conformance coverage for the complete current language surface and its viable edge cases.
- Add malformed-query, semantic-rejection, unit-registry and parameter-binding edge coverage.
- Keep routine semantic conformance fast through in-process production execution while retaining representative real-CLI parity checks.

## Discover 0.20.0 - Multilingual Measures

- Move duration and temporal unit names into external JSON unit-definition files.
- Load English and Welsh units through the same case-insensitive registry, including aliases and shared short forms.
- Resolve derived units recursively to fixed seconds or Gregorian calendar months, with explicit validation for cycles, unresolved references and token collisions.
- Accept Unicode unit names while preserving strict duration and date/time type rules.
- Correct the optional YouTube.js tool-check fixture to model the resolved module path reported by the bridge.

## Discover 0.19.0 - Acquisition Observability

- Resolve optional YouTube.js through the project Node environment and report the resolved module path in `--check-tools`.
- Add coarse stderr progress for lengthy source enumeration while preserving clean stdout query output.
- Emit live large-source notices when enumeration reaches `--warn-source-size`.
- Warn before very-high-cost automatic full-source plans where no safe source boundary is available.
- Refresh tests and current documentation for acquisition and tool-discovery behaviour.

## Downloader 1.6.0 - Optional Cookies

- Make cookies optional by default while continuing to use script-local `cookies.txt` automatically when present.
- Add strict `--cookies FILE` and explicit `--no-cookies` controls.
- Keep missing explicitly requested cookie files as configuration errors.
- Refresh tests and current documentation for the cookie policy.

## Repository - Test-suite organisation

- Replace historical Discover phase-based test modules with capability-oriented test modules.
- Split Downloader's catch-all behavioural tests into CLI, input-source, output-profile, queue-reconciliation and command-planning modules.
- Keep routine, scale and stress conformance tiers unchanged while making test ownership clearer for future language work.
- Expand `.gitignore` coverage for script-relative credentials, queues, caches, provenance, downloaded media and yt-dlp sidecars.
- No tool version changed.

## 0.18.1 - Tiered Testing

- Exclude large and huge conformance datasets from routine pytest and pull-request CI by default.
- Add explicit `scale` and `stress` pytest tiers for selected large-dataset and huge torture tests.
- Split cardinality and prefix-contract checks so routine tests never construct the large or huge corpora implicitly.
- Retire the golden query-dataset concept in favour of deterministic generated inputs plus the independent Python semantic oracle.
- Retain deliberately designed semantic anchor records inside the deterministic generator.
- Fix the remaining Ruff test-style finding.

## Downloader 1.5.0

- Adopt the mature downloader policy, profile-resolution and input-source architecture from the canonical implementation.
- Separate output-profile settings from global download policy through explicit `OutputProfile` and `DownloadPolicy` models.
- Formalise direct, batch-file and standard-input source handling through a single `InputSource` abstraction.
- Strengthen profile validation, archive reconciliation, completion callbacks and environment validation.
- Standardise the executable and documentation name on `yt-download.py`.

## Repository - Pre-canonical audit

- Recorded intentional version and executable-name differences from the earlier supplied endpoint.
- Added a final canonical comparison checklist covering code, documentation, tests, tooling, modes and repository hygiene.
- No tool version changed.

## Repository - Reliability and stress-test policy

- Made large and huge conformance tests opt-in through the `stress` pytest marker.
- Expanded ignore rules for runtime credentials, ID lists, generated caches and local development state.
- Added downloader test-package scaffolding for cleaner fixture sharing and import isolation.
- Pinned Ruff GitHub Actions checks and restricted workflow permissions to repository read access.
- No tool version changed.

## Discover 0.18.0

- Converged Discover on the mature typed YT-SQL parser, schema and execution model.
- Added dedicated archive, date, output, report, tool-registry, YouTube.js and yt-dlp support modules.
- Expanded acquisition planning, observability, source handling and cache semantics.
- Replaced the preliminary conformance harness with the mature deterministic generator, dataset specification and independent oracle suite.
- Kept large and huge conformance profiles available for deliberate stress runs while disabling them in the default automated suite.
- Added the current Discover and YT-SQL reference documentation.
- Downloader remains at 1.4.2.

## Repository - Executable-mode correction

- Restored executable file modes on the two shebang-bearing CLI entry points after the Phase 37 packaging workflow dropped them.
- No tool version changed.

## Repository - Conformance architecture

- Expanded the deterministic YT-SQL dataset generator to version 2.
- Added `small`, `normal`, `large` and `huge` profiles plus exact-size generation.
- Added an independent expected-result oracle and golden conformance fixtures.
- No tool version changed.

## Discover 0.17.1 / Downloader 1.4.2

- Fixed remaining Ruff E701 findings in Discover parameter coercion.
- Marked both shebang-bearing CLI scripts executable so Ruff EXE001 passes.
- No user-facing behaviour changed beyond the revision maintenance fixes.

Entries are annotated by tool or repository so the independent version lines remain clear.

## Repository - Package foundation

- Moved mature Discover support modules into `yt_media_tools`.
- Moved the YouTube.js bridge beside the packaged source backend.
- Migrated existing Discover tests to package imports.
- No tool version changed.

## Downloader 1.4.1

- Hardened exact completed-ID queue removal.
- Preserved queue permissions and unrelated raw bytes during replacement.
- Centralised script-relative runtime paths.

## Downloader 1.4.0

- Moved queue completion to yt-dlp's per-item `after_move` lifecycle.
- Retained pre-run archive reconciliation as a recovery path.

## Downloader 1.3.0

- Added an explicit input-source model.
- Expanded the stable yt-dlp runtime policy.

## Repository - Ruff validation

- Added `ruff.toml`.
- Added check-only Ruff validation in GitHub Actions.

## Discover 0.17.0 / Downloader 1.2.0

- Resolved the first locally identified Ruff findings.
- Made Discover date handling consistently timezone-aware.

## Downloader 1.1.0

- Hardened persistent queue reconciliation and exact-ID removal.

## Downloader 1.0.1

- Fixed profile output templates being ignored during command construction.

## Repository - First automated tests

- Added pytest configuration and separate Discover and Downloader test roots.
- No tool version changed.

## Discover 0.16.2 / Downloader 1.0.0

- Rejected duplicate Discover named-parameter bindings.
- Marked the Downloader interface as stable for ordinary use.

## Discover 0.16.1 / Downloader 0.9.0

- Corrected DISTINCT/LIMIT planning and NULL comparison semantics.
- Formalised the Downloader `@profile` format.

## Discover 0.16.0 / Downloader 0.8.0

- Added DISTINCT, OFFSET, scalar functions, parameters and provenance.
- Narrowed Downloader profiles to presentation settings.

## Discover 0.15.0 / Downloader 0.6.0

- Added proof-based LIMIT-aware acquisition and execution analysis.
- Improved Downloader profile discovery and validation.

## Discover 0.14.0 / Downloader 0.5.0

- Added conservative incremental source refresh.
- Expanded Downloader input handling.

## Discover 0.13.0

- Made the persistent cache a first-class execution source.
- Added offline querying and cache-status reporting.

## Discover 0.12.0

- Added persistent SQLite caching and targeted detailed refresh.
- Added the LGPL-2.1 licence and repository ignore rules.

Earlier reconstructed development remains represented by Git history.
