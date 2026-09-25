# Discover changelog

This file is the authoritative changelog for yt-discover. Active development and release history are kept here independently from yt-downloader.

## Completed development

### Reconcile independent metadata provider investigations (#105)

- [maintenance] Reconcile issue #105 after its independent provider investigations and the completed issue #113 production-candidate programme.
- [maintenance] Retain the shared provider benchmark and deferred-provider adapters as explicit research infrastructure with documented revisit conditions rather than production acquisition paths.
- [maintenance] Remove the superseded standalone YouTube.js basic-metadata benchmark script, documentation and tests now that the shared provider benchmark and production capability cover its continuing purposes.
- [docs] Consolidate the durable provider outcomes around the accepted YouTube.js and ytmusicapi production capabilities plus the deferred or rejected provider decisions.
- [release] Close issue #105 after every investigated provider has a durable production, deferred or rejected disposition and both demonstrated production candidates have completed their implementation branches.

### Add capability-scoped YouTube.js exact-scalar metadata acquisition (#114)

- [feature] Register a production YouTube.js `getBasicInfo()` capability for the exact known-video scalar fields established by issue #113.
- [maintenance] Require conservative resolved YouTube source evidence before the capability can participate in provider selection.
- [maintenance] Keep publication dates, provider-native state flags and all unproven fields outside the capability boundary so mixed requirements retain the established acquisition path.
- [maintenance] Remove the discontinued human authority-assessment machinery and the temporary raw-response/date diagnostic instrumentation after their investigations concluded.
- [maintenance] Add backend-neutral production lowering that maps only complete eligible metadata requirements to the registered YouTube.js capability and leaves unsupported requirements on the established acquisition path.
- [feature] Execute wholly lowered exact-scalar requirements through the production YouTube.js `getBasicInfo()` bridge after conservative YouTube source resolution.
- [maintenance] Fall back to yt-dlp for bridge failure or individual videos omitted by YouTube.js, and do not persist partial specialised-provider rows into the existing yt-dlp-oriented detailed metadata cache.
- [maintenance] Add a production `--basic-info` bridge operation while retaining the benchmark alias for compatibility.
- [feature] Expose conditional specialised-provider lowering in human and JSON explain output without claiming runtime source eligibility before backend resolution.
- [feature] Record explicitly observed specialised metadata provider and operation counts in provenance output while leaving cache and untagged origins unattributed.
- [maintenance] Preserve the demonstrated YouTube.js cost advantage by batching each production request through one bridge process and reusing one Innertube session across all video IDs in that batch.
- [test] Lock production batch/session reuse to one bridge invocation for a multi-video metadata request.
- [test] Cover the exact field boundary, source eligibility, mixed unsupported requirements, cookie-context eligibility, conservative production lowering, runtime execution and whole-request or per-entry fallback.
- [docs] Record that YouTube.js `MediaInfo.basic_info` does not propagate `PlayerMicroformat.publish_date` or `upload_date`, while populated `PlayerMicroformat` fields themselves are direct mappings of the corresponding player response values. Publication dates remain outside the #114 production authority boundary.
- [test] Exhaustively cover every non-empty subset of the five-field authority surface, unsupported-field contamination and mixed-provider fallback ordering.
- [docs] Reconcile issue #114 around its final closed authority, lowering, execution, fallback, provenance, explain and session-reuse boundaries in preparation for parent issue #113.
- [release] Close issue #114 after acceptance of the complete capability-scoped YouTube.js production integration.

### Add capability-scoped ytmusicapi specialised metadata acquisition (#116)

- [feature] Register and execute an anonymous `YTMusic.get_song()` capability for the conservative five-field exact scalar surface established by the provider investigation.
- [maintenance] Require independently resolved YouTube identity plus positive `music` source evidence derived from consistently observed `music.youtube.com` origins before ytmusicapi can participate.
- [maintenance] Keep `musicVideoType`, publication dates, descriptions, keywords, category, live/playability state and `YTMusic.get_song_credits()` outside the production authority boundary.
- [maintenance] Preserve the lower-cost YouTube.js capability as the preferred exact-scalar path and use ytmusicapi only as an independently eligible unresolved-ID fallback before yt-dlp.
- [maintenance] Prevent later specialised providers from overwriting earlier authoritative results, reject unexpected or duplicate records deterministically, and keep partial specialised rows out of the full detailed metadata cache.
- [feature] Preserve explicit ytmusicapi provider/operation attribution in runtime provenance and expose its conditional source-trait requirement through existing human and JSON explain output.
- [security] Keep production ytmusicapi acquisition anonymous; browser or cookie authentication remains outside the demonstrated production requirement.
- [test] Exhaustively cover every non-empty subset of the five-field authority surface, unsupported-field contamination, source-trait uncertainty, authentication boundaries, deterministic provider ordering, unresolved-ID fallback, duplicate/extraneous records and mixed-provider provenance.
- [docs] Reconcile issue #116 around its final authority, source-evidence, acquisition, fallback, disagreement, provenance and explain boundaries in preparation for parent issue #113.
- [release] Close issue #116 after acceptance of the complete capability-scoped ytmusicapi production integration.

### Reconcile metadata provider production candidates (#113)

- [maintenance] Reconcile accepted issue #114 as the completed YouTube.js production-integration branch of issue #113.
- [maintenance] Reconcile accepted issue #116 as the completed specialised ytmusicapi production-integration branch of issue #113.
- [docs] Preserve deferred and rejected provider conclusions from issue #113 without promoting experimental adapters during parent reconciliation.
- [docs] Reconcile both accepted production children against the original provider findings and retain their authority, provenance, source-resolution and disagreement boundaries.
- [release] Close issue #113 after both demonstrated production candidates are implemented and accepted through issues #114 and #116.

### Discover - specialised ytmusicapi metadata benchmark

- [feature] Add ytmusicapi as an optional experimental core metadata provider for issue #112 without changing production provider selection or yt-sql semantics.
- [maintenance] Treat ytmusicapi as a specialised resolved-source-type candidate rather than a general YouTube replacement, preserving provider-native music signals separately from common-field comparison.
- [maintenance] Register `YTMusic.get_song()` with shared external-tool diagnostics and advance the experimental metadata benchmark schema to version 12.
- [test] Cover specialised provider eligibility, conservative `get_song()` normalisation, provider-native music evidence and deterministic failure recording.
- [docs] Add a five-item music-oriented probe with a non-music control before any larger specialised-provider corpus is attempted.
- [fix] Preserve normalised metadata and provider-native playability evidence when `YTMusic.get_song()` returns a non-OK playability state instead of discarding the response as an exception.
- [maintenance] Classify non-OK ytmusicapi playability as `playability_rejection`, distinct from transport, library and generic provider failures, and advance the experimental benchmark schema to version 13.
- [test] Cover metadata-bearing non-OK playability responses and the additional high-popularity music-video probe case.
- [fix] Treat usable ytmusicapi metadata acquisition as successful independently of provider-native playback eligibility, while retaining non-OK playability as diagnostic evidence.
- [feature] Add opt-in current-signature and native browser-authenticated ytmusicapi benchmark variants for controlled three-way comparison.
- [security] Keep ytmusicapi browser-auth credential paths and contents out of serialised benchmark results and external-invocation diagnostics.
- [maintenance] Advance the experimental metadata benchmark schema to version 14 and expose deterministic variant comparisons.
- [test] Cover metadata/playability independence, metadata-free rejection, explicit signature forwarding and browser-auth credential isolation.
- [fix] Make the explicit current day-based signature timestamp the normal experimental ytmusicapi acquisition path after the controlled probe eliminated the library default's blanket music-item `UNPLAYABLE` result.
- [maintenance] Retain library-default signature and browser-authenticated acquisition only as explicit diagnostic variants and advance the experimental benchmark schema to version 15.
- [security] Ignore `browser.json` as credential material while keeping authenticated ytmusicapi outside the prospective production path.
- [test] Cover deterministic epoch-day signature calculation and automatic current-signature provider dispatch.
- [docs] Record that browser authentication and VPN removal did not change the controlled results, while the explicit current signature timestamp did, and retain `musicVideoType` as useful provider-native source-type evidence.

### Discover - Piped metadata benchmark reconciliation

- [maintenance] Conclude issue #111 without promoting Piped into production acquisition planning.
- [docs] Record that two explicitly selected public instances failed operationally: one reached its streams API but its server-side YouTube acquisition was rejected, while the other timed out during the TLS handshake.
- [docs] Retain Piped as experimental infrastructure for explicitly configured operator-controlled deployments while rejecting automatic instance discovery or fallback.
- [docs] Record that metadata-semantic compatibility remains insufficiently measured because neither public-instance probe returned successful video metadata.

### Discover - explicitly configured Piped metadata benchmark

