# yt-sql parser migration gate

A replacement parser is eligible for cut-over only after it is plugged into the differential harness defined by `YT-SQL-PARSER-EQUIVALENCE.md`. No candidate parser is introduced by this contract.

The deterministic accepted and malformed corpora are the primary gate. They are supplemented by grammar-anchored valid generation, controlled malformed mutation, property-style invariants, seeded bounded fuzzing, canonical formatting convergence and representative performance measurements. A fuzz failure becomes a deterministic regression case before closure.

For valid queries, the reference and candidate parsers must produce equivalent normalised yt-sql models. Meaning-bearing structure must agree, and available user-written source origins must identify equivalent constructs. Both parsers must converge through canonical formatting.

For invalid queries, both parsers must reject with the same diagnostic category, an equivalent meaningful source region and an equivalent reason for rejection. Exact human-readable wording may differ. Where wording differs, the differential case must state the stable rejection reason being compared rather than deriving language semantics from exception prose.

Syntax that is intentionally parsed but rejected semantically is compared at the syntactic-model boundary first. The same semantic validation layer then remains responsible for rejecting unsupported execution. Candidate parsers must not absorb semantic policy merely to make a differential test pass.

Performance comparison uses recorded reference workloads covering ordinary, complex, malformed and deeply nested bounded inputs. Sustained regressions, scaling, memory where measurable and pathological behaviour are reviewed before cut-over. A repeatable slowdown around twofold is an investigation trigger rather than a hard-coded pass/fail rule.

During migration, grammar revision 1 and the accepted hand-written parser remain frozen references. Any discrepancy is classified before either reference is changed. Unrelated grammar evolution is outside the migration.
