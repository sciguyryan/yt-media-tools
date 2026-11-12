# Phase 6.5a text-function migration evidence

This is an intermediate, independently reviewed text-function migration increment, not the completed 6.5a.1 function-family audit or Phase 6 certification.

The 21 new portable fixtures cover Unicode case expansion and non-ASCII case mappings, composed versus decomposed accents, code-point rather than grapheme-cluster length, nested text functions, and field-based Unicode projections. Expected results were specified from the documented Unicode strings and YT-SQL output contract, then checked against the Python adapter. The five field-based assertions in `test_lower_upper_and_length_follow_python_unicode_string_semantics` are now represented by five independent normative fixtures; that Python test has been retired and recorded in `REVIEWED-RETIREMENTS.json`.

The existing CHAR and CONCAT module reviews and their implementation-specific optimiser checks remain intact. The existing POSITION fixtures remain authoritative for their represented behaviours, but the final-result POSITION family still requires a separate comprehensive migration review. The Python adapter currently reports some rejected POSITION placements and invalid integer arguments to LOWER, UPPER and LENGTH as unclassified semantic diagnostics. These are unresolved normative error-classification obligations and must not be silently converted to approved expectations or removed from legacy coverage.

Before declaring the text group complete, review every text- and POSITION-related assertion in cross-cutting parser, relational, optimiser, Unicode and torture modules, including parameterised variants. Retire only assertions with documented portable replacement evidence. This document records work completed, not a claim that those obligations are closed.

## POSITION and invalid text-argument continuation

Fourteen additional reviewed fixtures now specify final-result POSITION ordering, pagination, empty results, invalid argument arity, invalid placement, and numeric-field type rejection for LOWER, UPPER and LENGTH. The invalid placements are syntax-level violations of the standalone final-projection restriction, whereas numeric arguments to text functions are type errors. The Python adapter now recognises only the explicit diagnostic reasons for these cases; it does not infer portable errors from diagnostic wording. Existing message-specific tests remain valuable for Python's diagnostic contract.

The POSITION ordering-and-pagination semantic assertion previously embedded in `test_position_numbers_after_ordering_before_offset_and_limit` has been replaced by `function-conformance.position_second_after_offset`. The implementation-specific assertion that evaluation does not mutate source records remains as `test_position_projection_does_not_mutate_source_records`.

The formatter's ST06 rule was also disabled for YT-SQL because rearranging SELECT targets changes observable column order. A regression test protects the target ordering while retaining the authoritative parse-tree and idempotence checks. This exception applies to YT-SQL only, not SQLite.

This continuation does not certify the entire text/POSITION family. In particular, all parameterised POSITION interactions, nested CTE behaviour, Unicode textual predicates and the broader cross-module assertion inventory still require a comprehensive retirement audit before 6.5a.1 can be declared complete. Passing the Python adapter alone is not independent proof of the normative expectations.
