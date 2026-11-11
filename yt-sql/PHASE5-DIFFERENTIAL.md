# Phase 5.2: Differential execution

The differential runner executes every approved portable case twice, using the Python evaluator with relational optimisation enabled and disabled. Both paths must independently match the committed, independently authored JSON expectation, and must agree with each other under the case's declared ordering contract. The runner never writes expectations or silently converts adapter failures into expected language errors.

Run `python yt-sql/compare_differential.py` for the focused check. The pytest module `python/yt_discover_tests/test_portable_differential.py` integrates the same behavioural checks into the ordinary suite.

This tests the evaluator's public `relational_optimisation` switch. It does not establish equivalence for every internal optimiser pass or acquisition planner, and does not substitute for the metamorphic and cross-platform work in Phase 5.3. All legacy semantic tests remain in place pending Phase 6 coverage closure.
