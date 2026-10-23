# YT-SQL ordering: implementation audit

This is my initial read-only audit of the SQLFluff-formatted tree. I have not changed the evaluator or approved any new ordering semantics. I want to settle the unresolved behaviour and cover it with executable tests before we admit further Phase 7 migration cases.

## Where we have agreed to go

We have agreed that a query without `ORDER BY` does not promise a particular row sequence. `ORDER BY` determines the order of its keys, but rows with equal keys have no guaranteed relative order. `LIMIT` and `OFFSET` give a predictable selection only when the requested ordering distinguishes the rows at the relevant boundaries. I do not want to add an implicit `id` or source-position tie-breaker to make an underspecified query appear deterministic.

This matters to the shared tests. When a test requires an exact sequence, its query needs a complete order. Without `ORDER BY`, we should compare multisets and preserve duplicate counts. For deliberately tied ordering or ambiguous LIMIT boundaries, we will need assertions that check what the query permits rather than accepting one incidental Python result as the language rule.

## What I found in the current tree

| Area | What I found | What still needs deciding or checking |
| --- | --- | --- |
| Ordinary Python queries | `_apply_query_body` in `python/yt_media_tools/query_evaluator.py` sorts stably, working backwards through the ordering keys. A comment describes source order as an implicit final tie-breaker. | Stable sorting can remain an implementation detail, but we need to stop presenting it as a language guarantee. |
| Aggregate queries | `_apply_aggregate_query` uses the same reversed-key stable sorting approach. Groups are constructed in first-encounter order. | I want to check that grouping and limiting do not rely on tie stability. |
| Compound queries | `_apply_composed_query` sorts the materialised compound result before applying trailing `OFFSET` and `LIMIT`. | Branch encounter order must not become an undocumented tie-breaker; compound and set-operation tests are needed. |
| NULL placement | The ordinary, aggregate and compound paths I inspected put `None` after non-NULL values for each key, for both ASC and DESC. The CLI help also says missing ordering values are last. | We need to distinguish SQL NULL from unavailable or unacquired metadata, and check whether the grammar supports explicit NULL placement. NULL-last is a plausible rule, not yet an approved one. |
| Mixed types | Ordinary and aggregate sorting catch `TypeError` and compare `str(value)` instead. The compound left-query path does not have the same fallback. | I do not think a Python string-conversion fallback is a sound language definition. We need to decide which types can be compared and what happens otherwise. |
| Text | Native Python comparisons govern text in the inspected paths. | We need to specify case handling, Unicode ordering, normalisation and whether locale affects comparison, after checking existing identifier and Unicode behaviour. |
| Portable comparison | `yt-sql/compare_outcomes.py` supports `ordered` and `unordered`; `yt-sql/typed_values.py` uses positional comparison or a `Counter` multiset comparison. | Neither mode proves that a partially ordered result respects its sort keys. We need a dedicated assertion design. |
| First migration | `yt-sql/migration-proposals/offset_limit/query.sql` uses `ORDER BY view_count DESC LIMIT 5 OFFSET 3`; the review records ties. | The proposed exact result is ambiguous. I would add a unique secondary key, recalculate the expected rows independently and review it before admission. |
| Rust | I could not identify a Rust YT-SQL parser, evaluator or Discover execution adapter under `rust/crates/`; the Rust downloader's ordering is unrelated. | Rust YT-SQL parity is not testable in this tree. It should remain pending, rather than being described as passing or failing. |
| CLI help | `python/yt_media_tools/discover_cli.py` advertises “stable source-order tie-breaking”. | The wording is corrected in the first ordering-contract documentation increment; the sort implementation itself is unchanged. |

## Decisions I want to settle before changing the evaluator

**NULLs and missing metadata.** The current NULL-last behaviour looks consistent across the inspected sorting paths, but I have not established that every missing-value state is equivalent to SQL NULL. I want to check the parser, resolver and fixtures before we write a public rule for ASC, DESC or any explicit NULL placement syntax.

**Mixed values and text.** The string fallback worries me more than the stable sort. It can make mixed-type comparisons appear to work while giving them surprising lexical meaning, and it is not even consistent across the inspected paths. We need a deliberate type-comparison rule. Text collation needs the same care, particularly with Unicode and case sensitivity.

**Relational boundaries.** We should spell out what DISTINCT, grouping, UNION and derived queries do, and do not, preserve about ordering. An inner query's encounter order should not silently become a guarantee on the outer result.

**LIMIT and OFFSET.** We have already agreed not to force a hidden tie-breaker. I want tests that distinguish a fully ordered boundary from one that cuts through equal-key rows, without rejecting an otherwise permissible selection.

**Portable assertions.** Partial-order checks need access to the actual ordering keys, even where the query does not project those keys. Merely comparing an unordered bag of rows would miss a genuinely incorrect `ORDER BY`. I would design this carefully rather than extend the comparator with a permissive shortcut.

## What I would require before further Phase 7 migration

- We have approved and documented the ordering rules in the main YT-SQL language reference, including the places where order is deliberately unspecified.
- Python has focused regression tests for ordinary, aggregate and compound ordering, NULLs, ties, duplicate rows and LIMIT/OFFSET boundaries. Where optimisation can change execution order, I also want optimised and unoptimised paths checked against the same semantics.
- CLI help and other public documentation no longer promise source-order tie stability.
- The portable comparison machinery can test the agreed guarantees without turning one observed sequence into a universal expectation.
- We have made `offset_limit` unambiguous and independently reviewed its expected result before admitting it.
- Rust YT-SQL execution remains explicitly pending until there is an implementation and adapter to test.

The agreed guarantees for unspecified order, tied keys and LIMIT/OFFSET are now recorded in `docs/YT-SQL.md`, and the CLI no longer advertises stable source-order tie-breaking. I still need to resolve NULL placement, mixed-type comparison, text ordering and portable assertions before admitting the first migration. This audit has not changed execution behaviour, the normative corpus or the provisional migration expectation.