- [feature] Add Piped as an optional experimental core metadata provider for issue #111 without changing production provider selection.
- [security] Require an explicitly selected Piped API instance and capability-probe `/streams/:id` before disclosing the remaining corpus.
- [maintenance] Reuse the successful capability-probe response, bound remote requests and register Piped with shared external-tool diagnostics.
- [maintenance] Advance the experimental metadata benchmark schema to version 11.
- [test] Cover explicit instance validation, documented stream-field normalisation, capability preflight, selected-instance routing and preflight reuse.
- [docs] Begin the Piped comparison with a small-probe workflow and preserve the remote-instance trust boundary.
- [fix] Distinguish upstream YouTube authentication rejection from Piped API access denial and generic provider-side HTTP failure.
- [security] Bound remote Piped error detail and avoid echoing provider stack traces into normal benchmark errors.
- [test] Cover upstream authentication classification and bounded unstructured remote error bodies.
- [docs] Record the first public-instance probe as an operational API success whose upstream YouTube acquisition was rejected.

### Discover - Invidious metadata benchmark reconciliation

- [maintenance] Conclude issue #110 without promoting Invidious into production acquisition planning.
- [docs] Record that four explicitly selected public instances produced a TLS handshake timeout, a disabled video endpoint or HTTP 403 responses, leaving metadata-semantic compatibility insufficiently measured.
- [docs] Retain Invidious as experimental infrastructure for explicitly configured operator-controlled deployments while rejecting automatic instance discovery or fallback.

### Discover - explicitly configured Invidious metadata benchmark

- [fix] Replace the reachability-only Invidious stats preflight with a video-API capability preflight so instances returning `403 Endpoint disabled` fail before the remaining corpus is disclosed.
- [maintenance] Reuse the successful video capability-probe payload as the first benchmark result and record the probed ID in diagnostics.
- [test] Cover disabled video-API capability preflight and verify the successful probe is not requested twice.
- [docs] Record the disabled-video-endpoint finding and select another current official public instance for the next explicit probe.
- [fix] Preflight the explicitly selected Invidious instance with a five-second stats request before disclosing or iterating over a benchmark corpus.
- [maintenance] Bound individual Invidious video metadata requests to 15 seconds and record preflight/request timeout diagnostics.
- [test] Verify failed Invidious preflight stops before any video endpoint is requested.
- [docs] Replace the ambiguous placeholder-only example with a small-probe workflow and a contemporaneous official-list instance example.
- [feature] Add Invidious as an optional experimental core metadata provider for issue #110 without changing production provider selection.
- [security] Require the benchmark operator to select the Invidious instance explicitly and reject credential-bearing, query-bearing or fragment-bearing instance URLs.
- [maintenance] Register Invidious with the shared external-tool invocation diagnostics and advance the experimental metadata benchmark schema to version 10.
- [test] Cover explicit instance selection, URL validation, documented field normalisation, provider-native live-state signals and selected-instance request routing.
- [docs] Document the remote-disclosure boundary, explicit configuration contract and initial anonymous Invidious benchmark procedure.

### Discover - NewPipeExtractor metadata benchmark

- [fix] Reject whitespace-containing benchmark video IDs before provider execution so malformed corpus arguments cannot be reinterpreted differently by providers.
- [maintenance] Add an opt-in NewPipeExtractor bridge stderr diagnostic path without weakening normal bridge failure handling or contaminating JSON output.
- [docs] Reconcile issue #109 benchmark evidence, authority boundaries and production-promotion limits.
- [feature] Add a heterogeneous issue #109 corpus spanning multiple source shapes for a second NewPipeExtractor compatibility run.
- [maintenance] Add conservative text-normalised description analysis and similarity evidence without treating similarity as semantic equivalence, advancing the experimental benchmark schema to version 9.
- [test] Cover description representation normalisation and the deterministic heterogeneous corpus contract.
- [docs] Document the heterogeneous benchmark variation and interpretation boundary.
- [feature] Add NewPipeExtractor v0.26.5 as an optional experimental known-video metadata provider for issue #109 without changing production provider selection.
- [feature] Add a minimal Java 21 bridge that keeps one JVM alive across a benchmark corpus and reports provider-native metadata and per-item acquisition time.
- [maintenance] Register NewPipeExtractor with the shared external-tool invocation diagnostics and advance the experimental metadata benchmark schema to version 8.
- [test] Cover NewPipeExtractor provider selection, normalisation, failure classification, single-JVM corpus execution and external-tool registration.
- [docs] Document bridge construction, benchmark invocation, timing interpretation and the production-promotion boundary.

### External tool invocation diagnostics

- [feature] Add a shared registry and structured invocation model for external command, bridge and Python-library integrations.
- [cli] Add `--debug-external` for safely redacted live invocation diagnostics and `--debug-external-unsafe` for deliberate unredacted diagnostics.
- [security] Redact credential-bearing command options and sensitive annotated library arguments by default.
- [test] Cover registry completeness, deterministic rendering, redaction and library-call annotation.

### Repository - Authenticated metadata benchmark variants

- [feature] Translate Discover Netscape cookie files for authenticated YouTube.js acquisition at the provider boundary.
- [feature] Allow metadata benchmarks to compare anonymous and authenticated YouTube.js using Netscape cookie files.
- [security] Redact cookie credentials from provider diagnostics before benchmark reports are serialised.
- Added an optional cookie-authenticated YouTube.js benchmark variant alongside the anonymous run and wired Discover cookie files through the YouTube.js adapter when that backend is selected.
- Kept cookie material out of subprocess arguments and reports, with fail-closed serialisation checks for accidental credential leakage.
- Added direct authenticated-versus-anonymous comparison output and advanced the experimental benchmark schema to version 5.

### Discover - comparable metadata benchmark profiles

- [fix] Separate core metadata timing from optional extended capability probing so provider elapsed times describe the same acquisition contract.
- [feature] Add explicit core and full measurement profiles with provider support declarations and fail-closed handling for unsupported profile/provider combinations.
- [feature] Add structural yt-dlp thumbnail, chapter and caption inventory for direct full-profile comparison with pytubefix without retaining media URLs or caption contents.
- [test] Cover profile support, core-only pytubefix acquisition and structural yt-dlp extended capability reporting.
- [maintenance] Exclude virtual environments and nested Node dependency trees from project Markdown linting.

### Discover - pytubefix metadata benchmark

- [feature] Add pytubefix as an optional experimental provider in the shared known-video metadata benchmark without changing production provider selection.
- [feature] Preserve pytubefix playability and video-detail signals and inventory thumbnail, chapter and caption capabilities separately from scalar normalisation.
- [maintenance] Advance the experimental metadata benchmark schema to version 6 and retain per-video pytubefix acquisition timing.
- [test] Cover pytubefix provider selection, normalisation, extended capability isolation and per-video failure handling with deterministic fixtures.
- [docs] Define the issue #104 benchmark method, optional dependency, capability inventory and production-promotion boundary.

### Discover - Capability-oriented metadata provider selection

- [maintenance] Add backend-neutral metadata requirement and provider-capability contracts covering authority, field coverage, resolved source applicability, authentication, acquisition granularity, provenance and relative physical cost.
- [maintenance] Project existing physical acquisition stages into provider requirements without changing yt-sql semantics or runtime acquisition behaviour.
- [test] Add deterministic coverage for exact authority, field coverage, source constraints, cookie requirements, cost ordering and physical-plan projection.
- [docs] Define the provider-selection boundary and its deliberate exclusions before provider benchmarks and production integration.

### Discover - Backend source resolution

- [feature] Retain yt-dlp's reported extractor identity, extractor key, result type and source domains as backend source-resolution provenance.
- [ux] Show observed backend source resolution at verbose interactive output without changing query-result output.
- [maintenance] Derive a conservative extractor-family namespace for future physical provider eligibility without treating it as yt-sql platform semantics.
- [test] Add deterministic coverage for YouTube, Twitch, generic and missing backend-resolution metadata.
- [docs] Define the distinction between user source expressions, Discover logical sources and backend-reported resolution evidence.

### Discover - YouTube.js basic metadata benchmark

- [fix] Make the benchmark subprocess policy explicit with `check=False` while preserving manual return-code diagnostics.
- [maintenance] Extend the existing YouTube.js bridge with an experimental `getBasicInfo()` benchmark mode that reuses one Innertube session across a known-ID corpus.
- [test] Add deterministic benchmark-contract coverage for scalar field comparison and missing-value handling without adding live network tests to pytest.
- [docs] Define the benchmark methodology, candidate scalar field surface, publication-date gap, corpus requirements and production-integration boundary.

### Discover - yt-sql query file input

- [feature] Add `--query-file FILE` for loading reusable UTF-8 yt-sql queries through the existing query-processing path.
- [cli] Keep query files mutually exclusive with `--query` and `--where` while preserving the established positional-source plus query form.
- [test] Add deterministic coverage for inline equivalence, parameters, positional sources, conflicting inputs, unreadable files and invalid UTF-8.
- [docs] Document reusable `.yt-sql` file workflows and keep query files limited to ordinary yt-sql without a separate preprocessing or scripting layer.

### Discover active development

