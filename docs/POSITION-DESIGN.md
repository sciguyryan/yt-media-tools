# Final-result POSITION() design contract

GitHub issue #150 introduces `POSITION()` as a deferred, one-based result-sequence value. Part 1 introduced the language contract. Part 2 evaluates standalone final-result projections after ordering and DISTINCT but before OFFSET and LIMIT, including grouped results. Explicit set-operation projections remain rejected pending the composition-aware execution and optimiser audit.

`POSITION()` belongs to the completed logical sequence after WHERE, grouping, HAVING, set operations, DISTINCT and final ORDER BY, but before OFFSET and LIMIT. For an ordered query with `LIMIT 10 OFFSET 100`, returned positions start at 101. With no deterministic final ORDER BY, positions reflect the observed execution order without promising repeatability; ties remain unspecified unless the ordering breaks them. The function does not impose a hidden sort or tie-breaker.

The initial placement contract permits only a standalone SELECT projection such as `SELECT POSITION() AS position, id FROM @source ORDER BY id`. It rejects use inside other scalar expressions, predicates, grouping keys and ORDER BY expressions. ORDER BY dependencies on POSITION aliases are rejected to avoid circular ordering. Explicit compound-result projection placement remains unsupported and is rejected rather than silently assigning incorrect positions; nested query scopes require additional conformance coverage. DISTINCT must operate on the underlying values before the deferred position is attached, so POSITION cannot make otherwise identical rows distinct.

`POSITION()` is distinct from future window functions. Window expressions will have independent partition and ordering semantics; both features may share staged expression evaluation and row-context plumbing, but POSITION must not be implemented by injecting an implicit `ROW_NUMBER() OVER (...)`.

Part 2 must add the actual deferred result-position stage before this function can be considered executable. Parts 3 through 5 will reconcile optimiser assumptions, Lark parity, conformance, maximal torture tests and documentation.
