# Downloader changelog

This file is the authoritative changelog for yt-downloader. Active development and release history are kept here independently from yt-discover.

## Active development

### Parameter-profile option coverage

- [feature] Add typed profile and CLI support for yt-dlp impersonation targets with explicit inherited-policy removal.
- [maintenance] Classify every public CLI destination by persistence semantics so future options require an explicit profileability decision.
- [test] Cover impersonation profile validation, command compilation, override behaviour and CLI classification completeness.
- [docs] Document profileable impersonation policy and the deliberate invocation-only option classes.

## Release history

### Downloader 1.21.1 - Profile Coverage

- Add typed reusable `impersonate` request policy to profiles and the CLI, compiling to yt-dlp `--impersonate`.
- Add `--no-impersonate` so explicit invocations can remove impersonation inherited from a profile.
- Classify every public Downloader CLI destination by persistence semantics and expose the classification through the versioned machine contract.
- Keep input selection, inspection controls, execution modes, reporting destinations and queue-mutating side effects deliberately invocation-scoped.
- Add regression coverage for impersonation policy, profile override behaviour and complete CLI persistence classification.

### Downloader 1.21.0 - Request Policy

- Add typed reusable HTTP request and network policy for User-Agent, Referer, custom headers, proxy, socket timeout, source address and IP-family selection.
- Compile User-Agent and Referer policy to yt-dlp's recommended `--add-headers` representation and reject ambiguous duplicate dedicated and generic headers.
- Adopt the configured Firefox/Linux User-Agent as the shipped default across all bundled profiles through the shared `$values.general.user-agent` value.
- Add the `1440p-slow` bundled profile with a 2.5M rate limit while retaining the shared 1440p output layout and default User-Agent.

### Downloader 1.20.0 - One Profile

- Unify reusable download policy and output layout in the versioned JSON profile system.
- Select the shipped `default` profile automatically and include equivalent single-item and playlist output layouts in `defaults.json`.
- Replace separate parameter/output profile terminology and machine-plan fields with one profile contract, while retaining `--parameter-profile` and `--list-parameters` as compatibility aliases.
- Remove the legacy `@profile` files, `profiles/` directory and separate `-P/--output-profile` selector.
- Remove profile generation, recording and overwrite commands so profiles are managed directly as hand-editable JSON.
- Bump the machine contract and explain-plan schema versions for the unified profile representation.
- Add typed `$values.*` references so profiles can reuse shared JSON values without duplicating configuration, with recursive resolution, cycle detection and `$$` literal-dollar escaping.

### Downloader 1.19.1 - Shared Runtime

- Reuse the shared yt-dlp runtime for executable resolution, version probing, cookie-file resolution, authentication argument emission and diagnostic command formatting.
- Preserve Downloader's typed download policy, command planning, machine contracts and public compatibility wrappers while removing duplicated runtime mechanics.

### Downloader 1.19.0 - Machine Check

- Add runtime parameter-profile validation through `--validate-config`.
- Add human-readable and versioned JSON environment capability reporting.
- Version the non-executing `--explain-json` plan contract independently from Downloader releases.
- Reconcile Downloader TODO and future-work documentation around genuinely outstanding work.

### Downloader 1.18.0 - Common Tongue

- Add `--schema-json` for a versioned, language-neutral Downloader machine contract.
- Publish complete JSON Schema descriptions for parameter-profile files and settings with unknown-key rejection and structural cross-field constraints.
- Expose canonical finite values, configuration precedence and runtime semantic-validation boundaries for machine consumers.
- Keep machine-contract, parameter-profile and run-manifest schema versions independent.
- Add deterministic coverage for contract versioning, runtime-key/schema synchronisation, canonical values, structural constraints and environment-independent schema output.

### Downloader 1.17.0 - Section Slice

- Add first-class derivative acquisition by chapter regular expression and validated time range.
- Use section-aware output naming while preserving the selected output profile's home path.
- Disable whole-item archive completion for partial-media runs and reject completed-ID queue mutation.
- Record derivative section policy and archive state in explain output and run manifests.
- Add explicit whole-item override for partial-media settings inherited from parameter profiles.
- Add deterministic parsing, precedence, command, naming, archive, queue and explanation coverage.

### Downloader 1.16.0 - Live Line

- Add explicit live-media policy with live-edge and supported live-from-start acquisition.
- Add validated scheduled-stream waiting with CLI controls for overriding inherited wait policy.
- Add requested live-chat sidecars without replacing existing subtitle-language selection.
- Keep long-running retry choices explicit and preserve existing interruption, queue, archive and run-manifest completion boundaries.
- Prevent external yt-dlp configuration from silently changing live-from-start or scheduled-wait policy during explicit live mode.
- Add deterministic coverage for live policy validation, profile precedence, command construction, retry composition, live-chat selection and explain output.

### Downloader 1.15.0 - Selected Range

