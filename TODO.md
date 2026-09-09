# TODO

This file records accepted future work that is not part of the current released behaviour. Items should be removed or rewritten when they are implemented rather than retained as historical release notes.

## yt-sql language and optimiser

- Extend the generic optimiser as the expression language grows. Keep every rewrite semantics-preserving under yt-sql's SQL-like three-valued NULL logic, typed temporal infinity values, deterministic ordering and parameter semantics. Differential tests must execute both the unoptimised and optimised resolved queries against the same deterministic data and require identical results.
- Extend scalar constant folding and predicate simplification only where each transformation can be justified conservatively. Redundant-bound elimination is implemented. Continue investigating temporal-bound inference, field and capability analysis, source-boundary planning and metadata-acquisition planning. Expose material optimisation decisions through explain and diagnostic output.
- Maintain `YT-SQL-OPTIMISATION.md` as the living per-feature optimisation strategy, documenting implemented rewrites, deliberately rejected transformations and plausible future strategies as the language grows.
- Investigate, but do not assume the value of, a versioned compiled or short-form yt-sql representation that could avoid repeated parsing and resolution overhead. Compare serialised resolved AST, compact IR/bytecode and canonical query-plan caching approaches, including compatibility, security, portability, cache invalidation and explainability.
- Evaluate future syntax only against the accepted coverage inventory and optimiser safety contracts. New language work must add independent semantic coverage, malformed/boundary cases, composition tests and optimiser differential checks where applicable rather than weakening the established baseline.
- Preserve and extend the torture selection covering deeply nested expressions, hostile whitespace, malformed clauses, keyword ambiguity, Unicode boundaries, comments or unsupported tokens where relevant, CTE/UNION composition, source/facet identity, RANDOM semantics, NULL/three-valued logic, precedence, numeric literal forms, temporal literals, aggregate syntax, deterministic error locations and optimised-versus-unoptimised equivalence.
- After the completeness review, survey useful ideas from established SQL dialects and genuinely new Discover-specific language features. Treat every candidate as a fresh design decision rather than assuming SQL familiarity makes it appropriate. Existing deferred candidates include useful date extraction functions, aggregate DISTINCT arguments, `NULLS FIRST`/`NULLS LAST` and `DISTINCT ON`.
- Preserve the explicit non-goal of relational joins. Do not add `JOIN`, DML, DDL, transactions, indexes, procedures or triggers merely for SQL familiarity when they do not fit Discover's acquisition/query model.
- Extend the deterministic multi-source fixtures as new source/facet and composition features arrive. The current suite covers channel-like, playlist-like and Twitch-like source shapes with missing metadata, NULLs, incompatible dynamic kinds, Unicode, duplicate elimination, aggregation and composition boundaries; reserve broad large/huge cross-source coverage for explicit scale or stress testing rather than routine CI.

## Source collections and extractor independence

- Keep the completed `OF` source/facet architecture conservative as new extractor adapters are considered. Source/facet identity, per-facet schemas, provenance and cache isolation are now established invariants and must not regress.
- Expand deterministic capability discovery beyond the YouTube channel adapter only where yt-dlp extractors expose meaningful stable collections. Unsupported facets must continue to fail clearly rather than being silently ignored, substituted or interpreted as a different source.

## Query usability

- Add saved queries.
- Add query-file execution for `.yt-sql` files.
- Add persistent configuration where it reduces repetitive CLI options without making query behaviour implicit or difficult to reproduce.
- Add shell completion for stable CLI and yt-sql surfaces where practical.
