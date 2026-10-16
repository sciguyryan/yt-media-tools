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
| `--schema-json` | Must be the only CLI argument; emits the versioned Downloader machine contract and profile JSON Schema. | Reference snapshot implemented; freshness check required | **Part 3 required:** capture the Python schema as a reference fixture, implement the same versioned contract and test exact machine semantics before closure. |
| `--capabilities` | Must be the only CLI argument; emits a human-readable capabilities report. | Unsupported | **Parts 4-5 deferred content:** Part 3 must reject incompatible arguments; keep the report guarded until native capability facts are available. |
| `--capabilities-json` | Must be the only CLI argument; emits a sorted, indented JSON capabilities payload. Cannot be combined with `--capabilities`. | Unsupported | **Parts 4-5 deferred content:** Part 3 must reject incompatible arguments; keep the report guarded until native capability facts are available. |
| `--validate-config [FILE]` | Optional path. When omitted, validates the resolved defaults path. Emits a sorted, indented JSON validation result; validation errors are parser errors. | Implemented subset | Part 3 parity review for implicit-path resolution, diagnostics and machine output. |
| `--profile-tree [NAME]` | Optional focus name. Uses the resolved defaults path, returns an informative message if implicit defaults are absent, and renders a validated hierarchy with a terminal-encoding-dependent ASCII fallback. | Implemented subset | Part 3 terminal-encoding and diagnostics review. |
| `--list-profiles` / `--list-parameters` | Lists names from resolved defaults and handles absent implicit defaults without failure. | Implemented subset | Part 3 parity review. |

The Python entry point handles `--schema-json`, `--capabilities` and `--capabilities-json` before normal configuration loading and explicitly requires their argument to be used alone. It handles `--validate-config` before profile selection and handles `--profile-tree` before ordinary listing. The ordering is significant: these commands should not inadvertently require a selected download profile or attempt a download.

**Implementation boundary:** The versioned Python machine schema and capabilities payload are public contracts, not incidental text. Until Rust has an equivalent source of truth, it must continue to fail closed rather than print a fabricated or incomplete payload. A command may be explicitly deferred beyond Part 3 only if that exception is documented and approved during closure review.

### Positional targets and option ordering

Python accepts multiple positional targets and input-file workflows. Rust recognises only a single positional target as an unavailable download operation. A robust parse-only contract must be established without accidentally enabling download execution.

### Value semantics and errors

Python argparse enforces supported `--audio-format` choices at the CLI boundary; Rust currently validates after profile selection. Python normalises audio-quality values and has distinct error wording. Compare accepted/rejected values, repeated flags, `--option=value`, Unicode/path arguments, negative-looking values and exit status.

### Remaining settings and profiles

Reconcile the complete Python argument inventory against the Rust typed settings registry, including defaults precedence, explicit overrides, profile inheritance, cross-setting constraints, `chapter-sections` regular-expression semantics and output/provenance behaviour.

## Closure gate for Part 3

Part 3 is **not ready to close**. It can be proposed for closure only when:

1. A complete Python-to-Rust CLI option inventory has been reviewed and every difference is implemented, explicitly deferred with a rationale, or assigned to the native execution parts.
2. The opposing-switch semantics above are reconciled with Python and covered by regression tests.
3. Profile loading, inheritance, validation, selection, precedence, diagnostics and inspection commands have an accepted compatibility boundary.
4. Local formatting, Clippy and Cargo tests pass against the exact candidate package.
5. The user explicitly accepts Part 3 closure.

The Python yt-dlp renaming plugin must remain available and behaviourally compatible at the eventual Rust cutover. That requirement extends beyond Part 3 and is not waived by its closure.

## Profile-tree parity review

The Rust hierarchy renderer follows the Python `profile_tree()` implementation for deterministic sibling sorting, Unicode and ASCII connectors, root grouping, and focused ancestry. Document-level `$defaults` is displayed only for profile document version 3, matching the Python condition. The Rust executable currently selects Unicode connectors unconditionally, whereas Python falls back to ASCII when stdout encoding is not UTF-based. Terminal encoding selection remains an explicit Part 3 compatibility item.

The Rust CLI accepts `--profile-tree [NAME]` with an optional `--defaults FILE` or `-d FILE` in either argument order. The executable-facing regression suite exercises both orders using a real temporary version 3 configuration file, including focused ancestry, unknown-profile diagnostics and rejection of unrelated download switches. The remaining terminal-encoding fallback and broader inspection-command inventory are still subject to reconciliation.

