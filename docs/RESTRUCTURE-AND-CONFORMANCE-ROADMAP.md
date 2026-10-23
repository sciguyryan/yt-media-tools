# Repository restructure and cross-implementation roadmap

Status: Python relocation and the combined Python/Rust test runner are implemented. Shared operational SQLite statements live under `common/sqlite/`. The root `yt-sql/` corpus has approved-case validation, a Python execution adapter and a permanent CI conformance runner; Rust adoption and systematic migration of existing language tests remain outstanding. This roadmap retains the original programme rationale; current commands and contracts are documented in the relevant component READMEs.

## Long-term organisation

Maintain the Python and Rust implementations as first-class, independently supported tools. Introduce a `python/` subtree analogous to the existing `rust/` subtree, retaining existing Python module and executable names unless there is a separately justified compatibility change. The root README will describe the components and point to their own documentation, tests, entry points and support status. Keep Discover and Downloader changelogs separate.

Do not assume that moving a source directory is only a Git operation. Audit imports, launchers, `PYTHONPATH`, test discovery, subprocess working directories, fixture paths, CI, build/release packaging, documentation links, shell examples, and external consumers. In particular, verify yt-dlp discovery of `yt_dlp_plugin_packages` in direct Python invocation, packaged Python installations and Rust-launched yt-dlp processes. Avoid opportunistic global `sys.path` changes and accidental loading of a different plugin installation. Preserve Git file modes, executable entry points and combined-project archive contents.

## Shared SQL source policy

Canonical operational SQLite statements belong in `common/sqlite/statements/`, grouped by common operations or owning database schema. Python and future Rust consumers should load or embed the same resources rather than copy queries. SQLite's schema versions, transactions and migration invariants remain owned by the relevant implementation. The [SQLite README](../common/sqlite/README.md) defines placement, linting, parameter binding and justified exceptions to externalisation.

The separate root `yt-sql/` directory holds the language-neutral **yt-sql conformance corpus**, not SQLite operational statements or the yt-sql engine. Each implementation will maintain an expectations manifest, defaulting to passing canonical positive and negative tests, with explicit justified `xfail` entries for known deviations.

## Preparatory programme before issue #166 resumes

1. Inventory current root-level Python files, packages, scripts, tests, CI, releases, paths, documentation and plugin-loading assumptions. Produce an explicit relocation map and acceptance matrix.
2. Relocate the Python implementation to `python/` with semantic preservation, repaired invocations and explicit plugin-discovery regression tests.
3. Inventory SQLite schemas and migration sources. Extract appropriate statements into `common/sqlite/`, preserving historical database compatibility and packaging integrity. This work is under way.
4. Reconcile documentation, CI, release archives, executable permissions and complete test suites before resuming issue #166. Keep the accepted #166 Phase 1 candidate and its planning notes intact during this preparatory programme.

## YT-SQL conformance corpus programme

**Sequence:** after the Downloader work is complete, but **before beginning the Rust Discover port**, establish a language conformance corpus modelled conceptually on Web Platform Tests: portable, independently inspectable test cases specifying a query, a deterministic dataset and the expected result or expected diagnostic. Python Discover, Rust Discover and any future yt-sql implementation must execute the same cases and satisfy the same observable contract.

The current `yt_discover_tests/conformance/` infrastructure already provides deterministic generated datasets, seeded profiles, semantic anchors and an independent Python oracle. Its present README explicitly states that it does not maintain a checked-in golden query/result corpus. The portable corpus now includes independently reviewed expectations, while the existing Python oracle remains a distinct testing layer. Neither is interchangeable with the other.

### Corpus design requirements

- Define a versioned, language-neutral manifest and dataset format with stable record identity, field types, NULL semantics, timestamps, Unicode, collections, numeric boundaries and deterministic ordering rules. Preserve source/facet context where relevant.
- Store each test's query, input dataset reference, parameter bindings, expected result or expected error, feature tags, canonical serialisation rules and provenance. Distinguish ordered results from unordered relations explicitly; do not depend on incidental SQLite row order.
- Cover the supported yt-sql grammar and semantic features systematically, including joins, CTEs, set operations, grouping, aggregates, expressions/functions, NULL/three-valued logic, temporal behaviour, numeric bases, Unicode, parameters, randomness and diagnostics. Specify seeded randomness and exclude or separately classify inherently volatile expectations.
- Include deliberately complex interactions and the previously agreed maximal yt-sql torture case, without relying on that single case as a substitute for focused semantic coverage.
- Derive initial cases from existing tests, independent oracle behaviour and separately reasoned specifications. Review and freeze expected outcomes independently rather than blindly recording whichever result the current Python engine happens to emit. Track corrections and compatibility changes through corpus versions.
- Provide a common runner protocol and per-implementation adapters. Verify complete, canonical outputs and error classifications, not just success status. Keep synthetic datasets and fixtures reproducible and runnable offline.
- Maintain distinct layers for language conformance, optimiser differential/property tests, performance/stress tests, backend acquisition and integration tests. Conformance cases can replace duplicated language-semantic assertions only when equivalent coverage and regression sensitivity are demonstrated. Retain implementation-specific and non-semantic tests.
- Establish governance for adding features, resolving disputed semantics, deprecating cases, reviewing corpus changes and reporting per-feature conformance. No implementation is permitted to silently alter expected outcomes to match itself.

### Delivery boundary

The corpus is separate from the repository relocation and issue #166 queue/filesystem work. Its initial Python runner and CI gate are implemented, but Rust adoption and systematic replacement of overlapping Python semantic tests require separate review. Existing independent oracle and implementation-specific tests remain in place until equivalent coverage is demonstrated.
