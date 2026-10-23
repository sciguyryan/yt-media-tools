# Shared YT-SQL conformance corpus

This directory contains implementation-independent YT-SQL language tests. It is separate from the operational SQLite statements in `common/sqlite/`.

Each case has `query.sql`, `test.json` and `expected.json`. `test.json` names one or more datasets, parameter bindings, language features and whether rows are ordered. Expected outputs describe observable columns and typed values, or an expected diagnostic category. Negative error tests are ordinary passing tests when the specified error occurs.

The committed `python-v6-small` and `python-v6-normal` fixtures contain portable materialised records from the deterministic generator (version 6, seed 31415926). Source and facet topology fixtures are also committed and independently validated. The fixture format and validation rules are described below.

Every case defaults to passing. `expectations/python.json` and `expectations/rust.json` may record justified implementation-specific `xfail` entries, including a reason and preferably an issue. An unexpected pass (XPASS) must fail the suite. A known failure must match its recorded failure category; an unrelated crash must not count as XFAIL. A query expected to produce a language error is **not** an xfail.

The first case is a format/semantics proof only. It must not replace the existing independent Python oracle or other language tests. Before enabling production execution, freeze the portable dataset representation, numeric and temporal encodings, source/facet identity, ordered and multiset comparison, and diagnostic taxonomy. Do not use production engine output to author expected results without independent review.

The existing test and dataset audit is in `EXISTING-TEST-INVENTORY.json`. Python test removal is explicitly deferred until each migrated case is proven equivalent and implementation-specific assertions are retained. Parallel execution should use pytest-xdist with isolated cache and temporary state per worker.

## Coverage inventory

The Phase 1 source-derived baseline is `COVERAGE-INVENTORY.json`, and the existing Python test audit is `EXISTING-TEST-INVENTORY.json`. **Both files are built together** by running `python yt-sql/build_coverage_inventory.py` from the repository root. Run `python yt-sql/build_coverage_inventory.py --check` to check both files for drift without modifying them. The builder reads the feature registry, Python conformance cases, parser function names, dataset specifications and test-file inventory. Existing per-file migration classifications are retained when rebuilding; newly discovered test files default to retention pending review. The historical `source_snapshot` field is retained as provenance, not regenerated as a claim about the current working tree. See `COVERAGE-POLICY.md` for coverage dimensions, limitations and the mandatory review-before-approval rule for generated expected results.

### Phase 1 language-surface audit

Run `python yt-sql/build_language_surface_audit.py` to regenerate the conservative parser audit in `LANGUAGE-SURFACE-AUDIT.json`. Run with `--check` to detect drift without rewriting the report. Rebuild `COVERAGE-INVENTORY.json` first if the parser or registered language features have changed. This is a discovery report, not a certification of grammar completeness or expected-result correctness.

### Language-element registration

The curated `LANGUAGE-ELEMENTS.json` lists known features, functions, keywords and operators, with provisional review states. It is not generated from source automatically and cannot be assumed exhaustive. When changing YT-SQL syntax or semantics, update the registry and add thoroughly reviewed conformance tests. Regenerate the companion audit after the coverage inventory and gap matrix:

```bash
python yt-sql/build_language_element_registry.py
python yt-sql/build_language_element_registry.py --check
```

The minimum approved-case CI gate will be activated after the normative corpus is populated. No generated candidate output counts as approved coverage without review.

### Lexical and semantic rejection discovery

Run `python yt-sql/build_semantic_surface_audit.py` to regenerate `SEMANTIC-SURFACE-AUDIT.json`, or pass `--check` to detect drift. The report inventories lexer token alternatives, exception-raising sites and conditional branches in the parser, resolver and evaluator. These are stable, source-derived investigation targets rather than approved conformance claims. In particular, not every exception is a user-facing language diagnostic, and a conditional branch does not necessarily represent a distinct grammar rule. Review the hand-written lexer and recursive-descent parser before declaring the language inventory complete.

Run `python yt-sql/build_grammar_reconciliation.py` to regenerate `GRAMMAR-RECONCILIATION.json`, or pass `--check` to detect drift. The report compares the hand-written parser's literal keyword and token calls against the curated registry and summarises diagnostic exception classes. Unmatched items require review and must not be treated as automatically supported features or certified coverage.

