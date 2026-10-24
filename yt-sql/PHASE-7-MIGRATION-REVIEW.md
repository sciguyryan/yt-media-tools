# Phase 7 portable conformance migration review

## Scope and evidence

This review establishes the migration backlog from the existing source-derived inventories. It does not approve expectations or certify language coverage. The source of truth remains the case definitions, parser, resolver, evaluator and independently reviewed portable expectations.

- Existing Python conformance case identifiers: **157**.
- Registered feature entries in the coverage-gap matrix: **189**.
- Function entries in the coverage-gap matrix: **19**.
- Python test files classified in the migration inventory: **211**.
- Normative portable corpus cases currently present: **9**.
- Curated language elements pending review: **267** of 267.

The gap matrix currently records its dimensions as unverified. Existing feature tags are useful discovery evidence, not proof that valid syntax, errors, types, boundaries, interactions or adversarial cases have been independently checked.

## Existing Python test disposition

| Inventory classification | Files |
| --- | ---: |
| retain: implementation/integration pending review | 172 |
| retain: independent oracle/differential coverage | 3 |
| review: language semantics | 36 |

These are existing inventory labels, not migration decisions. A file can contain both portable language assertions and implementation-specific checks. Individual assertions need review before a Python test is retired.

## First migration batches

The identifiers below occur in the existing Python conformance inventory. They are candidates for review, not approved normative cases. Each batch should retain the original test until the portable case and any residual implementation-specific coverage are accounted for.

### Ordering and row selection

`offset_limit`, `source_order_limit`, `final_position_offset`, `chronological_same_day_subsort`, `null_timestamp_last`.

### NULL, comparisons and Boolean logic

`null_and_boolean_logic`, `comparison_equal`, `comparison_not_equal`.

### Scalar functions and expressions

`scalar_functions_and_alias_order`, `nested_scalar_functions_and_expression_order`, `scalar_arithmetic_projection_and_order`.

### Pattern matching

`contains_case_insensitive`, `matches_regex`, `like_prefix`, `ilike_contains`, `not_like`, `not_ilike`, `like_single_wildcard`, `like_escaped_percent`.

### Collections and parameters

`bound_parameters`, `collection_index_null_and_bounds`, `collection_index_with_bound_parameter`, `collection_any_predicate`, `collection_not_any_predicate`, `collection_all_predicate`.

## Migration acceptance per case

1. Read the original Python case, including its dataset, expected result and feature tags.
2. Check the query against the formal YT-SQL contract and independently review expected values and diagnostics.
3. Translate fixtures and parameters into portable, implementation-independent representations.
4. Choose the correct comparison mode: exact ordered, unordered multiset, or tied groups. For ambiguous LIMIT/OFFSET boundaries, resolve the intended contract before approval.
5. Execute through the Python reference conformance runner, verify approved expectations remain immutable, and retain implementation-specific assertions separately.
6. Map the approved case to relevant language elements and coverage dimensions. Regenerate all source-derived inventories and audits, then run focused and local acceptance checks.

## Remaining completion work

The migration batches above do not exhaust the 157 existing cases or establish completeness. After migration, systematically enumerate every registered function and supported grammar alternative against valid, invalid, NULL/type, boundary, interaction and adversarial assertions. Add maximal coherent torture queries and reproducible malformed-input tests. Document any unsupported combinations rather than silently omitting them.

The existing `offset_limit` proposal remains provisional. Its tied LIMIT/OFFSET boundary cannot be certified using ordinary exact-row comparison. The separate tied-slice primitive does not itself make that proposal normative.

## First approved Unicode scalar cases

Six portable cases now exercise `UPPER` and `LOWER` with explicit expected values: sharp-s expansion, dotted-I expansion, composed and decomposed accents, and NULL propagation for each function. They are stored under `cases/unicode/` and execute through the permanent Python conformance harness. The original Python Unicode regression tests remain in place because they also cover implementation-specific output and optimiser behaviour.

These cases specify their exact results without deriving expected strings from Python's Unicode library at test time. They do not yet define a complete, versioned Unicode mapping profile. A later conformance increment must resolve Unicode version dependencies, broader case mappings, locale behaviour and coverage for the remaining scalar functions before claiming cross-language completeness.

## NULL and comparison migration increment

Two independently enumerated expectations from the committed `python-v6-small` fixture are now approved: `semantics.null_and_boolean_logic` and `semantics.comparison_equal`. Both pass the Python portable runner. The original Python conformance cases remain intact.

`comparison_not_equal` is deliberately deferred: its existing `source_index <= 36` predicate produced no rows through the portable runner against the committed dataset, while straightforward record-position enumeration predicted non-empty results. The source-index contract and fixture projection need reconciliation before approving a portable expectation.
