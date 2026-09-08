# TODO

This file records accepted future work that is not part of the current released behaviour. Items should be removed or rewritten when they are implemented rather than retained as historical release notes.

## yt-sql language and optimiser

- Extend the generic optimiser as the expression language grows. Keep every rewrite semantics-preserving under yt-sql's SQL-like three-valued NULL logic, typed temporal infinity values, deterministic ordering and parameter semantics. Differential tests must execute both the unoptimised and optimised resolved queries against the same deterministic data and require identical results.
- Extend scalar constant folding and predicate simplification only where each transformation can be justified conservatively. Redundant-bound elimination is implemented. Continue investigating temporal-bound inference, field and capability analysis, source-boundary planning and metadata-acquisition planning. Expose material optimisation decisions through explain and diagnostic output.
- Maintain `YT-SQL-OPTIMISATION.md` as the living per-feature optimisation strategy, documenting implemented rewrites, deliberately rejected transformations and plausible future strategies as the language grows.
- Investigate, but do not assume the value of, a versioned compiled or short-form yt-sql representation that could avoid repeated parsing and resolution overhead. Compare serialised resolved AST, compact IR/bytecode and canonical query-plan caching approaches, including compatibility, security, portability, cache invalidation and explainability.
- Add `CHAR()` in the next scalar-language dot release with Unicode scalar-value validation, explicit NULL and arity semantics, constant folding and exhaustive Unicode conformance coverage.
- Add hexadecimal, octal and binary integer literals in the following dot release, including mixed-base arithmetic and exhaustive parser, optimiser and conformance coverage. Decide digit-separator syntax explicitly rather than introducing it accidentally.
- Continue the scalar-expression expansion afterwards with `GREATEST`, `LEAST`, `NULLIF`, useful date extraction functions, and a deliberately defined `SELECT *` contract. General arithmetic, nested scalar functions, expression-based `ORDER BY`, and searched `CASE` are implemented.
- Add aggregate query support in a coherent tranche, including `COUNT`, `MIN`, `MAX`, `AVG`, `SUM`, `GROUP BY`, `HAVING` and aggregate `FILTER`, with comprehensive deterministic conformance and negative coverage.
- Consider `NULLS FIRST`/`NULLS LAST` and `DISTINCT ON` after the general expression and aggregate foundations are stable.
- Later investigate multiple sources, `WITH`/CTEs and `UNION`/`UNION ALL`. Do not add relational database features such as `JOIN`, DML, DDL, transactions, indexes, procedures or triggers merely for SQL familiarity when they do not fit Discover's acquisition/query model.

## Source collections and extractor independence

- Replace the CLI-specific `--tab` concept with a natural yt-sql source/collection/facet model. Do not encode YouTube-specific syntax such as `TAB videos` into the language.
- Model source selection generically as source -> logical collection or facet -> extractor adapter. The query should request a logical collection as part of source resolution, while the active adapter maps that request onto capabilities exposed by the underlying service or extractor.
- Keep the model extractor-agnostic. YouTube may expose collections such as videos, shorts or live, but other yt-dlp extractors may expose different collections or none at all. The grammar and core planner must not assume YouTube's channel-tab model.
- Add deterministic capability discovery and validation. Unsupported collections must produce clear errors rather than being silently ignored, substituted or interpreted as a different source.
- Select the final yt-sql spelling only after checking that it composes cleanly with the existing `@source` syntax and future multiple-source, CTE and `UNION` work. Candidate shapes include qualified source references and table-function-like source expressions, but none is selected yet.
- Retain `--tab` as a compatibility CLI mapping during a practical migration period if doing so does not require a separate execution path. Both old and new surfaces should resolve through the same internal collection/facet representation.

## Query usability

- Add saved queries.
- Add query-file execution for `.yt-sql` files.
- Add persistent configuration where it reduces repetitive CLI options without making query behaviour implicit or difficult to reproduce.
- Add shell completion for stable CLI and yt-sql surfaces where practical.
