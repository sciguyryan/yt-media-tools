# Phase 6.5a.1 text predicate follow-up

This increment adds four portable, independently calculated predicate outcomes against the committed `python-v6-small` dataset. The expected IDs were selected directly from the fixture titles, rather than copied from Python adapter output. The adapter subsequently agreed with all four cases.

The cases cover case-sensitive and case-insensitive Mars prefixes, a negated LIKE predicate, and a literal underscore escape with an empty result. The empty-result case is deliberate: it guards against treating an escaped underscore as a wildcard.

No legacy Python test was retired in this increment. The existing parametrised `test_like_semantics` uses a different, hand-authored record set and tests three-valued evaluation of individual predicates, including NULL. The four new dataset-based cases do not yet replace those assertions. That distinction must be preserved during the remaining assertion-level audit, together with POSITION parser, optimiser and execution checks.

These cases are discovered automatically through their `test.json` files; no central registration is necessary. The generated coverage and retirement inventories have been refreshed to reflect the added cases.