For the provisional grammar candidate classification, run `python yt-sql/build_grammar_candidate_review.py` from the repository root, or add `--check` to verify that the committed report is current. Unsupported forms are tracked as negative-test requirements rather than treated as supported language features.

### Operator spelling audit

Run `python yt-sql/build_operator_spelling_audit.py` from the repository root to regenerate `OPERATOR-SPELLING-AUDIT.json`, or pass `--check` to detect drift. This audit distinguishes lexical recognition from supported grammar and approved semantic coverage. Its alias probes are deliberately non-normative: an unrecognised symbolic spelling must not be registered merely because another SQL dialect supports it. The curated registry requires manual reconciliation and reviewed tests before certification.

### Textual predicates and Boolean spellings

Run `python yt-sql/build_textual_predicate_audit.py` from the repository root to regenerate `TEXTUAL-PREDICATE-AUDIT.json`, or add `--check` to detect drift. The report cross-references curated Boolean, truth-test, membership and text-predicate spellings with literal calls in the hand-written parser and the maintained language registry. Parser-call evidence is not a semantic guarantee, and keywords used in multiple contexts (particularly `AND` and `NOT`) require separate reviewed conformance cases. This report does not automatically approve or register language features.

### Phase 1 consolidated assessment

Run `python yt-sql/build_phase1_coverage_assessment.py` to rebuild `PHASE1-COVERAGE-ASSESSMENT.json`, or add `--check` to verify drift. The assessment collates provisional source evidence into review queues; it does not certify supported grammar or approve expectations. Unsupported forms require negative cases, not supported-feature registry entries.

### Curated grammar reconciliation

Run `python yt-sql/reconcile_language_elements.py --check` from the repository root to verify the reviewed source classifications against the maintained registry. The reconciliation deliberately distinguishes recognised unsupported grammar forms from supported keyword entries. Arithmetic spellings are now explicitly registered as pending operator entries, including `*`, whose multiplication and wildcard contexts need distinct conformance tests. `&&` and `||` remain unregistered because lexer recognition has not been established. New source candidates must be classified deliberately; this check does not approve expectations or establish semantic completeness.

### Phase 1 completeness checkpoint

Run `python yt-sql/build_phase1_completeness.py` to regenerate `PHASE1-COMPLETENESS.json`, or use `--check` to verify it. The report consolidates outstanding review obligations; it does not certify the language or approve generated expectations.

### Phase 2 portable fixture export

`datasets/python-v6-small.json` now contains the materialised 60-record small fixture, including source identity, record order, nested values, NULLs, Unicode and a canonical SHA-256 digest of the ordered records. Consumers read its committed `records` directly; they must not invoke the Python generator. The provenance identifies the original generator but does not confer authority over query expectations. Run `python yt-sql/export_portable_dataset.py --check` from the repository root to verify reproducibility or omit `--check` to re-export deliberately. The digest uses each record serialised as UTF-8 JSON with sorted keys, no insignificant whitespace, non-ASCII characters preserved, and a newline after each record. The dataset schema describes this static form. Larger profiles and richer typed fixture semantics require separate contracts; this export does not establish query-result semantics.

## Unicode fixture coverage

The materialised small fixture contains deliberately selected Unicode edge cases. `UNICODE-FIXTURE-AUDIT.json` indexes representative records by category and lists areas requiring separate investigation. Run `python yt-sql/build_unicode_fixture_audit.py --check` from the repository root to verify that the index still refers to the committed fixture.

This inventory establishes the presence of test input data, **not** the expected behaviour of Unicode comparison, case conversion, normalisation, matching or collation. Candidate query expectations must be reviewed before approval. Some boundary cases, including invalid UTF-8 byte sequences, cannot be represented directly as JSON strings and will require an explicit input/error contract if supported.

### Portable dataset validation

Run `python yt-sql/validate_portable_dataset.py` to validate all committed dataset JSON files independently of the Python YT-SQL engine and fixture generator. The validator checks dataset identity, version, static fixture provenance, unique record identifiers, ordered SHA-256 record digests, UTF-8 representability, duplicate JSON keys and malformed numeric constants. A valid dataset establishes integrity and portability, not approved query semantics. The JSON Schema provides a complementary structural contract; the Python validator enforces additional cross-field and digest invariants. The existing small dataset is unchanged.

### Materialised deterministic profiles