- Add pytubefix as an optional experimental provider in the shared known-video metadata benchmark for issue #104 without changing production acquisition planning.
- Preserve pytubefix playability and video-detail source signals while keeping live-state authority unassigned pending corpus evidence.
- Inventory thumbnail, chapter and caption capabilities separately from the normalised scalar comparison surface and retain per-video acquisition timing.
- Add a shared experimental known-video metadata benchmark for YouTube.js, youtube-innertube and yt-dlp without changing production acquisition planning.
- Add explicit youtube-innertube normalisation and field-by-field comparison across the issue #103 scalar metadata surface.
- Report absolute and relative view-count deltas when lightweight providers differ from the yt-dlp reference so mutable-count drift can be interpreted rather than treated as an undifferentiated mismatch.
- Preserve adversarial benchmark output when individual acquisitions fail, with structured failure classification, provider summaries and explicit failed-comparison states.
- Capture yt-dlp diagnostics during JSON benchmark runs while retaining per-video failure evidence and corpus-level timing.
- Preserve provider-native playability, live-state and availability signals in benchmark evidence so final #103 semantic discrepancies can be investigated without promoting those signals into Discover semantics.
- Filter the reproduced routine YouTube.js attachment-run parser warning at the bridge boundary while preserving genuine standard-error failures and an explicit diagnostic escape hatch.
- Document benchmark corpus reuse, authentication limitations, reliability considerations and the provider-promotion boundary.

## Release history

### Discover 0.29.9 - Identifier Contract

- Freeze the yt-sql identifier and keyword contract around exact case-sensitive identifier identity and case-insensitive contextual keyword recognition.
- Make field, alias, CTE and semantic identifier resolution case-sensitive while preserving ordinary contextual keyword spellings as identifiers where grammar position is unambiguous.
- Define ordinary unquoted identifiers with explicit Unicode XID-style recognition, preserve the established hyphen extension and perform no implicit Unicode normalisation.
- Add backtick-quoted identifiers across fields, aliases, CTEs, relation qualification, structured members and raw backend-key segments, with doubled backticks for embedded backticks.
- Canonically quote identifiers only where required by the ordinary identifier grammar or reserved-word contract, preserving exact spelling and semantic identity through round trips.
- Make the deliberately small reserved vocabulary and the contextual structural keyword vocabulary explicit and conformance-tested without broadly reserving future grammar words.
- Extend deterministic and adversarial coverage for case-distinct identifiers, Unicode spelling, quoted identifiers, raw keys, relation aliases, optimiser behaviour and canonical formatting.
- Reconcile the completed identifier and keyword audit into the canonical language and testing documentation and retire the temporary audit material.

### Discover 0.29.8 - Temporal Contract

- Freeze the yt-sql temporal grammar across deterministic query-captured relative time, accepted date and timestamp forms, multilingual duration units, temporal arithmetic boundaries and typed temporal infinity.
- Confirm that duration-unit recognition remains contextually separate from ordinary identifiers and that temporal arithmetic introduces no independent precedence ambiguity beyond its deliberately bounded grammar.
- Normalise equivalent accepted temporal spellings in canonical resolved-query output, including date and timestamp forms, duration aliases and relative `TODAY()` and `NOW()` unit aliases.
- Preserve relative `TODAY()` and `NOW()` expressions symbolically during canonicalisation rather than replacing them with captured absolute values.
- Define deterministic syntax-versus-semantic temporal failure boundaries and semantic parse-resolve-format-parse-resolve stability as durable conformance requirements.
- Reconcile the completed temporal grammar audit into the canonical language and test documentation and retire the temporary audit material.

### Discover 0.29.7 - Literal Contract

- Freeze the yt-sql literal and parameter contract across decimal, hexadecimal, octal and binary integers, strict numeric separators, quoted strings, reserved literals, query parameters and unary signs.
- Confirm deterministic lexical boundaries between numbers, temporal units and identifiers, and preserve the lexical base of unchanged integer literals through canonical parse-and-format behaviour.
- Reserve `TRUE`, `FALSE` and `NULL` throughout the grammar so the literal words cannot be reused in aliases, relation names, facets, collection bindings or other identifier-only positions.
- Add dedicated deterministic diagnostics for unterminated quoted strings and incomplete terminal string escapes while preserving the established string language.
- Define the parameter binding boundary, canonical formatting rules and malformed-input behaviour as durable conformance requirements for the formal grammar and differential parser tests.
- Reconcile the completed literal and parameter audit into the canonical language and test documentation and retire the temporary audit material.

### Discover 0.29.6 - Operator Principles

- Define durable criteria for deciding when an operation deserves dedicated yt-sql operator syntax, favouring grammar for structural and scope-changing semantics while keeping ordinary value transformations in functions where appropriate.
- Record readability, discoverability, composition and parser complexity as explicit operator-design considerations, and retain `COALESCE(...)` rather than adding a dedicated null-coalescing `??` operator.
- Audit the established operator surface and resolve the two identified language gaps through NULL-safe comparison and complete truth-value inspection.
- Add `IS DISTINCT FROM` and `IS NOT DISTINCT FROM` as total NULL-safe comparisons over compatible scalar expressions while preserving ordinary comparison three-valued logic.
- Generalise `IS TRUE`, `IS NOT TRUE`, `IS FALSE` and `IS NOT FALSE` to predicate expressions and add `IS UNKNOWN` and `IS NOT UNKNOWN` as total truth-value inspection operators.
- Preserve left-to-right Boolean reachability, volatility, NULL semantics and conservative optimisation across the new predicate forms.
- Add deterministic conformance coverage for NULL-safe comparison and truth-value inspection across ordinary predicates, HAVING, JOIN contexts, formatting, diagnostics and optimisation.
- Retire the completed operator-surface audit after reconciling its enduring semantics into the canonical language, operator-design and test documentation.

### Discover 0.29.5 - Boolean Boundaries

- Define left-to-right `AND` and `OR` evaluation as observable yt-sql language semantics, including exact TRUE, FALSE and UNKNOWN reachability behaviour.
- Unify ordinary row predicates and `HAVING` behind one lazy three-valued Boolean connective implementation while preserving relation-aware and collection predicate semantics.
- Constrain Boolean optimisation by evaluation reachability so a known final truth value cannot suppress or reorder an earlier observable operand without a proof of observational equivalence.
- Carry proven short-circuit reachability through optimiser decisions and explain output separately from Boolean truth and textual predicate simplification.
- Add comprehensive deterministic and adversarial conformance coverage for nested Boolean expressions, NULL and three-valued logic, reachable failures, volatile expressions, `HAVING`, JOIN predicates and collection quantifiers.
- Remove avoidable per-row callback allocation from the shared lazy Boolean evaluator, restoring representative end-to-end performance to the 0.29.3 baseline while preserving the completed language contract.
- Reconcile the yt-sql language and optimisation documentation around the completed short-circuit decision, including the corrected language-reference heading hierarchy and explicit proof requirements for any future Boolean operand reordering.

### Discover 0.29.4 - Relations Resolved

- Add first-class single-relation JOIN grammar, resolution and execution for `INNER`, `LEFT`, `SEMI` and `ANTI`, with explicit relation aliases, qualified field ownership, deterministic ambiguity diagnostics and conservative unsupported-form guards.
- Define joined projection semantics, including primary-relation `*`, explicit `alias.*`, unique output-name requirements and precise LEFT JOIN NULL extension.
- Integrate JOIN execution with CTEs, UNION and UNION ALL while preserving relation identity, source/facet provenance, acquisition ownership and deterministic set-composition semantics.
- Add proof-limited hash execution for simple and compound cross-relation equality keys across supported JOIN families while retaining an independent nested-loop reference executor and exact NULL/three-valued matching behaviour.
- Expose JOIN identity, kind, predicate dependencies, acquisition requirements and selected execution strategy through the shared explain model and console, JSON and Graphviz presentations.
- Extend shared semantic provability with bounded Boolean constraints, authoritative source-field type and nullability facts, proven relation emptiness/cardinality consequences and deliberately conservative result-provenance boundaries.
- Add deterministic JOIN conformance, independent-oracle, optimiser-differential and torture coverage spanning duplicates, NULLs, empty relations, aliases, overlapping schemas, CTEs, set composition, functions and unsupported multi-way execution.
- Add stable relational performance benchmarks for one-to-one, one-to-many, no-match, asymmetric, compound-equality, SEMI and acquisition-planning workloads.
- Reconcile relational performance against the 0.29.2 release baseline, removing unnecessary composed-resolution and eager evaluation-context overhead while retaining established semantics and improving the representative offline end-to-end benchmark.
- Improve routine test infrastructure with reusable deterministic conformance populations, an in-process CLI harness where process isolation is not part of the contract, and a project-owned parallel test runner with an explicit serial mode.
- Complete the planned 0.29.4 relational architecture work, leaving the accepted hand-written parser and formalised language contracts as the foundation for the remaining 0.29.x language and parser reconciliation.

### Discover 0.29.3 - Groundwork Complete