- Add typed playlist selection by individual 1-based indices, inclusive ranges and explicit slices.
- Preserve mixed CLI selection order and compile the complete selection into one canonical yt-dlp playlist-items expression.
- Add `--playlist-forward` as an explicit override for reverse traversal inherited from parameter profiles.
- Support ordered `playlist-items` policy in parameter profiles with strict index and slice validation.
- Reject playlist item selection with explicit no-playlist policy or durable completed-ID queue mutation.
- Preserve normal yt-dlp archive filtering for selected playlist child entries and keep random traversal outside Downloader policy.
- Add deterministic coverage for parsing, validation, profile precedence, command construction, explanation and queue boundaries.

### Downloader 1.14.0 - Source First

- Add first-class `--audio-only` source selection that does not enable audio conversion.
- Add exact source codec/container constraints with explicit fallback control.
- Add `--audio-format` and `--audio-quality` as the explicit boundary that permits yt-dlp/FFmpeg audio conversion.
- Keep existing preferred audio codec/channel settings as fallback-friendly source sorting policy in audio workflows.
- Reject raw format selectors, video-only format policy and subtitle embedding when they conflict with first-class audio mode.
- Expose source-only versus conversion-enabled audio policy through explain output and parameter profiles.
- Add deterministic coverage for source selectors, fallback semantics, conversion commands, validation and cross-policy conflicts.

### Downloader 1.13.0 - Receipt

- Add `--run-manifest FILE` for redacted machine-readable records of actual Downloader runs.
- Record Downloader and yt-dlp versions, timestamps, exit state, known targets, resolved plan data, queue outcomes and successfully completed primary output paths.
- Capture primary output paths through yt-dlp `after_move` callbacks instead of parsing human-readable console output.
- Add optional `--hash-outputs` SHA-256 values for completed primary files as ordinary integrity checks rather than authenticity or provenance claims.
- Reuse explain-plan redaction so sensitive extractor-argument values are never copied into manifests.
- Record requested associated-artefact policy without guessing sidecar paths that Downloader has not authoritatively observed.
- Remove temporary output-event ledgers after manifest construction.
- Add deterministic unit and simulated orchestration tests for manifest schema, output capture, hashing, redaction, interruption, validation and failure handling.

### Downloader 1.12.1 - Closed Loop

- Add orchestration-level regression tests for post-processing failure, completion-callback failure and atomic queue-rewrite failure.
- Require deterministic Downloader behaviour to be covered by automated tests whenever controlled fixtures or simulated process outcomes can represent it faithfully.
- Reserve manual verification for genuinely external or environment-dependent behaviour that cannot be reproduced faithfully in the automated suite.
- Reconcile the Downloader roadmap with the implemented queue and associated-artefact behaviour.

### Downloader 1.12.0 - Queue State

- Add conservative queue outcome accounting for requested, already archived, newly completed and unresolved targets.
- Print a concise queue summary after file-backed completion-removal runs.
- Add `--queue-report FILE` for deterministic machine-readable JSON outcome reports.
- Add `--failed-targets FILE` for atomically generated reusable unresolved-target batch files.
- Preserve unresolved queue entries on failed or interrupted runs and identify interruption explicitly in JSON reports.
- Keep unavailable, skipped and failed classifications deliberately unresolved until the executor can establish those per-target outcomes reliably.
- Add deterministic tests for queue snapshots, outcome classification, interruption and atomic report generation.
- Add simulated end-to-end executor tests proving queue, archive, report and retry-file behaviour for partial failure and interruption.

### Downloader 1.11.0 - Alongside

- Add typed manual/automatic subtitle policy, language and format selection, and independent subtitle embedding.
- Add opt-in thumbnail and info-JSON sidecars plus independent thumbnail embedding.
- Make metadata and chapter embedding explicit typed policy while preserving the established enabled-by-default behaviour.
- Make SponsorBlock policy explicit, preserving remove-all as the built-in default while supporting validated mark/remove categories and complete disabling.
- Expose associated-artefact, metadata, chapter and SponsorBlock decisions through human and JSON explanation.
- Add deterministic tests for historical defaults, explicit disablement, profile precedence, SponsorBlock validation and command compilation.
- Reconcile the shipped parameter-profile example with the 1.10.0 defaults file so it no longer shows removed redundant raw format selectors.

### Downloader 1.10.0 - Selection Rules

- Add declarative hard bounds for minimum/maximum resolution and frame rate, compiled into yt-dlp format filters.
- Add fallback-friendly preferences for video codec, audio codec, frame rate, HDR class and audio channel count using yt-dlp format sorting.
- Add merge-container policy using `--merge-output-format` without silently remuxing or transcoding media.
- Keep raw `-f/--format` selectors authoritative by rejecting combinations with hard declarative format constraints instead of rewriting expert expressions.
- Expose the resolved generated selector, sort order, format bounds, preferences and merge container through human and JSON explanation.
- Remove redundant raw format selectors from the shipped parameter profiles so their effective behaviour continues to inherit Downloader's built-in selector.
- Add deterministic format-policy tests for validation, precedence, selector compilation, sorting, raw-selector authority and explanation output.

