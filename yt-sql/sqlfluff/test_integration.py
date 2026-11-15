"""Regression checks for the pinned, process-local SQLFluff YT-SQL integration."""

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "yt-sql/sqlfluff/run.py"
CONFIG = ROOT / ".sqlfluff-ysql"
CASES = ROOT / "yt-sql/cases"


# Keep one real SQLFluff linter alive for the parser/formatter contract tests.
# The CLI boundary remains covered by the corpus lint test and a dedicated smoke test.
from format_safely import ReusableSQLFluff  # noqa: E402
from sqlfluff.core import FluffConfig, Linter  # noqa: E402

_ENGINE = None
_SQLITE_ENGINE = None


def invoke(command: str, *args: str, source: str | None = None) -> subprocess.CompletedProcess[str]:
    global _ENGINE
    if command not in {"parse", "format"} or args != ("-",):
        return subprocess.run(
            [sys.executable, str(LAUNCHER), command, "--config", str(CONFIG), *args],
            cwd=ROOT,
            input=source,
            text=True,
            capture_output=True,
            check=False,
        )
    if _ENGINE is None:
        _ENGINE = ReusableSQLFluff()
    try:
        if command == "parse":
            _ENGINE.parse(source or "")
            output = "file:\n"
        else:
            output = _ENGINE.format(source or "")
        return subprocess.CompletedProcess([command], 0, output, "")
    except ValueError as exc:
        return subprocess.CompletedProcess([command], 1, "", str(exc))


