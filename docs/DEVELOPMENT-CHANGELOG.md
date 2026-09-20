# Development changelog

This file records meaningful changes during active development. It is not release history. When a dot release is completed and accepted, relevant entries are reconciled into the root `CHANGELOG.md` and the completed development section is cleared or advanced for the next work item.

## Discover 0.29.6 - Post-release language contract review

- [docs] Audit the literal and parameter contract against the settled 0.29.x language decisions.
- [docs] Confirm deterministic numeric, temporal-unit and identifier lexical boundaries and base-preserving parse-and-format behaviour.
- [feature] Reserve `TRUE`, `FALSE` and `NULL` lexically so they cannot be reused in identifier-only grammar positions.
- [test] Add deterministic conformance coverage for reserved literal tokenisation, expression semantics, identifier rejection and predicate use.
- [fix] Add dedicated diagnostics for unterminated quoted strings and incomplete terminal string escapes.
- [test] Cover malformed single-quoted and double-quoted strings with deterministic messages and source positions.
- [docs] Resolve the malformed-string diagnostics finding from the literal and parameter audit.
- [docs] Freeze the settled literal and parameter contract in the canonical yt-sql language reference.
- [docs] Document lexical forms, numeric separators, string escaping, reserved literals, parameters, unary signs, canonical formatting and deterministic malformed-input behaviour.
- [docs] Retire the completed literal and parameter audit after reconciling its durable conclusions into canonical documentation and test-coverage guidance.

## Downloader 1.19.x - Unreleased

- [feature] Add `--remove-completed-rows` for annotated file-backed queues whose first whitespace-delimited field is the download target.
- [maintenance] Preserve the exact-line semantics of `--remove-completed-ids` while sharing archive reconciliation and queue reporting with annotated-row removal.
- [test] Add deterministic annotated-row parsing, atomic removal, archive reconciliation and command-planning coverage.
