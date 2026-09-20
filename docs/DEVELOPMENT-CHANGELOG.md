# Development changelog

This file records meaningful changes during active development. It is not release history. When a dot release is completed and accepted, relevant entries are reconciled into the root `CHANGELOG.md` and the completed development section is cleared or advanced for the next work item.

## Discover 0.29.6 - Post-release language contract review

- [docs] Audit the literal and parameter contract against the settled 0.29.x language decisions.
- [docs] Confirm deterministic numeric, temporal-unit and identifier lexical boundaries and base-preserving parse-and-format behaviour.
- [docs] Identify reserved TRUE, FALSE and NULL alias acceptance as a parser-language defect requiring separate implementation.
- [docs] Identify the generic unterminated-string diagnostic as a remaining malformed-literal diagnostics decision.

## Downloader 1.19.x - Unreleased

- [feature] Add `--remove-completed-rows` for annotated file-backed queues whose first whitespace-delimited field is the download target.
- [maintenance] Preserve the exact-line semantics of `--remove-completed-ids` while sharing archive reconciliation and queue reporting with annotated-row removal.
- [test] Add deterministic annotated-row parsing, atomic removal, archive reconciliation and command-planning coverage.
