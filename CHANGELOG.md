# Changelog

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
