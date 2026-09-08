# yt-sql language reference

yt-sql is the SQL-inspired metadata query language used by `yt-discover`. It is deliberately not a claim of SQL-standard or PostgreSQL compatibility. The language borrows relational query concepts where they map naturally to media discovery and analysis, while retaining domain-specific conveniences such as duration literals, relative dates, `CONTAINS`, `MATCHES`, `LIKE`, and `ILIKE`.

The preferred filename extension for saved query text is `.yt-sql`.

## Current grammar surface

A complete yt-sql query has the following broad form:

```text
[SELECT [DISTINCT] <projection> [, ...]]
[FROM <source>]
[WHERE <expression>]
[ORDER BY <scalar-expression> [ASC|DESC] [, ...]]
[LIMIT <positive integer>]
[OFFSET <non-negative integer>]
```

If `SELECT` is omitted, yt-discover behaves as though `SELECT id` had been requested.

Current predicates include `=`, `!=`, `<>`, `<`, `<=`, `>`, `>=`, `BETWEEN`, `IN`, `IS NULL`, `IS TRUE`, `IS FALSE`, `CONTAINS`, `MATCHES`, `LIKE`, `ILIKE`, Boolean `AND`, `OR`, and `NOT`, and parentheses. yt-sql uses SQL-like three-valued NULL logic for ordinary comparisons.

Scalar expressions are accepted in `SELECT` and `ORDER BY`. Arithmetic operators are `+`, `-`, `*`, `/`, and `%`, with unary `+` and `-`, conventional arithmetic precedence, and parentheses. Arithmetic is numeric and NULL-propagating; division or modulo by zero yields NULL rather than aborting the query. Scalar functions `LOWER`, `UPPER`, `LENGTH`, `COALESCE`, `CHAR`, `NULLIF`, `GREATEST`, and `LEAST` may be nested and may accept scalar expressions as arguments. `CHAR(codepoint [, ...])` constructs text from one or more Unicode scalar values; NULL in any argument yields NULL, and constant surrogate or out-of-range code points are rejected. `NULLIF(a, b)` returns NULL only when `a = b` is TRUE. `GREATEST` and `LEAST` require at least two compatible arguments and return NULL if any argument is NULL; textual extrema use exact normalisation-sensitive Unicode ordering. Projection aliases may be referenced by later `ORDER BY` expressions. Searched `CASE WHEN <predicate> THEN <scalar-expression> ... [ELSE <scalar-expression>] END` is also supported wherever scalar expressions are accepted. CASE conditions use the ordinary yt-sql Boolean predicate language; only TRUE selects a branch, while FALSE and UNKNOWN fall through. If no branch matches and `ELSE` is omitted, the result is NULL.

Date/time helpers include `TODAY()` and `NOW()` together with yt-sql relative date/time syntax. Query parameters use `:name` placeholders bound with repeatable `--param name=value` options.

Examples:

```sql
SELECT id, duration / 60 AS minutes
FROM @example
ORDER BY minutes DESC

SELECT id, (view_count + 10) * 2 AS score
FROM @example
ORDER BY score + 1 DESC

SELECT id, LENGTH(LOWER(title)) AS characters
FROM @example
ORDER BY characters DESC

SELECT id, CASE
    WHEN duration < 10m THEN 'short'
    WHEN duration < 1h THEN 'medium'
    ELSE 'long'
END AS length_class
FROM @example
ORDER BY length_class
```

## Numeric literals

Decimal integers may use underscores between digits for readability, such as `1_000_000`. Integer literals also support hexadecimal (`0x`), octal (`0o`), and binary (`0b`) prefixes. Prefix letters are case-insensitive, and underscores may separate digits in every supported base.

```sql
SELECT 1_000_000
SELECT 0xFF_FF
SELECT 0o755
SELECT 0b1010_0101
SELECT 0x10 + 0o10 + 0b10 + 10
```

Underscores must occur between digits. Leading, trailing, or repeated underscores are rejected. Commas are list and argument separators rather than numeric grouping characters, so write `1_000_000` rather than `1,000,000`. Non-decimal forms are integer-only. Decimal fractional values and the existing decimal `k`, `m`, and `b` count suffixes retain their established semantics.

## Data-driven units

yt-sql unit names are loaded from JSON files in the repository `units/` directory rather than being hard-coded into the parser. All `*.json` files in that directory are loaded into one case-insensitive registry. This allows additional languages and domain-specific units to be added or removed without editing Python code.

Each file declares canonical units and optional aliases. A terminal fixed unit uses `fixed_seconds`; a Gregorian calendar unit uses `calendar_months`; and a derived unit uses a positive `value` plus another `unit`. Derived definitions are resolved recursively until they reach a terminal definition. Unknown references and cycles are errors.

For example:

