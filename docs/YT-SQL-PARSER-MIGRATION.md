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

## Lark differential conclusion

The bounded issue #144 gate now compares the complete migration and established conformance corpora, three rounds of grammar-anchored generation, controlled malformed neighbours and a slew of fuzz seeds. The permanent suite exercises more than 200 accepted inventory entries, the established malformed corpus, 39 generated malformed neighbours and more than 800 seeded fuzz executions. Every accepted fuzz result also passes same-parser canonical round trips and cross-parser canonical convergence. The seed and failing source are reported with deterministic token-deletion candidates when a property fails.

The fuzz phase achieved its goals and exposed three material implementation defects rather than normalising them away: negation detection assumed an ASCII space after `NOT`; an `IS [NOT] DISTINCT FROM` right operand could be reduced directly to a token instead of a wrapper tree; and a missing separator after the required `FROM` keyword had a different diagnostic span and expected-token set. Each defect is corrected and represented by a deterministic corpus or model-construction regression.

No behavioural differences remain within the bounded gate across acceptance, normalised models, user-written source origins, canonical formatting or normalised diagnostics.

The remaining concern is compatibility at the operational boundary: complete Lark parsing is still approximately 3.5 to 5.4 times slower on the representative workloads, and raw Lark tree construction alone exceeds the complete hand-written parser. The Lark candidate is therefore behaviourally conformant within the issue #144 gate but is not recommended for production cut-over. Investigation of another declarative engine is separate work and does not alter this conclusion.

## Experimental Tree-sitter boundary

The Tree-sitter investigation starts as a separate optional grammar package under `experiments/tree-sitter-yt-sql`. It does not change the production parser or ordinary Python dependencies. The formal EBNF and hand-written parser remain the de facto references, and the Lark candidate remains available as supporting evidence until a later cut-over decision.

Part 1 pins Tree-sitter CLI at 0.26.13, Python runtime 0.26.0 and language ABI 15. The grammar source and generated C are committed together. Node.js and the CLI are required to regenerate the parser, but not to build the committed source. npm's install-script approval is limited to the exact CLI version rather than allowing dependency scripts generally.

The Python language binding is its own experimental package. The adapter imports it only when the Tree-sitter path is called, keeps concrete syntax trees private and rejects recovered or missing syntax instead of treating Tree-sitter's error recovery as acceptance. Tree-sitter's UTF-8 byte offsets are converted to the existing Python character-offset model at the adapter boundary.

The smoke grammar proves generation, native compilation, case-insensitive keyword recognition, Python loading and strict recovery rejection. It recognises only a deliberately tiny projection shape for the moment. This is primarily because this is to be used as a performance feasibility, representative grammar coverage and the first meaningful benchmark gate belong to part 2.

The early performance gate remains deliberately uncomfortable: raw Tree-sitter parsing should take no more than approximately 60 to 70 percent of the hand-written parser's time. Final cut-over would additionally require end-to-end model construction to meet or beat the reference parser, behavioural and diagnostic parity, supported packaging, and a real reduction in hand-maintained parser complexity. Generated C is reported separately rather than counted as a maintenance saving.

## Tree-sitter performance feasibility

Part 2 extends the experimental grammar only far enough to recognise the established simple, complex and collection-heavy parser workloads. This slice covers projections, aliases, known scalar functions, nested collection transforms, collection predicates, Boolean precedence, comparisons, text matching, NULL tests, representative literals, ordering and slicing. It does not imply complete grammar acceptance, and arbitrary function names remain outside the experiment's syntax.

Grammar revision 2 extends that bounded slice with physical and derived relation operands, nested query expressions, `UNION` and `UNION ALL`, predicate-only derived queries, optional aliases and derived JOIN operands. The bounded grammar also follows the current lexical contract for `#` line comments and decimal, hexadecimal, octal and binary `LIMIT` and `OFFSET` integers. This covers the new relation and slicing boundaries without claiming that the remainder of revision 2 is already implemented. Stable `parser.tree_sitter.*` benchmark targets measure raw Tree-sitter parsing through the optional Python binding, including UTF-8 encoding but excluding query-model construction.

On one local CPython run after the revision-2 update, the hand-written parser completed the simple, complex, collection and base-sliced derived-relation workloads in approximately 23.7, 142.1, 85.9 and 87.8 microseconds. Raw Tree-sitter parsing completed them in approximately 2.8, 11.8, 8.5 and 8.0 microseconds, or roughly 8 to 12 percent of the reference time. The corpus and adapter tests accept nested, UNION, predicate-only and JOIN-derived relations, line comments and base-aware row slicing while rejecting empty, unclosed, illegal `OF` and malformed slicing forms through the strict recovery boundary.

Tree-sitter therefore passes the early 60 to 70 percent raw-parser gate by a wide margin and is worth taking into complete grammar recognition. The result is not a cut-over recommendation. A fuller grammar may add parser cost, and model construction, exact source origins, diagnostics, packaging and complete differential conformance remain unmeasured or incomplete.

The accepted hand-written parser and current formal grammar remain the behavioural references during migration. Issue #148 deliberately advances the production language from grammar revision 1 to revision 2 with derived relations. The experimental Lark parser implements revision 2 across its complete parity boundary. The Tree-sitter feasibility slice now targets revision 2 for the relation forms it recognises, while complete grammar recognition remains Part 3. Differential evaluation must compare like-for-like grammar revisions, and any discrepancy is classified before a parser reference is changed.
