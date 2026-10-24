# Experimental YT-SQL SQLFluff integration

The integration targets SQLFluff 4.4.0 and uses a process-local registration hook because SQLFluff does not expose a public custom-dialect registration interface. It is intentionally separate from `.sqlfluff`, which governs SQLite statements.

Run the experimental parser and lint checks from the repository root:

```bash
python yt-sql/sqlfluff/run.py parse --config .sqlfluff-ysql yt-sql/cases/unicode/upper_sharp_s/query.ysql
python yt-sql/sqlfluff/run.py lint --config .sqlfluff-ysql yt-sql/cases/unicode/upper_sharp_s/query.ysql
```

The dialect currently inherits SQLite's grammar and adds support for the `@yt_sql_fixture` source reference and the YT-SQL `ILIKE`, `CONTAINS`, `MATCHES` and related negated predicate spellings omitted by SQLFluff's SQLite grammar. This is an initial compatibility scaffold, **not complete YT-SQL syntax support**. Do not enable mandatory linting or automatic formatting for the entire corpus until valid syntax, semantic preservation and idempotence have been verified, including deliberately unusual parser fixtures. SQLFluff must never define YT-SQL validity independently of Discover's parser.

The normative corpus is checked independently from SQLite SQL in `.github/workflows/ytsql-sql-quality.yml`. Run the same checks locally:

```bash
python -m unittest discover -s yt-sql/sqlfluff -p 'test_*.py'
```

The tests lint every normative `.ysql` query and check formatter idempotence, including preservation of Unicode string literals and fixture-source spelling. They also exercise formatting of a deliberately unformatted query. The YT-SQL configuration excludes SQLFluff rule AM09 because unordered `LIMIT` is a valid part of the YT-SQL contract. This exception does not affect SQLite SQL linting.

The integration is still limited to the normative query subset. SQLFluff's SQLite-derived grammar is not a substitute for Discover's authoritative parser; no claim of full YT-SQL grammar coverage or general semantic equivalence is made.

The separate predicate regression checks parse and format both `ILIKE` and `NOT ILIKE`, including a Unicode literal, and verify formatting idempotence. These checks exercise the formatter grammar only and do not promote additional portable conformance cases.

The predicate regression suite exercises `CONTAINS`, `CONTAIN`, `MATCHES`, `MATCH`, `ILIKE` and `LIKE`, including `NOT` and `DOES NOT` forms recognised by Discover. Each case checks parsing before and after formatting, operator preservation, Unicode literal preservation and idempotence. These are formatter parsing checks rather than an assertion that the inherited SQLite grammar matches all YT-SQL expression rules.

The regression suite also covers `IS DISTINCT FROM` and `IS NOT DISTINCT FROM` with Unicode literals. These constructs already parse through the inherited grammar; the additional tests guard against formatter regressions without extending the dialect or claiming complete YT-SQL coverage.

The regression suite additionally covers `BETWEEN`, `NOT BETWEEN`, `IN`, `NOT IN`, `IS NULL` and `IS NOT NULL` through the inherited grammar, checking reparsing and formatter idempotence without introducing unnecessary dialect overrides.

## Maintaining compatibility with YT-SQL

The SQLFluff dialect must evolve alongside the authoritative YT-SQL language implementation. Any change that introduces, modifies or removes YT-SQL syntax must include a review of the SQLFluff integration as part of the same development work. This applies to functions, operators, predicates, expressions, clauses, literals, source references and other language constructs.

If the existing SQLFluff grammar already supports the change correctly, add or extend regression tests to establish that coverage. Otherwise, update the dedicated YT-SQL dialect and its tests before considering the language change complete. Where applicable, tests must cover parsing, formatting, preservation of literals and identifiers, reparsing, formatting idempotence and semantic equivalence against Discover's authoritative parser.

Keep the YT-SQL SQLFluff configuration and checks independent of SQLite SQL linting. Do not weaken grammar validation or suppress errors merely to accommodate unsupported syntax. Record any remaining limitations explicitly, and do not enable automatic formatting for constructs whose safe handling has not been established.

The portable YT-SQL conformance corpus should provide representative cases for new language features so that future changes can be checked consistently across implementations.
