# Changelog

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
