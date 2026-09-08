# yt-sql language reference

yt-sql is the SQL-inspired metadata query language used by `yt-discover`. It is deliberately not a claim of SQL-standard or PostgreSQL compatibility. The language borrows relational query concepts where they map naturally to media discovery and analysis, while retaining domain-specific conveniences such as duration literals, relative dates, `CONTAINS`, and `MATCHES`.

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

Current predicates include `=`, `!=`, `<>`, `<`, `<=`, `>`, `>=`, `BETWEEN`, `IN`, `IS NULL`, `IS TRUE`, `IS FALSE`, `CONTAINS`, `MATCHES`, Boolean `AND`, `OR`, and `NOT`, and parentheses. yt-sql uses SQL-like three-valued NULL logic for ordinary comparisons.

Scalar expressions are accepted in `SELECT` and `ORDER BY`. Arithmetic operators are `+`, `-`, `*`, `/`, and `%`, with unary `+` and `-`, conventional arithmetic precedence, and parentheses. Arithmetic is numeric and NULL-propagating; division or modulo by zero yields NULL rather than aborting the query. Existing projection functions `LOWER`, `UPPER`, `LENGTH`, and `COALESCE` may be nested and may accept scalar expressions as arguments. Projection aliases may be referenced by later `ORDER BY` expressions. Searched `CASE WHEN <predicate> THEN <scalar-expression> ... [ELSE <scalar-expression>] END` is also supported wherever scalar expressions are accepted. CASE conditions use the ordinary yt-sql Boolean predicate language; only TRUE selects a branch, while FALSE and UNKNOWN fall through. If no branch matches and `ELSE` is omitted, the result is NULL.

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

## Predicate optimiser

yt-sql resolves a query's schema and typed literals before running a dedicated predicate optimiser. The optimiser is deliberately semantics-preserving: executing the resolved query before optimisation and executing the optimised query must produce identical predicate truth values, selected rows and output. This includes SQL-like three-valued NULL behaviour, so an expression that evaluates to UNKNOWN for a NULL value must not be rewritten into one that evaluates to FALSE merely because both would currently be rejected by `WHERE`.

The optimiser performs conservative reductions that make later language growth easier to reason about. Predicate subtrees embedded in searched CASE conditions are optimised with the same fixed-point rules as top-level WHERE predicates:

- normalise `NOT` around comparisons and negatable predicates, including double negation;
- remove duplicate `AND` and `OR` terms while ignoring non-semantic source-position metadata;
- collapse `BETWEEN x AND x` to equality and its negated form to inequality;
- remove subsumed lower or upper bounds on the same resolved field;
- remove a redundant bound when a same-field equality already implies it, or remove the equality from an `OR` when the surviving bound already includes it.

Optimisation runs to a deterministic fixed point and records every rewrite. `--explain` reports the applied rules and resulting filter when all referenced fields can be resolved before acquisition. JSON explain output exposes the same information under `predicate_optimiser`; dynamic metadata fields defer this part of explanation until post-acquisition type resolution. Verbose execution also reports applied rewrites.

The optimiser intentionally does not fold contradictory field predicates to a Boolean constant yet. For example, `field = 5 AND field > 10` still evaluates to UNKNOWN rather than FALSE when `field` is NULL, and that distinction is part of yt-sql semantics even though both values are rejected by a `WHERE` filter. Future optimiser passes must preserve the same invariant.

## Intentional dialect behaviour

yt-sql includes syntax that is useful for media metadata but is not intended to be portable SQL. Examples include duration literals such as `1h`, readable comparison aliases, `CONTAINS`, `MATCHES`, relative calendar expressions, and source forms such as `@handle`.

`JOIN` is out of scope by design. yt-discover queries media-source metadata rather than exposing its internal persistence tables as a relational database. If multi-source composition is added later, it should use a domain-appropriate abstraction rather than forcing users to join implementation tables.

Database mutation and administration statements such as `INSERT`, `UPDATE`, `DELETE`, `CREATE`, `ALTER`, transactions, indexes, triggers, stored procedures, and database permissions are also outside the purpose of yt-sql.

## Conformance suite

The executable semantics of yt-sql are guarded by the conformance architecture under `yt_discover_tests/conformance/`. Test datasets are generated ephemerally rather than committed as canonical output blobs. Four deterministic profiles, `small`, `normal`, `large`, and `huge`, provide increasing scales, and tests may request an exact custom record count when needed. For a fixed generator version, seed, and size, the logical dataset is reproducible; smaller datasets are exact prefixes of larger datasets for the same version and seed.

Routine development and pull-request CI deliberately use only `small` and `normal`. Selected correctness checks that genuinely depend on higher cardinality are marked `scale` and use `large`; torture and scalability checks are marked `stress` and may use `huge`. The default pytest configuration excludes both markers. Run them explicitly with `python -m pytest -m scale`, `python -m pytest -m stress`, or `python -m pytest -m "scale or stress"`.

The harness generates the requested dataset and real SQLite cache at test time and visibly reports profile generation progress. Routine semantic cases compare the independent Python oracle with the production parser, resolver, evaluator and serializer in-process so broad language coverage remains fast. A representative subset is also run through the real offline `yt-discover` CLI to verify end-to-end parity, including CLI-only behaviour such as parameter binding. Pytest removes the temporary corpus after the session.

The generated corpus deliberately includes same-day uploads, identical and NULL timestamps, exact duration boundaries, duplicate values, case variants, Unicode, regex metacharacters, large counts, availability and live-state values, dynamic scalar metadata, stable source ordering, repeated categorical values, and multiple synthetic channel identities. These deliberately designed records are semantic anchors inside the deterministic generator, not a separately maintained golden dataset. Expected query semantics come from the independently authored Python oracle rather than generated snapshots or production code.

An explicit conformance feature manifest records the current language surface and requires every registered feature to have deterministic semantic coverage. New yt-sql syntax must add independent oracle coverage, boundary cases, malformed-input coverage where relevant, and cross-feature interactions as part of its implementation. Larger profiles should be used only where scale is relevant to the behaviour under test.

## Planned analytical expansion

General scalar expressions, arithmetic, nested scalar functions, expression-based ordering, and searched `CASE` are now part of the language. The next expression work is expected to evaluate and, where appropriate, add `LIKE`/`NOT LIKE`, `ILIKE`/`NOT ILIKE`, `GREATEST`, `LEAST`, `NULLIF`, useful date extraction functions, and a deliberately defined `SELECT *` contract. Aggregates, `GROUP BY`, `HAVING`, aggregate `FILTER`, explicit NULL ordering, and PostgreSQL-inspired `DISTINCT ON` remain later analytical work.
