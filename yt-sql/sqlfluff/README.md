# Experimental YT-SQL SQLFluff integration

The integration targets SQLFluff 4.4.0 and uses a process-local registration hook because SQLFluff does not expose a public custom-dialect registration interface. It is intentionally separate from `.sqlfluff`, which governs SQLite statements.

Run the experimental parser and lint checks from the repository root:

```bash
python yt-sql/sqlfluff/run.py parse --config .sqlfluff-ysql yt-sql/cases/unicode/upper_sharp_s/query.ysql
python yt-sql/sqlfluff/run.py lint --config .sqlfluff-ysql yt-sql/cases/unicode/upper_sharp_s/query.ysql
```

The dialect currently inherits SQLite's grammar and adds support for the `@yt_sql_fixture` source reference. This is an initial compatibility scaffold, **not complete YT-SQL syntax support**. Do not enable mandatory linting or automatic formatting for the entire corpus until valid syntax, semantic preservation and idempotence have been verified, including deliberately unusual parser fixtures. SQLFluff must never define YT-SQL validity independently of Discover's parser.

The normative corpus is checked independently from SQLite SQL in `.github/workflows/ytsql-sql-quality.yml`. Run the same checks locally:

```bash
python -m unittest discover -s yt-sql/sqlfluff -p 'test_*.py'
```

The tests lint every normative `.ysql` query and check formatter idempotence, including preservation of Unicode string literals and fixture-source spelling. They also exercise formatting of a deliberately unformatted query. The YT-SQL configuration excludes SQLFluff rule AM09 because unordered `LIMIT` is a valid part of the YT-SQL contract. This exception does not affect SQLite SQL linting.

The integration is still limited to the normative query subset. SQLFluff's SQLite-derived grammar is not a substitute for Discover's authoritative parser; no claim of full YT-SQL grammar coverage or general semantic equivalence is made.
