# Window-function design contract

GitHub issue #151 introduces SQL window functions to yt-sql, beginning with `ROW_NUMBER() OVER (...)`, as the first increment of the Phase 14 window-function foundation in `DISCOVER-FUTURE-WORK.md`. The initial implementation deliberately supports one function on a genuine window model rather than a broad function set on a shallow one. `RANK`, `DENSE_RANK`, windowed aggregates, `LAG`/`LEAD`, `FIRST_VALUE`/`LAST_VALUE`, window frames and `QUALIFY` remain future increments; the grammar, model and evaluation stage described here should not need structural rework when they arrive.

This contract parallels `POSITION-DESIGN.md` deliberately, because both features attach values to result rows outside ordinary per-row scalar evaluation. The two remain independent: `POSITION()` numbers the final result sequence, while a window function numbers (or later aggregates) rows over its own window specification. `POSITION()` must not be implemented as an implicit window function, and a window function must not be implemented as a `POSITION()` variant.

## Evaluation order

Window expressions are evaluated once per query body over that body's input relation: after `WHERE` filtering and, for aggregate queries, after grouping and `HAVING`; before `DISTINCT`, final `ORDER BY`, `OFFSET` and `LIMIT`. A window expression reads the complete set of rows it numbers, so its input is the filtered relation as a whole, not a per-row subquery and not the presentation order of the result. This is the semantic distinction from final-result `POSITION()`: the two examples in issue #151 — chronological numbering under a title-ordered final result, and chronological numbering under no result-ordering guarantee at all — both follow from evaluating the window before the final ordering stage.

`PARTITION BY` groups rows by exact resolved scalar equality of the partition expressions, with NULL keys grouped together, matching the established `GROUP BY` NULL-key behaviour. No implicit Unicode normalisation or case folding applies to partition keys. A partition with no partitioning expressions, where one is accepted in future functions, denotes the complete input relation.

Window-local `ORDER BY` reuses the final `ORDER BY` contract: NULL ordering values sort after non-NULL values for both `ASC` and `DESC`, text compares by Unicode code points without normalisation, integer and floating-point values compare numerically, and incompatible non-NULL ordering values raise a comparison error rather than being converted to text. Rows whose complete window-ordering keys compare equal receive no guaranteed relative numbers. yt-sql does not add an implicit tie-breaker based on `id`, source position or any other hidden value, and conformance cases that require repeatable numbers must fully distinguish their window-ordering keys. This is the same honesty the language already applies to final ordering ties rather than a new restriction: the tied-numbering behaviour is unspecified language behaviour, not a defect.

`ROW_NUMBER()` numbers rows one-based within each partition, in window order. It never returns NULL. An empty input relation produces no rows and therefore no numbers.

## Placement

The initial contract permits window function calls only inside `SELECT` projection expressions of a query body. A projection alias bound to a window expression may be referenced in the final `ORDER BY`, where explicit projection aliases already take precedence over same-spelled input fields. Direct window function calls in `ORDER BY` are rejected in the initial implementation; the alias route is explicit, avoids duplicate window-specification evaluation, and can be revisited later without changing evaluation order.

Window function calls are rejected in every other position: `WHERE` predicates, `GROUP BY` expressions, `HAVING`, `JOIN ... ON` predicates, aggregate `FILTER (WHERE ...)` predicates, collection predicates and transforms, predicate-only queries, and the window specifications of other window functions. These placements are either evaluated before the window stage exists or would make numbering depend on a value that has not been established; each rejection is deterministic and diagnosed by reason code rather than by message text.

Window functions are rejected in aggregate queries (`GROUP BY` or aggregate projections present) in the initial implementation. The evaluation-order contract already reserves the post-grouping stage, so a later increment can enable windows over grouped rows with group-compatible specification expressions; enabling that combination is deliberately deferred because it interacts with the aggregate projection compatibility rules and deserves its own conformance coverage. Aggregate functions inside a window specification are likewise rejected: in a non-aggregate query an aggregate has no established group, and aggregate queries reject windows outright.

`RANDOM()` is rejected inside window specification expressions (both `PARTITION BY` and window-local `ORDER BY`). A volatile ordering key would make the numbering itself volatile, which contradicts the deterministic-expectation requirement of the conformance corpus. `RANDOM()` elsewhere in a projection is unaffected and remains per-row volatile under the existing rules.

## Distinct, slicing and acquisition

Window values are ordinary projected values once established. `SELECT DISTINCT` therefore operates on complete projected rows including window results, so two rows identical in every other projection can both survive when their numbers differ. This differs deliberately from `POSITION()`, which is attached after `DISTINCT` so it cannot make identical rows distinct; the difference is the same evaluation-order boundary that gives windows their numbering semantics.

