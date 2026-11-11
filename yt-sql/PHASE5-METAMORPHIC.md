# Phase 5.3: Metamorphic transport checks

The portable metamorphic runner executes every approved case with its original query and with two semantics-preserving transport variations: additional surrounding whitespace and CRLF line endings. Each observation must match the independently authored JSON expectation and the original observation under the case's ordering contract. The runner never generates or modifies normative expectations.

Run `python yt-sql/compare_metamorphic.py` for the focused check. The corresponding pytest module is `python/yt_discover_tests/test_portable_metamorphic.py`.

This is deliberately limited to query transport transformations. It does not prove equivalence under arbitrary algebraic rewrites, alternate backends or operating systems. The existing nine-environment Python report comparison remains the cross-platform gate, and Phase 6 must still establish complete semantic coverage before legacy tests can be retired.
