# Development changelog

This file records meaningful changes during active development. It is not release history. When a dot release is completed and accepted, relevant entries are reconciled into the root `CHANGELOG.md` and the completed development section is cleared or advanced for the next work item.

## Downloader 1.19.x - Unreleased

- [feature] Add `--remove-completed-rows` for annotated file-backed queues whose first whitespace-delimited field is the download target.
- [maintenance] Preserve the exact-line semantics of `--remove-completed-ids` while sharing archive reconciliation and queue reporting with annotated-row removal.
- [test] Add deterministic annotated-row parsing, atomic removal, archive reconciliation and command-planning coverage.

## Discover JOIN grammar - Unreleased

- [feature] Add parser-level `JOIN`, `INNER JOIN`, `LEFT [OUTER] JOIN`, `SEMI JOIN` and `ANTI JOIN` grammar with explicit relation, alias, facet and `ON` predicate AST structures.
- [maintenance] Keep `RIGHT`, `FULL`, `CROSS` and `NATURAL` joins unsupported and fail closed during semantic resolution until JOIN execution is implemented.
- [test] Add deterministic parser, formatter, composition, malformed-input and semantic-rejection coverage for the staged JOIN grammar.

## Discover test infrastructure - Unreleased

- [test] Cache deterministic small and normal conformance populations within the pytest process for read-only semantic fixtures instead of regenerating identical records repeatedly.
- [test] Allow ephemeral conformance caches to reuse an already generated record population, avoiding duplicate generator work while preserving the real SQLite cache boundary.
- [test] Reuse already compared optimiser result populations when checking serialised conformance output instead of executing both queries a second time.
- [maintenance] Keep tests that intentionally verify generator freshness, determinism, seed behaviour or mutation isolation on the uncached generator path.
- [test] Add an in-process Discover CLI harness for tests whose contract does not depend on operating-system process isolation.
- [test] Migrate high-frequency CLI behaviour tests to the shared harness while retaining explicit subprocess coverage for process-boundary contracts.
- [test] Add a pinned pytest-xdist dependency and a project-owned `run-tests.py` entry point using the measured three-worker dynamic-load policy for routine test execution.
- [test] Preserve explicit serial execution through `./run-tests.py --serial` and pass additional pytest arguments through unchanged.
- [maintenance] Use the project-owned routine test entry point in GitHub Actions so local and CI execution share one parallel test policy.
