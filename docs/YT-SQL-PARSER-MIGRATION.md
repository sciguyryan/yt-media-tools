# yt-sql parser migration conclusion

The hand-written parser remains the production yt-sql implementation and behavioural reference. The Lark and Tree-sitter replacement experiments are concluded, neither candidate will proceed to production integration, and their implementation-specific code and tooling have been removed.

This decision is based on the complete evaluation surface rather than parser throughput alone. A replacement must preserve accepted and malformed syntax, normalised query models, user-written source origins, parser-independent diagnostics and canonical formatting. It must also justify its operational and maintenance costs across ordinary, malformed and bounded pathological inputs. The reusable contract is defined in `YT-SQL-PARSER-EQUIVALENCE.md`.

## Evaluation evidence

Both candidates were exercised against the established migration and conformance corpora, grammar-anchored generation, controlled malformed neighbours, fixed seeded fuzz inputs and canonical parse-format-parse checks. The final bounded inventories covered more than 200 accepted queries, the curated malformed corpus, 39 generated malformed neighbours and more than 800 deterministic fuzz executions. Material differences were investigated rather than hidden through compatibility normalisation.

Lark reached bounded behavioural conformance after moving from Earley parsing to a conflict-free LALR grammar with contextual lexing. Complete model construction nevertheless remained approximately 3.5 to 5.4 times slower than the hand-written parser on representative queries. Raw Lark tree construction alone exceeded the complete reference-parser cost, leaving no credible optimisation route that also preserved exact source origins.

Tree-sitter also reached bounded conformance and its raw parser was substantially faster than the reference implementation. After model-builder optimisation, its complete path was approximately 4 to 24 percent faster across the simple, complex, collection and derived representative workloads. That advantage did not remain consistent across the wider decision surface:

- accepted expressions at bounded parenthesis depths were approximately 14 to 21 percent slower;
- malformed nested inputs were approximately 30 to 68 percent slower;
- traced Python allocation growth was materially higher with nesting;
- a missing parenthesis before `FROM` retained a diagnostic-span compatibility difference outside the bounded differential inventory; and
- maintained source was reduced by only approximately 3 to 5 percent once the adapter, model builder and declarative grammar were counted and generated C was excluded.

Tree-sitter therefore met the representative throughput target but did not provide the same consistency as the hand-written parser across performance, allocation, diagnostics and maintenance.

## Durable outcomes

The experiments materially strengthened yt-sql even though neither candidate was selected. The project retains:

- the authoritative parser-neutral EBNF and grammar-revision contract;
- parser-independent model, source-origin and diagnostic normalisation;
- the reusable differential harness and explicit difference classification;
- accepted and malformed migration corpora;
- grammar-derived generation, controlled mutation and deterministic fuzz inputs;
- canonical round-trip and idempotence checks;
- regression coverage for comments, mixed-base row slicing, derived relations and the maximal revision-2 composition query; and
- production-parser benchmarks for representative, malformed, nested and traced-allocation workloads.

These assets remain available for language hardening and for any future parser proposal. A later proposal would start from this evidence and must demonstrate a material overall advantage rather than reopening either concluded implementation by default.
