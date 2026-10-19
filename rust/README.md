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

The Part 5 acceptance boundary and remaining certification requirements are recorded in [`PART-5-ACCEPTANCE.md`](PART-5-ACCEPTANCE.md).

## Compatibility and future work

`rust/CLI-COMPATIBILITY-AUDIT.md` records supported behaviour, deliberate differences and regression checks. `rust/PYTHON-CLI-OPTION-INVENTORY.md` records Python options and their preliminary ownership; it does not imply that deferred options are accepted by Rust.

Native target handling, invocation context, side-effect-free yt-dlp planning and execution lifecycle contracts form the architectural foundation. Opt-in library adapters now provide controlled metadata acquisition and supervised yt-dlp execution with structured progress; the public Rust CLI still refuses downloads. Real download-output parity, output processing and persistent queue workflows remain separate later work. Preserve the existing Python yt-dlp renaming plugin and certify naming equivalence before any Rust cutover.

## Target-source resolution

The native `targets` module represents positional targets, standard input and batch files without invoking yt-dlp. It preserves target ordering and duplicates, recognises a lone `-` as standard input, and applies the Python Downloader's existing-file rule to a single positional target. An explicit input file cannot be combined with positional targets. Collection manifests are rejected by this module until their separate collection-resolution contract is implemented. Target resolution is a library capability only: the experimental CLI still refuses native downloads, and no execution plan or yt-dlp process integration is implied.

## Invocation context

The native `invocation` module combines a validated profile selection, explicit settings overrides and a resolved target source into a typed context. It preserves profile provenance and direct-target order, rejects invalid effective policy and conflicting target sources, and does not construct yt-dlp commands or start downloads. Callers must load and validate profile documents before constructing the context. Collection manifests remain unsupported by the target resolver. The executable is unchanged; planning and execution integration are separate work.

The native `planning` module constructs a deterministic, inspectable yt-dlp argument plan from a validated invocation context. It preserves target order and batch/stdin distinctions. Only explicitly mapped boolean settings are currently translated; other validated settings fail closed until their full Python-compatible semantics are implemented. The plan contains arguments, not an executable invocation, and does not launch yt-dlp or enable downloads.

## Execution lifecycle contracts

The native `lifecycle` module defines explicit execution states, transition validation, structured progress and failure events, an event-sink interface and a thread-safe cancellation signal. These are library-only contracts for a future yt-dlp process adapter. A lifecycle holds an existing execution plan but never launches a process, performs I/O or interprets external output. Invalid transitions and inconsistent progress reports are rejected without emitting events. Cancellation requests are signals; the future adapter is responsible for honouring them and safely terminating any child process.

## Part 4 regression certification

The cross-module tests in `crates/yt-downloader/tests/part4_contract.rs` exercise profile loading and overrides through target resolution, argument planning and lifecycle transitions without launching yt-dlp. `CLI-COMPATIBILITY-AUDIT.md` records the supported contracts and the unimplemented Python-equivalence boundaries. The planner's five mapped boolean settings are deliberately not a complete download policy. Actual process execution, format selection, output naming and queue handling require separate implementation and certification.

## Native process launch boundary

The `process` module constructs an unspawned `std::process::Command` from a validated execution plan and caller-selected executable and working directory. It retains argument order, duplicates and standard-input batch semantics without shell interpretation or implicit working-directory changes. Standard streams are inherited pending a dedicated output and cancellation supervisor. This library-only boundary does not launch yt-dlp or enable downloads in the experimental executable.

## Process supervision

The native `supervision` module provides a synchronous, library-only child-process adapter for a prepared `ProcessLaunch`. It records running, successful, unsuccessful and cancelled outcomes through the existing lifecycle and event-sink contracts. A cancellation request terminates and reaps the child; a request made before launch prevents spawning. Spawn failures are returned without falsely marking a process as running. Standard streams remain inherited and no yt-dlp output is interpreted. The experimental CLI does not call this adapter, and download execution remains disabled pending compatibility certification.

The `process_output` module provides a bounded, library-only parser for explicitly framed byte-progress records. It rejects malformed values, overlong records and completed counts greater than a known total, while ignoring unrelated process output. The supervisor still inherits standard streams: configuring a yt-dlp progress template, capturing streams and feeding validated observations into lifecycle events remain subsequent integration work.

The experimental process supervisor also offers an explicitly selected yt-dlp progress launch that appends `--newline` and a `--progress-template` download record. Generic launches are unchanged, and the public CLI does not yet activate this execution path. Progress records with unavailable totals remain advisory and do not replace terminal lifecycle state.

## Part 5: Metadata acquisition and explicit execution

The native `metadata` module decodes a bounded yt-dlp JSON document into a validated single-media identity record. It rejects collections and malformed records, and exposes an opt-in acquisition API with a caller-selected executable, explicit working directory, bounded output and a configurable execution deadline. This does not implement implicit executable discovery, format selection or public CLI download activation.

The `download` module exposes an opt-in library execution adapter that accepts an already validated plan, a caller-selected executable, an explicit working directory, a cancellation signal and an event sink. It uses the supervised yt-dlp progress path, preserves planned target arguments and reports successful, failed and cancelled outcomes. The public Rust executable continues to reject download operations.

Unix mock-process tests cover structured progress before terminal success or failure, cancellation after progress, literal and duplicate targets, batch-file argument forwarding and the standard-input marker. The standard-input fixture does not read inherited stdin, so delivery of actual stdin contents is not certified. These tests do not establish complete Python Downloader compatibility, real yt-dlp download success, output naming equivalence, renaming-plugin parity or persistent queue behaviour. Those remain explicit certification requirements before native download activation.
