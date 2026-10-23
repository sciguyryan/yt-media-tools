# YT-SQL shared conformance suite: vision and migration plan

## Purpose

YT-SQL needs one independently reviewable definition of observable language behaviour that can be exercised by the current Python implementation and future implementations, including Rust. A shared corpus should make disagreements visible without embedding Python internals into the specification. This is a development plan, not permanent contributor guidance. Once the migration is complete, retain the practical contract in `yt-sql/README.md` and the relevant changelog, and remove this planning document from the working tree. Git history will preserve the reasoning.

## Core decisions

- Keep the corpus at the repository root in `yt-sql/`, distinct from operational SQLite statements in `common/sqlite/`.
- Store each test as `query.sql`, `test.json` and `expected.json`. The manifest declares a stable ID, referenced dataset or datasets, parameters, feature tags and comparison mode.
- Use portable, versioned, deterministic datasets. Audit existing Python synthetic generators and fixtures before promoting their outputs; do not make the permanent corpus depend on running Python to produce data.
- Define expected results independently of the implementation under test. Do not mechanically bless Python output as the oracle. Record observable column names, ordering, types, values, duplicates and diagnostics.
- Permit batch execution against the current Python implementation to generate candidate expectations, but require review and approval before any generated output becomes normative. The review requirement does not prescribe a reviewer or method.
- Maintain comprehensive positive, negative, boundary, interaction and torture coverage for every supported grammatical construct, operator and function; audit completeness against the registered language inventory.
- Default every test to expected success. Keep implementation-specific deviations in `yt-sql/expectations/python.json`, `yt-sql/expectations/rust.json` and equivalent future manifests. Require reasons and preferably issue references for expected failures.
- Treat negative language tests as ordinary passing tests when they produce the specified error. Treat XFAIL as a known implementation defect, XPASS as a failing signal requiring investigation, and unrelated crashes as failures rather than acceptable XFAILs.
- Integrate Python through pytest parametrisation and pytest-xdist initially. Keep the shared corpus independent of pytest so other language adapters can consume it.
- Preserve existing Python language, parser, optimiser, independent-oracle, cache, migration and integration tests until coverage has been classified and proven replaceable. Never delete implementation-specific checks solely because a shared query passes.

## Proposed corpus layout

```text
yt-sql/
  README.md
  schema/
    test-case.schema.json
    expected.schema.json
    dataset.schema.json
  datasets/
  cases/<feature>/<case-id>/
    query.sql
    test.json
    expected.json
  expectations/
    python.json
    rust.json
```

The case ID is stable and unique. Directory names describe the language feature, not a Python implementation detail or release number. Dataset manifests identify source and facet identities, typed fields, rows and any acquisition metadata required to reconstruct the same logical environment. Multiple datasets may be combined only under explicit conflict and identity rules.

## Observable comparison contract

Define portable encodings for SQL NULL, booleans, integers outside JSON's reliably interoperable range, finite and non-finite numeric values where supported, text and Unicode, temporal values and diagnostic categories. Preserve column names and column order. Ordered queries compare row sequences; unordered queries compare multisets, retaining duplicate counts. Do not let incidental SQLite, Python or filesystem ordering become a language guarantee. Parameters, seeds, time sources and volatile functions must have declared deterministic behaviour or a deliberately constrained assertion.

The corpus should distinguish syntax and semantic errors from runtime or acquisition failures. Expected diagnostics should assert a stable public category and, only where promised, location or message details. They should not rely on implementation-specific exception classes.

## Execution architecture

A common corpus loader validates schemas, IDs, dataset references and expectation manifests. An implementation adapter materialises isolated fixture state, executes a query, normalises observable output and returns either typed results or a structured diagnostic. A shared comparison layer classifies PASS, FAIL, XFAIL, XPASS and explicit SKIP. FAIL and XPASS produce non-zero status. Unexpected exceptions must not be hidden by expected-failure entries.

For Python, use pytest parametrisation and existing pytest-xdist support, starting with the repository's normal worker default. Each worker owns mutable caches, databases and temporary paths; immutable fixture definitions may be shared. Preserve deterministic reporting and a machine-readable result summary, with filtering by ID, feature, dataset and expectation status. Benchmark worker scaling before increasing concurrency.

## Candidate expectation generation and validation

The existing Python YT-SQL implementation may be used to execute proposed conformance tests and generate candidate expected results in bulk. This provides a practical way to develop comprehensive coverage without manually calculating every result.

**Generated expectations are provisional and must be reviewed before they are accepted as authoritative conformance results.**

The review must establish that each expected result agrees with the intended YT-SQL semantics, the test query, its parameters and the referenced datasets. Successful execution by the reference implementation is not, by itself, sufficient evidence of correctness. The process does not prescribe who or what performs the review.

Any discrepancies, implementation defects or ambiguities discovered during review must be investigated and resolved before the affected expectation is approved. Cases whose correct behaviour cannot yet be established must remain provisional.