Final `ORDER BY`, `OFFSET` and `LIMIT` apply to rows that already carry their window values, so slicing cannot alter numbering. Because numbering requires the complete input relation, the source-order early-LIMIT acquisition optimisation must be disabled for any query containing a window expression, mirroring the existing `POSITION()` safety barrier.

## Compound queries, CTEs and derived relations

Window evaluation belongs to a query body. CTEs and derived relations evaluate their own window expressions and materialise numbered rows; an enclosing query then reorders, filters or composes those rows freely. This is the documented `POSITION()` scoping behaviour applied at the window stage.

Explicit `UNION` and `UNION ALL` branch projections may contain window expressions in the initial implementation: each branch is an ordinary query body, evaluated and materialised before positional reconciliation, so per-branch numbering is well defined without new composition machinery. Branch-local numbering inside parenthesised boundaries follows the same rule. Whether this per-branch allowance is kept or initially rejected like `POSITION()` set-operation projections is recorded as an open question below.

Multi-facet `OF` expansion follows the documented `OF` contract: query-level `WHERE` and grouping apply per facet before composition, and projection is evaluated over the composed rows. A window expression in an `OF`-expanded query therefore numbers the composed facet set continuously. This is a deliberate consequence of the stronger `OF` sugar semantics and must be documented alongside the explicit-`UNION ALL` per-branch contrast, because the two spellings produce different numbering for otherwise similar queries. The evaluator's actual `OF` expansion path must be verified against this contract during implementation; if the current implementation projects per facet, that is a defect in this feature's interaction with the documented `OF` contract, not an argument for changing the contract silently.

## Coexistence with POSITION()

A query may project both `POSITION()` and `ROW_NUMBER() OVER (...)`. Each is evaluated at its own stage: window numbering over the window input relation, final-result numbering over the ordered, distinct, sliced result. Ordering dependencies on a `POSITION()` alias remain rejected as established; ordering dependencies on a window alias are permitted because window numbering does not depend on the final ordering.

## Grammar revision 3

The accepted-syntax change advances the EBNF to grammar revision 3, updating the revision header, `YT-SQL-GRAMMAR.md` and the pinned assertions in `test_formal_grammar_contract.py` together. The new productions add a window-function scalar atom rather than a special case:

```text
scalar-atom           = ... | window-function ;
window-function       = row-number-call, window-specification ;
row-number-call       = "ROW_NUMBER", "(", ")" ;
window-specification  = "OVER", "(", [ window-partition ], [ window-order ], ")" ;
window-partition      = "PARTITION", "BY", scalar-expression, { ",", scalar-expression } ;
window-order          = "ORDER", "BY", order-term, { ",", order-term } ;
```

`OVER` and `PARTITION` join the contextual keyword vocabulary; `BY` and `ORDER` already exist. Function names are not globally reserved merely because a function exists, so `row_number` remains available as an ordinary identifier where the grammar is unambiguous. The parser accepts `ROW_NUMBER()` case-insensitively like other function names; canonical formatting emits `ROW_NUMBER`.

`OVER` is already a natural-comparison spelling meaning `>`, as in `duration OVER 5m`. The window form is recognised only immediately after a function call, where the natural-comparison reading cannot apply: the natural-comparison suffix requires a literal value after the keyword and accepts no parenthesised expression, so `ROW_NUMBER() OVER (` is unambiguous. This disambiguation must be verified against the actual hand-written parser rather than assumed from the EBNF, and dedicated tests must confirm that `field OVER 5m` keeps working and that `function() OVER (...)` never parses as a comparison.

`OVER ()` and partition-only specifications are syntactically valid because future window functions give them meaning, but are rejected for `ROW_NUMBER()` by semantic resolution: numbering without a window ordering key is not deterministic, and the language prefers explicit rejection of insufficient ordering over arbitrary behaviour. Frames (`ROWS`, `RANGE`, `GROUPS`) are not grammar productions, so frame syntax is rejected as ordinary syntax errors; per the grammar contract, speculative future syntax does not enter the EBNF to improve diagnostics.

## Diagnostics

New resolver reason codes, following the established placement-validation pattern:

- `invalid-window-placement` — a window function outside a permitted position;
- `window-order-required` — `ROW_NUMBER()` with an empty or partition-only window specification;
- `invalid-window-volatile` — `RANDOM()` inside a window specification;
- `unsupported-window-aggregate-query` — a window function in an aggregate query;
- `unsupported-window-nesting` — a window function inside another window function or a window specification.