- Add deterministic performance benchmarking with immutable and per-phase baselines, compact terminal comparison output, machine-readable results and documented regression guidance.
- Add shared yt-sql AST traversal and consolidated query analysis so planning and semantic-property derivation can reuse established structural work.
- Batch detailed metadata cache reads into bounded source-scoped SQLite queries, substantially reducing repeated lookup work for realistic candidate sets.
- Add explicit semantic relation scope, relation identity, field ownership and logical row identity foundations without introducing relational query syntax.
- Add an explicit read-only expression evaluation context for metadata records and lexical collection bindings while preserving established evaluator entry points and semantics.
- Strengthen syntax and semantic diagnostics with deterministic source positions, line and column information and expression-level anchoring.
- Add independent relation-oriented conformance infrastructure for qualification, ambiguity, field ownership and logical row identity without depending on production resolution as the oracle.
- Fuse deterministic MAP-over-FILTER collection evaluation where volatility analysis proves the transformation safe, while retaining the established path for RANDOM-sensitive pipelines.
- Add typed variadic `CONCAT()` with textual arguments, NULL propagation, deterministic evaluation and constant folding.
- Preserve SQL NULL and three-valued logic, lexical collection semantics, source and facet identity, volatility boundaries and conservative optimisation guarantees throughout the preparatory architecture work.
- Define left-to-right AND/OR short-circuit semantics, including identical HAVING behaviour, and distinguish proven final truth from proven evaluation reachability in the shared semantic proof model.
- Add conservative relation-level provability for explicit cardinality bounds and proven emptiness propagation through CTEs, single JOIN semantics and UNION composition, consuming authoritative stable source-field type, nullability, structural-support and collection-ordering contracts while refusing unsupported result-column facts and physical-source cardinality inference.
- Lift authoritative source-field facts through proven single-source identity projections while keeping computed, CTE, set, grouped and JOIN result propagation explicitly unknown.
- Reconcile cumulative performance evidence, retaining the collection-pipeline and batched-cache improvements while removing unnecessary simple-resolution composition and eager evaluation-context overhead from ordinary hot paths.

### Discover 0.29.2 - Collection Querying Beyond Indexing

- Add lexical collection-element bindings with deterministic nested scope and outer-reference semantics.
- Add `ANY` and `ALL` collection predicates with exact SQL three-valued behaviour for NULL, empty and nullable collections.
- Add `CARDINALITY` and scoped collection `COUNT` while preserving existing aggregate `COUNT` semantics.
- Add typed `FILTER` and `MAP` collection expressions that preserve collection nullability and logical ordering without inventing positional guarantees.
- Carry collection-query requirements and correlations through acquisition planning, permitting backend pushdown only when an adapter explicitly proves exact yt-sql-equivalent semantics.
- Extend the deterministic conformance generator to version 6 with independent-oracle, optimiser, formatter and offline CLI coverage for collection querying, including structured and dynamic raw collections.
- Document collection binding, three-valued quantifiers, counting, filtering, projection and conservative acquisition fallback semantics across the Discover and yt-sql documentation.

### Discover 0.29.1 - Structured Member Access

- Add first-class structured value types with opaque, declared and dynamic member schemas, preserving nullability through nested structured expressions.
- Add composable postfix `.member` syntax after indexed, function-valued and parenthesised expressions while preserving established dotted field paths and canonical round trips.
- Resolve and evaluate structured members with deterministic errors for invalid operands or unknown members, SQL NULL propagation and conservative runtime dictionary boundaries.
- Define closed yt-sql member schemas for formats, chapters and thumbnails without exposing arbitrary backend dictionaries or changing their existing ordering contracts.
- Carry precise nested and indexed member requirements through source-boundary and physical acquisition planning, using member-level acquisition only when a backend proves exact equivalence and otherwise falling back conservatively.
- Support dynamic `raw.*` structured member access through compatible runtime dictionaries and ordered raw record collections while keeping unsafe, inconsistent and whole structured raw values opaque or non-selectable.
- Extend the deterministic conformance generator to version 5 and add independent-oracle, optimiser, formatter and offline CLI coverage for direct, nested, indexed, nullable and predicate member access.
- Document structured-value semantics, member schemas, dynamic raw inference and acquisition fallback behaviour across the yt-sql reference and Discover testing documentation.

### Discover 0.29.0 - Typed Collections and Indexing

- Add first-class typed collection values with declared element types, nullability and explicit logical ordering contracts.
- Add composable zero-based postfix indexing with deterministic NULL, out-of-range and invalid-index semantics across projection, ordering and predicates.
- Model tags, categories, formats, chapters and thumbnails as collection metadata while preserving conservative ordering for structured collections.
- Support ordered dynamic `raw.*` sequence indexing without promoting backend-specific order or opaque structured values into portable yt-sql semantics.
- Carry indexed and whole-collection requirements through source-boundary and physical acquisition planning, permitting partial indexed acquisition only when a backend explicitly proves exact equivalence.
- Serialise collection results as JSON arrays and expose collection type, element type, ordering, positional-indexing and acquisition capability through explain output.
- Extend the deterministic conformance corpus, formatter round trips, offline CLI integration and regression coverage for collection indexing, parameters, NULLs, bounds, raw metadata and malformed predicates.
- Preserve the scalar-only `SELECT *` contract and deterministic predicate diagnostics while integrating general indexed scalar expressions into WHERE.

### Discover 0.28.13 - Optimiser Differential and Acquisition Torture

- Add a broad deterministic optimiser differential corpus spanning NULL and three-valued logic, Unicode, temporal infinity, numeric literal forms, CASE/scalar expressions, aggregation, CTEs, set composition, DISTINCT, slicing and seeded RANDOM.
- Reconcile optimised execution against deliberately unoptimised resolved queries and require optimiser idempotence across the new semantic corpus.
- Add heterogeneous-source and same-source cross-facet differential cases so source/facet identity and schema isolation remain part of optimiser correctness.
- Add generated equivalent Boolean transformations that exercise duplicate elimination, double negation and rewrite stability without introducing a property-testing dependency into the routine suite.
- Add mutation-style fixture-sensitivity checks for comparison boundaries, Boolean conjunction/disjunction and NULL predicates so representative unsafe rewrites are proven observable.
- Add deterministic malformed-input repetition checks and canonical format/parse round-trip checks across the semantic corpus.
- Add acquisition torture coverage for static branch elimination, LIMIT barriers, detailed-stage termination, temporal frontiers, metadata deferral, CTE requirement pruning, shared-source unions, dynamic raw metadata and volatile RANDOM ordering.
- Keep structurally unavailable metadata distinct from metadata that is merely not yet acquired.

### Discover 0.28.12 - Explainable Optimisation and Acquisition

- Add a versioned deterministic explanation model for planner decisions and rendered plan structure.
- Add compact console plan and decision-tree output derived from the same explanation data as JSON.
- Use ANSI colour for semantic console states when an interactive terminal supports it, with explicit auto/always/never control and `NO_COLOR` support.
- Use conservative Unicode box drawing and arrows for terminal structure, with deterministic ASCII fallback for redirected or unsuitable output.
- Report applied, rejected, deferred and eliminated planning decisions, including predicate staging, source-boundary predicate pushdown, bounded acquisition, metadata deferral, CTE projection pruning and LIMIT termination.
- Add Graphviz-backed SVG explain rendering without making Graphviz part of query semantics or normal execution.
- Keep JSON free of terminal presentation sequences and expose the explanation schema, decision list and graph model explicitly.
- Add deterministic coverage for explanation schema versioning, console modes, ANSI suppression, Unicode/ASCII fallback, DOT generation and JSON cleanliness.

### Discover 0.28.11 - Cost and Selectivity Heuristics

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

### Discover 0.28.10 - Metadata Acquisition Plan

- Add a backend-neutral physical metadata acquisition plan with ordered semantic stages.
- Distinguish source identity enumeration, basic metadata, complete metadata, formats, subtitles and captions, chapters, thumbnails, tags, and dynamic raw metadata.
- Derive acquisition stages from pruned physical field requirements so CTE, branch and relation simplifications carry through to remote work.
- Represent statically empty source boundaries with no required acquisition stages.
- Add an isolated yt-dlp lowering that maps identity/basic stages to flat enumeration and deeper stages to complete JSON extraction.
- Keep nested metadata stages explicit when yt-dlp must currently collapse them into one detailed extraction phase.
- Make runtime detailed-metadata decisions consume the explicit physical acquisition plan.
- Report physical metadata stages through verbose output and human and JSON explain output.
- Add deterministic coverage for identity-only, lightweight, detailed, collection, dynamic, UNION and empty-boundary acquisition plans.

### Discover 0.28.9 - Static Relation and Branch Simplification

- Add proof-backed relation simplification for filters that can never evaluate TRUE under SQL three-valued logic.
- Prove incompatible same-field equality/range constraints and mutually exclusive NULL requirements empty without rewriting their scalar UNKNOWN behaviour.
- Prove constant HAVING predicates before acquisition and skip source work when no group can survive.
- Remove source-capability predicates proven TRUE from physical filtering and stop their otherwise redundant fields contributing to metadata requirements.
- Exclude statically empty UNION and UNION ALL uses from source-boundary field unions and acquisition.
- Skip an entire physical source/facet boundary when every logical use is proven empty.
- Preserve existing scalar optimiser rules for duplicate predicates, exact subsumption and Boolean normalisation rather than duplicating them at relation level.
- Expose eliminated logical uses, redundant WHERE filters and relation-simplification reasons through human and JSON explain output.
- Add regression coverage for contradictory bounds, constant HAVING, capability-proven TRUE filters, empty set branches and shared-source metadata pruning.

