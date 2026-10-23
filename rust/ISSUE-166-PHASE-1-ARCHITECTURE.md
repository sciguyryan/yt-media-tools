# Issue #166: Phase 1 architecture and compatibility contracts

Status: candidate for local acceptance. The GitHub issue body was not retrievable, so reconcile this specification against its exact acceptance criteria. This phase does not implement persistent queue storage.

## Audited baseline

Python `yt-download.py` implements file-based queue input, completion reconciliation and reports. `queue_targets` and `queue_row_targets` preserve first-seen order while deduplicating meaningful targets, including annotated first-field rows. `remove_completed_id` preserves unrelated bytes, and `remove_completed_row` handles annotated rows. `queue_run_report` distinguishes archived, completed, unresolved and interrupted outcomes. `atomic_write_bytes` uses exclusive sibling temporary creation, flush/fsync, replacement and attempted parent-directory sync. `yt_downloader_tests/test_queue_reconciliation.py` tests these paths and interruption, failure and preservation cases.

Python also has an optional **separate SQLite collection continuation store** in `yt_media_tools/collection_state.py`. It tracks per-collection completion membership and observations, not persistent general download jobs. Its versioned schema, provenance rules and fail-closed migration behaviour are precedents; never repurpose or automatically migrate this database.

The Rust `yt-downloader` crate has process, supervision, metadata, lifecycle, planning, targets and download modules, but no SQLite dependency and no activated general public download CLI.

## Storage and ownership contracts

Use opt-in synchronous `rusqlite` with bundled SQLite for a separate job ledger. Keep Python batch files and collection continuation compatible through explicit import/export/reconciliation boundaries. Do not automatically convert, overwrite or delete existing Python inputs. Keep transactions short, enable foreign keys, bound busy waits and version the schema; unsupported future schemas must fail without mutation.

Only one active executor may own a queue database, while controlled concurrent readers may be permitted. SQLite transaction locking does not replace executor ownership. Specify stale ownership detection before implementing it. Candidate records: `queue_jobs` (stable ID, insertion sequence, exact target, effective settings fingerprint, state and revision), `queue_attempts` (attempt number, ownership, times and outcome), `queue_events` (state transitions) and schema migration metadata. Identical targets with different configurations must not be globally deduplicated.

## State and crash consistency

Candidate states: queued, claimed, running, completed, failed, cancelled and needs_reconciliation. Retry eligibility is separate from last outcome. A claim is not proof of process start; process exit is not proof of output completion. Transitions and claims require atomic compare-and-set/ownership validation. Never hold a database transaction open during a download. Abandoned work becomes reconciliation-needed, not automatically completed or blindly retried.

SQLite and filesystem changes cannot commit atomically together. Record intent, execute the operation, confirm observed results, and test crashes at each boundary. Reconciliation must inspect known output, partial-file and archive evidence without deleting recoverable user data.

## Filesystem contracts

Separate filesystem primitives from queue persistence. Distinguish user inputs, external yt-dlp outputs and positively identified application-owned temporary artefacts. Never infer cleanup ownership from a filename alone. Define symlink, traversal, collision, directory, permissions, cross-device and atomic-replace behaviour before implementation. Preserve valid existing output on failure. Partial-media downloads must not be treated as whole-item completions.

## Python compatibility matrix

| Behaviour | Evidence | Requirement |
| --- | --- | --- |
| First-seen batch ordering and deduplication | `queue_targets`, queue tests | Preserve per-mode semantics |
| Annotated-row targets and preservation | `queue_row_targets`, row tests | Preserve unrelated rows |
| Completed-ID reconciliation | `remove_completed_id`, byte-preservation tests | Exact matching only |
| Archive, completed, unresolved and interruption reporting | `queue_run_report`, failure tests | Distinct observed outcomes |
| Durable report and retry-file writes | `atomic_write_bytes`, fault tests | No truncation on failed replacement |
| Optional collection continuation database | `collection_state.py`, collection-state tests | Keep schema and provenance separate |
| Partial media and output layout | `test_partial_media_policy.py`, `test_output_layout.py` | Preserve policy before completion |

## Toolchain and dependencies

Pin a specific stable Rust toolchain and upgrade it only through deliberate review and local acceptance. This candidate pins 1.99.1; availability and Cargo checks have **not** been verified in this environment. Keep `Cargo.lock` reproducible. Defer `rusqlite` and any test-helper dependency changes until Phase 2 validates crate versions and requirements. Do not introduce Tokio, an ORM or a connection pool without justification.

## Phase gates and unresolved questions

Phase 2: transactional schema, ordering, migrations and contention. Phase 3: claims, recovery, retries and idempotency. Phase 4: path, collision, atomic replacement and cleanup. Phase 5: existing execution-adapter integration. Phase 6: deterministic crash/fault injection and Python/Rust compatibility. Phase 7: reconciliation and closure.

Before Phase 2, settle database placement, queue identity, lock ownership, network filesystem policy, corruption/backup strategy, retry eligibility and file import/export boundaries. Phase 1 acceptance requires issue-body reconciliation and green local Rust formatting, Clippy and tests. The pre-Phase 1 note remains as provisional reasoning.
