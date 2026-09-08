# yt-sql optimisation strategy

This document records the optimisation strategy for yt-sql. It is a living design document and should be updated whenever syntax, semantic resolution, acquisition planning or execution optimisation changes.

The governing rule is semantic equivalence. An optimisation is acceptable only when the optimised resolved query is observationally equivalent to the unoptimised resolved query for every supported input. Differential tests therefore execute both forms against the same deterministic records and compare predicate truth values where applicable, selected rows, row order, projected values and serialised output.

Optimisation happens after semantic resolution unless a section explicitly says otherwise. Resolved field kinds, typed temporal literals, typed infinity sentinels and SQL-like three-valued NULL behaviour are part of the language semantics and must be preserved.

## Optimisation classes

yt-sql currently distinguishes several related optimisation layers:

- **Predicate optimisation** simplifies resolved Boolean predicate trees without changing TRUE, FALSE or UNKNOWN results.
- **Scalar-expression optimisation** simplifies resolved scalar expressions used by projection, ordering and CASE results.
- **Acquisition optimisation** reduces remote metadata work only where the planner can prove that doing so cannot change the final query result.
- **Metadata planning** determines which fields and capabilities a query requires. It is not currently a rewrite pass, but future work may use expression analysis to avoid unnecessary acquisition.

The optimiser records material rewrites deterministically. Applicable rewrites are exposed through verbose execution and explain output. The JSON explain field remains named `predicate_optimiser` for compatibility even though its rewrite list now also includes scalar-expression decisions; a future versioned explain schema may adopt a more general name.

## Boolean operators: `AND`, `OR` and `NOT`

### Implemented

`NOT` is normalised around operators that have an exact inverse. Double negation is removed. Comparison operators are inverted directly, and `BETWEEN`, `IN`, `IS NULL` and text predicates toggle their existing negated form.

Repeated terms in the same flattened `AND` or `OR` chain are removed using semantic AST identity rather than source positions.

The predicate optimiser runs to a deterministic fixed point with a bounded pass count. CASE `WHEN` predicates use the same fixed-point optimiser as top-level `WHERE` predicates.

### Deliberately not implemented

General Boolean constant propagation and contradiction folding are not implemented. A rewrite such as `field = 5 AND field > 10 -> FALSE` would be incorrect for a NULL field because the original expression evaluates to UNKNOWN. Any future Boolean constant representation must preserve three-valued logic exactly.

### Future candidates

Safe De Morgan normalisation, common-subexpression extraction and canonical Boolean ordering may be considered if they produce measurable planning or execution benefits. Each would require differential coverage for NULL-heavy inputs and nested negation.

## Comparisons and bounds

### Implemented

Same-field lower and upper bounds are simplified conservatively. For `AND`, the stronger compatible bound survives. For `OR`, the weaker compatible bound survives. Strict and inclusive boundaries are handled explicitly.

A same-field equality removes a bound in `AND` when the equality necessarily satisfies that bound. In the corresponding `OR` case, the equality is removed when the surviving bound already includes it.

Degenerate `BETWEEN x AND x` is rewritten to equality. `NOT BETWEEN x AND x` is rewritten to inequality.

Typed temporal values and the `INFINITY()` and `-INFINITY()` sentinels participate in bound comparison only after semantic resolution.

### Deliberately not implemented

Contradictory comparison sets are not collapsed to Boolean constants because NULL inputs can make the original expression UNKNOWN rather than FALSE.

Cross-field algebra, transitive inference between unrelated metadata fields and reordering based on assumed evaluation cost are not performed.

### Future candidates

Temporal-bound inference may be expanded where the planner can use a proven universal bound for acquisition. More complete interval reasoning may also be useful, provided UNKNOWN semantics remain identical.

## `BETWEEN`, `IN`, `IS NULL` and text predicates

### Implemented

These predicates participate in negation normalisation and duplicate-term removal. Degenerate `BETWEEN` additionally collapses to equality or inequality.

Literal `LIKE` and `ILIKE` patterns are translated and compiled during semantic resolution, then retained through a bounded compilation cache for repeated row evaluation. This is an execution optimisation rather than an AST rewrite. It removes per-row pattern translation and compilation without changing the resolved predicate. Lightweight acquisition rejection can evaluate LIKE predicates when the required text value is already authoritative.

### Deliberately not implemented

