# Changelog

## Discover 0.28.11 - Cost and Selectivity Heuristics

- Add deterministic coarse cost, selectivity and information-value heuristics without fabricated numeric estimates.
- Rank safe deterministic enumeration-stage AND terms by expected information value per local evaluation cost.
- Preserve original query order for equally ranked predicate terms.
- Keep residual predicate evaluation order and the logical query AST unchanged.
- Record per-boundary acquisition cost, selectivity, information-value and deferred expensive-stage guidance.
- Align heuristic cost tiers with the existing planner cost classes.
- Identify detailed, nested collection and dynamic raw stages that can remain behind cheap authoritative enumeration filters.
- Keep source-branch acquisition order unchanged until a semantics-preserving bailout or dependency rule can justify reordering.
- Expose predicate and boundary heuristic decisions through verbose, human explain and JSON explain output.
- Add deterministic coverage for predicate ordering, tie stability, expensive-stage deferral, dynamic metadata costs and explain output.

## Discover 0.28.10 - Metadata Acquisition Plan

- Add a backend-neutral physical metadata acquisition plan with ordered semantic stages.
- Distinguish source identity enumeration, basic metadata, complete metadata, formats, subtitles and captions, chapters, thumbnails, tags, and dynamic raw metadata.
- Derive acquisition stages from pruned physical field requirements so CTE, branch and relation simplifications carry through to remote work.
- Represent statically empty source boundaries with no required acquisition stages.
- Add an isolated yt-dlp lowering that maps identity/basic stages to flat enumeration and deeper stages to complete JSON extraction.
- Keep nested metadata stages explicit when yt-dlp must currently collapse them into one detailed extraction phase.
- Make runtime detailed-metadata decisions consume the explicit physical acquisition plan.
- Report physical metadata stages through verbose output and human and JSON explain output.
- Add deterministic coverage for identity-only, lightweight, detailed, collection, dynamic, UNION and empty-boundary acquisition plans.

## Discover 0.28.9 - Static Relation and Branch Simplification

- Add proof-backed relation simplification for filters that can never evaluate TRUE under SQL three-valued logic.
- Prove incompatible same-field equality/range constraints and mutually exclusive NULL requirements empty without rewriting their scalar UNKNOWN behaviour.
- Prove constant HAVING predicates before acquisition and skip source work when no group can survive.
- Remove source-capability predicates proven TRUE from physical filtering and stop their otherwise redundant fields contributing to metadata requirements.
- Exclude statically empty UNION and UNION ALL uses from source-boundary field unions and acquisition.
- Skip an entire physical source/facet boundary when every logical use is proven empty.
- Preserve existing scalar optimiser rules for duplicate predicates, exact subsumption and Boolean normalisation rather than duplicating them at relation level.
- Expose eliminated logical uses, redundant WHERE filters and relation-simplification reasons through human and JSON explain output.
- Add regression coverage for contradictory bounds, constant HAVING, capability-proven TRUE filters, empty set branches and shared-source metadata pruning.

## Discover 0.28.8 - Safe LIMIT/OFFSET Early Termination

- Formalise LIMIT/OFFSET early termination as a stage-aware proof with an explicit `OFFSET + LIMIT` authoritative match target.
- Stop lightweight source enumeration when the complete filter and selected output are authoritative at enumeration time.
- Preserve source-order detailed-acquisition termination for queries that still require authoritative detailed metadata.
- Reject early termination across explicit ordering, DISTINCT, aggregation/HAVING, CTE materialisation, UNION composition, dynamic fields and volatile expressions unless a dedicated proof exists.
- Avoid lowering final-row limits to yt-dlp positional item ranges because skipped or unavailable source entries can break positional equivalence.
- Expose the selected LIMIT termination mode through explain, explain-analyse, verbose execution and run reports.

## Discover 0.28.7 - CTE Dependency Propagation