### Downloader 1.9.0 - Known Limits

- Expand typed parameter-profile and CLI policy for rate limiting, throttling, fragment concurrency and retry behaviour.
- Add configurable download-archive and temporary paths while preserving the existing built-in defaults.
- Add repeatable retry-sleep and extractor-argument settings with strict JSON typing and explicit CLI precedence.
- Add browser-cookie selection as a first-class authentication source alongside cookie files, automatic cookies and explicit cookie disabling.
- Extend resolved plans and explain output with operational policy, authentication and path decisions, redacting sensitive extractor-argument values from explanation output.
- Keep queue reconciliation bound to the resolved archive path rather than the historical script-local constant.
- Add deterministic coverage for profile validation, precedence, command compilation and explain output.

### Downloader 1.8.0 - Clear Intent

- Separate resolved Downloader configuration from command execution with an explicit immutable download-plan model.
- Add `--explain` and `--explain-json` so effective profiles, policy, authentication, paths, queue behaviour and the final yt-dlp command can be inspected without execution.
- Record whether effective parameter values came from a selected parameter profile or an explicit command-line override.
- Keep `--dry-run` as the exact command-only surface while routing normal execution through the same resolved plan.
- Add deterministic plan-level tests for precedence provenance, command equivalence and human/machine-readable explanation.
- Remove the completed parameter-profile implementation work from the project TODO list.

### Downloader 1.7.0 - Parameter Profiles

- Add versioned JSON parameter profiles selected with `-p/--parameter-profile` and alternate defaults files selected with `-d/--defaults`.
- Ship `best`, `4k`, `1440p` and `playlist` parameter profiles using yt-dlp format selectors directly.
- Add `--list-parameters`, deterministic profile generation, explicit write support and refusal of accidental profile overwrites.
- Add `--overwrite-profile` for deliberate replacement and omit a redundant profile-removal command.
- Preserve command-line precedence over profile settings, including symmetric cookie and playlist overrides.
- Move output-layout profile selection to `-P/--output-profile` while retaining `--profile` as a legacy long-option alias.
- Add `-f/--format` so yt-dlp format selectors can be stored in profiles or overridden directly.

### Downloader 1.6.0 - Optional Cookies

- Make cookies optional by default while continuing to use script-local `cookies.txt` automatically when present.
- Add strict `--cookies FILE` and explicit `--no-cookies` controls.
- Keep missing explicitly requested cookie files as configuration errors.
- Refresh tests and current documentation for the cookie policy.

### Repository - Test-suite organisation

- Replace historical Discover phase-based test modules with capability-oriented test modules.
- Split Downloader's catch-all behavioural tests into CLI, input-source, output-profile, queue-reconciliation and command-planning modules.
- Keep routine, scale and stress conformance tiers unchanged while making test ownership clearer for future language work.
- Expand `.gitignore` coverage for script-relative credentials, queues, caches, provenance, downloaded media and yt-dlp sidecars.
- No tool version changed.

### Downloader 1.5.0

- Adopt the mature downloader policy, profile-resolution and input-source architecture from the canonical implementation.
- Separate output-profile settings from global download policy through explicit `OutputProfile` and `DownloadPolicy` models.
- Formalise direct, batch-file and standard-input source handling through a single `InputSource` abstraction.
- Strengthen profile validation, archive reconciliation, completion callbacks and environment validation.
- Standardise the executable and documentation name on `yt-download.py`.

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

### Repository - Executable-mode correction

- Restored executable file modes on the two shebang-bearing CLI entry points after the Phase 37 packaging workflow dropped them.
- No tool version changed.

### Repository - Conformance architecture

- Expanded the deterministic YT-SQL dataset generator to version 2.
- Added `small`, `normal`, `large` and `huge` profiles plus exact-size generation.
- Added an independent expected-result oracle and golden conformance fixtures.
- No tool version changed.

### Repository - Package foundation

- Moved mature Discover support modules into `yt_media_tools`.
- Moved the YouTube.js bridge beside the packaged source backend.
- Migrated existing Discover tests to package imports.
- No tool version changed.

### Downloader 1.4.1

- Hardened exact completed-ID queue removal.
- Preserved queue permissions and unrelated raw bytes during replacement.
- Centralised script-relative runtime paths.

### Downloader 1.4.0

- Moved queue completion to yt-dlp's per-item `after_move` lifecycle.
- Retained pre-run archive reconciliation as a recovery path.

### Downloader 1.3.0

- Added an explicit input-source model.
- Expanded the stable yt-dlp runtime policy.

### Repository - Ruff validation

- Added `ruff.toml`.
- Added check-only Ruff validation in GitHub Actions.

### Downloader 1.1.0

- Hardened persistent queue reconciliation and exact-ID removal.

### Downloader 1.0.1

- Fixed profile output templates being ignored during command construction.

### Repository - First automated tests

- Added pytest configuration and separate Discover and Downloader test roots.
- No tool version changed.
