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

The following contracts are confirmed from `yt-download.py` in this combined archive. They are not yet implemented by the Rust executable. Machine-readable output must not be approximated or advertised as equivalent until its schema and versioning are ported and tested.

| Python command | Python behaviour | Rust status | Proposed ownership |
| --- | --- | --- | --- |
| `--schema-json` | Must be the only CLI argument; emits the versioned Downloader machine contract and profile JSON Schema. | Unsupported | Part 3, after a schema parity fixture is established. |
| `--capabilities` | Must be the only CLI argument; emits a human-readable capabilities report. | Unsupported | Part 3 for command validation; capability discovery and content may depend on Parts 4 and 5. |
| `--capabilities-json` | Must be the only CLI argument; emits a sorted, indented JSON capabilities payload. Cannot be combined with `--capabilities`. | Unsupported | Part 3 for command validation; capability content may depend on Parts 4 and 5. |
| `--validate-config [FILE]` | Optional path. When omitted, validates the resolved defaults path. Emits a sorted, indented JSON validation result; validation errors are parser errors. | Unsupported | Part 3, using existing profile loading and validation, subject to exact output parity. |
| `--profile-tree [NAME]` | Optional focus name. Uses the resolved defaults path, returns an informative message if implicit defaults are absent, and renders a validated hierarchy with a terminal-encoding-dependent ASCII fallback. | Unsupported | Part 3, after hierarchy and formatting contracts are verified. |
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

Self-note: the Python yt-dlp renaming plugin **must** remain available and behaviourally compatible at the eventual Rust cutover. That requirement extends beyond Part 3 and is not waived by its closure.
