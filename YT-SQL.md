# yt-sql language reference

yt-sql is the SQL-inspired metadata query language used by `yt-discover`. It is deliberately not a claim of SQL-standard or PostgreSQL compatibility. The language borrows relational query concepts where they map naturally to media discovery and analysis, while retaining domain-specific conveniences such as duration literals, relative dates, `CONTAINS`, and `MATCHES`.

The preferred filename extension for saved query text is `.yt-sql`.

## Current grammar surface

A complete yt-sql query has the following broad form:

```text
[SELECT [DISTINCT] <projection> [, ...]]
[FROM <source>]
[WHERE <expression>]
[ORDER BY <field-or-projection-alias> [ASC|DESC] [, ...]]
[LIMIT <positive integer>]
[OFFSET <non-negative integer>]
```

If `SELECT` is omitted, yt-discover behaves as though `SELECT id` had been requested.

Current predicates include `=`, `!=`, `<>`, `<`, `<=`, `>`, `>=`, `BETWEEN`, `IN`, `IS NULL`, `IS TRUE`, `IS FALSE`, `CONTAINS`, `MATCHES`, Boolean `AND`, `OR`, and `NOT`, and parentheses. yt-sql uses SQL-like three-valued NULL logic for ordinary comparisons.

Current projection functions are `LOWER`, `UPPER`, `LENGTH`, and `COALESCE`. Date/time helpers include `TODAY()` and `NOW()` together with yt-sql relative date/time syntax. Query parameters use `:name` placeholders bound with repeatable `--param name=value` options.

## Intentional dialect behaviour

yt-sql includes syntax that is useful for media metadata but is not intended to be portable SQL. Examples include duration literals such as `1h`, readable comparison aliases, `CONTAINS`, `MATCHES`, relative calendar expressions, and source forms such as `@handle`.

`JOIN` is out of scope by design. yt-discover queries media-source metadata rather than exposing its internal persistence tables as a relational database. If multi-source composition is added later, it should use a domain-appropriate abstraction rather than forcing users to join implementation tables.

Database mutation and administration statements such as `INSERT`, `UPDATE`, `DELETE`, `CREATE`, `ALTER`, transactions, indexes, triggers, stored procedures, and database permissions are also outside the purpose of yt-sql.

## Conformance suite

The executable semantics of yt-sql are guarded by the conformance architecture under `yt_discover_tests/conformance/`. Test datasets are generated ephemerally rather than committed as canonical output blobs. Four deterministic profiles, `small`, `normal`, `large`, and `huge`, provide increasing scales, and tests may request an exact custom record count when needed. For a fixed generator version, seed, and size, the logical dataset is reproducible; smaller datasets are exact prefixes of larger datasets for the same version and seed.

Routine development and pull-request CI deliberately use only `small` and `normal`. Selected correctness checks that genuinely depend on higher cardinality are marked `scale` and use `large`; torture and scalability checks are marked `stress` and may use `huge`. The default pytest configuration excludes both markers. Run them explicitly with `python -m pytest -m scale`, `python -m pytest -m stress`, or `python -m pytest -m "scale or stress"`.

The harness generates the requested dataset and real SQLite cache at test time, visibly reports profile generation progress, evaluates the Python oracle, runs the equivalent yt-sql through the real `yt-discover` CLI in offline mode, compares the complete serialised results, and allows pytest to remove the temporary corpus after the session.

The generated corpus deliberately includes same-day uploads, identical and NULL timestamps, exact duration boundaries, duplicate values, case variants, Unicode, regex metacharacters, large counts, availability and live-state values, dynamic scalar metadata, stable source ordering, repeated categorical values, and multiple synthetic channel identities. These deliberately designed records are semantic anchors inside the deterministic generator, not a separately maintained golden dataset. Expected query semantics come from the independently authored Python oracle rather than generated snapshots or production code.

New yt-sql syntax must add independent oracle coverage, boundary cases, and cross-feature interactions as part of its implementation. Larger profiles should be used only where scale is relevant to the behaviour under test.

## Planned analytical expansion

The next yt-sql language pass is expected to evaluate and, where appropriate, add `SELECT *`, general scalar expressions, arithmetic, `CASE`, `LIKE`/`ILIKE`, aggregates, `GROUP BY`, `HAVING`, aggregate `FILTER`, expression ordering, explicit NULL ordering, PostgreSQL-inspired `DISTINCT ON`, and a curated set of additional scalar/date functions. These are planned capabilities, not syntax accepted by the current parser.
