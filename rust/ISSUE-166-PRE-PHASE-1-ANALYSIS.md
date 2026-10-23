# Issue #166: pre-Phase 1 analysis and decisions

Status: provisional planning note. This document records the reasoning available before implementation and may be removed once its useful conclusions have been incorporated into permanent architecture and acceptance documentation. Issue: [Port persistent download queues and filesystem operations #166](https://github.com/sciguyryan/yt-media-tools/issues/166).

## Context and boundaries

Issue #165 established the Rust yt-dlp execution and diagnostic-handling foundation. Issue #166 concerns persistent download queues and filesystem operations. This is an architectural investigation, not a declaration that Phase 1 has started or that any proposed design has been implemented. The exact issue body and all Python compatibility requirements still need to be checked against the current source and tests.

The existing Python Downloader has file-oriented queue workflows and related output and failure records. SQLite is therefore a proposed Rust implementation detail, not an existing Python queue database to copy. The user-visible queue formats and behaviour should remain compatible wherever required. We should not automatically replace or migrate users' Python queue files into a new database.

## Agreed toolchain policy

Pin a specific stable Rust version in `rust-toolchain.toml` (or an equivalent clearly scoped toolchain configuration). Do not track the moving `stable` channel automatically. Review each candidate compiler upgrade, verify toolchain and dependency compatibility, run the relevant formatting, Clippy, test and cross-implementation checks, then adopt the new pin in a deliberate, reviewable change. Keep `Cargo.lock` reproducible. A newer compiler does not replace dependency auditing. The exact initial version must be verified when Phase 1 begins; a version mentioned during discussion is not itself an accepted pin. Do not promise an older minimum supported Rust version unless there is a demonstrated requirement.

## Provisional persistence design

Prefer `rusqlite` with bundled SQLite for durable Rust queue state. Use a small synchronous persistence boundary, short explicit transactions, schema versioning and ordered migrations. Avoid introducing Tokio, a connection pool, a full ORM or a second queue persistence mechanism without evidence of need. Verify crate version, feature flags and lockfile compatibility before selecting a dependency version.

A candidate model separates jobs, execution attempts, lifecycle events and schema migrations. The state machine must specify queued, claimed/running, completed, failed, cancelled and interrupted/recovery-eligible conditions, with explicit legal transitions. A database claim must not be confused with a successfully started subprocess or a completed output. Keep attempt history and retry eligibility explicit. Define stable queue ordering, duplicate detection and idempotency against established Python behaviour rather than assuming an internal schema guarantees compatibility.

Start with one active queue executor per database, subject to a review of how ownership is established, how stale ownership is detected, and what controlled concurrent readers or writers may do. SQLite transaction locks and application-level executor ownership solve different problems. Consider WAL only after confirming the intended filesystem and deployment constraints; do not assume network-filesystem compatibility. Configure foreign keys, busy handling and durability pragmas explicitly and test their failure behaviour.

## Filesystem and crash consistency

Use a separate, testable filesystem-operation layer. Define ownership of application-generated temporary and partial files; never infer ownership merely from a familiar filename. Do not delete user-provided files during cleanup. Specify path validation, symlink behaviour, output collisions, directory creation, replacement policy and safe handling of existing files. Use same-filesystem atomic rename where appropriate, but account for platform-specific behaviour and durability requirements.

SQLite cannot atomically commit a filesystem rename or delete in the same transaction. Design recoverable intent and reconciliation states for the crash windows between database updates, subprocess termination and filesystem changes. Never mark a job completed merely because a database transaction succeeded. Retrying an interrupted job must not silently overwrite a valid output, duplicate completed work or discard recoverable partial output.

## Python compatibility investigation

Inspect the current Python queue read/write/reconciliation paths, output-layout rules, collision policy, temporary-file and cleanup handling, failure reports, archive/completion records, and existing tests. The earlier review identified first-seen ordering and deduplication, conservative completion-record updates, distinct unresolved/failure reporting and atomic output writes as relevant candidate contracts. These observations require source- and test-level confirmation, including their exact scope and exceptions, before becoming normative Rust requirements.

Preserve compatible file-based input/output workflows at explicit boundaries around Rust's internal persistence. Do not silently reinterpret existing queue files or require migration merely to use the Rust implementation. Document any deliberate semantic differences with regression tests.

## Proposed seven phases

1. Architecture and compatibility contracts: inspect issue text and both implementations; specify queue state, storage, locking, recovery, filesystem ownership and acceptance tests.
2. Persistent queue storage: implement transactional SQLite schema, mutations, migrations and durable ordering.
3. Lifecycle and recovery: implement queue claims, attempts, retries, interruption handling and ownership reconciliation.
4. Filesystem operations: implement isolated safe path, temporary output, collision, atomic replacement and cleanup primitives.
5. Execution integration: connect persistent jobs to the accepted Rust process adapter and progress/diagnostic lifecycle.
6. Certification: deterministic crash and fault injection, concurrency and filesystem tests, Python/Rust compatibility checks and representative integration tests.
7. Final reconciliation: review tests and documentation, remove obsolete material, validate full combined-project packaging and prepare issue closure.

Phase boundaries may be refined after inspecting the issue body. Each phase should have testable exit criteria and a locally accepted combined-project archive. Preserve existing tracked file modes and avoid unrelated changes. The public Rust CLI download activation and full Python feature parity must not be assumed to fall within #166 without confirmation.

## Open questions for Phase 1

- What precisely does #166 require, and which behaviours are explicitly excluded?
- Is the persistent queue per invocation, per profile, per user, or shared across processes?
- What constitutes the durable identity of a job, including duplicate URLs and distinct output configurations?
- Which Python queue file formats and reconciliation rules are contractual?
- What are the exact crash recovery, retry, cancellation and partial-output policies?
- Which platforms and filesystems must be supported, including network mounts?
- What is the intended database location, backup policy, migration/repair policy and corruption response?
- How will tests deterministically exercise process crashes and database/filesystem commit boundaries?
- Which exact Rust and `rusqlite` releases pass the project's full local acceptance gates?

## Acceptance principle

Do not begin implementation by treating these proposals as settled facts. Phase 1 should validate them against the issue, repository and tests, then record accepted invariants before persistence or filesystem code is introduced.
