# Cache-v3 migration oracle

`canonical-valid-v3.oracle.json` is the machine-readable semantic companion to the immutable v3 SQLite fixture. It records facts that later migration work can compare without deciding how cache v4 stores them.

The oracle is deliberately not an expected v4 database. It does not name v4 tables, columns, provider IDs or entity keys. Issue #126 freezes the source meaning; the v4 registry and storage work decides the target representation later.

The `facts` object mirrors the meaningful v3 rows in deterministic order. Tests independently read the SQLite fixture and require those facts to agree, so the JSON cannot become a second hand-maintained version of history.

`semantic_classification.established` records distinctions Discover already gives meaning to. `unresolved_raw_compatibility` is different: v3 made nested `raw.*` query-visible, but the same `raw_json` also contains backend material. This oracle keeps that tension visible rather than declaring the whole blob permanent or disposable. The later `raw.*` compatibility work must make that decision with evidence.

`not_recoverable_from_v3` records specialised provider observations that v3 never persisted. A migration cannot reconstruct information that is absent from its source database.

The oracle format has its own `oracle_version`. If the oracle itself ever needs an incompatible structural change, add a new version deliberately rather than silently changing the meaning of version 1.