- Propagate downstream CTE output requirements backwards through non-recursive CTE chains before physical metadata acquisition is planned.
- Remove unused deterministic CTE output dependencies from physical source field requirements while retaining producer predicates, grouping and ordering dependencies.
- Preserve volatile CTE projections so planning cannot change their materialisation evaluation count.
- Treat DISTINCT and UNION producers as conservative projection-pruning barriers until their cardinality and positional semantics have dedicated proofs.
- Apply propagated CTE requirements to both multi-source source boundaries and single-source physical acquisition requests.
- Expose required, retained and pruned CTE outputs plus physical input fields through human-readable and machine-readable explain output.
- Distinguish logical query requirements from post-propagation physical metadata requirements in explain output so pruned CTE fields are not presented as active acquisition requirements.
- Replace incidental machine-output version literals in tests with the canonical PROGRAM_VERSION constant while retaining a dedicated literal CLI release-version check.

## Discover 0.28.6 - Source-Boundary Predicate and Requirement Planning

- Build an independent physical planning boundary for every unique source/facet request in composed queries.
- Keep required fields, metadata depth, predicate stages, temporal bounds, ordering assumptions, cost and branch-emptiness proofs scoped to the source/facet that owns them.
- Union field requirements when the same source/facet is reused and combine its pre-acquisition predicates with OR so every logical use remains satisfiable.
- Preserve distinct facets of the same physical source as separate acquisition identities.
- Skip a multi-source acquisition branch only when source/facet capability proofs establish that every logical use of that request is empty.
- Expose source-boundary plans through verbose and explain diagnostics while keeping logical UNION and CTE reconciliation unchanged.

## Discover 0.28.5 - Temporal Bound and Frontier Inference

- Infer conservative lower and upper bounds for date and timestamp predicates across comparisons, BETWEEN, IN and Boolean composition.
- Use only bounds implied by every OR branch and combine AND constraints using the strongest proven interval.
- Convert proven lower upload-date bounds into ordered acquisition frontiers only for source/facet contracts with suitable trustworthy ordering.
- Keep timestamp and upper-bound inference visible to planning without pushing unsupported extractor filters.
- Keep query-specific bounded observations separate from reusable complete cache/frontier state.
- Expose inferred temporal intervals through verbose, human-readable explain and machine-readable explain output.

## Discover 0.28.4 - Staged Predicate Evaluation

- Partition safe top-level `AND` predicate fragments into authoritative enumeration-stage and residual later-stage work.
- Reject rows before detailed metadata acquisition only when acquired exact enumeration values prove a WHERE fragment cannot be TRUE.
- Preserve missing enumeration values as not-acquired knowledge rather than interpreting them as SQL NULL.
- Keep mixed `OR`, `NOT`, volatile and later-stage expressions intact unless the complete expression is safe at enumeration time.
- Expose staged predicate requirements through human-readable and machine-readable explain output.

## Discover 0.28.3 - Field Requirement and Metadata Pruning

- Partition physical query fields into authoritative enumeration and detailed-metadata requirements.
- Keep approximate flat metadata and dynamic fields in the detailed requirement set rather than treating them as authoritative enumeration values.
- Expose enumeration, detailed and predicate-stage field requirements through the physical acquisition plan.
- Skip detailed extraction for eligible single-source queries whose complete field requirements are authoritative in lightweight enumeration metadata.
- Overlay exact enumeration values onto cached or freshly detailed rows so detailed-cache freshness is checked only for genuinely detailed fields.
- Preserve full lightweight enumeration when enumeration-only execution would otherwise mix fresh flat values with a stale incremental frontier.
- Add focused field-depth and acquisition-planning regression coverage.
- Preserve verbose per-entry and inaccessible-entry telemetry when lightweight enumeration replaces detailed extraction.

## Discover 0.28.2 - Capability-Driven Predicate Simplification

