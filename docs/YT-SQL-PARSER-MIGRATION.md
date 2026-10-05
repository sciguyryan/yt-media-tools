# yt-sql parser migration gate

A replacement parser is eligible for cut-over only after it is plugged into the differential harness defined by `YT-SQL-PARSER-EQUIVALENCE.md`. No candidate parser is introduced by this contract.

The deterministic accepted and malformed corpora are the primary gate. They are supplemented by grammar-anchored valid generation, controlled malformed mutation, property-style invariants, seeded bounded fuzzing, canonical formatting convergence and representative performance measurements. A fuzz failure becomes a deterministic regression case before closure.

For valid queries, the reference and candidate parsers must produce equivalent normalised yt-sql models. Meaning-bearing structure must agree, and available user-written source origins must identify equivalent constructs. Both parsers must converge through canonical formatting.

For invalid queries, both parsers must reject with the same diagnostic category, an equivalent meaningful source region and an equivalent reason for rejection. Exact human-readable wording may differ. Where wording differs, the differential case must state the stable rejection reason being compared rather than deriving language semantics from exception prose.

Syntax that is intentionally parsed but rejected semantically is compared at the syntactic-model boundary first. The same semantic validation layer then remains responsible for rejecting unsupported execution. Candidate parsers must not absorb semantic policy merely to make a differential test pass.

Performance comparison uses recorded reference workloads covering ordinary, complex, malformed and deeply nested bounded inputs. Sustained regressions, scaling, memory where measurable and pathological behaviour are reviewed before cut-over. A repeatable slowdown around twofold is an investigation trigger rather than a hard-coded pass/fail rule.

## Experimental Lark optimisation review

The issue #144 candidate review replaces Earley parsing with LALR and Lark's contextual lexer. The initial revision-1 transcription could not construct an LALR parser because separate scalar, temporal and literal-sequence alternatives described the same token reductions. Comparison values now use one shared syntactic path: field comparisons retain the established literal model, while scalar comparisons retain scalar-expression construction. This removes the parser conflict rather than silencing it with rule priorities or compatibility normalisation.

Earley with the basic lexer cannot preserve contextual keywords and overlapping numeric tokens without duplicating parsing policy outside the grammar. Earley's dynamic-complete lexer and the optional third-party regular-expression engine were also measured and were slower than the original dynamic configuration on the deterministic generated inventory. These alternatives are rejected implementation experiments, not language limitations.

Repeated `SELECT` and `FROM` alternatives are factored through a shared query-head production. Case-insensitive grammar words remain ordinary readable literals in the Lark source; parser construction adds their identifier-continuation boundary and structural priority centrally. This replaces a large duplicated terminal block while allowing the contextual lexer to retain the same words as identifiers in unambiguous positions.

Local repeated measurements over the three-round generated inventory improved median grammar-recognition throughput from approximately 127 to 9,800 parses per second, roughly a 75-fold improvement. LALR grammar construction took about three times as long, but construction remains cached once per process. Adapter profiling also removed repeated hot-path imports, avoids a whole-tree validation walk when model construction already visits the relevant comparison, and bypasses validation walks when the source cannot contain the compatibility boundary being checked.

The remaining performance gap is inside the retained Lark machinery rather than hidden in model conversion. On one local CPython run, the hand-written parser completed the simple, complex and collection workloads in approximately 23, 139 and 85 microseconds. Raw Lark tree construction alone took approximately 78, 363 and 240 microseconds; complete Lark model construction took approximately 122, 489 and 321 microseconds. The candidate is therefore about 3.5 to 5.4 times slower end to end, while its raw tree-construction lower bound is already about 2.6 to 3.4 times slower than the complete hand-written parse.

Disabling propagated tree positions reduced raw Lark time, but was rejected because Lark omits grammar literals from ordinary child lists. Exact origins for constructs including `UNION`, `JOIN`, aggregate stars and postfix members could not then be recovered from tokens alone. An integrated model transformer could reduce allocation and adapter traversal, but cannot overcome the measured raw parser lower bound while the exact-origin contract is retained. Parser replacement therefore does not currently meet the performance objective, despite the substantial improvement over Earley. These figures are review evidence rather than a portable performance promise. Stable `parser.lark.*` benchmark targets preserve simple, complex and collection-heavy candidate workloads for later comparison with the hand-written `parser.*` surfaces.

Accepting arbitrary function names in the grammar and rejecting unknown calls later was deliberately excluded. That proposal changes the syntax-versus-semantic rejection boundary and requires a separate language-design decision rather than being introduced as parser optimisation.

During migration, grammar revision 1 and the accepted hand-written parser remain frozen references. Any discrepancy is classified before either reference is changed. Unrelated grammar evolution is outside the migration.