Only reviewed and approved expectations may enter the normative conformance corpus. Once approved, they define the expected behaviour independently of the implementation originally used to generate them.

Subsequent corrections to approved expectations must be deliberate, justified and traceable. Ordinary conformance test execution must never regenerate or silently overwrite approved expectations.

Generation and verification are separate operations. Batch review packages should preserve exact queries, parameters, dataset identities and digests, execution configuration, implementation version, diagnostics and candidate results. Review provenance belongs outside the portable normative result contract. Disagreements across parser paths or optimiser configurations should be flagged for investigation, not automatically resolved in favour of one execution path.

## Coverage completeness

Maintain a machine-readable inventory connecting each supported grammar construct, operator and function to positive, negative, boundary and interaction tests, plus relevant torture coverage. Include malformed syntax and invalid semantic combinations, NULL and three-valued logic, Unicode and temporal boundaries, source/facet identity, aggregation, ordering, volatility and optimiser differential behaviour. A registered feature without suitable coverage must be visible as an explicit gap, not silently treated as complete.

Torture tests should be semantically meaningful and independently reviewable. Include a maximal coherent YT-SQL query exercising all compatible supported features and functions, with companion cases for features that cannot sensibly coexist. Distinguish correctness stress from performance benchmarks.

## Existing asset audit and migration

The initial inventory is `yt-sql/EXISTING-TEST-INVENTORY.json`. It describes current Python conformance cases, language feature registrations, deterministic generator profiles and Python test files. The Python v6 small fixture descriptor is transitional: it refers to a generator, not a language-neutral exported dataset. Review the existing small, normal, large and huge profiles and specialised Unicode, temporal and relational fixtures. Promote useful fixtures to portable, versioned representations, preserving their semantics and provenance. Large stress fixtures may use a deterministic portable generation specification if a static export is impractical, but must not silently depend on Python-specific generation behaviour.

Classify each existing Python test as: portable language contract; Python implementation or diagnostic contract; optimiser or independent-oracle differential test; integration or backend behaviour; or redundant after demonstrated equivalent coverage. Track the mapping before deleting anything. Preserve negative and edge-case coverage, including three-valued logic, source and facet identity, aggregation, set operations, Unicode, temporal semantics, volatile functions and the maximal language torture test.

## Revised delivery sequence and acceptance

1. **Language inventory and coverage model.** Audit registered syntax, operators, functions and existing tests; define machine-readable completeness requirements and coverage gaps. Retain all existing tests.
2. **Portable datasets and fixtures.** Audit existing deterministic generators and fixtures; promote independently inspectable, versioned inputs and define multi-dataset composition and reproducibility.
3. **Corpus specification.** Finalise the three-file case contract, portable typed values, ordering and duplicate semantics, diagnostic taxonomy, parameters, determinism and expectation-review metadata.
4. **Python reference execution and candidate generation.** Execute batches through the real Python language pipeline; capture reproducible evidence and proposed expected results without modifying normative expectations.
5. **Expectation review and approval.** Establish candidate, reviewed and approved states; investigate disagreements, ambiguous semantics and implementation defects; promote only approved results. Do not prescribe reviewer identity or review mechanism.
6. **Permanent conformance harness.** Implement the shared comparator and Python adapter, strict PASS/FAIL/XFAIL/XPASS behaviour, negative-case handling, deterministic reporting and pytest-xdist isolation. Ordinary test execution must be read-only with respect to expectations.
7. **Existing test migration.** Port semantic cases in traceable batches, reviewing generated expectations against query intent and fixtures. Retain parser, oracle, optimiser, migration and integration checks unless equivalence is proven.
8. **Exhaustive and adversarial coverage.** Close grammar/function/operator matrices, malformed-input and boundary gaps, feature interactions, differential and metamorphic checks, and maximal coherent torture tests. Document remaining gaps explicitly.
9. **Multi-implementation readiness.** Validate corpus and adapter contracts independently of Python internals; establish Rust-compatible loading, execution and comparison semantics without requiring a complete Rust language implementation.
10. **Certification and reconciliation.** Run relevant full local test suites and static gates, verify serial/parallel reproducibility and coverage accounting, reconcile permanent documentation and changelog, and retire this temporary roadmap only after durable rules have moved to the contributor guide.

Each phase must leave the repository testable. No provisional expectation may be silently promoted, and no existing assertion may be removed merely because an unreviewed candidate happens to match Python's output. A structural corpus check does not demonstrate successful language execution. Expected query errors are not implementation XFAILs. Missing fixtures, malformed manifests, unrelated crashes and unexpected successes must remain visible failures.

## Questions to settle during implementation

The precise typed JSON representation, public diagnostic taxonomy, dataset conflict rules, fixture portability strategy, floating-point comparison policy, volatility controls and eventual Rust adapter interface remain design decisions. Record the chosen contracts in `yt-sql/README.md` and schema files when implemented, rather than leaving permanent behaviour defined only by this roadmap.