class SQLFluffYTSQLTests(unittest.TestCase):
    # Collection binding semantics are normative in the portable corpus (function-conformance.collection and random cases); this test guards the formatter only.
    def test_collection_binding_syntax_parses_and_formats(self) -> None:
        """The custom dialect must preserve both collection binding forms."""
        from format_safely import format_checked

        if _ENGINE is None:
            engine = ReusableSQLFluff()
        else:
            engine = _ENGINE
        for query in (
            "SELECT FILTER(tags AS item WHERE item = 'topic-1') AS result FROM @yt_sql_fixture LIMIT 1\n",
            "SELECT MAP(tags AS item SELECT UPPER(item)) AS result FROM @yt_sql_fixture LIMIT 1\n",
            "SELECT COUNT(tags AS item WHERE item = 'topic-1') AS result FROM @yt_sql_fixture LIMIT 1\n",
        ):
            with self.subTest(query=query):
                formatted = format_checked(query, engine=engine)
                self.assertEqual(formatted, format_checked(formatted, engine=engine))

    def test_cli_parse_and_format_smoke(self) -> None:
        """Retain genuine subprocess coverage for the SQLFluff entry point."""
        query = "SELECT id FROM @yt_sql_fixture LIMIT 1\n"
        for command in ("parse", "format"):
            result = subprocess.run(
                [sys.executable, str(LAUNCHER), command, "--config", str(CONFIG), "-"],
                cwd=ROOT,
                input=query,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_sqlite_and_ytsql_formatting_parity(self) -> None:
        """Shared SQL constructs must follow the same SQLFluff layout policy."""
        global _SQLITE_ENGINE
        if _SQLITE_ENGINE is None:
            _SQLITE_ENGINE = Linter(config=FluffConfig.from_root(extra_config_path=str(ROOT / ".sqlfluff")))

        def format_sqlite(source: str) -> str:
            result = _SQLITE_ENGINE.lint_string_wrapped(source, fix=True)
            self.assertFalse(result.count_tmp_prs_errors()[1], "SQLite SQLFluff parse errors")
            return result.paths[0].files[0].fix_string()[0]

        examples = (
            "SELECT id FROM {source} LIMIT 10\n",
            "SELECT UPPER('straße') AS result FROM {source} LIMIT 1\n",
            "SELECT id, title FROM {source} WHERE id > 1 ORDER BY id LIMIT 5\n",
            "SELECT\n    id\nFROM {source}\nLIMIT 10\n",
        )
        for template in examples:
            with self.subTest(template=template):
                sqlite_source = template.format(source="fixture")
                ytsql_source = template.format(source="@yt_sql_fixture")
                sqlite = format_sqlite(sqlite_source)
                ytsql = invoke("format", "-", source=ytsql_source)
                self.assertEqual(ytsql.returncode, 0, ytsql.stdout + ytsql.stderr)
                self.assertEqual(ytsql.stdout.replace("@yt_sql_fixture", "fixture"), sqlite)
                self.assertTrue(sqlite.startswith("SELECT\n    "), sqlite)
                for formatted, is_ytsql in ((sqlite, False), (ytsql.stdout, True)):
                    again = invoke("format", "-", source=formatted).stdout if is_ytsql else format_sqlite(formatted)
                    self.assertEqual(again, formatted)

    @staticmethod
    def _format_eligible_queries() -> list[Path]:
        """Only successful-result cases belong to the formatter contract.

        Expected-error queries are still exercised by portable conformance;
        malformed syntax must not be rewritten or required to lint cleanly.
        """
        eligible = []
        for query in sorted(CASES.rglob("*.ysql")):
            # Lexical torture intentionally perturbs layout; requiring canonical
            # formatting here would erase the behaviour under test.
            if "torture-portable" in query.parts:
                continue
            expectation = query.with_name("expected.json")
            if not expectation.is_file():
                raise AssertionError(f"Missing expectation for {query}")
            document = json.loads(expectation.read_text(encoding="utf-8"))
            if document.get("outcome") != "error":
                eligible.append(query)
        return eligible

    def test_normative_corpus_lints(self) -> None:
        queries = self._format_eligible_queries()
        self.assertTrue(queries, "No positive normative queries to lint")
        result = invoke("lint", *(str(query) for query in queries))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_normative_corpus_formatting_is_idempotent(self) -> None:
        for query in self._format_eligible_queries():
            with self.subTest(query=query.relative_to(ROOT)):
                original = query.read_text(encoding="utf-8")
                first = invoke("format", "-", source=original)
                self.assertEqual(first.returncode, 0, first.stderr)
                second = invoke("format", "-", source=first.stdout)
                self.assertEqual(second.returncode, 0, second.stderr)
                self.assertEqual(first.stdout, second.stdout)
                # These normative inputs are already formatted; changes to
                # literal spelling, including Unicode, must not go unnoticed.
                self.assertEqual(original, first.stdout)

        # ILIKE language semantics are normative through semantics.text_* and ilike cases; this test guards the formatter only.

    def test_ilike_predicates_parse_and_format(self) -> None:
        # SQLite's SQLFluff dialect deliberately omits ILIKE. YT-SQL accepts
        # it, including NOT ILIKE, so guard this extension independently.
        queries = (
            "SELECT id FROM @yt_sql_fixture WHERE title ILIKE '%straße%' LIMIT 1\n",
            "SELECT id FROM @yt_sql_fixture WHERE title NOT ILIKE '%a%' LIMIT 1\n",
        )
        for query in queries:
            with self.subTest(query=query):
                parsed = invoke("parse", "-", source=query)
                self.assertEqual(parsed.returncode, 0, parsed.stdout + parsed.stderr)
                self.assertNotIn("unparsable:", parsed.stdout.lower())
                first = invoke("format", "-", source=query)
                self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
                self.assertIn("ILIKE", first.stdout)
                self.assertIn("@yt_sql_fixture", first.stdout)
                if "straße" in query:
                    self.assertIn("'%straße%'", first.stdout)
                second = invoke("format", "-", source=first.stdout)
                self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
                self.assertEqual(first.stdout, second.stdout)

        # All nineteen spellings are normative through the semantics.text_* spelling cases; this test guards the formatter only.

    def test_text_predicate_variants_parse_and_format(self) -> None:
        # Discover accepts both long and short operator spellings, with NOT
        # and DOES NOT forms. Exercise each explicitly: a formatter must not
        # silently discard or rewrite an operator it cannot parse.
        operators = (
            "CONTAINS",
            "CONTAIN",
            "MATCHES",
            "MATCH",
            "ILIKE",
            "LIKE",
            "NOT CONTAINS",
            "NOT CONTAIN",
            "NOT MATCHES",
            "NOT MATCH",
            "NOT ILIKE",
            "NOT LIKE",
            "DOES NOT CONTAINS",
            "DOES NOT CONTAIN",
            "DOES NOT MATCHES",
            "DOES NOT MATCH",
            "DOES NOT ILIKE",
            "DOES NOT LIKE",
        )
        for operator in operators:
            with self.subTest(operator=operator):
                original = f"SELECT id FROM @yt_sql_fixture WHERE title {operator} 'straße' LIMIT 1\n"
                parsed = invoke("parse", "-", source=original)
                self.assertEqual(parsed.returncode, 0, parsed.stdout + parsed.stderr)
                self.assertNotIn("unparsable:", parsed.stdout.lower())
                first = invoke("format", "-", source=original)
                self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
                self.assertIn("'straße'", first.stdout)
                self.assertIn("@yt_sql_fixture", first.stdout)
                self.assertIn(f"title {operator} 'straße'", " ".join(first.stdout.split()))
                reparsed = invoke("parse", "-", source=first.stdout)
                self.assertEqual(reparsed.returncode, 0, reparsed.stdout + reparsed.stderr)
                self.assertNotIn("unparsable:", reparsed.stdout.lower())
                second = invoke("format", "-", source=first.stdout)
                self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
                self.assertEqual(first.stdout, second.stdout)

        # Distinctness semantics are normative through semantics.distinct_from_value and siblings; this test guards the formatter only.

    def test_distinctness_predicates_parse_and_format(self) -> None:
        # Discover supports SQL-style null-safe distinctness predicates.
        # Preserve the NOT modifier and the right-hand Unicode literal.
        for operator in ("IS DISTINCT FROM", "IS NOT DISTINCT FROM"):
            with self.subTest(operator=operator):
                original = f"SELECT id FROM @yt_sql_fixture WHERE title {operator} 'straße' LIMIT 1\n"
                parsed = invoke("parse", "-", source=original)
                self.assertEqual(parsed.returncode, 0, parsed.stdout + parsed.stderr)
                self.assertNotIn("unparsable:", parsed.stdout.lower())
                first = invoke("format", "-", source=original)
                self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
                self.assertIn("'straße'", first.stdout)
                self.assertIn("@yt_sql_fixture", first.stdout)
                self.assertIn(operator, first.stdout.upper())
                reparsed = invoke("parse", "-", source=first.stdout)
                self.assertEqual(reparsed.returncode, 0, reparsed.stdout + reparsed.stderr)
                self.assertNotIn("unparsable:", reparsed.stdout.lower())
                second = invoke("format", "-", source=first.stdout)
                self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
                self.assertEqual(first.stdout, second.stdout)

        # Range and NULL predicate semantics are normative through semantics.between_filter and siblings; this test guards the formatter only.

    def test_range_membership_and_null_predicates(self) -> None:
        # These YT-SQL constructs use the inherited grammar. Protect them
        # against formatter regressions without adding duplicate dialect rules.
        queries = (
            "SELECT id FROM @yt_sql_fixture WHERE view_count BETWEEN 10 AND 20 LIMIT 5\n",
            "SELECT id FROM @yt_sql_fixture WHERE view_count NOT BETWEEN 10 AND 20 LIMIT 5\n",
            "SELECT id FROM @yt_sql_fixture WHERE id IN (1, 2, 3) LIMIT 5\n",
            "SELECT id FROM @yt_sql_fixture WHERE id NOT IN (1, 2, 3) LIMIT 5\n",
            "SELECT id FROM @yt_sql_fixture WHERE title IS NULL LIMIT 5\n",
            "SELECT id FROM @yt_sql_fixture WHERE title IS NOT NULL LIMIT 5\n",
        )
        for original in queries:
            with self.subTest(query=original):
                parsed = invoke("parse", "-", source=original)
                self.assertEqual(parsed.returncode, 0, parsed.stdout + parsed.stderr)
                self.assertNotIn("unparsable:", parsed.stdout.lower())
                first = invoke("format", "-", source=original)
                self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
                self.assertIn("@yt_sql_fixture", first.stdout)
                reparsed = invoke("parse", "-", source=first.stdout)
                self.assertEqual(reparsed.returncode, 0, reparsed.stdout + reparsed.stderr)
                self.assertNotIn("unparsable:", reparsed.stdout.lower())
                second = invoke("format", "-", source=first.stdout)
                self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
                self.assertEqual(first.stdout, second.stdout)

    def test_parenthesised_boolean_expression_formats_without_changing_grouping(self) -> None:
        # Parentheses are semantic, not merely layout. Guard mixed AND/OR
        # expressions against formatting that changes their grouping.
        original = "SELECT id FROM @yt_sql_fixture WHERE (view_count > 10 AND title IS NOT NULL) OR id = 3 LIMIT 5\n"
        parsed = invoke("parse", "-", source=original)
        self.assertEqual(parsed.returncode, 0, parsed.stdout + parsed.stderr)
        self.assertNotIn("unparsable:", parsed.stdout.lower())
        first = invoke("format", "-", source=original)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertIn("@yt_sql_fixture", first.stdout)
        self.assertIn("(view_count > 10 AND title IS NOT NULL)", " ".join(first.stdout.split()))
        self.assertIn("OR id = 3", " ".join(first.stdout.split()))
        reparsed = invoke("parse", "-", source=first.stdout)
        self.assertEqual(reparsed.returncode, 0, reparsed.stdout + reparsed.stderr)
        self.assertNotIn("unparsable:", reparsed.stdout.lower())
        second = invoke("format", "-", source=first.stdout)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(first.stdout, second.stdout)

    def test_unformatted_fixture_query(self) -> None:
        original = "select upper('straße') as result from @yt_sql_fixture limit 1\n"
        first = invoke("format", "-", source=original)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("'straße'", first.stdout)
        self.assertIn("@yt_sql_fixture", first.stdout)
        second = invoke("format", "-", source=first.stdout)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(first.stdout, second.stdout)
        parsed = invoke("parse", "-", source=first.stdout)
        self.assertEqual(parsed.returncode, 0, parsed.stdout + parsed.stderr)
        self.assertNotIn("unparsable:", parsed.stdout.lower())


if __name__ == "__main__":
    unittest.main()
