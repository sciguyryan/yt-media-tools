# Changelog

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