## Final Part 3 reconciliation findings

The executable now supports explicit and implicit configuration validation and profile-tree inspection, including `--defaults` in either order for the tree command. Their implementation is not equivalent to certifying every Python diagnostic, schema field, terminal encoding or deployment path. In particular, the implicit Rust defaults path is executable-relative rather than Python-script-relative, and the Rust tree renderer currently uses Unicode connectors without Python's encoding-dependent ASCII fallback.

`--schema-json`, `--capabilities` and `--capabilities-json` remain deliberately guarded. Schema publication needs an independently verified contract fixture; capabilities reporting also depends on later native backend and execution architecture. These cannot be silently counted as complete Part 3 behaviour. Closure requires an explicit decision on whether schema parity remains in Part 3 and whether capability content belongs to the later execution/backend parts.

The remaining Python CLI option inventory, parser-level value errors and precedence interactions also require review before claiming complete Part 3 parity. The existing temporary-file profile-tree regression is useful coverage, but it is not a complete differential test of the Python and Rust CLIs. No native download execution is enabled by this work.

## Inspection-command ownership decision

Part 3 owns the complete parse-only CLI contract, typed profile configuration, validation, precedence, hierarchy inspection and configuration schema publication. In particular, `--schema-json` is not an execution-backend feature: it must publish a compatible, versioned machine contract and profile schema before Part 3 closes. Compare the actual Python output against a deterministic fixture rather than constructing an approximate schema from the Rust settings registry.

Part 3 also owns the *argument constraints* of `--capabilities` and `--capabilities-json`, including their mutually exclusive, standalone inspection behaviour. Their *report content* is explicitly deferred to the execution and metadata-backend implementation in Parts 4 and 5. The guarded commands must continue to fail closed until real native capability data is available; this deferral does not grant permission to return placeholder success output.

The remaining Part 3 gate therefore includes: a verified schema contract, a complete argument inventory with explicit disposition for execution-only options, terminal/diagnostic parity for profile inspection, deterministic configuration and precedence regressions, and the user's local Cargo acceptance. This ownership decision does not itself certify those items or close Part 3.

## Versioned schema reference

The Rust `--schema-json` command returns the canonical Python machine-contract snapshot stored in `rust/crates/yt-downloader/fixtures/python-machine-contract.json`. The snapshot was generated from the packaged Python `yt-download.py --schema-json` command, rather than reconstructed from the Rust profile setting definitions. It preserves the Python contract's complete JSON payload and deterministic presentation, including the Python Downloader version and interfaces that are not yet available in Rust. It is a **reference contract**, not an assertion that Rust implements every advertised interface. Revalidate and regenerate it whenever the Python machine contract changes. A future native capability descriptor must distinguish implemented Rust behaviour from the reference schema.

## Schema-reference freshness check

The committed `rust/crates/yt-downloader/fixtures/python-machine-contract.json` snapshot must remain byte-for-byte equal to the current Python Downloader `--schema-json` output. Run `python rust/tools/check_schema_fixture.py` from the repository root after Python schema changes and during Part 3 certification. The checker exits non-zero on drift and does not silently regenerate the reference. Any intentional contract change requires an independently reviewed fixture update and Rust compatibility assessment. The Rust regression test checks the embedded fixture's output, while this separate check catches drift in the Python source.

The `home` manifest dependency is now pinned to 0.5.12. The packaged `rust/Cargo.lock` has not been fully resolved; regenerate and commit it with Cargo before claiming a reproducible `--locked` build. Do not manufacture transitive lockfile entries.

## Source-derived option inventory

The companion `rust/PYTHON-CLI-OPTION-INVENTORY.md` enumerates the Python parser definitions and marks unresolved ownership explicitly. This is an inventory checkpoint, not a declaration that all Python switches have been ported.

## CLI option ownership disposition

All 116 direct Python `add_argument` definitions now have an explicit preliminary Part 3 or later-part owner in `rust/PYTHON-CLI-OPTION-INVENTORY.md`. This closes the *unassigned option inventory* task, not CLI semantic parity. The next Part 3 work must test supported parse-only switches against Python and address profile-tree encoding fallback and diagnostics.

## Terminal tree output compatibility

