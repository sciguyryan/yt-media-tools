# Development changelog

This file records meaningful changes during active development. It is not release history. When a dot release is completed and accepted, relevant entries are reconciled into the root `CHANGELOG.md` and the completed development section is cleared or advanced for the next work item.

## Discover - pytubefix metadata benchmark

- [feature] Add pytubefix as an optional experimental provider in the shared known-video metadata benchmark without changing production provider selection.
- [feature] Preserve pytubefix playability and video-detail signals and inventory thumbnail, chapter and caption capabilities separately from scalar normalisation.
- [maintenance] Advance the experimental metadata benchmark schema to version 6 and retain per-video pytubefix acquisition timing.
- [test] Cover pytubefix provider selection, normalisation, extended capability isolation and per-video failure handling with deterministic fixtures.
- [docs] Define the issue #104 benchmark method, optional dependency, capability inventory and production-promotion boundary.

## Discover - Capability-oriented metadata provider selection

- [maintenance] Add backend-neutral metadata requirement and provider-capability contracts covering authority, field coverage, resolved source applicability, authentication, acquisition granularity, provenance and relative physical cost.
- [maintenance] Project existing physical acquisition stages into provider requirements without changing yt-sql semantics or runtime acquisition behaviour.
- [test] Add deterministic coverage for exact authority, field coverage, source constraints, cookie requirements, cost ordering and physical-plan projection.
- [docs] Define the provider-selection boundary and its deliberate exclusions before provider benchmarks and production integration.

## Discover - Backend source resolution

- [feature] Retain yt-dlp's reported extractor identity, extractor key, result type and source domains as backend source-resolution provenance.
- [ux] Show observed backend source resolution at verbose interactive output without changing query-result output.
- [maintenance] Derive a conservative extractor-family namespace for future physical provider eligibility without treating it as yt-sql platform semantics.
- [test] Add deterministic coverage for YouTube, Twitch, generic and missing backend-resolution metadata.
- [docs] Define the distinction between user source expressions, Discover logical sources and backend-reported resolution evidence.

## Discover - YouTube.js basic metadata benchmark

- [fix] Make the benchmark subprocess policy explicit with `check=False` while preserving manual return-code diagnostics.
- [maintenance] Extend the existing YouTube.js bridge with an experimental `getBasicInfo()` benchmark mode that reuses one Innertube session across a known-ID corpus.
- [test] Add deterministic benchmark-contract coverage for scalar field comparison and missing-value handling without adding live network tests to pytest.
- [docs] Define the benchmark methodology, candidate scalar field surface, publication-date gap, corpus requirements and production-integration boundary.

## Discover - yt-sql query file input

- [feature] Add `--query-file FILE` for loading reusable UTF-8 yt-sql queries through the existing query-processing path.
- [cli] Keep query files mutually exclusive with `--query` and `--where` while preserving the established positional-source plus query form.
- [test] Add deterministic coverage for inline equivalence, parameters, positional sources, conflicting inputs, unreadable files and invalid UTF-8.
- [docs] Document reusable `.yt-sql` file workflows and keep query files limited to ordinary yt-sql without a separate preprocessing or scripting layer.