- Add source/facet capability proofs for predicate truth under SQL three-valued logic.
- Simplify predicates only when stable capability declarations prove TRUE, FALSE or UNKNOWN.
- Distinguish proven SQL UNKNOWN from an optimiser refusal caused by insufficient information.
- Allow the planner to mark a source branch as empty and skip physical acquisition when its WHERE predicate is proven unable to evaluate TRUE.
- Preserve unknown and not-yet-acquired metadata conservatively instead of treating missing capability evidence as SQL NULL.
- Add focused regression coverage for comparisons, NULL tests, Boolean composition, optimiser rewrites and branch-elimination planning.

## Discover 0.28.1 - Optimiser Proof and Safety Framework

- Add reusable optimiser proofs with explicit proven and not-proven states, provenance and deterministic reasons.
- Derive expression determinism and constantness from semantic property analysis and consume those proofs in optimiser rewrites.
- Prove structural field unavailability only from explicit source/facet capability declarations.
- Preserve proof metadata through nested optimisation decisions and refuse volatile-expression elimination without an appropriate proof.
- Add focused proof-framework regression coverage for constant, volatile, seeded-random, dynamic-field and source-capability cases.

## Discover 0.28.0 - Semantic Property Framework

- Add deterministic semantic-property analysis for resolved scalar expressions, predicates and query relations.
- Track required fields, resolved types, constantness, volatility, NULL sensitivity, evaluation stage, metadata depth, ordering, grouping and cardinality effects independently of execution.
- Introduce explicit knowledge states for acquired values, SQL NULL, structurally unavailable fields and supported metadata that has not yet been acquired.
- Expose source/facet dependencies and relation-completeness requirements to the planner without introducing new capability-driven rewrites.
- Add focused regression coverage for property analysis, seeded and volatile RANDOM behaviour, dynamic metadata depth and knowledge-state safety.

## Discover 0.27.7 - Reforged Reconciliation

- Reconcile the 0.27.x architectural refactor around the application, query, source, capability, optimiser and planner boundaries.
- Preserve the hardened yt-sql language and observable CLI behaviour while removing stale refactor-era duplication and compatibility assumptions where safe.
- Record multi-backend acquisition, information-value-aware scheduling, bounded concurrency and deterministic query-plan graphs as future optimiser and planner directions.
- Add reconciliation coverage for compatibility exports and architectural boundaries relied upon by the refactored modules.

## Discover 0.27.6 - Planner and Optimiser Boundaries

- Extract stable semantic query requirements into `query_properties.py` so acquisition planning no longer owns AST field traversal.
- Add a typed source-aware `QueryPlan` boundary combining semantic requirements, source/facet capabilities, acquisition strategy, LIMIT termination and cost classification.
- Keep logical optimisation source-independent while exposing source/facet capability contracts to the acquisition planner without changing established termination semantics.
- Preserve established planner helpers as compatibility exports and add architectural regression coverage for the new planning boundary.

## Discover 0.27.5 - Source, Facet and Capability Architecture

- Extract stable physical/logical source identity into `source_model.py` while preserving `sources.py` compatibility exports.
- Extract adapter, facet, logical-schema and field-acquisition capability declarations into `source_capabilities.py`.
- Distinguish stable logical support from dynamic metadata whose structure remains unknown until detailed acquisition.
- Declare YouTube channel, playlist and generic yt-dlp source capabilities conservatively without changing acquisition behaviour.
- Add deterministic architectural coverage for source identity, facet isolation, logical schemas and capability declarations.

## Discover 0.27.4 - Resolver and Evaluator Separation

- Extract semantic field/schema resolution, type checking, aggregate validation, CTE/set-operation reconciliation and RANDOM placement validation into `yt_media_tools/query_resolver.py`.
- Extract resolved scalar/predicate evaluation, projection, grouping, aggregation, ordering, CTE materialisation and UNION execution into `yt_media_tools/query_evaluator.py`.
- Centralise shared structural query inspection in `query_semantics.py` so the resolver and evaluator do not duplicate or cyclically depend on one another.
- Preserve the established resolver, evaluator and physical-source helper imports through the `query.py` compatibility facade.
- Add architectural regression coverage for the separated ownership boundary and resolved-query execution.