```json
{
  "format": 1,
  "language": "Cymraeg",
  "units": {
    "dydd": {"aliases": ["dyddiau"], "value": 24, "unit": "awr"},
    "wythnos": {"aliases": ["wythnosau"], "value": 7, "unit": "dydd"}
  }
}
```

The registry validates every canonical name and alias globally. A token may not be reused by another definition, even in another language file. Common short forms can therefore be shared through an already loaded definition rather than redefined. The built-in English file owns `d` as the short form of a day, so both `TODAY()-3d` and Welsh forms such as `TODAY()-8dyddiau` are valid while a second file attempting to redefine `d` is rejected.

Fixed units may be used for durations and relative temporal arithmetic when the resulting type is meaningful. Calendar units may be used for date/time arithmetic but are rejected as media durations. `TODAY()` requires fixed units to resolve to whole days; `NOW()` may use sub-day fixed units. Existing English units use exactly the same registry mechanism as additional language files.

The shipped English definitions also include `decade`, `century`, and `millennium` as calendar-aware units derived from `year`. A separate Maya Long Count file defines exact fixed-day units `kin`, `uinal`, `tun`, `katun`, and `baktun`. In that system a `tun` is 360 days, a `katun` is 7,200 days, and a `baktun` is 144,000 days. Because these definitions ultimately resolve to fixed days, they can be used in both suitable duration expressions and whole-day temporal arithmetic.

## Temporal infinity

`INFINITY()` and `-INFINITY()` provide typed unbounded values for temporal comparisons. The resolver assigns the infinity to the field's temporal type, so date fields receive date infinity and timestamp fields receive timestamp infinity. They are not generic numeric infinities and are rejected for count, duration and other non-temporal fields.

Normal SQL-like NULL semantics still apply. A NULL date or timestamp does not become comparable merely because the other operand is infinite. Use `IS NULL` or `IS NOT NULL` when NULL membership matters.

Examples:

```sql
WHERE upload_date BETWEEN -INFINITY() AND INFINITY()
WHERE release_timestamp < INFINITY()
WHERE upload_date >= TODAY()-1decade
WHERE upload_date >= TODAY()-1baktun
```

### Pattern matching

`LIKE` and `ILIKE` provide SQL-like wildcard matching over text fields. `LIKE` is case-sensitive and `ILIKE` is case-insensitive. `%` matches zero or more Unicode code points and `_` matches exactly one Unicode code point. Both wildcards can span newline characters.

A backslash quotes the following pattern character, so `\%`, `\_` and `\\` match literal percent, underscore and backslash characters respectively. A trailing unmatched backslash is rejected as invalid syntax rather than silently reinterpreted.

`NOT LIKE` and `NOT ILIKE` negate the corresponding match result. NULL input remains UNKNOWN before negation, preserving ordinary yt-sql three-valued logic. Patterns are quoted text literals.

Examples:

```sql
WHERE title LIKE 'Mars%'
WHERE title ILIKE '%quantum%'
WHERE title NOT LIKE '%live_'
WHERE title LIKE '100\%'
```

`MATCHES` remains the regular-expression predicate and uses Python regular-expression search semantics. It is not automatically interchangeable with LIKE syntax: anchoring, `.` versus `_`, `.*` versus `%`, newline behaviour, regex flags and case semantics must all be equivalent before any optimiser rewrite could be valid.

## Unicode text semantics

yt-sql treats metadata text as Unicode strings and does not perform implicit Unicode normalisation. Canonically equivalent composed and decomposed strings therefore remain distinct for equality, ordering, LIKE and regular-expression matching unless the operation itself defines case-insensitive behaviour. This preserves the extractor-provided text exactly rather than silently rewriting metadata.

`LENGTH` counts Unicode code points, not user-perceived grapheme clusters. A precomposed `é` contributes one code point, while `e` followed by U+0301 COMBINING ACUTE ACCENT contributes two. Emoji ZWJ sequences, regional-indicator flags and variation-selector sequences likewise contain multiple code points even when displayed as one glyph.

`LOWER` and `UPPER` use Unicode string case mappings and may change string length. `CONTAINS` compares Unicode `casefold()` forms, which deliberately provides stronger caseless matching than simple lowercasing. `ILIKE` uses Unicode-aware case-insensitive regular-expression matching over the LIKE translation. These mechanisms are not identical for every Unicode character, so optimiser rewrites must not substitute one for another without a proven equivalence.

ASCII `%`, `_` and backslash retain their LIKE meanings. Visually similar fullwidth or other Unicode characters are ordinary literals. Ordering compares the unmodified Unicode string values using the runtime's deterministic string ordering. JSON and other Unicode-capable outputs preserve the original text.

## Query optimiser