`MATCHES` regular expressions are not currently rewritten into `LIKE` or `ILIKE`. Apparent textual similarity is not sufficient proof of equivalence. yt-sql `MATCHES` uses regular-expression search semantics while LIKE matches the complete value. Regex `.` does not ordinarily match a newline, `_` always matches exactly one Unicode code point, `.+` requires at least one character while `%` permits zero, and regular-expression flags can alter case, anchoring and character semantics.

For example, `title MATCHES 'The .+?'` is not equivalent to `title LIKE 'The %'`: the regex may match in the middle of a title and requires a character after `The `, while the LIKE pattern is anchored to the whole value and allows an empty suffix. Such a rewrite is therefore forbidden.

### Future candidates

Literal-only `IN` normalisation, duplicate literal removal and safe singleton `IN` reduction may be considered. LIKE patterns can also be classified into exact, prefix, suffix and contains-only forms so execution can use direct string operations instead of a regular-expression engine where Unicode and case semantics remain identical.

A future regex-to-LIKE rewrite may be considered only for a deliberately small whitelist of regular-expression forms whose complete-value anchoring, wildcard cardinality, escaping, newline behaviour and case rules can be proved equivalent. Every accepted form must have differential tests containing counterexamples to neighbouring non-equivalent forms.

## `CHAR()`

### Implemented

- Resolve each argument as an ordinary scalar expression and require numeric-compatible values.
- Validate fully constant arguments as Unicode scalar values before execution.
- Fold a fully literal `CHAR()` call to one text literal through the existing scalar constant-folding pass.
- Preserve NULL propagation exactly.
- Preserve the constructed code-point sequence without Unicode normalisation.

### Deliberately not implemented

- Do not normalise or canonicalise constructed text. `CHAR(101, 769)` and `CHAR(233)` remain distinct values even when they render identically.
- Do not assume a dynamic numeric expression always produces a valid code point. Invalid dynamic values evaluate to NULL, so symbolic rewrites must preserve that possibility.

### Future candidates

- Revisit acquisition or expression-planning opportunities only if they can preserve invalid-value and NULL behaviour exactly.

## Unicode-sensitive text optimisation

### Implemented

Discover 0.23.4 establishes adversarial Unicode data as part of the routine deterministic conformance corpus. Optimised and unoptimised execution are compared across exact comparison, `CONTAINS`, `MATCHES`, `LIKE`, `ILIKE`, `LOWER`, `UPPER`, `LENGTH`, ordering, projection and serialisation. Scalar constant folding of literal text functions is therefore exercised against the same Unicode semantics as runtime evaluation.

No implicit normalisation is performed. Optimisation must preserve the extractor-provided code-point sequence exactly unless the source operation itself defines a transformation. `LENGTH` is code-point length, `LOWER` and `UPPER` use Unicode case mappings, `CONTAINS` uses `casefold()`, and `ILIKE` uses Unicode-aware case-insensitive regular-expression behaviour over the translated LIKE pattern.

### Deliberately not implemented

Text predicates are not rewritten merely because they appear equivalent under ASCII. In particular, `CONTAINS`, `ILIKE`, `LOWER`-based comparisons and regular-expression case-insensitivity are not substituted for one another. Unicode case folding, case conversion and regular-expression ignore-case semantics differ for characters such as sharp s, dotted and dotless I, long s, Kelvin sign and Greek sigma forms.

No optimiser pass inserts NFC, NFD, NFKC or NFKD normalisation. Canonically equivalent strings can remain observably different under exact equality, LIKE, MATCHES, ordering and length.

### Future candidates

An explicit normalisation scalar function may be considered as language syntax. If added, normalisation-aware rewrites could then be considered only within expressions whose normalisation form is explicit. Any future exact/prefix/suffix LIKE fast path or regex-to-LIKE reduction must be differentially tested against the Unicode torture corpus, including combining marks, supplementary-plane characters, ZWJ sequences, variation selectors, bidirectional marks and case-mapping edge cases.

## Numeric literals

### Implemented

Discover 0.23.6 resolves decimal, hexadecimal, octal and binary integer literals to ordinary integer values before optimisation. Underscores are readability separators only and do not survive semantic resolution. Different bases therefore have identical arithmetic semantics once resolved.

