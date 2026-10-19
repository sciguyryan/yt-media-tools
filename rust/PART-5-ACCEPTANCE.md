# Part 5 acceptance and reconciliation

This document records the acceptance boundary for the experimental Rust Downloader's Part 5 process and execution programme. It distinguishes the implemented library interfaces and deterministic regression coverage from capabilities that remain unimplemented or unverified. The Python Downloader remains the production application and behavioural authority.

## Implemented native boundaries

- Explicit subprocess construction from validated execution plans, retaining argument order and literal target handling without shell interpretation.
- Process supervision with lifecycle transitions, structured progress observations, cancellation and unsuccessful-exit reporting.
- Bounded progress parsing and stream decoding, reader completion and error reporting, and bounded reader shutdown.
- Single-record metadata decoding and controlled acquisition with bounded output, an execution deadline and explicit executable and working-directory selection.
- An opt-in download execution adapter with progress and lifecycle events. The public Rust CLI does not activate downloads.

## Evidence and acceptance checks

Rust unit and Unix mock-executable integration tests exercise metadata acquisition, planned argument forwarding, progress ordering, failure reporting, active cancellation, batch-file arguments and the standard-input marker. The metadata fixtures publish closed executable files before spawning; executable-busy startup retries are bounded by the acquisition deadline. The tests are intended to be deterministic but do not constitute live provider or cross-platform certification.

Run the following from `rust/` and retain the output with the Part 5 acceptance record:

```sh
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --all-targets --locked
```

From the repository root, after building the Rust executable, run the independent CLI contract checks:

```sh
python rust/tests/compare_python_rust.py --rust-binary rust/target/debug/yt-download-rs
python rust/tools/check_cli_contract.py rust/target/debug/yt-download-rs
```

The comparison harness includes the Python schema-fixture freshness check; there is no separate schema checker script. These commands must be evaluated in the user's local toolchain. Passing tests must not be inferred merely from the presence of test cases or a valid ZIP archive.

## Explicit exclusions and residual risks

- Live yt-dlp download compatibility, version-specific progress output, media format selection, post-processing, output naming, renaming-plugin behaviour and persistent queue workflows are not certified.
- Actual standard-input content delivery is not certified; current tests verify the forwarded source marker only.
- The process supervisor reaps its direct child, but does not guarantee termination of all descendants. A descendant retaining an output pipe can leave a detached reader alive after the bounded shutdown timeout.
- Progress observations use a bounded advisory queue and can be dropped under pressure. They are not a lossless audit record.
- Mock-executable integration tests are Unix-specific; equivalent Windows process and stream behaviour is not certified.
- The experimental Rust CLI remains download-disabled. Python version 2 profiles and much of the Python option inventory remain outside the implemented Rust interface.

## Final tests and documentation review

The final clean-up reviewed the Rust workspace test files, embedded module tests, Unix mock-executable integration coverage, CI quality gates and the three Rust documentation entry points. The Part 4 cross-module tests remain useful as a planning-only contract; Part 5 integration tests exercise subprocess behaviour separately. No test file was removed merely because its coverage overlaps another layer. The nonexistent `check_schema_fixture.py` invocation was removed from acceptance instructions: schema drift is already checked byte-for-byte by `compare_python_rust.py`. The README was consolidated to remove obsolete statements that process supervision and progress integration were still future work.

This is a source and packaging review, not an independent successful Cargo execution. Local acceptance results remain the authority for Rust compilation, Clippy and tests.

## Closure decision

Part 5 can be accepted as an **experimental library execution foundation**, not as a Python-compatible replacement Downloader, once the full local acceptance checks pass and the residual boundaries above are explicitly accepted. Any broader native CLI activation or claims of live download parity require a separate implementation and certification programme.

The combined-project release archive must retain both Python tools and the Rust workspace. Existing file bytes and executable modes must be preserved for unchanged entries, and changed entries must be checked against the repository's Git index rather than merely against the previous archive.