yt-sql resolves a query's schema and typed literals before running a dedicated predicate optimiser. The optimiser is deliberately semantics-preserving: executing the resolved query before optimisation and executing the optimised query must produce identical predicate truth values, selected rows and output. This includes SQL-like three-valued NULL behaviour, so an expression that evaluates to UNKNOWN for a NULL value must not be rewritten into one that evaluates to FALSE merely because both would currently be rejected by `WHERE`.

The optimiser performs conservative reductions that make later language growth easier to reason about. Predicate subtrees embedded in searched CASE conditions are optimised with the same fixed-point rules as top-level WHERE predicates:

- normalise `NOT` around comparisons and negatable predicates, including double negation;
- remove duplicate `AND` and `OR` terms while ignoring non-semantic source-position metadata;
- collapse `BETWEEN x AND x` to equality and its negated form to inequality;
- remove subsumed lower or upper bounds on the same resolved field;
- remove a redundant bound when a same-field equality already implies it, or remove the equality from an `OR` when the surviving bound already includes it.

Optimisation runs to a deterministic fixed point and records every rewrite. `--explain` reports the applied rules and resulting filter when all referenced fields can be resolved before acquisition. JSON explain output exposes the same information under `predicate_optimiser`; dynamic metadata fields defer this part of explanation until post-acquisition type resolution. Verbose execution also reports applied rewrites.

Discover 0.23.2 also performs conservative scalar constant folding after type resolution. Fully literal arithmetic, unary expressions and deterministic scalar-function calls are evaluated once and replaced with a literal. Symbolic field algebra is deliberately excluded, so `19 * 2 * 100 * 0` folds to `0` while `view_count * 0` remains unchanged because a NULL field must still produce NULL.

The optimiser intentionally does not fold contradictory field predicates to a Boolean constant yet. For example, `field = 5 AND field > 10` still evaluates to UNKNOWN rather than FALSE when `field` is NULL, and that distinction is part of yt-sql semantics even though both values are rejected by a `WHERE` filter. Future optimiser passes must preserve the same invariant.

`YT-SQL-OPTIMISATION.md` is the living optimisation reference. It records the current and prospective strategy for each language feature, including transformations that are deliberately not implemented because their equivalence has not been proved.

## Intentional dialect behaviour

yt-sql includes syntax that is useful for media metadata but is not intended to be portable SQL. Examples include duration literals such as `1h`, readable comparison aliases, `CONTAINS`, `MATCHES`, `LIKE`, `ILIKE`, relative calendar expressions, and source forms such as `@handle`.

`JOIN` is out of scope by design. yt-discover queries media-source metadata rather than exposing its internal persistence tables as a relational database. Multi-source composition uses CTEs plus positional `UNION`/`UNION ALL`; it does not expose implementation tables or relational join semantics.

Database mutation and administration statements such as `INSERT`, `UPDATE`, `DELETE`, `CREATE`, `ALTER`, transactions, indexes, triggers, stored procedures, and database permissions are also outside the purpose of yt-sql.

## Conformance suite

The executable semantics of yt-sql are guarded by the conformance architecture under `yt_discover_tests/conformance/`. Test datasets are generated ephemerally rather than committed as canonical output blobs. Four deterministic profiles, `small`, `normal`, `large`, and `huge`, provide increasing scales, and tests may request an exact custom record count when needed. For a fixed generator version, seed, and size, the logical dataset is reproducible; smaller datasets are exact prefixes of larger datasets for the same version and seed.

Routine development and pull-request CI deliberately use only `small` and `normal`. Selected correctness checks that genuinely depend on higher cardinality are marked `scale` and use `large`; torture and scalability checks are marked `stress` and may use `huge`. The default pytest configuration excludes both markers. Run them explicitly with `python -m pytest -m scale`, `python -m pytest -m stress`, or `python -m pytest -m "scale or stress"`.

The harness generates the requested dataset and real SQLite cache at test time and visibly reports profile generation progress. Routine semantic cases compare the independent Python oracle with the production parser, resolver, evaluator and serializer in-process so broad language coverage remains fast. A representative subset is also run through the real offline `yt-discover` CLI to verify end-to-end parity, including CLI-only behaviour such as parameter binding. Pytest removes the temporary corpus after the session.

The generated corpus deliberately includes same-day uploads, identical and NULL timestamps, exact duration boundaries, duplicate values, case variants, adversarial Unicode text, regex metacharacters, large counts, availability and live-state values, dynamic scalar metadata, stable source ordering, repeated categorical values, and multiple synthetic channel identities. Unicode anchors include composed and decomposed text, combining marks, supplementary-plane characters, emoji and ZWJ sequences, case-mapping edge cases, non-Latin scripts, bidirectional marks, unusual whitespace and line separators. These deliberately designed records are semantic anchors inside the deterministic generator, not a separately maintained golden dataset. Expected query semantics come from the independently authored Python oracle rather than generated snapshots or production code.