Literal base and spelling are not treated as semantic properties. Constant folding may canonicalise a mixed-base expression such as `0x10 + 0o10 + 0b10 + 10` to the decimal literal `36`.

### Deliberately not implemented

No optimiser attempts to preserve or reconstruct the user's original base spelling after a constant expression is folded. Numeric separators likewise carry no semantic information.

Non-decimal fractional literals are not supported, so there is no hexadecimal-floating-point or base-specific rounding behaviour for the optimiser to preserve.

## Scalar arithmetic: `+`, `-`, `*`, `/` and `%`

### Implemented

Discover 0.23.2 folds scalar subtrees whose operands are entirely literal after semantic resolution. Folding is recursive, so:

```sql
19 * 2 * 100 * 0
```

is reduced through deterministic constant folds to the literal `0` before row evaluation.

Unary `+` and `-` over literal operands are also folded. Division or modulo by literal zero folds to NULL because that is the existing yt-sql evaluation result. NULL propagation is therefore preserved rather than replaced with ordinary arithmetic identities.

### Deliberately not implemented

Symbolic algebra involving fields is not performed. In particular:

```sql
view_count * 0
```

is not rewritten to `0`, because a NULL `view_count` produces NULL in the original expression. Similar identities such as `x + 0`, `x * 1` or cancellation rules are deferred until their type, NULL and exceptional-value semantics can be proven for every supported scalar kind.

Floating-point reassociation is not performed. Reordering arithmetic could change rounding, overflow or future numeric semantics even when the mathematical expression appears equivalent.

### Future candidates

Safe identity elimination may be introduced selectively where the operand's resolved type and NULL behaviour prove equivalence. Constant-expression canonicalisation may also be useful for query caching or a future compiled representation.

## Scalar functions

### Implemented

A deterministic scalar function is folded when all of its arguments have already become literals. This currently applies to `LOWER`, `UPPER`, `LENGTH`, `COALESCE`, `CHAR`, `NULLIF`, `GREATEST`, and `LEAST`.

Nested functions and arithmetic are folded from the leaves upwards. For example, a literal arithmetic argument may fold before the containing function is considered.

### Deliberately not implemented

Functions with field-dependent arguments remain runtime expressions. No rewrite assumes properties such as case idempotence unless the full argument is already constant.

### Future candidates

As new deterministic scalar functions are added, their foldability should be declared explicitly. Time-dependent functions such as `TODAY()` require particular care because their value depends on the query date context rather than only on syntactic literals.

### `NULLIF`, `GREATEST`, and `LEAST`

Current strategy:

- Fold a fully literal call through the ordinary scalar constant-folding pass.
- Preserve `NULLIF` three-valued comparison behaviour: only TRUE equality returns NULL; an UNKNOWN comparison caused by a NULL second argument preserves the first argument.
- Preserve the explicit NULL-propagating contract for `GREATEST` and `LEAST`.
- Treat textual extrema as exact, normalisation-sensitive Unicode ordering. No case-folded, locale-aware, or normalisation-aware rewrite is inferred.

Future candidates:

- Remove duplicate literal extrema arguments after type resolution where doing so is demonstrably semantics-preserving.
- Simplify nested extrema calls only after NULL propagation, type compatibility, evaluation order and future error semantics are all proven equivalent.

Rejected or unsafe without stronger proof:

- Rewriting textual extrema through `LOWER`, `UPPER`, case folding or Unicode normalisation.
- Dropping a NULL argument from `GREATEST` or `LEAST`; NULL is semantically decisive under yt-sql's contract.
- Rewriting `NULLIF(a, b)` as a Boolean CASE shortcut unless UNKNOWN comparison behaviour remains identical.

## Searched `CASE`

### Implemented

Every `WHEN` predicate is optimised independently with the ordinary fixed-point predicate optimiser. Scalar expressions inside every `THEN` result and the optional `ELSE` result are recursively scalar-optimised, including constant folding.

Branch order is never changed.

### Deliberately not implemented

CASE branches are not currently removed or reordered, even when a condition appears statically decisive. The predicate language does not yet expose a general three-valued Boolean literal representation suitable for proving every such rewrite safely.

### Future candidates

Constant-condition branch pruning may be considered if the condition can be proven TRUE, FALSE or UNKNOWN without record data and the removed branches cannot affect diagnostics or semantics. Common branch-result folding may also be considered.

