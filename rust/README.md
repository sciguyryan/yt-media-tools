# Experimental Rust Downloader

The Rust Downloader is a parallel implementation of `yt-download.py`, provided as `yt-download-rs` in `rust/crates/yt-downloader`. The Python Downloader remains the production application and the behavioural reference. The Rust executable does not download media.

## Implemented foundation

The native library supports typed profile configuration, version 3 profile documents, `$values`, `$defaults`, single-parent inheritance, cycle detection, profile selection, precedence and provenance. The executable provides a bounded set of configuration inspection commands and supported CLI overrides, with diagnostics and explicit rejection of unavailable download operations. Rust deliberately rejects version 2 profile documents; Python continues to support them.

The Rust `--schema-json` output uses a snapshot of the Python machine contract as a compatibility reference. This is not a claim that the Rust executable implements all interfaces described by the schema. Native capability reports and actual yt-dlp execution are not yet implemented.

The workspace uses Rust edition 2024 and Cargo resolver 3. The crate uses Clap, serde_json, home and unicode-casefold. Its Cargo manifest refers to the repository's existing `LICENSE` file. Keep `rust/Cargo.lock` resolved by Cargo and committed for reproducible locked builds.

## Build and verification

From `rust/`:

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --all-targets --locked
cargo build --bin yt-download-rs --locked
```

From the repository root after building the binary:

```bash
python rust/tests/compare_python_rust.py --rust-binary rust/target/debug/yt-download-rs
python rust/tools/check_cli_contract.py rust/target/debug/yt-download-rs
```

Use the corresponding `.exe` binary path on Windows. The comparison harness verifies selected version 3 profile-validation outcomes and the Python schema reference, while recording help/version output without requiring text equality. The CLI checker verifies bounded executable inspection and diagnostic contracts. Neither check requires live downloads or proves complete Python/Rust parity.

## Compatibility and future work

`rust/CLI-COMPATIBILITY-AUDIT.md` records supported behaviour, deliberate differences and regression checks. `rust/PYTHON-CLI-OPTION-INVENTORY.md` records Python options and their preliminary ownership; it does not imply that deferred options are accepted by Rust.

Native target handling, invocation context, side-effect-free yt-dlp planning and execution lifecycle contracts form the next architectural stage. yt-dlp process integration, actual downloads, output processing and persistent queue workflows remain separate later work. Preserve the existing Python yt-dlp renaming plugin and certify naming equivalence before any Rust cutover.

## Target-source resolution

The native `targets` module represents positional targets, standard input and batch files without invoking yt-dlp. It preserves target ordering and duplicates, recognises a lone `-` as standard input, and applies the Python Downloader's existing-file rule to a single positional target. An explicit input file cannot be combined with positional targets. Collection manifests are rejected by this module until their separate collection-resolution contract is implemented. Target resolution is a library capability only: the experimental CLI still refuses native downloads, and no execution plan or yt-dlp process integration is implied.
