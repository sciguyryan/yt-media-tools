# Development changelog

This file records meaningful changes during active development. It is not release history. When a dot release is completed and accepted, relevant entries are reconciled into the root `CHANGELOG.md` and the completed development section is cleared or advanced for the next work item.

## Discover 0.29.x - Unreleased

- [docs] Audit the established temporal grammar across duration units, multilingual aliases, lexical boundaries, captured relative-time semantics, date and timestamp forms, typed infinity, precedence, formatting and error classification.
- [docs] Confirm that the temporal model is otherwise coherent while identifying source-preserving temporal formatting as the remaining discrepancy before grammar freeze.
- [feature] Normalise accepted temporal spellings in canonical resolved-query output, including date and timestamp forms, duration aliases and relative temporal unit aliases.
- [maintenance] Preserve relative `TODAY()` and `NOW()` expressions symbolically while canonicalising their base, spacing and unit spelling without replacing them with captured absolute values.
- [test] Add deterministic temporal parse-format-parse coverage across English and Welsh aliases, local and named dates, timestamps and durations.

## Downloader 1.19.x - Unreleased

- [feature] Add `--remove-completed-rows` for annotated file-backed queues whose first whitespace-delimited field is the download target.
- [maintenance] Preserve the exact-line semantics of `--remove-completed-ids` while sharing archive reconciliation and queue reporting with annotated-row removal.
- [test] Add deterministic annotated-row parsing, atomic removal, archive reconciliation and command-planning coverage.
