# Experimental Rust Downloader

The Rust Downloader (`yt-download-rs`) is an experimental implementation alongside the production Python `yt-download.py`. Python remains the behavioural reference. The Rust CLI supports a limited configuration and inspection interface but **does not download media**. The Rust library provides opt-in process execution for callers that explicitly select the executable and working directory.

## Supported interfaces

The Rust configuration layer supports version 3 profiles, typed settings, `$values`, `$defaults`, single-parent inheritance, cycle detection, profile selection, precedence and provenance. Version 2 profiles remain Python-only. The CLI supports a bounded set of configuration inspection commands and overrides, and rejects unavailable download operations. Its `--schema-json` response is a snapshot of the Python reference contract, not a declaration of implemented Rust capabilities.

The native library modules have separate responsibilities:

- `targets` resolves direct targets, batch-file paths and standard-input selection, preserving order and duplicates. Collection manifests are not supported.
- `invocation` validates the effective profile, explicit overrides and target source without launching processes.
- `planning` produces deterministic yt-dlp arguments. Only five mapped boolean settings are currently translated; unsupported settings fail closed.
- `lifecycle` defines execution states, progress and failure events, cancellation signals and transition validation.
- `process` constructs a process command from a validated plan, caller-selected executable and working directory, preserving literal arguments without a shell.
- `process_output` and `progress_stream` decode bounded, explicitly framed progress observations.
- `supervision` launches and reaps the direct child, handles cancellation, captures structured progress and bounds reader shutdown.
- `metadata` validates single-media JSON and offers controlled acquisition with an output limit and execution deadline.
- `download` executes an already validated plan through the supervised yt-dlp progress path. It is **not called by the public Rust CLI**.

## Build and verification

From `rust/`:

```sh
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --all-targets --locked
cargo build --workspace --all-targets --locked
RUSTDOCFLAGS="-D warnings" cargo doc --workspace --no-deps --locked
```

From the repository root, after building the Rust executable:

```sh
python rust/tests/compare_python_rust.py --rust-binary rust/target/debug/yt-download-rs
python rust/tools/check_cli_contract.py rust/target/debug/yt-download-rs
```

Use the corresponding `.exe` path on Windows. The comparison harness checks that the Python machine-schema output matches the committed reference fixture, and compares selected version 3 profile-validation results. These checks do not establish complete Python/Rust equivalence or live download compatibility. `rust/Cargo.lock` should be maintained through Cargo and committed for reproducible `--locked` builds.

## Compatibility and acceptance boundary

[`CLI-COMPATIBILITY-AUDIT.md`](CLI-COMPATIBILITY-AUDIT.md) records the detailed Python/Rust differences; [`PYTHON-CLI-OPTION-INVENTORY.md`](PYTHON-CLI-OPTION-INVENTORY.md) records the Python option inventory and preliminary ownership, not implemented Rust support. [`PART-5-ACCEPTANCE.md`](PART-5-ACCEPTANCE.md) records the accepted Part 5 scope and residual risks.

Unix mock-executable tests cover metadata acquisition, literal and duplicate targets, batch-file argument forwarding, the standard-input marker, progress, cancellation, failure handling and event ordering. They do not certify actual stdin content delivery, live yt-dlp downloads, cross-platform process behaviour, output naming, format selection, post-processing, the Python renaming plugin or persistent queues. The direct child is reaped, but descendant-process cleanup is not guaranteed, and progress is advisory rather than lossless. These limitations must be addressed separately before public Rust download activation.
