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
- `--audio-format`, `--audio-quality`: audio conversion settings, including
`--option=value` forms.
- Experimental help/version handling. Downloads are deliberately unavailable.

## Confirmed compatibility differences

### Mutually exclusive switches

Python constructs mutually exclusive argument groups for at least the `--playlist`/`--no-playlist`, `--audio-only`/`--no-audio-only`, and `--embed-thumbnail`/`--no-embed-thumbnail` pairs. Supplying both opposing switches is therefore a Python argparse error.

The executable-facing combined Rust override extractor now rejects opposing switches and permits repeated identical switches, matching the Python mutually exclusive group contract. The infallible public boolean-only extraction helper deliberately retains its established last-switch-wins contract for compatibility; only the combined parser used by the executable enforces mutual exclusion. Both behaviours have dedicated regression coverage.

### Machine-readable and inspection commands

Python exposes `--profile-tree`, `--schema-json`, `--validate-config`, `--capabilities`, and other inspection commands not yet implemented by the Rust executable. Their semantics and output contracts require a separate parity assessment before Part 3 can close.

### Positional targets and option ordering

Python accepts multiple positional targets and input-file workflows. Rust recognises only a single positional target as an unavailable download operation. A robust parse-only contract must be established without accidentally enabling download execution.

### Value semantics and errors

Python argparse enforces supported `--audio-format` choices at the CLI boundary; Rust currently validates after profile selection. Python normalises audio-quality values and has distinct error wording. Compare accepted/rejected values, repeated flags, `--option=value`, Unicode/path arguments, negative-looking values and exit status.

### Remaining settings and profiles

Reconcile the complete Python argument inventory against the Rust typed settings registry, including defaults precedence, explicit overrides, profile inheritance, cross-setting constraints, `chapter-sections` regular-expression semantics and output/provenance behaviour.

## Closure gate for Part 3

Part 3 is **not ready to close**. It can be proposed for closure only when:

1. A complete Python-to-Rust CLI option inventory has been reviewed and
every difference is implemented, explicitly deferred with a rationale, or assigned to the native execution parts.
2. The opposing-switch semantics above are reconciled with Python and
covered by regression tests.
3. Profile loading, inheritance, validation, selection, precedence,
diagnostics and inspection commands have an accepted compatibility boundary.
4. Local formatting, Clippy and Cargo tests pass against the exact
candidate package.
5. The user explicitly accepts Part 3 closure.

Self-note: the Python yt-dlp renaming plugin **must** remain available and behaviourally compatible at the eventual Rust cutover. That requirement extends beyond Part 3 and is not waived by its closure.
