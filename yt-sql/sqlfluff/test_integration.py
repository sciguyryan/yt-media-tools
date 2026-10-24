"""Regression checks for the pinned, process-local SQLFluff YT-SQL integration."""

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "yt-sql/sqlfluff/run.py"
CONFIG = ROOT / ".sqlfluff-ysql"
CASES = ROOT / "yt-sql/cases"


def invoke(command: str, *args: str, source: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(LAUNCHER), command, "--config", str(CONFIG), *args],
        cwd=ROOT,
        input=source,
        text=True,
        capture_output=True,
        check=False,
    )


class SQLFluffYTSQLTests(unittest.TestCase):
    def test_normative_corpus_lints(self) -> None:
        result = invoke("lint", str(CASES))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_normative_corpus_formatting_is_idempotent(self) -> None:
        for query in sorted(CASES.rglob("*.ysql")):
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