### Discover 0.28.8 - Safe LIMIT/OFFSET Early Termination

- Formalise LIMIT/OFFSET early termination as a stage-aware proof with an explicit `OFFSET + LIMIT` authoritative match target.
- Stop lightweight source enumeration when the complete filter and selected output are authoritative at enumeration time.
- Preserve source-order detailed-acquisition termination for queries that still require authoritative detailed metadata.
- Reject early termination across explicit ordering, DISTINCT, aggregation/HAVING, CTE materialisation, UNION composition, dynamic fields and volatile expressions unless a dedicated proof exists.
- Avoid lowering final-row limits to yt-dlp positional item ranges because skipped or unavailable source entries can break positional equivalence.
- Expose the selected LIMIT termination mode through explain, explain-analyse, verbose execution and run reports.

### Discover 0.28.7 - CTE Dependency Propagation

- Propagate downstream CTE output requirements backwards through non-recursive CTE chains before physical metadata acquisition is planned.
- Remove unused deterministic CTE output dependencies from physical source field requirements while retaining producer predicates, grouping and ordering dependencies.
- Preserve volatile CTE projections so planning cannot change their materialisation evaluation count.
- Treat DISTINCT and UNION producers as conservative projection-pruning barriers until their cardinality and positional semantics have dedicated proofs.
- Apply propagated CTE requirements to both multi-source source boundaries and single-source physical acquisition requests.
- Expose required, retained and pruned CTE outputs plus physical input fields through human-readable and machine-readable explain output.
- Distinguish logical query requirements from post-propagation physical metadata requirements in explain output so pruned CTE fields are not presented as active acquisition requirements.
- Replace incidental machine-output version literals in tests with the canonical PROGRAM_VERSION constant while retaining a dedicated literal CLI release-version check.

### Discover 0.28.6 - Source-Boundary Predicate and Requirement Planning

- Build an independent physical planning boundary for every unique source/facet request in composed queries.
- Keep required fields, metadata depth, predicate stages, temporal bounds, ordering assumptions, cost and branch-emptiness proofs scoped to the source/facet that owns them.
- Union field requirements when the same source/facet is reused and combine its pre-acquisition predicates with OR so every logical use remains satisfiable.
- Preserve distinct facets of the same physical source as separate acquisition identities.
- Skip a multi-source acquisition branch only when source/facet capability proofs establish that every logical use of that request is empty.
- Expose source-boundary plans through verbose and explain diagnostics while keeping logical UNION and CTE reconciliation unchanged.

### Discover 0.28.5 - Temporal Bound and Frontier Inference

- Infer conservative lower and upper bounds for date and timestamp predicates across comparisons, BETWEEN, IN and Boolean composition.
- Use only bounds implied by every OR branch and combine AND constraints using the strongest proven interval.
- Convert proven lower upload-date bounds into ordered acquisition frontiers only for source/facet contracts with suitable trustworthy ordering.
- Keep timestamp and upper-bound inference visible to planning without pushing unsupported extractor filters.
- Keep query-specific bounded observations separate from reusable complete cache/frontier state.
- Expose inferred temporal intervals through verbose, human-readable explain and machine-readable explain output.

### Discover 0.28.4 - Staged Predicate Evaluation

- Partition safe top-level `AND` predicate fragments into authoritative enumeration-stage and residual later-stage work.
- Reject rows before detailed metadata acquisition only when acquired exact enumeration values prove a WHERE fragment cannot be TRUE.
- Preserve missing enumeration values as not-acquired knowledge rather than interpreting them as SQL NULL.
- Keep mixed `OR`, `NOT`, volatile and later-stage expressions intact unless the complete expression is safe at enumeration time.
- Expose staged predicate requirements through human-readable and machine-readable explain output.

### Discover 0.28.3 - Field Requirement and Metadata Pruning

- Partition physical query fields into authoritative enumeration and detailed-metadata requirements.
- Keep approximate flat metadata and dynamic fields in the detailed requirement set rather than treating them as authoritative enumeration values.
- Expose enumeration, detailed and predicate-stage field requirements through the physical acquisition plan.
- Skip detailed extraction for eligible single-source queries whose complete field requirements are authoritative in lightweight enumeration metadata.
- Overlay exact enumeration values onto cached or freshly detailed rows so detailed-cache freshness is checked only for genuinely detailed fields.
- Preserve full lightweight enumeration when enumeration-only execution would otherwise mix fresh flat values with a stale incremental frontier.
- Add focused field-depth and acquisition-planning regression coverage.
- Preserve verbose per-entry and inaccessible-entry telemetry when lightweight enumeration replaces detailed extraction.

### Discover 0.28.2 - Capability-Driven Predicate Simplification

- Add source/facet capability proofs for predicate truth under SQL three-valued logic.
- Simplify predicates only when stable capability declarations prove TRUE, FALSE or UNKNOWN.
- Distinguish proven SQL UNKNOWN from an optimiser refusal caused by insufficient information.
- Allow the planner to mark a source branch as empty and skip physical acquisition when its WHERE predicate is proven unable to evaluate TRUE.
- Preserve unknown and not-yet-acquired metadata conservatively instead of treating missing capability evidence as SQL NULL.
- Add focused regression coverage for comparisons, NULL tests, Boolean composition, optimiser rewrites and branch-elimination planning.

### Discover 0.28.1 - Optimiser Proof and Safety Framework

- Add reusable optimiser proofs with explicit proven and not-proven states, provenance and deterministic reasons.
- Derive expression determinism and constantness from semantic property analysis and consume those proofs in optimiser rewrites.
- Prove structural field unavailability only from explicit source/facet capability declarations.
- Preserve proof metadata through nested optimisation decisions and refuse volatile-expression elimination without an appropriate proof.
- Add focused proof-framework regression coverage for constant, volatile, seeded-random, dynamic-field and source-capability cases.

### Discover 0.28.0 - Semantic Property Framework

- Add deterministic semantic-property analysis for resolved scalar expressions, predicates and query relations.
- Track required fields, resolved types, constantness, volatility, NULL sensitivity, evaluation stage, metadata depth, ordering, grouping and cardinality effects independently of execution.
- Introduce explicit knowledge states for acquired values, SQL NULL, structurally unavailable fields and supported metadata that has not yet been acquired.
- Expose source/facet dependencies and relation-completeness requirements to the planner without introducing new capability-driven rewrites.
- Add focused regression coverage for property analysis, seeded and volatile RANDOM behaviour, dynamic metadata depth and knowledge-state safety.

### Discover 0.27.7 - Reforged Reconciliation

- Reconcile the 0.27.x architectural refactor around the application, query, source, capability, optimiser and planner boundaries.
- Preserve the hardened yt-sql language and observable CLI behaviour while removing stale refactor-era duplication and compatibility assumptions where safe.
- Record multi-backend acquisition, information-value-aware scheduling, bounded concurrency and deterministic query-plan graphs as future optimiser and planner directions.
- Add reconciliation coverage for compatibility exports and architectural boundaries relied upon by the refactored modules.

### Discover 0.27.6 - Planner and Optimiser Boundaries

- Extract stable semantic query requirements into `query_properties.py` so acquisition planning no longer owns AST field traversal.
- Add a typed source-aware `QueryPlan` boundary combining semantic requirements, source/facet capabilities, acquisition strategy, LIMIT termination and cost classification.
- Keep logical optimisation source-independent while exposing source/facet capability contracts to the acquisition planner without changing established termination semantics.
- Preserve established planner helpers as compatibility exports and add architectural regression coverage for the new planning boundary.

### Discover 0.27.5 - Source, Facet and Capability Architecture

- Extract stable physical/logical source identity into `source_model.py` while preserving `sources.py` compatibility exports.
- Extract adapter, facet, logical-schema and field-acquisition capability declarations into `source_capabilities.py`.
- Distinguish stable logical support from dynamic metadata whose structure remains unknown until detailed acquisition.
- Declare YouTube channel, playlist and generic yt-dlp source capabilities conservatively without changing acquisition behaviour.
- Add deterministic architectural coverage for source identity, facet isolation, logical schemas and capability declarations.

### Discover 0.27.4 - Resolver and Evaluator Separation

- Extract semantic field/schema resolution, type checking, aggregate validation, CTE/set-operation reconciliation and RANDOM placement validation into `yt_media_tools/query_resolver.py`.
- Extract resolved scalar/predicate evaluation, projection, grouping, aggregation, ordering, CTE materialisation and UNION execution into `yt_media_tools/query_evaluator.py`.
- Centralise shared structural query inspection in `query_semantics.py` so the resolver and evaluator do not duplicate or cyclically depend on one another.
- Preserve the established resolver, evaluator and physical-source helper imports through the `query.py` compatibility facade.
- Add architectural regression coverage for the separated ownership boundary and resolved-query execution.

