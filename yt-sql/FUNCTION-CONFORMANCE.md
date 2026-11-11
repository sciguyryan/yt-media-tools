# Portable function and expression conformance

The normative corpus now contains focused function cases under `cases/function-conformance/`. Each case contains a YT-SQL query and a separately specified JSON expectation. The cases exercise the registered aggregate, collection and scalar function families, including valid and invalid arity, NULL handling, Unicode text, numeric boundaries, nesting and relational aggregate inputs. They complement the earlier scalar, aggregate and Unicode cases rather than replacing their expectations.

The corpus's `test.json` feature labels identify relevant language features. A label is not evidence that every semantic obligation for that feature has been certified. In particular, the `FUNCTION-SEMANTIC-AUDIT.json` investigation records outstanding type, coercion and cross-platform reviews. An execution adapter must not turn an unclassified semantic diagnostic into a guessed portable error category. The portable error expectations only cover classifications that the adapter can justify.

The Python adapter can run the cases with `python yt-sql/run_conformance.py --implementation python --json`. The corpus is checked structurally with `python yt-sql/validate_corpus.py`. The full local quality gate is still required for release acceptance. Neither a passing Python run nor matching feature labels establishes independent Rust or cross-platform conformance.

No legacy semantic test is retired by this expansion. Retirement requires an assertion-level replacement review using `SEMANTIC-RETIREMENT-AUDIT.json` and must preserve any residual implementation-specific tests.