The `small` (60 records) and `normal` (1,000 records) profiles are committed as `datasets/python-v6-small.json` and `datasets/python-v6-normal.json`. Both use generator v6 and seed `31415926`, and contain complete ordered records, source identity, provenance and record digests. They are directly consumable by implementations without running Python. Use `python yt-sql/export_portable_dataset.py --check` to verify both committed fixtures, or `--profile small` / `--profile normal` to check a single profile. Deliberate re-export without `--check` must be reviewed before accepting changed fixture bytes.

The `large` (10,000 records) and `huge` (100,000 records) profiles remain available through the existing Python generator for stress and scalability work. They are **not yet portable committed fixtures**, and the presence of these profile sizes must not be mistaken for independent cross-implementation fixture certification. Richer typed representations require a separate contract. Dataset validity is not approval of query expectations.

### Portable heterogeneous source topology

`datasets/heterogeneous-sources-v1.json` materialises the established six-record heterogeneous fixture across a YouTube-like channel, playlist and Twitch-like archive. Its ordered `sources` entries explicitly map source handles to record indices; every record belongs to exactly one source. The same `id` may appear in different sources, but cannot repeat within one source. Records retain `_yt_sql_source`, mixed numeric/string extractor values, NULLs and composed/decomposed Unicode. This is a portable input topology, not a new source/facet language specification or an approved expected result. Run `python yt-sql/export_portable_topology.py --check` and `python yt-sql/validate_portable_topology.py` to check it. Omit `--check` to regenerate deliberately. Facet-specific fixtures and empty relations are described below.

### Portable facet relations and empty inputs

`datasets/heterogeneous-facets-v1.json` extends the heterogeneous source fixture with six explicitly named source/facet relations, including three empty facets. Membership is ordered and validated against the owning source, with no implicit normalisation of Unicode or coercion of mixed metadata types. `export_portable_facets.py` regenerates this materialisation; `--check` detects drift without rewriting it. `validate_portable_facets.py` checks source membership, integrity, duplicate facet definitions, and missing assignments. This is a deliberately bounded fixture topology, not a declaration that these facet names are valid in the YT-SQL grammar, nor an approval of query outputs.

### Combined portable fixture gate

Run `python yt-sql/check_portable_fixtures.py` to validate all committed record, source and facet fixtures and check their deterministic regeneration and Unicode audit. This command never rewrites fixtures. Its explicit manifest must be extended when new fixture families are introduced; passing it is not a claim of comprehensive language conformance or approval of expected query results. Run `python scripts/json_quality.py` separately to check repository-wide JSON formatting and syntax.

### Cross-fixture consistency

Run `python yt-sql/check_fixture_relationships.py` to verify relationships between independently valid fixtures. The small and normal record profiles must agree on their declared source, source URL, generation timestamp, generator version and seed. The facet topology must retain the source topology's complete ordered records, source memberships, record count and digest, and include at least one empty relation. These checks deliberately do not assume that different-sized generated profiles have identical record prefixes. The consolidated fixture gate runs this check alongside individual validators and reproducibility checks. This establishes fixture consistency, not query-result conformance.

## Durable fixture contract and future extensions

The portable fixtures provide stable, deterministic inputs and integrity checks. They do not define expected query results. The large and huge generator profiles are not committed portable fixtures. Future work must define typed-value and temporal encodings, diagnostic categories, comparison semantics and case-level expected results. Python-generated expectations remain provisional until reviewed against intended semantics, the query, datasets and parameters. Maintain the curated language-element registry and source-derived audits as discovery aids, not as evidence of complete language coverage.

## Portable corpus structure validation

Run `python yt-sql/validate_corpus.py` to validate case file layout, dataset references, result-shape exclusivity, row widths, duplicate case IDs and implementation-specific XFAIL manifest references without invoking either language engine. The JSON schemas in `schema/` describe the same structural baseline. This validator deliberately does not certify query semantics or implement the eventual typed-value comparison rules. Generated expected results require independent review before inclusion in the normative corpus.

## Typed expected values and row comparison

The portable result contract permits JSON `null`, Boolean and string values directly. Integers use `{"type":"integer","value":"-42"}` with canonical base-ten digits; decimals use `{"type":"decimal","value":"1.250"}` with an exact finite decimal string; and timestamps use `{"type":"timestamp","value":"2026-01-01T00:00:00Z"}` with an explicit UTC offset. Untagged JSON numbers are rejected because they cannot reliably convey numeric type or precision across implementations. Other tagged types are reserved for separately specified extensions. Strings are compared as exact Unicode code-point sequences without implicit normalisation or locale collation. JSON cannot encode invalid Unicode surrogates.