## Discover 0.27.3 - Parser and Formatter Separation

- Extract lexical analysis, recursive-descent parsing and parser-owned literal syntax into `yt_media_tools/query_parser.py` while preserving compatibility exports from `query.py`.
- Extract canonical scalar, predicate and complete-query rendering into `yt_media_tools/query_formatter.py` without changing yt-sql formatting semantics.
- Keep semantic resolution and local evaluation outside the parser and formatter modules for the following refactor phase.
- Add architectural regression coverage for compatibility exports, parser/formatter ownership, canonical round trips and deterministic syntax diagnostics.

## Discover 0.27.2 - Shared yt-dlp Runtime Extraction

- Extract common yt-dlp executable resolution, version probing, cookie-file resolution, authentication argument emission and diagnostic command formatting into `yt_media_tools/ytdlp_runtime.py`.
- Keep Discover metadata acquisition, lazy enumeration and acquisition telemetry component-owned while routing common runtime mechanics through the shared boundary.
- Add deterministic shared-runtime coverage for executable discovery, version probing, cookie policy, browser-cookie arguments and shell-readable command formatting.

## Downloader 1.19.1 - Shared Runtime

- Reuse the shared yt-dlp runtime for executable resolution, version probing, cookie-file resolution, authentication argument emission and diagnostic command formatting.
- Preserve Downloader's typed download policy, command planning, machine contracts and public compatibility wrappers while removing duplicated runtime mechanics.

## Discover 0.27.1 - Query Model Extraction

- Extract the shared yt-sql AST, query/relation structures and deterministic query diagnostic type into `query_model.py` while preserving compatibility exports from `query.py`.
- Extract source-position-insensitive semantic identity and resolved-field equivalence into `query_semantics.py`, plus common comparison/grouping value helpers into `query_values.py`.
- Preserve existing schema/type descriptors in `schema.py` and temporal context/infinity values in `dates.py` as the stable model boundaries already established before this phase.
- Add deterministic regression coverage for model re-exports, exact structural equality and semantic identity across expressions, CASE, aggregates and composed queries.
- Replace Discover's machine-specific default cookie path with optional script-local `cookies.txt` discovery and add `--cookies FILE` as an explicit per-run override.

## Discover 0.27.0 - Application Shell Extraction

- Reduce `yt-discover.py` to a thin executable bootstrap.
- Extract CLI parsing and query preparation, explain/analyse presentation, acquisition/cache orchestration, output/provenance helpers and top-level application execution into focused package modules.
- Preserve the 0.26.6 query, acquisition, CLI, output and error behaviour while retaining the original project-root semantics for the relocated application layer.
- Add deterministic architectural regression coverage for the thin executable and extracted CLI boundary.

## Downloader 1.19.0 - Machine Check

- Add runtime parameter-profile validation through `--validate-config`.
- Add human-readable and versioned JSON environment capability reporting.
- Version the non-executing `--explain-json` plan contract independently from Downloader releases.
- Reconcile Downloader TODO and future-work documentation around genuinely outstanding work.

## Downloader 1.18.0 - Common Tongue

- Add `--schema-json` for a versioned, language-neutral Downloader machine contract.
- Publish complete JSON Schema descriptions for parameter-profile files and settings with unknown-key rejection and structural cross-field constraints.
- Expose canonical finite values, configuration precedence and runtime semantic-validation boundaries for machine consumers.
- Keep machine-contract, parameter-profile and run-manifest schema versions independent.
- Add deterministic coverage for contract versioning, runtime-key/schema synchronisation, canonical values, structural constraints and environment-independent schema output.

