# Experimental Rust Downloader

This workspace is the start of a parallel native implementation of `yt-download.py`. The Python application remains the production Downloader. The Rust binary currently implements only a development `--help` and `--version`; it does not download media or claim CLI compatibility.

The workspace uses Rust edition 2024 and Cargo resolver 3. Use the latest viable stable Rust toolchain with edition 2024 support. A specific minimum supported Rust version and toolchain pin should be chosen once dependencies and target platforms have been evaluated. No external crates are required by this initial scaffold. `Cargo.lock` is tracked for reproducibility.

The crate references the repository's existing `LICENSE` through Cargo's `license-file` field. This avoids claiming an SPDX licence grant that has not yet been verified.

From `rust/`, run `cargo build --workspace`, `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D warnings` and `cargo test --workspace`. The Rust GitHub Actions workflow runs these checks automatically, alongside `cargo doc` and `cargo audit`. Cargo was not available in the packaging environment, so local compilation and execution still require verification.

For an initial comparison of the two independently invoked entry points, run `python rust/tests/compare_python_rust.py --rust-binary rust/target/debug/yt-download-rs` from the repository root after building. The harness captures exit codes and output for `--help` and `--version`, but does not assert parity at this stage. Later implementation issues should add structured policy and execution-plan fixtures and explicit assertions.

The Part 1 audit is retained at `docs/development/RUST-DOWNLOADER-PART-1-AUDIT.md` until the port is reconciled. It can be removed in a later commit while remaining in Git history.

The initial Rust integration tests verify the experimental CLI help, version and fail-closed behaviour. They do not claim Python parity. Future differential tests must assert equivalence for each ported feature. Routine CI must remain independent of live network downloads.

## Part 3: CLI and configuration, first slice

The Rust library now provides side-effect-free parsing for the profile selection, defaults-file and profile-listing flags, including their Python aliases, plus strict ASCII profile-name validation. It does **not** load JSON profiles or execute these flags in the binary yet. The binary deliberately continues to reject them rather than pretending to implement profile resolution.

This is an intentionally narrow first step. The next step is to select a maintained JSON crate, implement strict version 2/3 profile loading, `$values` and `$defaults` references, inheritance and typed validation, then add deterministic differential tests against Python. Cargo dependencies and `Cargo.lock` should be updated together in a toolchain-enabled environment. Avoid hand-writing a JSON parser or fabricating a lockfile.

## CLI smoke-test repair

The initial smoke tests assumed that Cargo's binary test path was directly executable in every environment. The three checks now exercise the pure response function used by the actual binary, avoiding a second process launch. This verifies response semantics but does not replace a future end-to-end executable smoke test.

## Clap adoption candidate

The profile-option parser now delegates tokenisation and alias handling to Clap. This is a candidate requiring Cargo lockfile regeneration and local tests. The existing lockfile is deliberately not hand-edited. Run `cargo generate-lockfile` in `rust/` with the latest stable toolchain, commit the resulting `Cargo.lock`, then run the normal locked quality gates. Do not merge this candidate without the lockfile update. The binary remains intentionally fail-closed for profile operations until configuration resolution is implemented.
