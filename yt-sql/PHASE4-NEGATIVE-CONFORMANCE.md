# Phase 4.1 - Negative conformance

The first reviewed negative batch contains nine ordinary YT-SQL queries with independently specified diagnostic categories. The cases exercise malformed projections, trailing commas, unmatched parentheses, incomplete predicates and ordering clauses, negative pagination bounds, unresolved columns and invalid aggregate arity. These cases are approved as language errors, not expected implementation failures.

The initial investigation also exposed three distinct cases that must not be admitted as ordinary passing negatives yet: unknown function classification differs from the proposed resolution category; missing named bindings currently escape the portable adapter as an infrastructure error; and an unbound source is rejected by the adapter before language resolution. These require deliberate diagnostic-contract reconciliation in the remaining Phase 4 work. No implementation exception has been relabelled to make an expectation pass.

This batch does not complete Phase 4.1's exhaustive negative inventory or certify every function's invalid arity and type combinations. All existing semantic tests remain in place until verified migration and retirement in Phase 6.