`typed_values.py` supplies engine-independent value validation and comparison. Integer and decimal types remain distinct, even when numerically equal. Decimal values compare by exact mathematical value within the decimal type, without binary floating-point conversion. Timestamps compare as instants after offset conversion to UTC. Timestamp strings must use an explicit offset; this contract does not represent naive/local datetimes, named time zones, leap seconds or sub-microsecond precision. Fractional seconds are limited to six digits (microseconds); longer fractions are rejected rather than silently truncated. Offset-equivalent timestamps compare as the same instant. Those excluded representations require a later explicit extension. NULL is distinct from every other value. Ordered rows compare positionally; unordered rows compare as multisets, retaining duplicate multiplicities. Column names and diagnostic categories must be compared separately by a future execution harness. No tolerance-based numeric comparison is implied.

The corpus validator enforces the value shapes in committed `expected.json` files. This does not approve the expected values or define how an engine must serialise its runtime values. Parameter binding encodings and engine adapters remain separate future work. Expected outputs are reviewed before becoming normative.

## Portable language diagnostics

Expected language errors use one of six stable categories: `syntax` (invalid grammar or tokens), `resolution` (unresolved or ambiguous names), `type` (invalid operand or type combinations), `evaluation` (a language-level runtime evaluation error), `unsupported` (a recognised but unsupported language construct), or `parameter` (invalid or missing query parameter bindings). These categories describe the expected *observable language failure*, not a Python exception hierarchy or a Rust error type. Engine adapters must explicitly classify their errors; unexpected exceptions, process crashes, timeouts and infrastructure failures cannot be classified as a matching language error merely because a query failed.

An optional non-empty `code` narrows the expected diagnostic to an exact stable code. Without an expected code, only the category is compared. Error message wording, traceback, source location and implementation-specific details are deliberately excluded from the normative comparison. `diagnostics.py` provides the portable validator and matcher. The future execution harness must keep unrelated failures distinct from expected errors and must not use an XFAIL to disguise an unrelated crash. Existing category assignments and any stable codes require deliberate semantic review when conformance cases are added.

## Portable named parameters

Case `parameters` are optional, case-sensitive bindings whose names match `[A-Za-z_][A-Za-z0-9_]*`. The absent `parameters` field is equivalent to an empty binding map. A missing binding is not equivalent to a binding explicitly set to JSON `null`. Values use the same portable encoding as result cells: JSON `null`, booleans and Unicode strings, or tagged `integer`, `decimal` and offset-bearing `timestamp` objects. Untagged JSON numbers, malformed tagged values and unpaired Unicode surrogates are invalid. `parameters.py` validates these shapes independently of any engine. The adapter must bind values without implicit conversion and report missing or unsupported bindings as language diagnostics, not infrastructure failures. Parameter placeholder syntax, named binding resolution and implementation-specific runtime conversions are not certified by structural validation.

Diagnostic category and stable code are locale-independent; translated message text and presentation-specific source context are not normative comparison fields.

### Corpus contract consistency

The corpus validator enforces the case identifier and dataset-name patterns published in `schema/test-case.schema.json`, including the minimum case identifier length and optional description constraints. Implementation-specific override metadata must be non-empty text when supplied. `test_portable_contract_reconciliation.py` guards these boundaries against schema/validator drift. These checks validate the portable file contract only; they do not execute queries or establish expected-result authority. Before extending the corpus, reconcile any changes to the JSON schemas, Python validators and this documentation together.

## Shared schema consistency

The portable parameter and result-cell schemas use the same tagged-value definition. Keep `schema/test-case.schema.json` and `schema/expected.schema.json` synchronised when adding or changing a value type; `test_portable_schema_consistency.py` checks their structural equivalence. Schema validation is a portable structural check, while the Python validators additionally enforce semantic constraints such as calendar-valid timestamps, Unicode scalar values and row widths. Neither structural validation nor an engine-produced candidate result makes an expected result authoritative.

### Observable outcome comparison

