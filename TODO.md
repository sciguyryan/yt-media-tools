# TODO

This file records accepted future work that is not part of the current released behaviour. Items should be removed or rewritten when they are implemented rather than retained as historical release notes.

## yt-sql language and optimiser

- Extend the generic optimiser as the expression language grows. Keep every rewrite semantics-preserving under yt-sql's SQL-like three-valued NULL logic, typed temporal infinity values, deterministic ordering and parameter semantics. Differential tests must execute both the unoptimised and optimised resolved queries against the same deterministic data and require identical results.
- Add constant folding, Boolean and predicate simplification, redundant-bound elimination, temporal-bound inference, field and capability analysis, source-boundary planning and metadata-acquisition planning where each transformation can be justified conservatively. Expose material optimisation decisions through explain and diagnostic output.
- Expand scalar expressions and projection syntax, including `SELECT *`, arithmetic, expression-based `ORDER BY`, `CASE`, `LIKE`/`NOT LIKE`, `ILIKE`/`NOT ILIKE`, `GREATEST`, `LEAST`, `NULLIF`, and useful date extraction functions where they fit yt-sql cleanly.
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
