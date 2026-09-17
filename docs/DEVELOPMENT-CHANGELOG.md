# Development changelog

This file records meaningful changes during active development. It is not release history. When a dot release is completed and accepted, relevant entries are reconciled into the root `CHANGELOG.md` and the completed development section is cleared or advanced for the next work item.

## Downloader 1.19.x - Unreleased

- [feature] Add `--remove-completed-rows` for annotated file-backed queues whose first whitespace-delimited field is the download target.
- [maintenance] Preserve the exact-line semantics of `--remove-completed-ids` while sharing archive reconciliation and queue reporting with annotated-row removal.
- [test] Add deterministic annotated-row parsing, atomic removal, archive reconciliation and command-planning coverage.

## Discover JOIN grammar - Unreleased

- [feature] Execute one `SEMI JOIN` or `ANTI JOIN` as an existence filter over independently acquired relations without multiplying primary-relation rows.
- [maintenance] Include joined physical sources in acquisition discovery while keeping `INNER JOIN`, `LEFT JOIN` and multi-way JOIN execution behind deterministic guards.
- [test] Add executable SEMI/ANTI coverage for duplicate keys, SQL NULL matching, left-side filtering, physical-source discovery and unsupported execution boundaries.
- [docs] Document the initial executable existence-join boundary and the continuing restrictions on right-side projection and other join forms.

- [feature] Resolve each `JOIN ... ON` predicate against only the relations visible at that join edge, including the newly joined right relation.
- [maintenance] Reject forward relation references, aggregate functions and volatile `RANDOM` expressions from JOIN predicates before the execution boundary.
- [test] Add staged JOIN predicate coverage for relation ownership, prior-relation references, forward-reference rejection, ambiguity and row-safe expression restrictions.
- [docs] Document incremental JOIN predicate scope and row-level deterministic `ON` semantics.

- [feature] Define joined-relation projection semantics: plain `*` expands only the primary relation, while `alias.*` expands only the explicitly named relation.
- [maintenance] Require joined projections to expose unique output names and reject overlapping wildcard or explicit projections unless `AS` disambiguates them.
- [test] Add staged JOIN projection coverage for primary and qualified wildcard expansion, explicit right-side projection, duplicate names and the continuing execution guard.
- [docs] Document primary-relation star semantics, explicit right-side projection and deterministic duplicate-output rejection.

- [feature] Resolve explicit relation aliases and qualified fields across staged JOIN scopes while keeping relation qualification distinct from structured member access.
- [maintenance] Reject missing or duplicate relation aliases, ambiguous unqualified fields, unknown qualifiers and unknown qualified fields before the JOIN execution boundary.
- [test] Add deterministic scope-resolution coverage for qualified ownership, ambiguity, alias diagnostics and structured-member composition.

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