`compare_outcomes.py` combines the typed-row and diagnostic comparison contracts into an engine-independent outcome comparator. Column names and order are normative, including for empty results. Row order follows the case's `order` setting; unordered comparisons preserve duplicate multiplicity. An expected error matches only an observed classified language diagnostic of the same category, with exact code matching when the expectation specifies a code. Human-readable messages are not normative and must not be substituted for diagnostic identity. Engine adapters must distinguish language diagnostics from crashes, timeouts and infrastructure failures before invoking the comparator.

## Provisional Python observation staging

`stage_candidate.py` accepts an existing corpus case, a JSON observation captured by a Python execution adapter, and a new output path. It validates the case and observed outcome, then records the query, case manifest and referenced fixture SHA-256 digests alongside the observation. The resulting JSON is explicitly `provisional` and identifies the producing implementation as `python`. The output path must not exist: the command never replaces a prior candidate or changes `expected.json`.

```bash
python yt-sql/stage_candidate.py yt-sql/cases/smoke/source_order_limit /path/to/observed.json /path/to/candidate.json
```

Staging is not execution, independent semantic review, or approval. An adapter must explicitly classify language diagnostics and keep crashes and infrastructure failures outside the observable-outcome format. The staging script does not promote candidates into the normative corpus; review against the query, datasets, parameters and intended semantics remains a separate step. Candidate files should be kept outside the committed corpus until reviewed. The Python execution adapter produces provisional observations from actual queries within its documented binding limits.

## Execution configurations

Cases may declare `execution.configurations`, a non-empty list of uniquely named configurations. Each has an `id` and `settings`; the portable setting `optimisation` accepts `enabled` or `disabled`. An empty settings object requests the implementation default. All configurations share the case’s approved expectation. Adapters must report unsupported or ineffective settings explicitly rather than silently ignoring them. A configuration comparison is not a substitute for an independently reviewed expectation. Engine-specific settings, random seeds and configuration-scoped XFAILs require separate contracts; they are not implied by this schema. The supported query clock is documented below.

## Phase 4 Python candidate execution

`run_python_candidate.py` executes supported portable cases through the existing Python parser, resolver and evaluator. It writes observations for separate staging with `stage_candidate.py`; neither command approves or modifies `expected.json`. Candidate staging records the case identity and SHA-256 digests of the query, manifest and datasets, and refuses to overwrite an existing destination.

```bash
python yt-sql/run_python_candidate.py yt-sql/cases/smoke/source_order_limit /tmp/observed.json
python yt-sql/stage_candidate.py yt-sql/cases/smoke/source_order_limit /tmp/observed.json /tmp/candidate.json
```

### Fixture binding and relational execution

The adapter accepts one static, source-topology or facet-topology dataset per case. Declared physical source and facet requests are bound to their corresponding records and schemas; undeclared requests fail explicitly, and an empty facet does not acquire records from its parent source. The existing engine handles JOINs, CTEs and set operations. Regression tests exercise INNER, LEFT, SEMI and ANTI joins, NULL-sensitive predicates, empty facets, CTE composition, duplicate-preserving `UNION ALL` and optimised/unoptimised relational execution. These tests verify adapter behaviour, not independently approved language expectations.

Multiple datasets and queries without a physical source binding are not supported by this adapter. `settings.optimisation` controls the evaluator's `relational_optimisation` flag, not every optimiser stage. Unsupported configurations fail rather than silently falling back.

### Parameters and reproducibility

Case-sensitive named parameters are substituted as YT-SQL literals using the portable typed-value contract. NULL, Boolean, integer, decimal and escaped text values retain their distinct representations. Timestamp parameters are converted to UTC ISO datetime tokens with microsecond precision; their original offset spelling is not preserved. Missing or unused bindings are rejected, and placeholders inside quoted SQL text are left untouched. This differs deliberately from the CLI's case-folded text-parameter interface.

An execution configuration may set `settings.clock` to an offset-aware RFC 3339 timestamp, such as `2026-09-01T10:30:00Z`. Invalid timestamps and missing offsets are rejected. Without this setting, the adapter uses its historical fixed instant, `2026-09-01T00:00:00Z`. The clock is passed to the Python date-resolution context; it is not a general clock contract for all future implementations. Temporal parameter regressions exercise offset conversion and actual fixture timestamp boundaries through the parser, resolver and evaluator.

### Diagnostic classification and safety

