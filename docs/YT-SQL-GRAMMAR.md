# yt-sql formal grammar contract

`YT-SQL-GRAMMAR.ebnf` is the authoritative parser-neutral grammar for yt-sql syntax. It describes the accepted syntactic structure of the language independently of the current recursive-descent parser and independently of any future parser library. Parser-generator notation such as Lark or TatSu grammar syntax is therefore never the language specification merely because an implementation happens to use it.

The grammar has its own monotonic revision number recorded in the EBNF header. Grammar revision 1 was introduced by yt-discover 0.29.15. Grammar revision 2 adds parenthesised derived relations as relation operands in `FROM` and `JOIN`. The grammar revision changes only when accepted yt-sql syntax changes; ordinary Discover implementation, optimiser, backend, diagnostic or semantic changes do not require a grammar revision. A syntax-changing release must update the EBNF, its revision, the conformance coverage and the language reference together. Revision 1 has since received contract corrections discovered by the declarative-parser prototype: `select-query` explicitly requires at least one clause; standalone projection `*` and repeated Boolean `NOT` are represented; and established unit, date, time, relative temporal and infinity literals are represented in their accepted predicate-value positions. These corrections record existing parser behaviour without changing accepted yt-sql syntax, so they do not advance the grammar revision.

## Authority

The EBNF is authoritative for syntactic structure: clause ordering, grouping, operators, delimiters, expression composition and the shapes of accepted constructs. `YT-SQL.md` is authoritative for semantics and for context-sensitive language rules that EBNF cannot usefully express, including name resolution, typing, NULL behaviour, source/facet capabilities, execution support and field-aware interpretation. `YT-SQL-DIAGNOSTICS.md` defines rejection categories and source-location behaviour, while `YT-SQL-FORMATTING.md` defines canonical representation and round-trip guarantees.

If prose and the EBNF disagree about whether a token sequence is syntactically well formed, the EBNF is the specification to correct or implement against. If the disagreement concerns what a well-formed construct means or whether it can execute in a particular context, the semantic prose governs. A discovered disagreement is a defect: authority rules decide how it is reconciled, not permission to leave the documents inconsistent.

The EBNF also retains the established predicate-only compatibility query as an explicit production; omission of `SELECT` in the ordinary query body remains separately defined by the language reference.

The EBNF deliberately uses named lexical terminals for rules whose exact acceptance boundary is clearer in the lexical contract than in a large regular-expression transcription. Unicode XID-style identifiers, quoted identifiers, numeric validation, strings and escapes, temporal token shapes, contextual keywords and malformed-token rejection remain explicitly specified in `YT-SQL.md`. Parameter substitution occurs before parsing and is therefore part of the language boundary but not an AST grammar production.

## Precedence and associativity

The production hierarchy is itself authoritative for precedence. For readability, from loosest to tightest binding, the principal expression layers are:

| Layer | Forms | Associativity |
| --- | --- | --- |
| Boolean OR | `OR` | left |
| Boolean AND | `AND` | left |
| Boolean negation | `NOT` | right/prefix |
| Predicates | comparisons, `BETWEEN`, `IN`, `IS`, text predicates | defined by production |
| Additive scalar | `+`, `-` | left |
| Multiplicative scalar | `*`, `/`, `%` | left |
| Unary scalar | unary `+`, unary `-` | right/prefix |
| Postfix scalar | indexing, member access | left/chained |
| Scalar atom | fields, literals, functions, `CASE`, parenthesised scalar expressions | atomic |

Parentheses may override the ordinary expression hierarchy. Query-expression parentheses additionally create the compound-query boundaries defined in the language and formatting contracts.

## Syntactic recognition and execution support

Grammar acceptance and executable semantics are separate contracts. The formal grammar contains syntax that the parser intentionally recognises even when semantic validation restricts execution. For example, the grammar permits a sequence of accepted `JOIN` clauses, while the current execution contract rejects unsupported multi-way `JOIN` execution deterministically. Such limitations belong in semantic validation and documentation rather than being disguised as parser failures.

Speculative future syntax does not belong in the authoritative grammar. A construct is added only when its syntax has been accepted as part of yt-sql, even if its executable semantics are deliberately staged. Unsupported conventional SQL forms such as `RIGHT JOIN`, `FULL JOIN`, `CROSS JOIN` and `NATURAL JOIN` are not productions merely because the parser recognises their prefixes in order to provide a better diagnostic.

## Verification

No finite test suite can prove complete equivalence between a prose EBNF and an independently implemented parser. The repository instead treats agreement as a maintained conformance obligation. Tests verify representative forms for every major production, malformed near-misses and boundaries, precedence and grouping, canonical parse-format-parse behaviour, and the deterministic rejection surface. The broader conformance and torture corpora exercise combinations that production-by-production tests cannot cover economically.

Any future candidate parser must consume the same language surface and is compared against the same conformance corpus and canonical formatter. Parser differential testing compares accepted/rejected syntax, semantic structure, diagnostic class and source region rather than parser-library-native trees or error messages.
The concrete migration gate and reusable comparison strategy are defined in `YT-SQL-PARSER-EQUIVALENCE.md` and `YT-SQL-PARSER-MIGRATION.md`.

The grammar is maintained directly rather than generating the general user documentation from it. Generation would add machinery without removing the need for semantic explanation. If duplicated syntax documentation later becomes a demonstrated maintenance problem, generation can be reconsidered without changing the EBNF's authority.
