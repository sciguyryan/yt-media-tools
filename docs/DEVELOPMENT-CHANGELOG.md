# Development changelog

This file records meaningful changes during active development. It is not release history. When a dot release is completed and accepted, relevant entries are reconciled into the root `CHANGELOG.md` and the completed development section is cleared or advanced for the next work item.

## Downloader 1.19.x - Unreleased

- [feature] Add `--remove-completed-rows` for annotated file-backed queues whose first whitespace-delimited field is the download target.
- [maintenance] Preserve the exact-line semantics of `--remove-completed-ids` while sharing archive reconciliation and queue reporting with annotated-row removal.
- [test] Add deterministic annotated-row parsing, atomic removal, archive reconciliation and command-planning coverage.

## Discover test infrastructure - Unreleased

- [test] Cache deterministic small and normal conformance populations within the pytest process for read-only semantic fixtures instead of regenerating identical records repeatedly.
- [test] Allow ephemeral conformance caches to reuse an already generated record population, avoiding duplicate generator work while preserving the real SQLite cache boundary.
- [test] Reuse already compared optimiser result populations when checking serialised conformance output instead of executing both queries a second time.
- [maintenance] Keep tests that intentionally verify generator freshness, determinism, seed behaviour or mutation isolation on the uncached generator path.
- [test] Add an in-process Discover CLI harness for tests whose contract does not depend on operating-system process isolation.
- [test] Migrate high-frequency CLI behaviour tests to the shared harness while retaining explicit subprocess coverage for process-boundary contracts.
- [test] Add an opt-in pinned pytest-xdist dependency and documented worker-count measurements for evaluating parallel routine test execution without changing the authoritative serial path.
