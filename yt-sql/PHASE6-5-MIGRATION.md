# Phase 6.5: semantic migration and retirement

The normative portable corpus is the intended authority for YT-SQL semantics. A passing Python observation does not establish normative correctness. The current semantic retirement audit deliberately retains legacy tests pending assertion-level review; no legacy test is retired solely because a portable case has a similar name or feature tag.

## Public query-to-case authoring tool

Run `python scripts/ytsql_query_to_case.py path/to/query.ysql /tmp/yt-sql-draft --id draft.my_case` from the repository root. Use `--dataset` to select a declared portable dataset and `--order` to specify `ordered` or `unordered` comparison. The destination must not exist and must be outside `yt-sql/cases/`. The tool emits `query.ysql`, `test.json`, `expected.json` and `REVIEW.json`.

**Every generated result is fallible.** The tool observes the current Python implementation, which may contain parser, type, NULL, arithmetic, optimisation or diagnostic defects. The generated expectation is a candidate only. The accompanying review record is marked `unverified`, and the tool warns on every successful run. The standard conformance harness does not load these drafts, and the authoring tool is not required to execute approved portable fixtures.

To promote a candidate, independently determine the intended semantics, inspect every returned value and type or error category, and review boundary and interaction cases. Resolve any disagreement by fixing the implementation or correcting the independently reasoned expectation, not by automatically accepting Python's output. Only then copy the reviewed `.ysql` and JSON files into the normative corpus under an approved ID; omit draft review metadata from the portable case contract. Record the review evidence in the semantic migration process.

## Retirement gate

For each legacy semantic assertion, identify the exact expected behaviour and its normative replacement case IDs, review equivalent values, types, errors and relevant execution conditions, and distinguish language semantics from implementation-specific or infrastructure tests. Preserve any assertion without independently reviewed replacement evidence. The retirement audit currently reports `not_certified` and `retain_pending_assertion_level_review` for unresolved obligations. Do not interpret these statuses as permission to delete tests.

Phase 6 certification requires exhaustive function, expression, statement, parser, negative, boundary, interaction and torture coverage, plus explicit legacy assertion reconciliation. The current increment does not assert that this gate has been met.

## Python unittest integration

The portable corpus is exposed as individual `unittest.TestCase` methods by `python/yt_discover_tests/test_normative_ysql_unittest.py`. Each method reads the committed `.ysql` query and approved JSON expectation. No semantic expectation is duplicated in Python source. Discovery validates the corpus once per process rather than once per case.

Run all cases with `python scripts/ytsql_unittest.py`, or distribute them across isolated processes with `python scripts/ytsql_unittest.py --workers 4`. Select a case with `python scripts/ytsql_unittest.py --case smoke.source_order_limit`. Standard `unittest discover` also discovers these methods, and `-k` can select individual methods. Workers use stable, disjoint ordinal shards; each case is executed exactly once. Process isolation avoids shared adapter state, although parallelism is optional because process startup and repeated corpus validation can outweigh its benefit for small suites.

This integration does not author expectations or certify coverage. Legacy semantic tests must only be retired after an independently reviewed, assertion-level replacement audit. Existing implementation and harness tests remain necessary.
