# yt-sql parser equivalence

A future yt-sql parser must produce the established parser-independent yt-sql model. Parser-library trees, token objects and implementation-specific exceptions are not language interfaces and do not participate in migration equivalence.

For accepted input, parser comparison has two related contracts. The normalised model preserves node kinds, operators, child ordering, names, literal values and types, aliases, relation structure, qualification, facets, JOINs, CTEs, set operations and other meaning-bearing attributes. Parser construction bookkeeping and original query text are excluded. User-written source origins are compared separately. The current AST stores start positions on many nodes rather than complete end spans, so migration must preserve equivalent available origins without pretending richer AST spans already exist.

For rejected input, the structured diagnostic contract in `YT-SQL-DIAGNOSTICS.md` governs equivalence. Category, meaningful failure source region and reason for rejection must remain equivalent. Curated expected-token information should remain equivalent where supplied. Human-readable wording may improve and is not required to match byte-for-byte.

The accepted hand-written parser and the current formal grammar revision remain frozen references during parser migration. A discrepancy must first be classified as a reference-parser defect, candidate-parser defect, specification defect or deliberate language change. Parser replacement is not permission for unrelated grammar evolution.

## Generated and exploratory coverage

Deterministic corpora remain the primary migration gate. Grammar-anchored generation expands valid coverage beyond hand-written cases, and controlled mutation creates reproducible invalid neighbours around accepted syntax. Property-style invariants then exercise these inputs across parse, normalisation and formatting boundaries.

Seeded grammar-aware fuzzing complements those deterministic layers. It focuses on token boundaries, whitespace, delimiters, nesting and composed grammar forms rather than unconstrained random bytes. Fuzz inputs are bounded for ordinary tests, record their seed, and provide deterministic smaller candidates for failure minimisation. A fuzz-discovered regression must become a stable regression case before it is considered fixed.

## Canonical and performance oracles

Canonical formatting is an independent convergence oracle. For valid input, parse-format-parse must preserve the normalised model and formatting must be idempotent. When a candidate parser exists, formatting either parser's accepted model and reparsing that canonical text through the other parser must converge on the same normalised model and canonical representation.

Parser performance is measured before cut-over using representative ordinary, complex, malformed and deeply nested bounded workloads. Baselines record elapsed parsing cost and throughput without turning one provisional multiplier into a language rule. Candidate evaluation considers sustained latency, scaling, memory where measurable and pathological behaviour. A roughly twofold repeatable slowdown is an investigation trigger, not an automatic acceptance threshold; operational significance and architectural benefit still require explicit review.