### Discover 0.27.3 - Parser and Formatter Separation

- Extract lexical analysis, recursive-descent parsing and parser-owned literal syntax into `yt_media_tools/query_parser.py` while preserving compatibility exports from `query.py`.
- Extract canonical scalar, predicate and complete-query rendering into `yt_media_tools/query_formatter.py` without changing yt-sql formatting semantics.
- Keep semantic resolution and local evaluation outside the parser and formatter modules for the following refactor phase.
- Add architectural regression coverage for compatibility exports, parser/formatter ownership, canonical round trips and deterministic syntax diagnostics.

### Discover 0.27.2 - Shared yt-dlp Runtime Extraction

- Extract common yt-dlp executable resolution, version probing, cookie-file resolution, authentication argument emission and diagnostic command formatting into `yt_media_tools/ytdlp_runtime.py`.
- Keep Discover metadata acquisition, lazy enumeration and acquisition telemetry component-owned while routing common runtime mechanics through the shared boundary.
- Add deterministic shared-runtime coverage for executable discovery, version probing, cookie policy, browser-cookie arguments and shell-readable command formatting.

### Discover 0.27.1 - Query Model Extraction

- Extract the shared yt-sql AST, query/relation structures and deterministic query diagnostic type into `query_model.py` while preserving compatibility exports from `query.py`.
- Extract source-position-insensitive semantic identity and resolved-field equivalence into `query_semantics.py`, plus common comparison/grouping value helpers into `query_values.py`.
- Preserve existing schema/type descriptors in `schema.py` and temporal context/infinity values in `dates.py` as the stable model boundaries already established before this phase.
- Add deterministic regression coverage for model re-exports, exact structural equality and semantic identity across expressions, CASE, aggregates and composed queries.
- Replace Discover's machine-specific default cookie path with optional script-local `cookies.txt` discovery and add `--cookies FILE` as an explicit per-run override.

### Discover 0.27.0 - Application Shell Extraction

- Reduce `yt-discover.py` to a thin executable bootstrap.
- Extract CLI parsing and query preparation, explain/analyse presentation, acquisition/cache orchestration, output/provenance helpers and top-level application execution into focused package modules.
- Preserve the 0.26.6 query, acquisition, CLI, output and error behaviour while retaining the original project-root semantics for the relocated application layer.
- Add deterministic architectural regression coverage for the thin executable and extracted CLI boundary.

### Discover 0.26.6 - No Loose Ends

- Complete the cleanup, optimiser and test-completeness reconciliation without adding yt-sql syntax.
- Remove stale release-phase narration and duplicated version claims from current reference documentation, keeping historical sequencing in the changelog.
- Add corpus-wide canonical parse-format-parse stability checks for every directly parsed conformance query.
- Add corpus-wide optimiser idempotence checks for every routine directly resolved semantic case.
- Extend the optimiser with exact duplicate-term and double-negation simplification inside HAVING, preserving three-valued logic and aggregate semantics.
- Extend semantic AST identity to scalar, aggregate and CASE expressions so position metadata cannot prevent safe equivalence checks.
- Reconcile the durable coverage and optimisation references with the implemented source/facet, aggregate and optimiser contracts.
- Give the split GitHub Actions workflows distinct display names while preserving their independent files and jobs.

### Discover 0.26.5 - Pressure Test

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

### Discover 0.26.4 - Measured Cuts

- Complete the dedicated optimiser-audit phase without adding or changing yt-sql syntax.
- Deduplicate literal `IN` members, collapse singleton `IN` and `NOT IN`, and remove provably subsumed same-field membership predicates while preserving NULL/UNKNOWN behaviour.
- Add a direct exact-match execution path for case-sensitive `LIKE` patterns that contain no unescaped wildcard, preserving exact Unicode and escaping semantics without invoking the regular-expression engine.
- Extend proof-based LIMIT-aware acquisition termination to source-order `OFFSET` queries by stopping only after `OFFSET + LIMIT` authoritative matches have been observed.
- Add direct differential and idempotence coverage for membership rewrites, exact-LIKE fast paths and LIMIT-plus-OFFSET planning.
- Audit tempting but unsafe rewrites, including contradiction folding, volatile RANDOM simplification, Unicode case substitutions and symbolic arithmetic identities with observable floating-point edge cases.
- Keep new syntax frozen pending the exhaustive completeness and torture-test phase.

### Discover 0.26.3 - Quiet Sweep

- Begin the post-0.26.2 hardening programme without adding or changing yt-sql syntax.
- Remove unused scalar compatibility wrappers, an unused metadata-output helper, an unused schema helper and an unused unit-registry constructor.
- Remove the stale package-level `__version__` value so `PROGRAM_VERSION` remains the single application version authority.
- Remove the unused legacy source-resolver import from the Discover CLI while preserving the intentional compatibility resolver API and `--tab` behaviour.
- Add the project-local pinned `markdownlint-cli2` development dependency and npm lint script, with `node_modules/**` excluded by the shared Markdown lint configuration.
- Audit production definitions, imports, module-level constants and explicit TODO/FIXME/HACK markers for dead or stale implementation artefacts.
- Preserve behaviour, grammar, source/facet semantics and the split GitHub Actions workflow organisation unchanged.

### Discover 0.26.2 - Crossing Streams

- Remove the temporary same-source cross-facet composition restriction now that each physical source/facet request has an independent execution identity.
- Key per-source query schemas by both physical source and logical facet so heterogeneous metadata cannot leak between branches.
- Tag acquired records with their logical facet and filter UNION/CTE inputs by the complete source/facet identity.
- Keep cache, coverage and frontier state isolated through each facet's independently resolved canonical acquisition URL.
- Include the logical facet in deterministic seeded `RANDOM(seed)` row identity so the same media ID in different facets remains independently reproducible.
- Preserve per-request acquisition counts and facet provenance when one physical source appears through several facets.
- Add same-source cross-facet UNION, UNION ALL, CTE, aggregate, Unicode, schema, seeded-randomness and global LIMIT/OFFSET regression coverage.
- Preserve the split Ruff, pytest and Markdown lint GitHub Actions workflows.
- Complete the planned 0.26.x source/facet series and freeze further syntax work pending the dedicated test-completeness and parser-torture review.

### Discover 0.26.1 - One Path

- Separate physical source classification, logical capability discovery and facet-to-acquisition mapping into explicit source-layer stages.
- Add deterministic `SourceCapabilities` metadata so the query/planner layer can reason about advertised logical facets without knowing extractor URL details.
- Route legacy `--tab` values through the same canonical facet request used by yt-sql `OF`; matching `OF`/`--tab` requests resolve identically and conflicts continue to fail closed.
- Report source adapter names and advertised facets through explain output and provenance.
- Improve unsupported-facet diagnostics by naming the active adapter and the exact facets it advertises.
- Preserve the user's split GitHub Actions workflow files for Ruff, pytest and Markdown linting.
- Keep same-source cross-facet composition disabled until the 0.26.2 identity/composition hardening pass.

### 0.26.0 - OF Origins

### Discover

- Add `FROM <source> OF <facet>` as the extractor-agnostic source collection syntax.
- Route `OF videos`, `OF shorts` and `OF live` through the existing YouTube channel acquisition adapter.
- Preserve bare `FROM <source>` as the default collection and keep `--tab` as a compatibility surface over the same facet model.
- Reject unsupported physical-source facets, conflicting `OF`/`--tab` requests and attempts to apply `OF` to CTE result relations.
- Add deterministic source/facet grammar and capability tests covering CTE and UNION composition.
- Fail closed when one composed query requests multiple facets of the same physical source until cross-facet cache and schema identity are hardened.
- Refresh the TODO roadmap and freeze further syntactic sugar until the post-0.26.2 test-completeness review.

### Discover 0.25.3 - Random Rendezvous

- Add `RANDOM()` for volatile per-execution row ordering and projected synthetic values.
- Add `RANDOM(seed)` with deterministic row-stable values derived from the integer seed and stable logical row identity rather than evaluation order.
- Permit RANDOM in scalar projection and ordering contexts, including aliases, CTEs and UNION-derived relations, while rejecting grouping and HAVING placement and retaining existing predicate grammar restrictions.
- Keep RANDOM calls opaque to constant folding and deterministic scalar rewrites, and preserve complete-result acquisition for explicit random ordering.
- Materialise projected random aliases so the value displayed to the user is the same value used by `ORDER BY` within that execution.
- Add a pinned markdownlint-cli2 GitHub Actions job, enforcing the established MD001 heading-increment and MD012 multiple-blank-line rules across project Markdown.

### Discover 0.25.2 - Composition Crucible