Lexical and grammatical failures produce portable `syntax` observations. Only reviewed, structured semantic reasons are mapped to other categories: `unknown-field`, `unknown-relation-alias` and `ambiguous-field` map to `resolution`; `non-numeric-aggregate` maps to `type`. Classification never relies on human-readable exception messages.

Other semantic errors remain unclassified. Unexpected evaluator exceptions, including Python `TypeError`, `ValueError` and `ZeroDivisionError`, are infrastructure failures rather than valid portable `evaluation` outcomes. Any future evaluation mapping requires an explicit language-level reason and negative regression coverage. No generated observation becomes normative without independent review in Phase 5.

### Phase 4 completion boundary

Before handing over to Phase 5, reconcile supported and unsupported case shapes, observation and staging failure paths, reproducibility, the coverage inventories and the documented execution settings. The permanent conformance harness and systematic migration of existing tests belong to Phases 6 and 7 respectively. Retain existing Python tests and independent oracles until equivalence has been established.

## Phase 5 expectation review preflight

`review_candidate.py` checks a provisional candidate's identity, query, manifest and dataset digests against the current corpus. It validates the observed outcome and reports whether it matches the current `expected.json` under the case's ordering contract. A match is **not** evidence that the existing expectation is semantically correct, and a mismatch is not automatically a defect in either implementation. This command never approves, promotes or rewrites an expectation.

```bash
python yt-sql/review_candidate.py yt-sql/cases/smoke/source_order_limit /tmp/candidate.json
```

The version 1 candidate format does not record the execution configuration that produced an observation. The review report makes that limitation explicit; candidates involving non-default or multiple configurations must not be approved on the strength of this preflight alone. Independent reviewers must examine the intended query semantics, fixtures, parameters, temporal and optimisation settings, diagnostics and relevant independent oracles before deciding whether a normative expectation is justified. Approval records and configuration provenance are described below.

### Configuration-verified review candidates

For a new candidate with an explicitly verified execution configuration, run the Python adapter with `--configuration CONFIG`, then stage the observation using `stage_candidate.py CASE OBSERVED DESTINATION --configuration CONFIG`. Staging re-executes the declared configuration and rejects any observation that differs from the new result before recording the selected configuration in a version 2 provisional candidate. The review preflight checks that this configuration still matches the case manifest. This is reproducibility evidence, not independent semantic approval. Legacy version 1 candidates remain readable, but their execution configuration is unknown and must not be inferred. Re-execution can be unsuitable for genuinely volatile, unseeded queries; such cases require a separately reviewed reproducibility policy.

### Independent review records

`record_review.py` writes a separate, immutable-by-default review record for a provisional candidate. The reviewer supplies an explicit `approve` or `reject` decision, their identity and a substantive rationale based on independent examination of the query, fixtures and intended language semantics. The tool verifies candidate preflight and binds the record to the exact candidate bytes using SHA-256. Approval records require version 2 candidates with verified configuration provenance; legacy candidates may be rejected but cannot be approved through this workflow.

```bash
python yt-sql/record_review.py yt-sql/cases/smoke/source_order_limit /tmp/candidate.json /tmp/review.json --decision approve --reviewer "Reviewer name" --rationale "Independently checked the query semantics and fixture records"
```

A review record is an attestation supplied by the reviewer, not automated proof of semantic correctness. It is not cryptographically signed and does not itself promote or modify `expected.json`. An approval record alone is not an approved corpus expectation; admission or promotion must still be performed explicitly. Existing review records are never silently overwritten.

### Controlled expectation promotion

`promote_candidate.py` requires an exact candidate-digest match against an independently issued approval record, a current corpus preflight and a configuration-verified version 2 candidate. Promotion is a separate explicit action; neither staging nor recording a review modifies normative expectations. Existing `expected.json` files require `--replace`, and the previous bytes are retained as `expected.json.before-promotion` with overwrite protection. Keep review records and the candidate as durable evidence outside the normative case directory. A recorded approval is a human attestation, not automated proof of semantic correctness.

```bash
python yt-sql/promote_candidate.py yt-sql/cases/smoke/source_order_limit /tmp/candidate.json /tmp/review.json --replace
```

