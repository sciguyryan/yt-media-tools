# Experimental Rust Downloader

This workspace is the start of a parallel native implementation of `yt-download.py`. The Python application remains the production Downloader. The Rust binary currently implements only a development `--help` and `--version`; it does not download media or claim CLI compatibility.

The workspace uses Rust edition 2024 and Cargo resolver 3. Use the latest viable stable Rust toolchain with edition 2024 support. A specific minimum supported Rust version and toolchain pin should be chosen once dependencies and target platforms have been evaluated. No external crates are required by this initial scaffold.

The crate references the repository's existing `LICENSE` through Cargo's `license-file` field. This avoids claiming an SPDX licence grant that has not yet been verified.

From `rust/`, run `cargo build --workspace`, `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D warnings` and `cargo test --workspace`. Cargo was not available in the packaging environment, so these commands still require local verification.

For an initial comparison of the two independently invoked entry points, run `python rust/tests/compare_python_rust.py --rust-binary rust/target/debug/yt-download-rs` from the repository root after building. The harness captures exit codes and output for `--help` and `--version`, but does not assert parity at this stage. Later implementation issues should add structured policy and execution-plan fixtures and explicit assertions.

The Part 1 audit is retained at `docs/development/RUST-DOWNLOADER-PART-1-AUDIT.md` until the port is reconciled. It can be removed in a later commit while remaining in Git history.
