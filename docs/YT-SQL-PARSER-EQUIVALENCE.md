# yt-sql parser equivalence

A future yt-sql parser must produce the established parser-independent yt-sql model. Parser-library trees, token objects and implementation-specific exceptions are not language interfaces and do not participate in migration equivalence.

For accepted input, parser comparison has two related contracts. The normalised model preserves node kinds, operators, child ordering, names, literal values and types, aliases, relation structure, qualification, facets, JOINs, CTEs, set operations and other meaning-bearing attributes. Parser construction bookkeeping and original query text are excluded. User-written source origins are compared separately. The current AST stores start positions on many nodes rather than complete end spans, so migration must preserve equivalent available origins without pretending richer AST spans already exist.

For rejected input, the structured diagnostic contract in `YT-SQL-DIAGNOSTICS.md` governs equivalence. Category, meaningful failure source region and reason for rejection must remain equivalent. Curated expected-token information should remain equivalent where supplied. Human-readable wording may improve and is not required to match byte-for-byte.

The accepted hand-written parser and the current formal grammar revision remain frozen references during parser migration. A discrepancy must first be classified as a reference-parser defect, candidate-parser defect, specification defect or deliberate language change. Parser replacement is not permission for unrelated grammar evolution.
