# Rust Downloader CLI compatibility audit

This audit compares the experimental Rust argument surface with the Python Downloader in the same combined project. It records observed contracts and outstanding differences; it does not authorise changes to accepted behaviour without accompanying regression coverage.

## Implemented in Rust

- `-p`, `--profile`, `--parameter-profile`: named profile selection.
- `-d`, `--defaults`: defaults file selection.
- `--list-profiles`, `--list-parameters`: profile listing.
- `--playlist`, `--no-playlist`: playlist policy.
- `--audio-only`, `--no-audio-only`: source-selection policy.
- `--embed-metadata`, `--no-embed-metadata`: metadata embedding.
- `--embed-chapters`, `--no-embed-chapters`: chapter embedding.
- `--embed-thumbnail`, `--no-embed-thumbnail`: thumbnail embedding.
- `--audio-format`, `--audio-quality`: audio conversion settings, including `--option=value` forms.
- Experimental help/version handling. Downloads are deliberately unavailable.

## Confirmed compatibility differences

### Mutually exclusive switches

Python constructs mutually exclusive argument groups for at least the `--playlist`/`--no-playlist`, `--audio-only`/`--no-audio-only`, and `--embed-thumbnail`/`--no-embed-thumbnail` pairs. Supplying both opposing switches is therefore a Python argparse error.

The executable-facing combined Rust override extractor now rejects opposing switches and permits repeated identical switches, matching the Python mutually exclusive group contract. The infallible public boolean-only extraction helper deliberately retains its established last-switch-wins contract for compatibility; only the combined parser used by the executable enforces mutual exclusion. Both behaviours have dedicated regression coverage.

### Machine-readable and inspection commands

The following contracts are confirmed from `yt-download.py` in this combined archive. Some inspection commands remain guarded and others have partial Rust implementations. Machine-readable output must not be approximated or advertised as equivalent until its schema and versioning are ported and tested.

| Python command | Python behaviour | Rust status | Proposed ownership |
| --- | --- | --- | --- |
| `--schema-json` | Must be the only CLI argument; emits the versioned Downloader machine contract and profile JSON Schema. | Reference snapshot implemented; freshness check required | Reference snapshot implemented; keep it in sync with Python. |
| `--capabilities` | Must be the only CLI argument; emits a human-readable capabilities report. | Unsupported | Parts 4–5: retain guarded behaviour until native capability facts are available. |
| `--capabilities-json` | Must be the only CLI argument; emits a sorted, indented JSON capabilities payload. Cannot be combined with `--capabilities`. | Unsupported | Parts 4–5: retain guarded behaviour until native capability facts are available. |
| `--validate-config [FILE]` | Optional path. When omitted, validates the resolved defaults path. Emits a sorted, indented JSON validation result; validation errors are parser errors. | Implemented subset | Retain differential validation and diagnostics checks. |
| `--profile-tree [NAME]` | Optional focus name. Uses the resolved defaults path, returns an informative message if implicit defaults are absent, and renders a validated hierarchy with a terminal-encoding-dependent ASCII fallback. | Implemented subset | Retain terminal-encoding and diagnostics checks. |
| `--list-profiles` / `--list-parameters` | Lists names from resolved defaults and handles absent implicit defaults without failure. | Implemented subset | Retain profile-listing regression checks. |

The Python entry point handles `--schema-json`, `--capabilities` and `--capabilities-json` before normal configuration loading and explicitly requires their argument to be used alone. It handles `--validate-config` before profile selection and handles `--profile-tree` before ordinary listing. The ordering is significant: these commands should not inadvertently require a selected download profile or attempt a download.

**Implementation boundary:** The versioned Python machine schema and capabilities payload are public contracts, not incidental text. Until Rust has an equivalent source of truth, it must continue to fail closed rather than print a fabricated or incomplete payload. Deferred commands must remain explicitly guarded until their implementation is verified.

### Positional targets and option ordering

Python accepts multiple positional targets and input-file workflows. Rust recognises only a single positional target as an unavailable download operation. A robust parse-only contract must be established without accidentally enabling download execution.

### Value semantics and errors

Python argparse enforces supported `--audio-format` choices at the CLI boundary; Rust currently validates after profile selection. Python normalises audio-quality values and has distinct error wording. Compare accepted/rejected values, repeated flags, `--option=value`, Unicode/path arguments, negative-looking values and exit status.

### Remaining settings and profiles

Reconcile the complete Python argument inventory against the Rust typed settings registry, including defaults precedence, explicit overrides, profile inheritance, cross-setting constraints, `chapter-sections` regular-expression semantics and output/provenance behaviour.

## Compatibility boundaries

Rust supports version 3 profiles; Python continues to support version 2. The native executable remains download-disabled, and unsupported execution options must fail closed. The Python machine schema snapshot is a reference contract rather than a statement that every interface is implemented in Rust. Capabilities reporting remains unavailable until it can describe the native backend truthfully.

The profile-tree renderer supports deterministic hierarchy presentation and a locale-based ASCII fallback. Python determines fallback from stdout encoding, which can differ from locale-derived behaviour, particularly on Windows. The Rust defaults path is executable-relative, whereas the Python path is script-relative. These differences should remain visible in compatibility testing.

