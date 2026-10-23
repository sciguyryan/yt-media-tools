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
| NULL placement | The ordinary, aggregate and compound paths I inspected put `None` after non-NULL values for each key, for both ASC and DESC. The CLI help also says missing ordering values are last. | We need to distinguish SQL NULL from unavailable or unacquired metadata, and check whether the grammar supports explicit NULL placement. NULL-last in both directions is now specified in `docs/YT-SQL.md`; the distinction between SQL NULL and unacquired or structurally unavailable metadata still needs focused tests. |
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

## Mixed-type and text comparison: closer inspection

I traced the ordering loops in `python/yt_media_tools/query_evaluator.py` rather than treating the original audit's "string fallback" as one uniform mechanism. The difference matters because a future shared test could otherwise approve behaviour that only one query shape exhibits.

| Evaluation path | Current mixed-type behaviour | Relevant location |
| --- | --- | --- |
| Ordinary row query | Attempts native Python comparison; on `TypeError`, retries the entire non-NULL sort using `str(value)`. | `_apply_query_body` |
| Grouped or aggregate query | Attempts native Python comparison of evaluated group expressions; on `TypeError`, retries using `str(value)`. | `_apply_aggregate_query` |
| Wrapper query with `left_query` and no set operations | Attempts native comparison without a `TypeError` fallback. | `_apply_composed_query`, first branch |
| Compound query's direct set-operation branch | Attempts native comparison, then retries with `str(value)` on `TypeError`. | `_apply_composed_query`, set-operation branch |
| Materialised set-operation result | Attempts native comparison, then retries with `str(value)` on `TypeError`. | `_apply_composed_query`, final ordering loop |

The fallback is not a type-aware comparison rule. A mixed numeric/text column can switch from numeric ordering to lexical ordering for *every* non-NULL value in that sort term, depending on whether Python raises `TypeError`. For example, lexical comparison places the string representation of `10` before `2` in ascending order. It is therefore possible for adding one incompatible value to change the relative order of two otherwise comparable numeric values. The wrapper-query path can instead raise the Python exception. I regard this as an implementation discrepancy, not a candidate language guarantee.

Native Python string comparison is case-sensitive and lexicographic by Unicode code point; it does not apply locale collation or Unicode normalisation. That is consistent with the existing text-extrema description in `docs/YT-SQL.md`, but I have not yet proved that every supported ordering expression resolves to plain text values or that all expression paths apply exactly the same comparison rules. The documented exact-spelling rule for identifiers is related, but does not by itself specify value collation.

**My proposed direction:** retain exact, case-sensitive, normalisation-sensitive Unicode ordering for text values. For mixed values, first identify the compatible type families recognised by the resolver and expression evaluator, then choose an explicit rejection or conversion rule. I lean towards rejecting incompatible comparisons, but I do not want to turn that preference into a specification before we understand whether existing metadata fields can legitimately contain heterogeneous values. In particular, we should not replace the fallback in one execution path and leave the other paths inconsistent.

The next implementation increment should start with focused fixtures for ordinary, grouped, wrapped and set-operation queries. Those fixtures should establish current outcomes for homogeneous numeric and text values, heterogeneous values, NULLs and mixed ASC/DESC terms. Once we agree on the compatibility boundary, the evaluator should use one shared comparison policy across those paths. Until then, this section is an investigation, not an amendment to `docs/YT-SQL.md`.

## Executable baseline before changing mixed-type semantics

I have added `python/yt_discover_tests/test_ordering_type_baseline.py` to characterise the existing evaluator without treating its current behaviour as the language specification. The tests cover ordinary, grouped, wrapped and compound queries. Homogeneous numeric ordering, NULL placement in both directions and exact Unicode text ordering are exercised across all four paths. The mixed-type tests deliberately record the lexical fallback in three paths and the `TypeError` in the wrapper path.

