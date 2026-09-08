# TODO

This file records accepted future work that is not part of the current released behaviour. Items should be removed or rewritten when they are implemented rather than retained as historical release notes.

## yt-sql language and optimiser

- Extend the generic optimiser as the expression language grows. Keep every rewrite semantics-preserving under yt-sql's SQL-like three-valued NULL logic, typed temporal infinity values, deterministic ordering and parameter semantics. Differential tests must execute both the unoptimised and optimised resolved queries against the same deterministic data and require identical results.
- Extend scalar constant folding and predicate simplification only where each transformation can be justified conservatively. Redundant-bound elimination is implemented. Continue investigating temporal-bound inference, field and capability analysis, source-boundary planning and metadata-acquisition planning. Expose material optimisation decisions through explain and diagnostic output.
- Maintain `YT-SQL-OPTIMISATION.md` as the living per-feature optimisation strategy, documenting implemented rewrites, deliberately rejected transformations and plausible future strategies as the language grows.
- Investigate, but do not assume the value of, a versioned compiled or short-form yt-sql representation that could avoid repeated parsing and resolution overhead. Compare serialised resolved AST, compact IR/bytecode and canonical query-plan caching approaches, including compatibility, security, portability, cache invalidation and explainability.
- Freeze new syntactic sugar after the `OF` source/facet series through 0.26.2. Do not add further grammar features until the post-0.26.2 completeness review has finished.
- After 0.26.2, conduct a full test-completeness review before considering more language syntax. Add brutal parser torture suites covering deeply nested expressions, hostile whitespace, malformed clauses, keyword ambiguity, Unicode boundaries, comments or unsupported tokens where relevant, CTE/UNION composition, precedence, numeric literal forms, temporal literals, aggregate syntax and deterministic error locations.
- After that completeness review, survey useful ideas from established SQL dialects and genuinely new Discover-specific language features. Treat every candidate as a fresh design decision rather than assuming SQL familiarity makes it appropriate. Existing deferred candidates include useful date extraction functions, aggregate DISTINCT arguments, `NULLS FIRST`/`NULLS LAST` and `DISTINCT ON`.
- Preserve the explicit non-goal of relational joins. Do not add `JOIN`, DML, DDL, transactions, indexes, procedures or triggers merely for SQL familiarity when they do not fit Discover's acquisition/query model.
- Extend the deterministic multi-source fixtures as new source/facet and composition features arrive. The current suite covers channel-like, playlist-like and Twitch-like source shapes with missing metadata, NULLs, incompatible dynamic kinds, Unicode, duplicate elimination, aggregation and composition boundaries; reserve broad large/huge cross-source coverage for explicit scale or stress testing rather than routine CI.

## Source collections and extractor independence

- Complete the extractor-agnostic source/facet series with the 0.26.2 composition and identity hardening pass. `OF` is the selected syntax; 0.26.1 separates classification, capability discovery and facet mapping without adding further grammar.
- Expand deterministic capability discovery beyond the YouTube channel adapter only where yt-dlp extractors expose meaningful stable collections. Unsupported facets must continue to fail clearly rather than being silently ignored, substituted or interpreted as a different source.
- Extend cache/source identity so two facets of the same physical source cannot contaminate one another's completeness, frontier or detailed-metadata assumptions.
- Remove the temporary same-source/multiple-facet composition rejection once cache identity, per-facet schemas, source tagging, provenance and UNION reconciliation are all independently safe.
- Add brutal heterogeneous composition coverage for CTEs and UNION across distinct extractors, same-source different facets, missing metadata, incompatible dynamic kinds, Unicode identities, RANDOM ordering, aggregates and global LIMIT/OFFSET ordering boundaries.

## Query usability

- Add saved queries.
- Add query-file execution for `.yt-sql` files.
- Add persistent configuration where it reduces repetitive CLI options without making query behaviour implicit or difficult to reproduce.
- Add shell completion for stable CLI and yt-sql surfaces where practical.

## yt-downloader parameter profiles

- Add JSON-based named parameter profiles for ordinary downloader CLI options, kept conceptually separate from output profiles unless a later design deliberately unifies them. Explicit CLI arguments must take precedence over profile values.
- Add `--list-parameters` to list available named parameter profiles.
- Add safe profile generation/export that refuses to overwrite an existing profile name unless the user gives explicit overwrite intent. Do not add a profile-removal command; direct JSON editing remains sufficient for deletion.