The Python yt-dlp renaming plugin, its packaging and output naming behaviour must be preserved at any eventual Rust cutover.

## Versioned schema reference

The Rust `--schema-json` command returns the canonical Python machine-contract snapshot stored in `rust/crates/yt-downloader/fixtures/python-machine-contract.json`. The snapshot was generated from the packaged Python `yt-download.py --schema-json` command, rather than reconstructed from the Rust profile setting definitions. It preserves the Python contract's complete JSON payload and deterministic presentation, including the Python Downloader version and interfaces that are not yet available in Rust. It is a **reference contract**, not an assertion that Rust implements every advertised interface. Revalidate and regenerate it whenever the Python machine contract changes. A future native capability descriptor must distinguish implemented Rust behaviour from the reference schema.

## Schema-reference freshness check

The committed `rust/crates/yt-downloader/fixtures/python-machine-contract.json` snapshot must remain byte-for-byte equal to the current Python Downloader `--schema-json` output. Run `python rust/tools/check_schema_fixture.py` from the repository root after Python schema changes and during Part 3 certification. The checker exits non-zero on drift and does not silently regenerate the reference. Any intentional contract change requires an independently reviewed fixture update and Rust compatibility assessment. The Rust regression test checks the embedded fixture's output, while this separate check catches drift in the Python source.

The `home` manifest dependency is now pinned to 0.5.12. The packaged `rust/Cargo.lock` has not been fully resolved; regenerate and commit it with Cargo before claiming a reproducible `--locked` build. Do not manufacture transitive lockfile entries.

## Source-derived option inventory

`rust/PYTHON-CLI-OPTION-INVENTORY.md` records all 116 direct Python parser definitions and their preliminary implementation ownership. Assignment does not establish Rust support or complete CLI equivalence. Target handling and execution planning are addressed in Part 4; native downloads remain unavailable.

## Regression checks

From the repository root, after building the Rust binary, run:

```bash
python rust/tests/compare_python_rust.py --rust-binary rust/target/debug/yt-download-rs
python rust/tools/check_cli_contract.py rust/target/debug/yt-download-rs
```

The comparison harness checks the Python machine schema snapshot and representative version 3 configuration validation outcomes, including defaults, inheritance, missing parents, cycles and invalid versions. It also records help/version differences without asserting text equality. The executable contract checker covers inspection commands, argument conflicts and missing-value diagnostics. These bounded checks complement the Rust unit and integration tests; they do not establish full CLI or download parity.

From `rust/`, run `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets --locked -- -D warnings` and `cargo test --workspace --all-targets --locked`. A complete, Cargo-resolved `Cargo.lock` is required for locked builds; do not construct dependency resolutions manually.

## Native Part 4 contract certification

The Part 4 library boundary is exercised by `rust/crates/yt-downloader/tests/part4_contract.rs`. These integration tests compose the validated version 3 profile loader, explicit profile selection and overrides, target resolution, deterministic argument planning and lifecycle transitions. They also check conflicting sources, the distinct batch-file and standard-input plans, terminal-state protection and the explicit failure for `preferred-fps`.

| Contract | Native coverage | Remaining compatibility boundary |
| --- | --- | --- |
| Direct target ordering, duplicates and leading dashes | Target unit tests and cross-module plan test | Python CLI positional parsing and real yt-dlp invocation are not ported. |
| Standard input and batch-file argument distinction | Target, planner and cross-module tests | File contents, queue operations and actual process input remain unimplemented. |
| Profile selection, inheritance and explicit overrides | Profile tests and cross-module plan tests | Python version 2 profile support is intentionally absent in Rust. |
| Deterministic yt-dlp argument planning | Planner unit tests and cross-module plan tests | Only five boolean settings are mapped; all other settings fail closed. |
| Lifecycle states, progress, failure and cancellation | Lifecycle unit tests and cross-module terminal-state test | No child-process adapter, output parser, cancellation enforcement or cleanup exists. |
| Python CLI and machine schema | `rust/tests/compare_python_rust.py` and `rust/tools/check_cli_contract.py` | Inspection checks and selected profile validation are not execution equivalence. |

The Part 4 tests establish internal native contract consistency, not comprehensive Python/Rust behavioural equivalence. In particular, the five mapped settings (`playlist`, `write-info-json`, `write-thumbnail`, `write-subs` and `write-auto-subs`) are an explicitly limited planning subset. Any other validated setting, including `preferred-fps`, must be rejected rather than omitted. The renaming plugin and its packaging remain Python-owned until execution and output parity can be certified. No test in this certification suite invokes yt-dlp or downloads media.

## Part 5 execution adapter boundary

The opt-in Rust library execution adapter now launches a caller-selected executable from a validated plan and forwards structured yt-dlp progress to the lifecycle event sink. Unix mock-process tests cover progress, unsuccessful exits, active cancellation, literal target ordering and duplicates, batch-file paths and the `--batch-file -` marker. The public Rust CLI still does not download media.

The standard-input execution test verifies argument forwarding only; it does not verify actual stdin content delivery. The mock executable tests do not establish compatibility with real yt-dlp versions, Python's output naming and renaming plugin, format selection, persistent queue workflows or the full Python option inventory. Those boundaries remain open and must not be inferred from passing internal tests.
