# yt-discover test-suite audit

This audit was performed after the cache-v4 registered-metadata work to remove temporary implementation scaffolding without weakening durable behavioural coverage.

## Removed or consolidated

`test_raw_metadata_contract_inventory.py` was a temporary issue inventory guard. It asserted phase wording, a literal stage name and documentation text rather than a durable behaviour. The live dynamic-raw planning behaviour remains covered by acquisition-plan, cost/selectivity and raw-compatibility tests.

`test_metadata_acquisition_audit_contract.py` duplicated current capability and acquisition-plan coverage. Its useful lightweight authority assertions now live in `test_capabilities.py`; the planner suite already covers distinct collection and dynamic acquisition stages.

`test_cache_v4_ytdlp_migration.py` contained durable registered-metadata and migration-accounting assertions, so those tests were consolidated into `test_cache_v4_raw_compatibility.py` rather than deleted.

`test_refactor_reconciliation.py` only asserted object identity for compatibility re-exports introduced during the 0.27 refactor. Current tests import and exercise those public compatibility modules extensively, so retaining a dedicated historical reconciliation file no longer added meaningful behavioural coverage.

## Retained after review

The parser migration-equivalence suite remains useful. It provides deterministic accepted and rejected corpora, generated grammar cases, malformed-neighbour mutation checks, seeded fuzzing, shrinking and a parser performance harness. Its name is historical, but its coverage is still active parser hardening.

The v3 cache migration, contract and oracle suites remain useful while v3 is an accepted migration boundary. They verify historical databases and fixtures that current v4 migration code must continue to understand.

The formal grammar contract remains useful because the parser-neutral grammar is a maintained public artefact. Its documentation checks establish the authority boundary, while its positive and negative cases verify parser agreement.

JOIN and relation oracle suites remain useful because they provide independent relational expectations rather than phase bookkeeping. Phase wording in old module docstrings is cosmetic and does not make the executable coverage obsolete.

Tests were not removed merely because they mention an old issue, release or phase. The deciding question was whether they still protect executable behaviour, a supported compatibility boundary, a maintained artefact or an independent oracle.
