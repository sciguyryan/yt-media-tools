# Experimental YT-SQL SQLFluff integration

The integration targets SQLFluff 4.4.0 and uses a process-local registration hook because SQLFluff does not expose a public custom-dialect registration interface. It is intentionally separate from `.sqlfluff`, which governs SQLite statements.

Run the experimental parser and lint checks from the repository root:

```bash
python yt-sql/sqlfluff/run.py parse --config .sqlfluff-ysql yt-sql/cases/unicode/upper_sharp_s/query.ysql
python yt-sql/sqlfluff/run.py lint --config .sqlfluff-ysql yt-sql/cases/unicode/upper_sharp_s/query.ysql
```

The dialect currently inherits SQLite's grammar and adds support for the `@yt_sql_fixture` source reference. This is an initial compatibility scaffold, **not complete YT-SQL syntax support**. Do not enable mandatory linting or automatic formatting for the entire corpus until valid syntax, semantic preservation and idempotence have been verified, including deliberately unusual parser fixtures. SQLFluff must never define YT-SQL validity independently of Discover's parser.