Promotion explicitly refuses a missing or symlinked `expected.json`; initial admission uses the separate workflow described below. Existing backups and temporary promotion files also block a new promotion rather than being overwritten or silently removed. The replacement is prepared and synchronised before the recovery copy is written, and failures before the final atomic rename clean up newly created artefacts. A process interruption can still leave recoverable staging files; inspect them manually before retrying. Adding entirely new cases uses the separate admission workflow described below. Promotion is not a substitute for independent semantic review or Phase 6 cross-implementation verification.

### Admission of new portable cases

A new case may be prepared with `test.json` and `query.sql`, referencing an existing validated dataset, but without `expected.json`. This is a provisional case, **not** a valid member of the normative corpus: `validate_corpus.py` continues to reject it until admission. The Python adapter, candidate staging and independent review preflight accept this narrowly defined missing-expectation state; other case structure and dataset checks remain in force.

After generating an observation, stage it with `--configuration`, obtain a separately authored approval record using `record_review.py`, then run `python yt-sql/admit_candidate.py CASE CANDIDATE REVIEW`. Admission requires a verified version 2 candidate, current query/manifest/dataset digests and an independent approval bound to the exact candidate bytes. It creates `expected.json` only if absent, refuses stale recovery artefacts and does not modify existing expectations. Replacement remains the separate, explicit `promote_candidate.py --replace` workflow. Admission publishes a fully written expectation without overwriting another process's file; interrupted temporary artefacts require inspection before retrying.

Reviewers must establish the semantics independently. Successful Python execution and reproducibility are not sufficient grounds for approval. Keep provisional cases out of committed normative corpus changes until their expectation has been admitted and corpus validation succeeds.

### Phase 5 final reconciliation and review

Admission and replacement use the same approval-evidence validator, which checks the current candidate preflight, exact candidate digest, review decision and verified configuration provenance. Both operations remain explicit and retain their distinct file-safety rules. Review records are unsigned attestations; a reviewer must verify semantics independently rather than merely accepting Python output. No case is admitted or expectation replaced as part of this reconciliation.

The current workflow is deliberately local and file-based. It does not provide a multi-file crash transaction, signed reviewer identity, automatic recovery of stale artefacts or cross-implementation certification. Keep the candidate and review record as external audit evidence, inspect interrupted operations manually and rerun corpus validation after admission or replacement. Phase 6 will consume approved expectations without treating candidate execution as the oracle.

## Phase 6 permanent conformance runner

`run_conformance.py` compares each committed `expected.json` against an implementation observation. It never reads staged candidates or review records as an oracle. The initial adapter is Python, registered explicitly in `conformance_adapters.py`; requesting an unregistered implementation fails closed. Adapters produce observations only and do not own approved expectations. The command returns exit status 0 only when every case passes or has an explicitly supported known outcome mismatch. It returns 1 for failures, infrastructure errors and unexpected passes, and 2 for invalid setup.

```bash
python yt-sql/run_conformance.py
python yt-sql/run_conformance.py --json
```

Reports distinguish `pass`, `fail`, `error`, `xfail` and `xpass`. An adapter exception is always an infrastructure error, even for a case marked XFAIL. The initial XFAIL support is restricted to the explicit `outcome-mismatch` category; other categories cannot silently excuse a mismatch. The `--configuration` option selects one named configuration for every case, so it is suitable only where that configuration exists in each case. Multiple-configuration scheduling, Rust execution, isolated subprocess execution and richer failure classification remain future Phase 6 work.

Exact case selection is available with repeatable `--case ID` arguments, and `--list-cases` lists approved case IDs without executing an adapter. Selected cases are deduplicated and run in case-ID order for stable output; an unknown case ID is a setup error. The entire corpus is still validated before selection, so filtering cannot hide malformed normative cases or expectation manifests.

For CI and other automated consumers, `--report-file PATH` writes the same deterministic JSON report to a file using atomic replacement. It is independent of `--json`, so the normal human-readable console output can be retained while saving a machine-readable result. Reports are written for completed conformance runs even when cases fail; invalid setup does not produce a new report. The destination directory must already exist. Report files are generated evidence, not approved expectations, and should not be committed to the normative corpus.

### Continuous integration

The `YT-SQL portable conformance` GitHub Actions workflow runs the approved Python conformance corpus on pushes and pull requests. It retains the harness exit status as the CI gate and uploads `conformance-python.json` as a generated diagnostic artefact when a completed run has produced one, including on conformance failures. The report is not a normative expectation and must not be used to approve candidate results. Rust execution remains outside this workflow until its independent adapter is implemented.
