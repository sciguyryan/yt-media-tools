# Shared SQLite extraction

Phase 3 established `common/sqlite/statements/` as the canonical location for fixed SQLite statements shared by the Python implementation and prospective Rust consumers. This reduces duplicated SQL and gives schema, query and positional parameter contracts one review and linting surface. Database owners still control connections, schema transitions, authorisation, transactions and recovery.

The permanent contributor rules for statement placement, naming, parameterisation, SQLFluff and testing are in [`common/sqlite/README.md`](../common/sqlite/README.md). Historical cache-v3 statements remain compatibility contracts for v3-to-v4 migration and certification, not templates for new schemas.

The [remaining execution-site register](SQLITE-EXTRACTION-PHASE-3-REMAINING-EXCEPTIONS.md) records the outstanding dynamic, indirect and caller-controlled SQL boundaries. It must be reviewed against the current source before Phase 3 is formally certified. Complete Python and Rust suites, SQLFluff, Ruff, Markdownlint, migration interruption regressions and relevant performance checks are acceptance requirements.
