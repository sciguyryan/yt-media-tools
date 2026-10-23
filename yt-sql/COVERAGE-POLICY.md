# YT-SQL conformance coverage policy

The coverage inventory is a source-derived starting point, not a declaration that the language is fully specified or tested. The registered feature list comes from the existing independent Python conformance suite. Function names are extracted from the reference parser. Neither source is assumed exhaustive: later phases must audit grammar productions, diagnostics, resolver constraints, execution behaviour, aliases, and supported syntax not represented by existing feature tags.

## Coverage dimensions

Each supported construct, operator and function requires evidence for the applicable dimensions:

- Valid syntax: accepted spellings, grammatical positions, precedence, associativity and nesting.
- Invalid syntax: missing or surplus tokens, malformed expressions, illegal combinations and expected diagnostic category.
- Semantics: independently established observable result and type, including order and duplicates.
- Type and NULL behaviour: supported argument types, invalid types, propagation, coercion and three-valued logic where relevant.
- Boundaries: empty and singleton inputs, extremes, Unicode, dates, numeric precision and unusual literals where applicable.
- Interactions: combinations with other language features, including grouping, source identity, optimisation and parameters.
- Adversarial cases: deeply nested, convoluted, high-cardinality or maximal coherent combinations, with deterministic expectations.

Each dimension is either supported by reviewed test identifiers or explicitly marked not applicable with a reason. A feature tag alone does not satisfy a dimension. Coverage completeness must be enforced by a later machine-readable matrix and quality gate, not inferred from the present inventory.

## Expectation authority

Reference Python execution may generate candidate expected results in bulk. These results are provisional. Every candidate must be reviewed against the query, input dataset, parameters and intended YT-SQL semantics **before** it is approved as a normative expected output. The policy does not prescribe who or what performs the review. Unresolved errors or ambiguities block approval. Ordinary conformance execution must never silently update approved expectations. Subsequent corrections require traceable justification.

## Existing tests and migration

The existing Python cases, parser tests, independent oracles, optimiser differential checks and integration tests remain in place. Inventory entries are evidence of existing coverage, not authorisation to delete tests. Migration requires a case-by-case equivalence review, preserving implementation-specific checks that do not belong in the portable corpus.

## Phase 1 boundary

`COVERAGE-INVENTORY.json` records the source-derived feature-to-case map, function names and currently shared cases. `build_coverage_inventory.py --check` detects drift in that snapshot. It does not validate the correctness of expected outputs or certify exhaustive grammar/function coverage. The later phases will establish the complete grammar inventory, full coverage matrix, candidate generation, review and execution gates.

## Deeper parser-surface audit

`build_language_surface_audit.py` produces `LANGUAGE-SURFACE-AUDIT.json` by inspecting the actual Python parser without executing it. The report records parser entry points, literal keyword-consumption sites, parser and lexer diagnostic raise sites, and function names from the baseline inventory. It deliberately does not equate a parser method, keyword or feature tag with complete conformance coverage. Dynamically assembled syntax, token regex alternatives, non-parser validation, function signature details and runtime errors still require targeted review.

Regenerate the baseline inventories before rebuilding the language-surface audit, then run both builders with `--check` to detect drift. Review the audit's priorities before assigning any coverage-complete status. The supplied regenerated inventory files are the input baseline for this increment.

## Coverage-gap matrix

`build_coverage_gap_matrix.py` generates `COVERAGE-GAP-MATRIX.json` from the registered feature inventory, parser function inventory and AST-visible parser entry points. It records source-visible function argument shapes, token and keyword expectations, and diagnostic raise-site references. All coverage dimensions remain **unverified** until reviewed test cases demonstrate them. A tagged legacy case is not automatically credited as reviewed conformance evidence. The function argument shapes are parser-level observations, not independently established type or semantic contracts. The report deliberately lists unresolved hand-written parser grammar, resolver and evaluator work rather than claiming completeness.

Regenerate the baseline inventories, then the language-surface audit, then the gap matrix. Each builder supports `--check` for drift detection. Expectation review remains mandatory before normative approval.

## Curated language-element registry and future CI gate

`LANGUAGE-ELEMENTS.json` is a deliberately curated registry of language elements, including keywords, functions, operators, syntax constructs and alternative spellings. The initial entries are a provisional seed and **not** an exhaustive specification. In particular, an operator such as `&&` must not be registered as supported merely because it is a familiar spelling in another SQL dialect: support must be established from the YT-SQL implementation and intended language contract. Grammar and evaluator audits must add missing constructs and aliases explicitly.

Every new or changed YT-SQL language feature requires thorough conformance tests appropriate to its valid and invalid syntax, types, NULL behaviour, boundaries, errors and interactions. New functions, operators, keywords, constructs and supported aliases must be registered; modifications to existing semantics require corresponding test and registry review. A source-derived discovery check cannot prove that the curated list is complete, so language-feature review and periodic audits remain essential.

`build_language_element_registry.py` validates the registry against discoverable feature and function inventories and generates `LANGUAGE-ELEMENT-AUDIT.json`. It does **not** automatically approve cases or infer coverage from keyword occurrences. Only independently reviewed and approved expectations may be linked as `approved_case_ids`. The final certification phase will enforce at least one approved case per supported registered element in CI, while reporting comprehensive semantic coverage separately. Until normative cases have been approved, the audit is informational about coverage gaps but strict about structural consistency and missing discoverable registrations.

## Structural semantic-surface discovery

`SEMANTIC-SURFACE-AUDIT.json` records lexical alternatives and exception/branch sites across the parser, resolver and evaluator. It deliberately excludes physical line numbers so source formatting alone does not invalidate the audit. Source-derived counts cannot establish that every supported syntax alternative or rejection path has been identified. Review the hand-written parser, the curated registry and the actual diagnostics before classifying coverage as complete. New language elements must be registered and thoroughly tested; the future CI gate checks minimum approved coverage, not exhaustiveness.

### Hand-written grammar reconciliation

`build_grammar_reconciliation.py` generates `GRAMMAR-RECONCILIATION.json` from literal calls in the hand-written recursive-descent parser, the curated language-element registry and the semantic-surface audit. It lists keyword and token candidates that do not currently have corresponding registry categories, together with exception classes for diagnostic review. These are **review candidates**, not automatically supported language features or proof of missing tests. Literal-call discovery cannot find every dynamically constructed alternative or establish actual runtime semantics. Review the candidates before modifying the curated registry; do not automatically populate approved-case lists.

## Grammar candidate classification

`build_grammar_candidate_review.py` produces `GRAMMAR-CANDIDATE-REVIEW.json`, a provisional, explicitly curated classification of the unmatched keyword and token candidates identified by grammar reconciliation. It distinguishes syntax candidates from forms recognised solely to produce unsupported-syntax diagnostics, and structural tokens from keywords. The classification is checked for drift against the generated reconciliation report. It is not a substitute for semantic review, a complete lexer/operator audit, or approved conformance expectations. A source change introducing a new unmatched candidate requires a deliberate classification update rather than silently expanding the registry.

### Textual operator and predicate reconciliation

Audit the hand-written parser's textual Boolean operators and predicates separately from symbolic lexer spellings. Each supported spelling, negation and context-dependent grammatical form needs deliberate registry review and appropriate positive, negative, boundary and interaction tests. Parser calls and source-derived inventories provide investigation evidence only, not approved conformance expectations. Review `TEXTUAL-PREDICATE-AUDIT.json` alongside `OPERATOR-SPELLING-AUDIT.json` before closing Phase 1.