- Harden `UNION` and `UNION ALL` across CTEs, aggregation, global ordering, LIMIT/OFFSET and heterogeneous extractor-shaped logical relations without adding new grammar.
- Add a reusable deterministic multi-source fixture covering channel-like, playlist-like and Twitch-like records, including missing metadata, duplicate logical rows, Unicode normalisation distinctions and deliberately incompatible dynamic field kinds.
- Preserve already-materialised aggregate rows across set-operation boundaries so aggregate UNION branches are not accidentally evaluated a second time.
- Keep execution-only CTE and aggregate row markers internal to the query engine and prevent them from leaking into public query results.
- Record per-source acquired-row counts in provenance for composed acquisitions while retaining the existing single-source provenance fields.
- Strengthen Unicode torture coverage by using the Welsh flag tag sequence and verifying LIKE `_` continues to count Unicode code points rather than displayed grapheme clusters.

### Discover 0.25.1 - Union Uprising

- Add positional `UNION` and `UNION ALL` composition across ordinary queries and non-recursive CTEs.
- Reconcile branch schemas by column position, retain output names from the first branch, promote compatible numeric kinds, and reject incompatible projected types.
- Allow a composed query to acquire multiple physical yt-dlp sources independently before logical reconciliation, preserving source identity internally through normalisation.
- Add per-source schema resolution so heterogeneous extractor metadata is type-checked before set composition rather than collapsed into one mixed acquisition schema.
- Apply global `ORDER BY`, `OFFSET` and `LIMIT` after the complete set expression and disable source-order early LIMIT termination for UNION queries.
- Extend optimiser traversal, physical-field planning, explain output and deterministic heterogeneous-source tests across channel-like, playlist-like and Twitch-like source shapes.
- Run the routine pytest suite automatically in GitHub Actions alongside Ruff while retaining `scale` and `stress` exclusions from normal CI.

### Discover 0.25.0 - Common Ground

- Add non-recursive `WITH` common table expressions with declaration-order scoping and case-insensitive CTE references.
- Materialise each CTE as a logical yt-sql result relation whose exported column names and resolved scalar kinds define the schema visible to later CTEs and the outer query.
- Allow CTEs to contain ordinary filtering, scalar projection, aggregation, `GROUP BY`, `HAVING`, ordering, DISTINCT, LIMIT and OFFSET using the established query semantics.
- Reject recursive CTEs, self-reference, forward references, nested `WITH` clauses and multiple physical extractor sources in this foundation release.
- Resolve the one physical extractor source through CTE chains so outer `FROM cte_name` queries do not mistake a logical relation for an external source.
- Extend optimiser traversal, physical-field planning, deterministic conformance and independent-oracle differential coverage across chained CTE execution.

### Discover 0.24.0 - Aggregate Ascent

- Add `COUNT(*)`, `COUNT(expr)`, `SUM`, `AVG`, `MIN` and `MAX` with SQL-like NULL elimination and deterministic empty-input behaviour.
- Add `GROUP BY` with normalisation-sensitive Unicode grouping and deterministic first-source-occurrence group order when no `ORDER BY` is present.
- Add aggregate-aware `HAVING` comparisons, Boolean composition, NULL tests and references to explicit SELECT aliases.
- Add SQL-style aggregate `FILTER (WHERE ...)`, evaluated over rows that survive the ordinary query `WHERE` predicate.
- Require non-aggregate projected and ordered expressions in aggregate queries to match a `GROUP BY` expression, reject nested aggregates, and keep `SELECT *` out of aggregate queries.
- Prevent limit-aware early acquisition termination for aggregate queries because complete input groups are required before final row shaping.
- Extend deterministic conformance, independent oracle coverage, Unicode grouping/extrema checks, optimiser differential verification and negative aggregate validation.

### Discover 0.23.8 - Schema Star

- Add `SELECT *` with deterministic expansion over canonical built-in scalar fields followed by observed top-level dynamic scalar fields in case-insensitive lexical order.
- Exclude aliases and `raw.*` paths from star expansion so values are not duplicated and extractor-internal metadata is not unexpectedly projected.
- Require `SELECT *` to stand alone rather than mixing it with explicit expressions or aliases.
- Make star expansion participate in ordinary acquisition-cost analysis, `DISTINCT`, output serialisation, provenance and optimiser differential checks after semantic resolution.

### Discover 0.23.7 - Scalar Summit

- Add `NULLIF`, `GREATEST` and `LEAST` as first-class scalar functions in projections, ordering expressions and nested scalar expressions.
- Define `NULLIF(a, b)` to return NULL only when the comparison is TRUE; UNKNOWN comparisons caused by NULL preserve the first argument.
- Require `GREATEST` and `LEAST` to receive at least two compatible scalar arguments and propagate NULL when any argument is NULL.
- Preserve exact, normalisation-sensitive Unicode ordering for textual extrema rather than introducing hidden case folding or normalisation.
- Fold fully literal calls through the existing scalar constant optimiser and verify optimised and unoptimised execution remain observationally equivalent.
- Extend deterministic conformance, arity, type-compatibility, NULL, Unicode and mixed-base numeric coverage for the new scalar functions.

### Discover 0.23.6 - Radix Revelry

- Add hexadecimal, octal and binary integer literals throughout yt-sql scalar and typed numeric value positions.
- Allow mixed-base scalar arithmetic and Unicode `CHAR()` arguments, with all non-decimal forms resolving to ordinary integer values before execution.
- Standardise readable numeric grouping on underscores and retire comma-grouped numeric literals so commas remain unambiguous list and function-argument separators.
- Require underscores to occur between digits and reject malformed base prefixes, invalid base digits, repeated separators and trailing separators.
- Extend scalar constant folding and optimiser differential coverage across mixed-base expressions.
- Add deterministic conformance and negative parser coverage for decimal, hexadecimal, octal and binary literal forms.

### Discover 0.23.5 - Character Forge

- Add `CHAR()` as a first-class scalar function for constructing Unicode text from one or more code-point expressions.
- Define `CHAR()` arguments as Unicode scalar values from 0 through U+10FFFF excluding surrogate code points, with NULL propagation and clear diagnostics for invalid constant arguments.
- Preserve yt-sql's normalisation-sensitive Unicode model so composed and decomposed sequences created with `CHAR()` remain observably distinct.
- Fold fully literal `CHAR()` calls through the existing scalar constant optimiser and verify optimised and unoptimised execution remain equivalent.
- Resolve the existing comma-grouped-number ambiguity inside scalar function calls so function commas are parsed as argument separators without changing grouped-number syntax in ordinary value positions.
- Add Unicode, arity, type, range, surrogate, arithmetic-expression, NULL, nesting and optimiser coverage for `CHAR()`.

### Discover 0.23.4 - Unicode Gauntlet

- Bump the deterministic yt-sql conformance generator to version 3 and expand the small semantic profile from 36 to 60 records so Unicode edge cases are always present in routine testing.
- Add deterministic anchors for composed and decomposed text, combining marks, supplementary-plane characters, emoji and ZWJ sequences, variation selectors, regional indicators, case-mapping edge cases, non-Latin scripts, bidirectional marks, Unicode whitespace and line separators.
- Add Unicode conformance coverage across exact comparison, `CONTAINS`, `MATCHES`, `LIKE`, `ILIKE`, `LOWER`, `UPPER`, `LENGTH`, ordering, projection, JSONL serialisation and scalar constant folding.
- Define yt-sql text as normalisation-sensitive Unicode text: no implicit NFC/NFD conversion is performed, and `LENGTH` counts Unicode code points rather than grapheme clusters.
- Document the deliberate distinction between case-folded `CONTAINS` semantics and Unicode-aware regular-expression case handling used by `ILIKE`.
- Extend optimiser differential requirements so Unicode-sensitive scalar rewrites and text execution paths must remain observationally equivalent before and after optimisation.

### Discover 0.23.3 - Like It or Not

- Add SQL-like `LIKE`, `NOT LIKE`, `ILIKE` and `NOT ILIKE` text predicates with `%` and `_` wildcards.
- Define backslash escaping for literal wildcard and backslash characters, and reject incomplete trailing escapes.
- Preserve SQL-like NULL/UNKNOWN behaviour and support the new predicates in lightweight acquisition rejection where exact metadata is available.
- Compile literal LIKE patterns during semantic resolution and cache compiled forms for repeated row evaluation.
- Extend deterministic conformance, malformed-input and differential optimiser coverage across case sensitivity, negation, escaping, Unicode, newlines and wildcard cardinality.
- Document conservative regex-to-LIKE optimisation candidates while declining rewrites whose anchoring, wildcard cardinality, newline or case semantics are not provably equivalent.

### Discover 0.23.2 - Known Quantities

- Add conservative post-resolution scalar constant folding for fully literal arithmetic, unary expressions and deterministic scalar functions.
- Fold nested constant subexpressions recursively while preserving yt-sql NULL behaviour, including NULL results for division and modulo by zero.
- Keep symbolic field algebra deliberately disabled where equivalence has not been proved, including `field * 0`, and extend differential optimiser coverage around those boundaries.
- Add `YT-SQL-OPTIMISATION.md` as the living per-feature optimisation strategy, documenting current rewrites, deliberately excluded transformations, future candidates and differential verification requirements.
- Record the exploratory compiled-query design direction without committing to an implementation.
- Add `El Psy Kongroo.` as a zero-argument Discover easter egg while retaining the existing required-source error and exit status.

