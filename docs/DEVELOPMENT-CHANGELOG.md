# Development changelog

This file records meaningful changes during active development. It is not release history. When a dot release is completed and accepted, relevant entries are reconciled into the root `CHANGELOG.md` and the completed development section is cleared or advanced for the next work item.

## Discover 0.29.6 - Unreleased

- [docs] Define reusable criteria for deciding when an operation deserves dedicated yt-sql operator syntax.
- [docs] Distinguish structural and scope-changing grammar from ordinary scalar, aggregate and media-specific value operations.
- [docs] Record null-coalescing `??` as deliberately unplanned because `COALESCE(...)` already expresses the value transformation without additional grammar.

## Downloader 1.19.x - Unreleased

- [feature] Add `--remove-completed-rows` for annotated file-backed queues whose first whitespace-delimited field is the download target.
- [maintenance] Preserve the exact-line semantics of `--remove-completed-ids` while sharing archive reconciliation and queue reporting with annotated-row removal.
- [test] Add deterministic annotated-row parsing, atomic removal, archive reconciliation and command-planning coverage.