Malformed `OVER` structure (missing parentheses, missing `BY`, malformed window ordering) is rejected at parse time with dedicated syntax reasons, mirroring the existing aggregate `FILTER` diagnostics. The portable corpus mapping in `run_python_candidate.py` `classify_semantic()` gains entries for the new reasons, with `unsupported` as the expected portable category for placement and support rejections; the mapping is reviewed as part of the conformance work rather than assumed.

## Optimiser, properties and explain

Window expressions are never constant-folded and are never rewritten. The scalar-expression optimiser's deferred guard extends from `{RANDOM, POSITION}` to include window function nodes so that future window functions inherit the barrier; the optimiser does not descend into a window specification in the initial implementation, because folding inside a specification changes the canonical specification spelling and any such rewrite requires its own determinism proof. Optimiser proof helpers treat window expressions as non-constant and non-foldable.

Property analysis classifies a window expression at a new window stage between grouping and the final-result stages, with no metadata depth of its own beyond its specification and argument expressions. `semantic_key()` must include window nodes so differential comparisons and round-trip checks observe them; this is required for the routine optimiser idempotence and parse-format-parse stability checks to cover window queries automatically.

The planner disables source-order early-LIMIT termination for window queries, recording the barrier. Explain output reports the window functions present with their specifications and the disabled early termination; a dedicated window plan operator is deliberately not part of the initial increment, matching the existing position that explain presentation of deferred stages is additive rather than blocking.

## Canonical formatting

`ROW_NUMBER() OVER (PARTITION BY a, b ORDER BY x ASC, y DESC)` is emitted in one deterministic spelling: `PARTITION BY` before `ORDER BY`, absent clauses omitted, direction suffixes emitted as established for ordering terms, contextual keywords uppercase, and no incidental whitespace inside the specification. The projection term text is produced through the ordinary expression formatter, so the existing projection aliasing and round-trip machinery applies unchanged. `YT-SQL-FORMATTING.md` gains a window section covering this layout, and parse-format-parse stability plus idempotence must hold for window queries through the existing canonical formatting contract tests.

## Conformance, registry and certification

The dedicated Python feature tests cover parsing, canonical formatting, resolution, typing, evaluation, placement rejections, determinism anchors, NULL ordering, partition identity (including NULL keys), DISTINCT and slicing interaction, CTE and derived-relation scoping, set-operation branches, `POSITION()` coexistence, `RANDOM()` rejection, and optimiser differential equivalence across both `relational_optimisation` modes. Independent oracle cases express the numbering directly over ordinary Python sequences without importing production code, following the established oracle pattern.

The portable corpus gains cases in the `function-conformance`, `negative`, `ordering` and `interaction` groups, including the maximal composition query once the surface is settled. Expectations follow the established workflow: observations are staged as provisional candidates and admitted only after independent review; window-ordering ties are excluded from normative expectations unless the ordering keys fully distinguish rows.

The curated registry gains entries for `OVER`, `PARTITION`, `ROW_NUMBER` and the window feature family; the standard audit chain (coverage inventory, language-surface audit, gap matrix, element registry, grammar reconciliation) is rebuilt with drift checks, and certification is regenerated by bumping `CERTIFIED_ON` after the corpus changes. Both the Python and Rust implementations must reproduce the complete corpus before re-certification; adding normative window cases without the Rust port would break the Rust conformance gate, so the Rust increment is part of this feature rather than optional follow-up. There is no Lark surface to update: the hand-written parser is the sole production implementation and the EBNF is the parser-neutral contract.

Documentation updates accompany the code in one coherent change: `YT-SQL.md` gains a window-functions section, the EBNF and grammar contract move to revision 3, `YT-SQL-FORMATTING.md` records the layout, `YT-SQL-TEST-COVERAGE.md` records the coverage standard, and `POSITION-DESIGN.md` notes the coexistence boundary. Changelog entries follow at release time.

## Open questions for review

1. Explicit set-operation branch projections: the recommendation above permits per-branch window expressions because each branch is an independently evaluated query body. The alternative is rejecting them initially like `POSITION()` set-operation projections. Permitting them costs little and matches the foundation requirement; rejecting them is the more conservative reading of the existing precedent.
2. Aggregate queries: the recommendation rejects window functions in aggregate queries initially, with the evaluation-order contract already reserving the post-grouping stage. Confirm this staging rather than enabling grouped windows in the first increment.
3. Direct window calls in final `ORDER BY`: the recommendation permits alias references only. Standard SQL allows direct calls; enabling them later is additive once alias-based coverage exists.
4. `OVER ()` and partition-only specifications: recognised syntactically, rejected semantically for `ROW_NUMBER()`. The alternative is a grammar-level rejection, which would forfeit the foundation value of the shared window-specification production.
5. Explain presentation: minimal reporting of window functions and the early-termination barrier is recommended; a dedicated plan operator is deferred.