An explicit conformance feature manifest records the current language surface and requires every registered feature to have deterministic semantic coverage. New yt-sql syntax must add independent oracle coverage, boundary cases, malformed-input coverage where relevant, and cross-feature interactions as part of its implementation. Larger profiles should be used only where scale is relevant to the behaviour under test.

## Aggregate queries

yt-sql supports `COUNT(*)`, `COUNT(expr)`, `SUM(expr)`, `AVG(expr)`, `MIN(expr)`, and `MAX(expr)`. `COUNT(expr)` ignores NULL and returns zero when no non-NULL value exists. `SUM`, `AVG`, `MIN`, and `MAX` ignore NULL and return NULL when no non-NULL input remains. `SUM` and `AVG` require numeric expressions; `MIN` and `MAX` use the ordinary resolved scalar ordering, including exact normalisation-sensitive Unicode ordering for text.

`GROUP BY` accepts non-aggregate scalar expressions. NULL keys group together, text keys are not normalised or case-folded, and groups retain first-source-occurrence order unless an explicit `ORDER BY` is present. Non-aggregate projected or ordered expressions in an aggregate query must match a grouping expression. Nested aggregates and `SELECT *` in aggregate queries are rejected.

`HAVING` provides aggregate-aware comparisons after grouping, including explicit SELECT aggregate aliases, Boolean `AND`/`OR`/`NOT`, parentheses, and `IS NULL`/`IS NOT NULL`. Aggregate `FILTER (WHERE predicate)` uses the ordinary row-predicate language and applies only to its aggregate after the query-level WHERE filter.

The first aggregate release does not implement `COUNT(DISTINCT expr)` or other DISTINCT aggregate arguments. Those may be considered separately if they fit the language cleanly. Aggregate queries require complete input groups, so the source-order early-LIMIT acquisition optimisation is disabled for them.

## Planned analytical expansion

General scalar expressions, arithmetic, nested scalar functions, expression-based ordering, searched `CASE`, Unicode `CHAR()` construction, decimal/hexadecimal/octal/binary integer literals, deterministic `SELECT *`, and the first aggregate query architecture are implemented. Integer digit grouping uses underscores, for example `1_000_000`, `0xFF_FF`, `0o755`, and `0b1010_0101`; comma-grouped numbers are not supported. Different integer bases may be mixed freely inside scalar arithmetic. Later expression work may add useful date extraction functions. Explicit NULL ordering and PostgreSQL-inspired `DISTINCT ON` remain later analytical work.

## Common table expressions

Non-recursive common table expressions use SQL-like `WITH name AS (query)` syntax:

```sql
WITH short AS (
    SELECT id, title, duration / 60 AS minutes
    FROM @example
    WHERE duration < 1h
),
mars AS (
    SELECT id, minutes
    FROM short
    WHERE title ILIKE '%mars%'
)
SELECT id, minutes
FROM mars
ORDER BY minutes DESC
```

A CTE exports only its projected columns. Their output names, including explicit `AS` aliases, and their resolved scalar kinds define the logical schema available to subsequent CTEs and the outer query. CTE names are case-insensitive. Later CTEs may reference earlier CTEs, but forward references, self-reference, `WITH RECURSIVE` and nested `WITH` clauses are rejected.

Discover 0.25.1 permits CTEs to contain positional `UNION` and `UNION ALL` expressions, including branches backed by different physical extractor sources. Each branch is resolved against its own physical-source schema before result-column reconciliation.


## Set composition

`UNION` and `UNION ALL` combine query results by column position:

```sql
SELECT id, title FROM @channel_a
UNION ALL
SELECT id, title FROM @playlist_b
ORDER BY title
LIMIT 50
```

All branches must project the same number of columns. The first branch defines the exported column names. Later aliases do not rename the set result. Compatible numeric kinds may reconcile to a common numeric kind; incompatible kinds are rejected. Plain `UNION` removes duplicate projected rows using exact yt-sql scalar values, including normalisation-sensitive Unicode strings. `UNION ALL` retains duplicates and branch order.

`ORDER BY`, `OFFSET` and `LIMIT` written after the final branch apply to the complete composed result. Branch-local ordering and limiting are not a separate grammar surface in this release. Set composition disables source-order early LIMIT acquisition because every contributing branch can affect the final result.

Physical sources are acquired independently. In automatic source mode, a quoted non-YouTube URL is preserved as a generic yt-dlp extractor source, while YouTube handles, channel URLs and playlist URLs retain their existing specialised classification. Source identity remains attached internally through normalisation so each branch sees only the records belonging to its declared `FROM` source. A missing value from one extractor is NULL when the field is otherwise part of the logical schema. Dynamic fields are resolved per physical source so incompatible extractor-specific types are detected before composition.

`JOIN` remains intentionally unsupported. yt-sql uses set composition and CTEs rather than relational join semantics.
