# Phase 3 Unicode reconciliation

Phase 3 adds portable, independently reviewed expected outcomes for scalar functions, NULL propagation, aggregates, collections and Unicode operations. The normative corpus now contains 80 cases. This increment adds 34 Unicode cases without introducing implementation-specific result tests or tests that assert the contents of generated planning files.

## Unicode contracts exercised

The added YT-SQL cases check full case-mapping expansions, context-sensitive Greek sigma, Turkish dotted and dotless I, German sharp s, Kelvin sign, ligatures, Cyrillic, Greek, Armenian, fullwidth Latin and supplementary-plane Deseret letters. They check Unicode scalar-value length rather than grapheme-cluster length, including combining sequences, zero-width-joiner emoji, variation selectors, regional indicators, CJK, Arabic and supplementary-plane characters. Concatenation cases check that distinct Unicode representations are preserved rather than silently normalised.

Each expected result was authored from the intended language contract, not copied from an evaluator observation. The same corpus is executed on every configured runtime. These cases do not imply that all Unicode algorithms or all versions of Unicode have been certified.

## Platform verification

The portable conformance workflow now exercises Python 3.12, 3.13 and 3.14 on Linux, macOS and Windows. Each job prints the Python runtime and `unicodedata.unidata_version` so any version-dependent differences can be diagnosed. Every job executes the same committed normative queries and expectations. No platform-specific expected-result exceptions are introduced.

The CI matrix must actually pass before cross-platform compatibility is claimed. Its results are not available from this local environment. Rust and optimiser differential certification remain Phase 5 obligations; neither is implied by the Python-only matrix.

## Remaining programme obligations

Phase 4 covers malformed inputs, unsupported constructs, nested interactions and adversarial semantic boundaries. Phase 5 covers differential Python/Rust and optimiser execution, repeatability, cross-platform acceptance and any Unicode-version-sensitive discrepancies discovered by the matrix. Phase 6 performs the final registered-element and coverage-dimension closure audit. In particular, the provisional coverage gap matrix must not be represented as certified language coverage merely because new cases exist.

The corpus is a growing set of concrete guarantees, not proof of exhaustiveness over all possible Unicode strings. Any newly promised language behaviour must be backed by independently authored normative cases and verified on supported runtimes before final certification.