The native profile-tree command now uses the existing ASCII tree renderer for an interactive terminal explicitly configured with the `C`, `POSIX`, or `C.US-ASCII` locale. Redirected output and other locales retain Unicode tree connectors. This is a conservative compatibility improvement, not full parity with Python's actual `sys.stdout.encoding` check; non-ASCII terminal encodings and platform-specific console detection still need certification before Part 3 closure. The locale predicate has deterministic unit coverage.

## Executable-level inspection and diagnostic smoke checks

After building the Rust executable, run `python rust/tools/check_cli_contract.py rust/target/debug/yt-download-rs` from the repository root (use the appropriate `.exe` path on Windows). This exercises the actual process exit status, stdout and stderr for the supported schema inspection contract, guarded capabilities modes, conflicting switches and missing-value diagnostics. It deliberately does not assert full Python CLI parity or attempt native downloads. The Python/Rust comparison harness checks schema fixture freshness, and the complete Cargo test suite remains mandatory for acceptance.
\n## Part 3 final reconciliation and remaining blockers\n\nThe Python option inventory and ownership dispositions are complete as a *classification*, not a proof of CLI compatibility. The schema reference and executable smoke checks cover selected inspection and error paths. The conservative ASCII fallback is not equivalent to Python's actual stdout encoding detection. Full supported-option differential parity, profile validation/precedence diagnostics and cross-platform terminal behaviour remain unverified.\n\nThe current packaged `rust/Cargo.lock` is an incomplete workspace-only stub. Run `cargo generate-lockfile` and commit the resulting resolved lockfile before attempting `--locked` certification. Cargo itself must verify the lockfile through the locked build and test commands; no separate static readiness checker is necessary.\n\nFor closure, run from the repository root:\n\n```bash\npython rust/tools/check_release_readiness.py\npython rust/tools/check_schema_fixture.py\ncd rust\ncargo fmt --all --check\ncargo clippy --workspace --all-targets --locked -- -D warnings\ncargo test --workspace --all-targets --locked\ncargo build --bin yt-download-rs --locked\ncd ..\npython rust/tools/check_cli_contract.py rust/target/debug/yt-download-rs\n```\n\nOnly propose closure after addressing the above semantic gaps, reviewing the results from the exact packaged tree, and receiving explicit user acceptance.\n
## Terminal fallback refinement

The interactive Rust profile-tree fallback now recognises explicitly non-UTF locale encodings, including ISO-8859 variants, rather than only C/POSIX ASCII locales. UTF locales continue to render Unicode. This is still a locale-based approximation: Python examines the actual stdout encoding, which can differ from locale settings, especially on Windows. Redirected Rust output remains Unicode. This difference requires explicit acceptance or platform-specific detection before Part 3 closure.

## Regression-check consolidation

The transient static readiness script has been removed: Cargo's locked build and test checks are authoritative for dependency resolution. Schema freshness is checked by the existing `rust/tests/compare_python_rust.py` comparison harness whenever it runs, before producing its normal help/version evidence. This avoids requiring a separate schema-check command while preserving the byte-for-byte Python reference check. The comparison harness still does not claim complete CLI parity.

## Expanded executable diagnostic matrix

The executable-level CLI contract checker now covers both orders of conflicting playlist switches, all five implemented boolean conflict families, and missing values for both profile selection and audio quality. These are deterministic native diagnostic checks, not a claim of byte-for-byte Python argparse diagnostic parity. The existing Python/Rust comparison harness currently reports help and version differences as scaffold evidence rather than enforcing parity; the closure review must explicitly decide whether those differences are acceptable for the experimental executable.

## Deliberate v3-only profile boundary

Rust rejects version 2 profiles with `InvalidVersion`; Python retains version 2 support. Rust help describes its supported experimental subset. The Python schema snapshot remains a reference, not a declaration of implemented Rust capabilities. Full v3 parity certification remains outstanding.

## Consolidated v3 regression coverage

The existing Rust profile parser tests now explicitly exercise v3 `$defaults` precedence, inherited values, child overrides, `false` values, reference resolution and provenance. Multiple version 2 document shapes must fail before resolution. These tests strengthen the native semantics but do not, by themselves, certify cross-language parity. The accepted Part 3 boundary requires comparing representative v3 outcomes with Python and reviewing any material differences before closure. No additional standalone checker is introduced.