### Discover 0.23.1 - Conditional Currents

- Add searched `CASE WHEN ... THEN ... [ELSE ...] END` as a first-class scalar expression in `SELECT` and `ORDER BY`.
- Preserve SQL-like three-valued condition semantics: only TRUE selects a branch, FALSE and UNKNOWN fall through, and omitted `ELSE` returns NULL.
- Validate CASE result compatibility while allowing NULL-only branches and compatible numeric result types.
- Extend acquisition field analysis through CASE conditions and result expressions.
- Optimise predicates nested inside CASE branches to the same deterministic fixed point as top-level filters, with differential conformance coverage for identical rows and serialised output.
- Add malformed syntax, type, nesting, ordering, NULL, planner and optimiser regression coverage for conditional expressions.

### Discover 0.23.0 - Expression Expanse

- Make scalar expressions first-class in `SELECT` and `ORDER BY` instead of treating projection functions as a special case.
- Add arithmetic operators `+`, `-`, `*`, `/` and `%`, including unary `+` and `-`, SQL-like precedence and parenthesised scalar expressions.
- Allow existing scalar functions to nest and accept scalar expressions as arguments while preserving their established NULL behaviour.
- Allow `ORDER BY` to use scalar expressions directly or reference aliases for computed projections.
- Extend acquisition field analysis and deterministic conformance coverage so nested scalar expressions request every metadata field they depend on.

### Discover 0.22.0 - Optimisation Origins

- Add a dedicated semantics-preserving yt-sql predicate optimiser that runs after typed semantic resolution.
- Normalise negation, remove duplicate Boolean terms, collapse degenerate `BETWEEN` expressions and eliminate subsumed same-field comparison bounds.
- Preserve SQL-like three-valued NULL behaviour exactly across optimiser rewrites rather than replacing UNKNOWN-producing contradictions with Boolean constants.
- Expose deterministic optimiser rewrite decisions through verbose execution and `--explain`, including machine-readable JSON explain output.
- Add differential optimiser tests that execute resolved queries before and after optimisation and require identical truth values, selected rows and serialised output across the routine conformance corpus.

### Discover 0.21.0 - Temporal Horizons

- Add typed `INFINITY()` and `-INFINITY()` bounds for date and timestamp comparisons while preserving SQL-like NULL semantics.
- Extend the data-driven unit registry with decade, century and millennium units.
- Add Maya Long Count units from kin through baktun as recursively resolved fixed-day measures.
- Extend deterministic conformance and query tests for temporal infinity and the new unit definitions.

### Discover 0.20.1 - Conformance Corrections

- Fix signed numeric literal resolution so negative values remain numeric after tokenisation, including scalar-function fallbacks such as `COALESCE(view_count, -1)`.
- Add comprehensive deterministic yt-sql conformance coverage for the complete current language surface and its viable edge cases.
- Add malformed-query, semantic-rejection, unit-registry and parameter-binding edge coverage.
- Keep routine semantic conformance fast through in-process production execution while retaining representative real-CLI parity checks.

### Discover 0.20.0 - Multilingual Measures

- Move duration and temporal unit names into external JSON unit-definition files.
- Load English and Welsh units through the same case-insensitive registry, including aliases and shared short forms.
- Resolve derived units recursively to fixed seconds or Gregorian calendar months, with explicit validation for cycles, unresolved references and token collisions.
- Accept Unicode unit names while preserving strict duration and date/time type rules.
- Correct the optional YouTube.js tool-check fixture to model the resolved module path reported by the bridge.

### Discover 0.19.0 - Acquisition Observability

- Resolve optional YouTube.js through the project Node environment and report the resolved module path in `--check-tools`.
- Add coarse stderr progress for lengthy source enumeration while preserving clean stdout query output.
- Emit live large-source notices when enumeration reaches `--warn-source-size`.
- Warn before very-high-cost automatic full-source plans where no safe source boundary is available.
- Refresh tests and current documentation for acquisition and tool-discovery behaviour.

### Repository - Test-suite organisation

- Replace historical Discover phase-based test modules with capability-oriented test modules.
- Split Downloader's catch-all behavioural tests into CLI, input-source, output-profile, queue-reconciliation and command-planning modules.
- Keep routine, scale and stress conformance tiers unchanged while making test ownership clearer for future language work.
- Expand `.gitignore` coverage for script-relative credentials, queues, caches, provenance, downloaded media and yt-dlp sidecars.
- No tool version changed.

### 0.18.1 - Tiered Testing

- Exclude large and huge conformance datasets from routine pytest and pull-request CI by default.
- Add explicit `scale` and `stress` pytest tiers for selected large-dataset and huge torture tests.
- Split cardinality and prefix-contract checks so routine tests never construct the large or huge corpora implicitly.
- Retire the golden query-dataset concept in favour of deterministic generated inputs plus the independent Python semantic oracle.
- Retain deliberately designed semantic anchor records inside the deterministic generator.
- Fix the remaining Ruff test-style finding.

### Repository - Pre-canonical audit

- Recorded intentional version and executable-name differences from the earlier supplied endpoint.
- Added a final canonical comparison checklist covering code, documentation, tests, tooling, modes and repository hygiene.
- No tool version changed.

### Repository - Reliability and stress-test policy

- Made large and huge conformance tests opt-in through the `stress` pytest marker.
- Expanded ignore rules for runtime credentials, ID lists, generated caches and local development state.
- Added downloader test-package scaffolding for cleaner fixture sharing and import isolation.
- Pinned Ruff GitHub Actions checks and restricted workflow permissions to repository read access.
- No tool version changed.

### Discover 0.18.0

- Converged Discover on the mature typed YT-SQL parser, schema and execution model.
- Added dedicated archive, date, output, report, tool-registry, YouTube.js and yt-dlp support modules.
- Expanded acquisition planning, observability, source handling and cache semantics.
- Replaced the preliminary conformance harness with the mature deterministic generator, dataset specification and independent oracle suite.
- Kept large and huge conformance profiles available for deliberate stress runs while disabling them in the default automated suite.
- Added the current Discover and YT-SQL reference documentation.
- Downloader remains at 1.4.2.

### Repository - Executable-mode correction

- Restored executable file modes on the two shebang-bearing CLI entry points after the Phase 37 packaging workflow dropped them.
- No tool version changed.

### Repository - Conformance architecture

- Expanded the deterministic YT-SQL dataset generator to version 2.
- Added `small`, `normal`, `large` and `huge` profiles plus exact-size generation.
- Added an independent expected-result oracle and golden conformance fixtures.
- No tool version changed.

### Discover 0.17.1 / Downloader 1.4.2

- Fixed remaining Ruff E701 findings in Discover parameter coercion.
- Marked both shebang-bearing CLI scripts executable so Ruff EXE001 passes.
- No user-facing behaviour changed beyond the revision maintenance fixes.

Entries are annotated by tool or repository so the independent version lines remain clear.

### Repository - Package foundation

- Moved mature Discover support modules into `yt_media_tools`.
- Moved the YouTube.js bridge beside the packaged source backend.
- Migrated existing Discover tests to package imports.
- No tool version changed.

### Repository - Ruff validation

- Added `ruff.toml`.
- Added check-only Ruff validation in GitHub Actions.

### Discover 0.17.0 / Downloader 1.2.0

- Resolved the first locally identified Ruff findings.
- Made Discover date handling consistently timezone-aware.

### Repository - First automated tests

- Added pytest configuration and separate Discover and Downloader test roots.
- No tool version changed.

### Discover 0.16.2 / Downloader 1.0.0

- Rejected duplicate Discover named-parameter bindings.
- Marked the Downloader interface as stable for ordinary use.

### Discover 0.16.1 / Downloader 0.9.0

- Corrected DISTINCT/LIMIT planning and NULL comparison semantics.
- Formalised the Downloader `@profile` format.

### Discover 0.16.0 / Downloader 0.8.0

- Added DISTINCT, OFFSET, scalar functions, parameters and provenance.
- Narrowed Downloader profiles to presentation settings.

### Discover 0.15.0 / Downloader 0.6.0

- Added proof-based LIMIT-aware acquisition and execution analysis.
- Improved Downloader profile discovery and validation.

### Discover 0.14.0 / Downloader 0.5.0

- Added conservative incremental source refresh.
- Expanded Downloader input handling.

### Discover 0.13.0

- Made the persistent cache a first-class execution source.
- Added offline querying and cache-status reporting.

### Discover 0.12.0

- Added persistent SQLite caching and targeted detailed refresh.
- Added the LGPL-2.1 licence and repository ignore rules.

Earlier reconstructed development remains represented by Git history.

- [maintenance] Use unambiguous backend extractor-family evidence to constrain source-specific metadata provider eligibility without changing yt-sql semantics.
- [maintenance] Preserve generic provider fallback and authentication requirements when backend source identity is unknown, generic or conflicting.
- [test] Cover resolution-aware provider selection, generic URL lookalikes, conflicting extractor families and cookie-authenticated eligibility.
- [docs] Document the conservative boundary between backend source resolution and physical provider selection.
