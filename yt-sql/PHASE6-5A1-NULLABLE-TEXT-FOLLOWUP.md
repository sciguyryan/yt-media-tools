# Phase 6.5a.1 nullable text predicate follow-up

Four independently reviewed portable cases exercise LIKE, ILIKE and NOT LIKE on `fixture_nullable` in the committed `python-v6-small` dataset. The dataset contains twelve NULL values and forty-eight two-character `g` values. The expected ID sequences are calculated from the committed fixture, not copied from an implementation's observed output. A NULL predicate does not satisfy WHERE, including for NOT LIKE. The one-character wildcard matches the second character of each non-NULL value.

The existing `test_like_semantics` parametrisation remains in Python because it asserts the full three-valued result of evaluating a predicate on individual records, including an explicit NULL outcome. A WHERE-filtered portable case cannot distinguish UNKNOWN from FALSE, so these new cases do not justify retiring that test. A future portable expression projection or direct predicate-result contract must preserve that distinction before retiring those assertions.

This increment does not complete the exhaustive cross-module assertion review required to close Phase 6.5a.1. Remaining POSITION parser, optimiser and execution-specific assertions must be classified individually; implementation-specific checks should remain in Python. No existing legacy test is retired in this increment.
