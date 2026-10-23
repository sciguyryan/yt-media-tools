# Shared SQLite resources

This directory owns the canonical SQLite statements shared across language implementations. Python loads them through `yt_media_tools.sqlite.load_statement()`; a future Rust adapter should read or embed these same files, not maintain duplicate query strings. The statements use SQLite syntax and SQLite positional `?` parameters.

`statements/common/` contains reusable inspection operations. `statements/collection_state/` belongs to the Downloader collection-state schema; it lives here to make the canonical SQL accessible to future implementations, not to imply that all consumers share its database schema. Database ownership, migration order and transaction boundaries remain in their respective implementations.

Statement identifiers are relative paths without `.sql`, such as `collection_state/select_completed`. Keep each file as one statement and update its consumers and tests together. The repository and release archive must retain `common/sqlite/` alongside `python/` and `rust/`; the Python adapter deliberately resolves the canonical tree instead of maintaining a copied package resource.

## SQL linting and formatting

SQLFluff is pinned in `common/sqlite/requirements-lint.txt` and configured in the root `.sqlfluff` file with the SQLite dialect. From the repository root, create a project-local environment and install the pinned tool. On Fish, the commands are:

```fish
python -m venv .venv
source .venv/bin/activate.fish
python -m pip install -r common/sqlite/requirements-lint.txt
```

Run `sqlfluff lint --config .sqlfluff common/sqlite/statements` to check the canonical statements without modifying them. SQLFluff's enabled layout rules are included in this lint check, which is also the CI quality gate. Apply formatting deliberately with `sqlfluff format --config .sqlfluff common/sqlite/statements`, then review the diff and rerun lint and database tests. `sqlfluff format` does not accept `--check`; do not use it as a CI check. To preview formatting suggestions, use `sqlfluff format --diff --config .sqlfluff common/sqlite/statements` where supported, but do not assume that a diff preview alone enforces the formatting gate.

SQLFluff operates on the canonical `.sql` resources; Python's Ruff configuration continues to apply to Python source. Formatting migration and schema statements requires review to ensure that their SQLite semantics remain unchanged.

The `common/page_size`, `common/page_count`, `common/freelist_count` and `common/auto_vacuum` statements provide canonical read-only page measurements used by maintenance, cache status and migration sizing. These are SQLite PRAGMA reads, not configuration writes.

## Statement ownership and placement

Prefer canonical `.sql` resources to embedding operational SQL in Python or Rust. Place SQLite-specific, reusable inspection statements under `statements/common/`, and place schema-owned statements under a directory named for their database or subsystem, such as `statements/collection_state/` or `statements/cache_v4/`. A statement's location identifies its owner; it does not imply that unrelated components should share that database or schema.

Use descriptive, stable operation names, such as `cache_v4/select_media_entity_id_by_identity` or `cache_v4/create_media_entities_table`. The owning directory supplies schema context. Never use generated hashes, arbitrary numeric suffixes or names tied to an implementation function. When names collide, compare the statement semantics: reuse genuine duplicates and distinguish different operations by purpose, predicate, result or lifecycle. Do not consolidate statements solely because their SQL text looks similar. Keep each ordinary `.sql` resource to one executable statement, with positional `?` bindings whose order is covered by tests. A schema-initialisation script may contain several ordered DDL statements when its caller intentionally uses SQLite's `executescript()`; review its transaction behaviour separately. Never substitute `executescript()` for `execute()` simply to load a file.

When adding or changing a query, first look for an existing canonical statement with the same semantics. Add a new statement to the appropriate owner directory if none exists, and update all relevant consumers and regression tests together. Avoid copying the same query into another tool or language adapter. Keep user-provided values bound as parameters; SQLite identifiers cannot be parameterised, so dynamically selected identifiers must come from explicitly validated or allowlisted names.

Direct SQL in an implementation should be exceptional and justified, for example when the statement is necessarily generated from validated runtime schema identifiers, or for explicit transaction-control operations such as `BEGIN` whose placement is part of the caller's transaction policy. Do not externalise SQL merely to hide dynamic construction or to move transaction ownership into the resource library. Record and test any necessary exception rather than creating a second canonical copy.

SQL resources are not a database migration framework. The owning component continues to decide connection configuration, schema versioning, transaction boundaries, migration ordering, recovery and finalisation. Do not change those behaviours as part of a statement-only extraction. Before accepting changes, run SQLFluff, relevant database and historical migration tests, and inspect any schema or query-plan changes. The language-neutral SQLite statements here are distinct from the planned top-level `sql/` yt-sql conformance corpus.

Historical cache-v3 contract statements belong under `statements/cache_v3/`, separately from current cache-v4 operations. They are immutable compatibility inputs for validating legacy databases, not a template for new database schemas. Changes must pass SQLFluff linting, targeted SQLite behavioural tests and the relevant historical migration regressions before acceptance.

## Schema and migration compatibility

Fresh cache-v4 schema resources and historical cache-v3 migration contracts share this resource tree but not their lifecycle. The owning implementation controls execution order, provider reconciliation, transaction boundaries, rollback and cleanup. Do not replace individual `execute()` calls with `executescript()`: this can change SQLite transaction behaviour. Preserve schema shape, result-column order, positional parameter contracts and historical migration certification. Run fresh-initialisation and historical migration regression coverage when these resources change.