## Projection and aliases

### Implemented

Projection expressions are optimised after alias and field resolution. A fully constant projected expression becomes a literal and is evaluated once by the optimiser rather than once per output row.

Alias names remain unchanged. Optimisation rewrites the canonical expression text attached to the resolved projection while preserving the selected output name.

### Future candidates

Unused-expression elimination may become useful after aggregate, CTE or more advanced projection syntax exists. It is not currently needed for the simple projection model.

## `ORDER BY`

### Implemented

Direct scalar ordering expressions and alias-resolved ordering expressions use the same scalar optimiser as projection. Constant subexpressions can therefore fold inside ordering keys.

Ordering terms themselves are not reordered or removed merely because an expression becomes constant.

### Future candidates

A completely constant ordering term could potentially be removed because it cannot distinguish rows, provided stable tie ordering is proven identical. This has not yet been implemented because deterministic ordering is an explicit yt-sql contract.

Future `NULLS FIRST` and `NULLS LAST` syntax will require its own optimisation notes.

## `DISTINCT`, `LIMIT` and `OFFSET`

### Implemented

No local AST rewrites currently change `DISTINCT`, `LIMIT` or `OFFSET`.

Discover does implement a separate proof-based acquisition optimisation for eligible `LIMIT` queries. When source order is preserved, no explicit ordering can allow later rows to displace earlier matches, required fields are statically known and other safety conditions hold, acquisition may stop once enough authoritative matches have been observed.

### Deliberately not implemented

`LIMIT` is not pushed through arbitrary ordering, dynamic raw fields or archive exclusion. These cases can change which rows survive.

### Future candidates

Additional safe limit propagation may become possible after source capabilities and collection semantics are richer, but it must remain proof-based rather than heuristic.

## Source and acquisition planning

### Implemented

The planner analyses required metadata fields recursively through scalar expressions, CASE conditions, CASE results, predicates and ordering. This allows acquisition to request the fields needed by a derived expression rather than treating the expression as opaque.

Capability-aware planning distinguishes available acquisition stages and can select bounded acquisition only when its preconditions are proven.

### Future candidates

Field/capability analysis can become more aggressive as the language grows. Potential work includes eliminating acquisition of fields made unnecessary by constant folding, source-boundary planning from inferred temporal predicates, and metadata-acquisition planning based on expression dependency sets.

These optimisations should remain separate from semantic rewrites so explain output can state whether a change alters the query tree or only the acquisition plan.

## Future language features

Each new syntax feature must add a section to this document when it is implemented. The following strategies are already anticipated:

- `SELECT *` is expanded during semantic resolution into the deterministic scalar schema. The optimiser sees the resulting ordinary projection terms rather than a wildcard. Star expansion itself is not an optimisation and cannot omit fields merely because they appear unused; acquisition planning must account for the complete expanded projection.
- Aggregates and `GROUP BY`: aggregate-specific constant handling, grouping-key analysis, HAVING simplification and possible early aggregation only where exactness is provable.
- CTEs and set operations: reusable resolved subplans, common-subexpression opportunities and source acquisition sharing. `JOIN` remains intentionally outside yt-sql.

## Differential verification requirements

Every optimiser feature must have direct unit coverage for the rewrite itself and differential execution coverage against the unoptimised resolved query. Tests should cover normal values, NULL values, boundary values, mixed nesting and any type-specific exceptional values relevant to the rule.

The routine deterministic conformance corpus is executed in both unoptimised and optimised forms. Selected rows and serialised output must match exactly. Predicate-focused tests additionally compare TRUE, FALSE and UNKNOWN results directly so an optimisation cannot hide a three-valued-logic regression behind `WHERE` filtering.

The optimiser must also be idempotent: optimising an already optimised query must produce the same query with no new decisions.

## Compiled-query investigation

A future design investigation may evaluate a compact compiled yt-sql representation to avoid repeated parsing and semantic-resolution overhead. Candidate forms include a versioned serialised resolved AST, a compact intermediate representation or bytecode, and a canonical cacheable query plan.

This is exploratory rather than committed work. Any design must justify its complexity with measurements and address language/schema versioning, cache invalidation, validation of untrusted compiled input, portability, deterministic behaviour, explainability and compatibility with future language evolution. A compiled form must never become an undocumented second language with semantics that can drift from textual yt-sql.
