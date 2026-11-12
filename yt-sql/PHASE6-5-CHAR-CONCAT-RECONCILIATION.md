# Phase 6.5 CHAR and CONCAT reconciliation

This corrective iteration re-examines the previously reviewed CHAR and CONCAT Python test modules in full. Portable assertions previously retained by mistake have been replaced by committed YT-SQL queries and independently reasoned JSON expectations. The replacement evidence is recorded in `REVIEWED-RETIREMENTS.json`.

CHAR now has portable cases for composed and decomposed Unicode comparison, exact decomposed output and length, constant expressions in projections and ordering, and each of the eight invalid argument variants. CONCAT now has portable cases for invalid arity and type combinations, and an exact five-row field projection with expression ordering. The observed outputs were checked against the existing fixture and Python adapter after the expectations were specified; Python output alone does not establish normative correctness.

The Python candidate adapter previously rejected the invalid argument cases as unclassified semantic diagnostics. The resolver now emits explicit, narrow diagnostic reasons for invalid CHAR and CONCAT arguments, which the adapter maps to the portable `type` error category. The syntax-only zero-argument cases remain `syntax` errors. No broad message-based exception classification was introduced.

Both reviewed modules now retain only tests that inspect optimiser implementation details, including the internal folded field and recorded optimisation rule. The observable outcomes of those queries are also represented in the portable corpus. The retirement audit checks that every remaining test function in each reviewed module is explicitly accounted for, and rejects newly introduced or unclassified functions until the review is updated.

The general retirement audit remains a discovery and evidence tool, not a claim of complete YT-SQL semantic certification. Other legacy modules and remaining Phase 6 obligations still require review. Existing JSON formatting checks are retained; corpus structure and expected-outcome schema are validated separately by `yt-sql/validate_corpus.py`.