This is useful regression evidence, but it is not an endorsement of lexical fallback. In particular, I do not want these assertions copied into the portable corpus. They are a temporary characterisation of the inconsistency we need to resolve, and their expectations should change alongside the eventual shared comparison policy. The next decision still concerns which scalar type families may be ordered together and how incompatible values should be reported.

## Resolved scalar types and the runtime comparison boundary

I checked `schema.py` and `query_resolver.py` against the sorting paths before choosing a mixed-type policy. The resolver distinguishes boolean, integer, number, string, date and datetime scalar kinds, rather than treating every value as an arbitrary Python object. Dynamic provider-derived fields have a separate inference boundary: `_infer_dynamic_value_type` rejects mixed scalar/container shapes, and `infer_kind` returns `mixed` for incompatible observed scalar kinds. Integer and floating-point observations are the deliberate exception: they can reconcile to the numeric `number` kind. An all-NULL dynamic field remains `unknown` and nullable.

This changes how I would approach the implementation. A blanket comparison of `str(value)` is not compatible with the type model: it can change numeric ordering, conceal a schema mismatch and give different results depending on which query path materialises the rows. Conversely, a blanket rejection based only on differing Python classes would incorrectly reject compatible integer/number values. The ordering policy needs to use the resolved scalar kind wherever it is available, with a narrowly defined runtime guard for unexpected provider values.

I have not yet established whether every ordering term retains its resolved type through projection aliases, aggregate results, wrapper queries and set composition. That is the next implementation boundary to trace. In particular, the existing baseline's mixed `view_count` values are useful for characterising the fallback, but a recognised field name may carry a declared numeric kind even when a synthetic record contains a string. I would not generalise from that fixture to a rule allowing heterogeneous metadata.

The current evidence supports compatible numeric comparison and exact Unicode text comparison as separate cases. It does not yet justify a universal ordering between booleans, numbers, text, temporal kinds or collections, nor a particular public diagnostic for an unexpected incompatible runtime value. I would first test type propagation through all four query shapes and distinguish resolution-time rejection from runtime data-integrity failures. No formal YT-SQL rule or evaluator behaviour changes in this investigation.

## What I would require before further Phase 7 migration

- We have approved and documented the ordering rules in the main YT-SQL language reference, including the places where order is deliberately unspecified.
- Python has focused regression tests for ordinary, aggregate and compound ordering, NULLs, ties, duplicate rows and LIMIT/OFFSET boundaries. Where optimisation can change execution order, I also want optimised and unoptimised paths checked against the same semantics.
- CLI help and other public documentation no longer promise source-order tie stability.
- The portable comparison machinery can test the agreed guarantees without turning one observed sequence into a universal expectation.
- We have made `offset_limit` unambiguous and independently reviewed its expected result before admitting it.
- Rust YT-SQL execution remains explicitly pending until there is an implementation and adapter to test.

The agreed guarantees for unspecified order, tied keys and LIMIT/OFFSET are now recorded in `docs/YT-SQL.md`, and the CLI no longer advertises stable source-order tie-breaking. NULL-last placement is now documented for both sort directions. I still need to test the missing-metadata boundary and resolve mixed-type comparison, text ordering and portable assertions before admitting the first migration. This audit has not changed execution behaviour, the normative corpus or the provisional migration expectation.

## Shared comparison implementation

I replaced the four separate sorting loops with a single `_order_rows` helper. The change preserves NULL-last placement, per-term direction and the absence of a promised tie-breaker. It also removes the lexical fallback: values that Python cannot compare now raise a consistent `TypeError` across ordinary, aggregate, wrapper and compound paths. Numeric values continue to use numeric comparison; text continues to use Python's case-sensitive Unicode ordering.

The earlier mixed-type baseline has been updated to test the shared rejection behaviour rather than preserve the old discrepancy. This is an evaluator-level step, not yet a portable conformance assertion. The remaining review should address resolved expression-type propagation, SQL NULL versus unavailable metadata, and the ordering assertions needed for the provisional `offset_limit` migration.
