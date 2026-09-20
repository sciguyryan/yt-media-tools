# Development changelog

This file records meaningful changes during active development. It is not release history. When a dot release is completed and accepted, relevant entries are reconciled into the root `CHANGELOG.md` and the completed development section is cleared or advanced for the next work item.

## Discover 0.29.x - Unreleased

- [docs] Audit identifier case sensitivity, contextual and reserved keywords, Unicode identifier behaviour, quoted identifiers, structured members and raw backend-key access.
- [docs] Identify case-folded identifier resolution, the implementation-defined Unicode identifier grammar and missing backtick-quoted identifiers as dependencies before the identifier and keyword contract can be frozen.
- [fix] Make field, alias, CTE and semantic identifier resolution case-sensitive while preserving contextual case-insensitive keywords.
- [fix] Define ordinary unquoted identifiers using explicit Unicode XID-style recognition without implicit normalisation, while preserving the established hyphen extension.
- [test] Add deterministic Unicode identifier coverage for combining marks, exact spelling, case sensitivity, invalid starts and hyphen compatibility.
- [feature] Add backtick-quoted identifiers for otherwise unavailable names, reserved literal spellings, aliases, CTEs, relation qualification, structured members and raw backend-key segments.
- [maintenance] Canonically quote identifiers only where the ordinary identifier grammar cannot represent them, using doubled backticks for embedded backticks.
- [test] Add deterministic quoted-identifier parsing, formatting, resolution, escaping and malformed-input coverage.
- [test] Extend the parser torture corpus with composed and decomposed Unicode identifiers, case-distinct names, contextual and reserved words, quoted raw keys, embedded backticks and quoted relation aliases.
- [maintenance] Make the reserved and contextual keyword classification explicit and conformance-tested without broadening the reserved vocabulary.
- [docs] Freeze the identifier and keyword contract, including exact case-sensitive identity, Unicode rules, contextual keywords, quoted identifiers and raw/structured member behaviour.
- [docs] Retire the completed identifier and keyword audit after reconciling its durable conclusions into canonical documentation.

## Downloader 1.19.x - Unreleased

- [feature] Add `--remove-completed-rows` for annotated file-backed queues whose first whitespace-delimited field is the download target.
- [maintenance] Preserve the exact-line semantics of `--remove-completed-ids` while sharing archive reconciliation and queue reporting with annotated-row removal.
- [test] Add deterministic annotated-row parsing, atomic removal, archive reconciliation and command-planning coverage.
