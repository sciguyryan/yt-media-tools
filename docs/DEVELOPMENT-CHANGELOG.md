# Development changelog

This file records meaningful changes during active development. It is not release history. When a dot release is completed and accepted, relevant entries are reconciled into the root `CHANGELOG.md` and the completed development section is cleared or advanced for the next work item.

## Discover 0.30.x - Unreleased

- [feature] Define left-to-right `AND` and `OR` evaluation, SQL three-valued results and dominating-left short-circuit reachability as observable yt-sql language semantics.
- [test] Cover the complete Boolean truth table together with skipped and necessarily reachable right operands.
- [docs] Document Boolean evaluation order, UNKNOWN behaviour and the boundary between final truth and permission to suppress evaluation.

## Downloader 1.19.x - Unreleased

- [feature] Add `--remove-completed-rows` for annotated file-backed queues whose first whitespace-delimited field is the download target.
- [maintenance] Preserve the exact-line semantics of `--remove-completed-ids` while sharing archive reconciliation and queue reporting with annotated-row removal.
- [test] Add deterministic annotated-row parsing, atomic removal, archive reconciliation and command-planning coverage.