## Downloader 1.17.0 - Section Slice

- Add first-class derivative acquisition by chapter regular expression and validated time range.
- Use section-aware output naming while preserving the selected output profile's home path.
- Disable whole-item archive completion for partial-media runs and reject completed-ID queue mutation.
- Record derivative section policy and archive state in explain output and run manifests.
- Add explicit whole-item override for partial-media settings inherited from parameter profiles.
- Add deterministic parsing, precedence, command, naming, archive, queue and explanation coverage.

## Downloader 1.16.0 - Live Line

- Add explicit live-media policy with live-edge and supported live-from-start acquisition.
- Add validated scheduled-stream waiting with CLI controls for overriding inherited wait policy.
- Add requested live-chat sidecars without replacing existing subtitle-language selection.
- Keep long-running retry choices explicit and preserve existing interruption, queue, archive and run-manifest completion boundaries.
- Prevent external yt-dlp configuration from silently changing live-from-start or scheduled-wait policy during explicit live mode.
- Add deterministic coverage for live policy validation, profile precedence, command construction, retry composition, live-chat selection and explain output.

## Downloader 1.15.0 - Selected Range

- Add typed playlist selection by individual 1-based indices, inclusive ranges and explicit slices.
- Preserve mixed CLI selection order and compile the complete selection into one canonical yt-dlp playlist-items expression.
- Add `--playlist-forward` as an explicit override for reverse traversal inherited from parameter profiles.
- Support ordered `playlist-items` policy in parameter profiles with strict index and slice validation.
- Reject playlist item selection with explicit no-playlist policy or durable completed-ID queue mutation.
- Preserve normal yt-dlp archive filtering for selected playlist child entries and keep random traversal outside Downloader policy.
- Add deterministic coverage for parsing, validation, profile precedence, command construction, explanation and queue boundaries.

## Downloader 1.14.0 - Source First

- Add first-class `--audio-only` source selection that does not enable audio conversion.
- Add exact source codec/container constraints with explicit fallback control.
- Add `--audio-format` and `--audio-quality` as the explicit boundary that permits yt-dlp/FFmpeg audio conversion.
- Keep existing preferred audio codec/channel settings as fallback-friendly source sorting policy in audio workflows.
- Reject raw format selectors, video-only format policy and subtitle embedding when they conflict with first-class audio mode.
- Expose source-only versus conversion-enabled audio policy through explain output and parameter profiles.
- Add deterministic coverage for source selectors, fallback semantics, conversion commands, validation and cross-policy conflicts.

## Downloader 1.13.0 - Receipt

- Add `--run-manifest FILE` for redacted machine-readable records of actual Downloader runs.
- Record Downloader and yt-dlp versions, timestamps, exit state, known targets, resolved plan data, queue outcomes and successfully completed primary output paths.
- Capture primary output paths through yt-dlp `after_move` callbacks instead of parsing human-readable console output.
- Add optional `--hash-outputs` SHA-256 values for completed primary files as ordinary integrity checks rather than authenticity or provenance claims.
- Reuse explain-plan redaction so sensitive extractor-argument values are never copied into manifests.
- Record requested associated-artefact policy without guessing sidecar paths that Downloader has not authoritatively observed.
- Remove temporary output-event ledgers after manifest construction.
- Add deterministic unit and simulated orchestration tests for manifest schema, output capture, hashing, redaction, interruption, validation and failure handling.

## Downloader 1.12.1 - Closed Loop

- Add orchestration-level regression tests for post-processing failure, completion-callback failure and atomic queue-rewrite failure.
- Require deterministic Downloader behaviour to be covered by automated tests whenever controlled fixtures or simulated process outcomes can represent it faithfully.
- Reserve manual verification for genuinely external or environment-dependent behaviour that cannot be reproduced faithfully in the automated suite.
- Reconcile the Downloader roadmap with the implemented queue and associated-artefact behaviour.

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
