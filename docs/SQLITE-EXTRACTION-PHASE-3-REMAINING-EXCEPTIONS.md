# Remaining SQLite execution boundaries

The Phase 3 review classified direct `execute`, `executemany` and `executescript` call sites in `python/yt_media_tools/*.py`. This register is intentionally limited to sites not using `load_statement()`. Its categories describe the execution expression rather than prove that the SQL is safe. The dynamic identifier paths and indirect statement producers require semantic review before declaring extraction complete.

- **connection and maintenance commands:** 23 execution sites
- **dynamic SQL construction:** 25 execution sites
- **explicit transaction control:** 3 execution sites
- **indirect SQL execution:** 5 execution sites

## Site dispositions

- `cache.py:104`: connection and maintenance commands
- `cache.py:106`: connection and maintenance commands
- `cache.py:169`: connection and maintenance commands
- `cache.py:170`: connection and maintenance commands
- `cache.py:171`: connection and maintenance commands
- `cache.py:366`: dynamic SQL construction
- `cache_entity_store.py:177`: indirect SQL execution
- `cache_entity_store.py:181`: dynamic SQL construction
- `cache_entity_store.py:191`: dynamic SQL construction
- `cache_entity_store.py:244`: dynamic SQL construction
- `cache_entity_store.py:256`: dynamic SQL construction
- `cache_entity_store.py:270`: dynamic SQL construction
- `cache_entity_store.py:453`: dynamic SQL construction
- `cache_entity_store.py:607`: dynamic SQL construction
- `cache_entity_store.py:709`: dynamic SQL construction
- `cache_entity_store.py:715`: dynamic SQL construction
- `cache_maintenance.py:121`: dynamic SQL construction
- `cache_maintenance.py:229`: dynamic SQL construction
- `cache_maintenance.py:262`: explicit transaction control
- `cache_maintenance.py:275`: dynamic SQL construction
- `cache_migration.py:135`: indirect SQL execution
- `cache_registry_store.py:164`: explicit transaction control
- `cache_status.py:114`: dynamic SQL construction
- `cache_status.py:190`: connection and maintenance commands
- `cache_v3_contract.py:80`: dynamic SQL construction
- `cache_v3_contract.py:115`: dynamic SQL construction
- `cache_v3_contract.py:146`: indirect SQL execution
- `cache_v3_to_v4_analysis.py:73`: indirect SQL execution
- `cache_v3_to_v4_migration.py:80`: dynamic SQL construction
- `cache_v3_to_v4_migration.py:100`: dynamic SQL construction
- `cache_v3_to_v4_migration.py:146`: dynamic SQL construction
- `cache_v3_to_v4_migration.py:252`: connection and maintenance commands
- `cache_v3_to_v4_migration.py:253`: connection and maintenance commands
- `cache_v3_to_v4_migration.py:254`: connection and maintenance commands
- `cache_v3_to_v4_migration.py:264`: explicit transaction control
- `cache_v3_to_v4_verification.py:40`: indirect SQL execution
- `cache_v3_to_v4_verification.py:103`: dynamic SQL construction
- `cache_v3_to_v4_verification.py:147`: dynamic SQL construction
- `cache_v3_to_v4_verification.py:160`: dynamic SQL construction
- `collection_state.py:107`: connection and maintenance commands
- `collection_state.py:108`: connection and maintenance commands
- `collection_state.py:113`: connection and maintenance commands
- `collection_state.py:117`: dynamic SQL construction
- `collection_state.py:119`: connection and maintenance commands
- `collection_state.py:127`: dynamic SQL construction
- `collection_state.py:132`: connection and maintenance commands
- `collection_state.py:135`: connection and maintenance commands
- `database_maintenance.py:201`: connection and maintenance commands
- `database_maintenance.py:329`: connection and maintenance commands
- `database_maintenance.py:335`: connection and maintenance commands
- `database_maintenance.py:409`: connection and maintenance commands
- `database_maintenance.py:411`: dynamic SQL construction
- `database_maintenance.py:421`: connection and maintenance commands
- `database_maintenance.py:448`: connection and maintenance commands
- `database_maintenance.py:449`: connection and maintenance commands
- `database_maintenance.py:468`: connection and maintenance commands
