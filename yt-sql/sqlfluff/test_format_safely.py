"""Dependency-independent checks for the conservative formatting boundary."""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from format_safely import format_checked, structural_tree  # noqa: E402
from yt_media_tools.query_parser import parse_query  # noqa: E402


class SafeFormattingTests(unittest.TestCase):
    def test_layout_does_not_change_structural_tree(self) -> None:
        first = "SELECT id FROM @yt_sql_fixture WHERE id = 1 LIMIT 2\n"
        second = "SELECT\n    id FROM @yt_sql_fixture\nWHERE id = 1 LIMIT 2\n"
        self.assertEqual(structural_tree(parse_query(first)), structural_tree(parse_query(second)))

    def test_predicate_change_is_detected(self) -> None:
        first = "SELECT id FROM @yt_sql_fixture WHERE id = 1 LIMIT 2\n"
        second = "SELECT id FROM @yt_sql_fixture WHERE id = 2 LIMIT 2\n"
        self.assertNotEqual(structural_tree(parse_query(first)), structural_tree(parse_query(second)))

    def test_rejects_semantic_rewrite(self) -> None:
        original = "SELECT id FROM @yt_sql_fixture WHERE id = 1 LIMIT 2\n"
        rewritten = original.replace("id = 1", "id = 2")

        def fake_run(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, rewritten if "format" in args else "file:\n", "")

        with (
            patch("format_safely.subprocess.run", side_effect=fake_run),
            self.assertRaisesRegex(ValueError, "changed the authoritative"),
        ):
            format_checked(original)

    def test_rejects_unparsable_sqlfluff_output(self) -> None:
        original = "SELECT id FROM @yt_sql_fixture LIMIT 2\n"
        with (
            patch(
                "format_safely.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "unparsable: bad", "")
            ),
            self.assertRaisesRegex(ValueError, "SQLFluff parse failed"),
        ):
            format_checked(original)

    def test_rejects_non_idempotent_output(self) -> None:
        original = "SELECT id FROM @yt_sql_fixture LIMIT 2\n"
        formatted = "SELECT\n id FROM @yt_sql_fixture LIMIT 2\n"
        alternate = "SELECT\n  id FROM @yt_sql_fixture LIMIT 2\n"
        outputs = ["file:\n", formatted, "file:\n", alternate]

        def fake_run(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, outputs.pop(0), "")

        with (
            patch("format_safely.subprocess.run", side_effect=fake_run),
            self.assertRaisesRegex(ValueError, "not idempotent"),
        ):
            format_checked(original)

    def test_progress_renders_counts_and_finishes_line(self) -> None:
        import io
        from format_safely import _show_progress

        output = io.StringIO()
        _show_progress(0, 4, stream=output, interactive=True)
        _show_progress(2, 4, stream=output, interactive=True)
        _show_progress(4, 4, stream=output, interactive=True)
        self.assertIn("0/4 (0%)", output.getvalue())
        self.assertIn("2/4 (50%)", output.getvalue())
        self.assertIn("4/4 (100%)", output.getvalue())
        self.assertTrue(output.getvalue().endswith("\n"))

    def test_progress_is_silent_for_non_interactive_output(self) -> None:
        import io
        from format_safely import _show_progress

        output = io.StringIO()
        _show_progress(1, 2, stream=output, interactive=False)
        self.assertEqual(output.getvalue(), "")

    def test_progress_does_not_affect_read_only_checks(self) -> None:
        import tempfile
        from format_safely import main

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("a.ysql", "b.ysql"):
                (root / name).write_text("SELECT id FROM @yt_sql_fixture LIMIT 1\n", encoding="utf-8")
            with (
                patch("format_safely.format_checked", side_effect=lambda query: query),
                patch("format_safely.sys.stderr.isatty", return_value=False),
            ):
                self.assertEqual(main(["--check", str(root)]), 0)
            self.assertEqual(len(list(root.glob("*.ysql"))), 2)

    def test_check_fails_when_formatting_is_needed(self) -> None:
        import tempfile
        from format_safely import main

        with tempfile.TemporaryDirectory() as directory:
            query = Path(directory) / "example.ysql"
            query.write_text("SELECT id FROM @yt_sql_fixture LIMIT 1\n", encoding="utf-8")
            with patch("format_safely.format_checked", return_value="SELECT\n    id FROM @yt_sql_fixture LIMIT 1\n"):
                self.assertEqual(main(["--check", str(query)]), 1)
            self.assertEqual(query.read_text(encoding="utf-8"), "SELECT id FROM @yt_sql_fixture LIMIT 1\n")

    def test_format_writes_only_validated_changes(self) -> None:
        import tempfile
        from format_safely import main

        with tempfile.TemporaryDirectory() as directory:
            query = Path(directory) / "example.ysql"
            query.write_text("SELECT id FROM @yt_sql_fixture LIMIT 1\n", encoding="utf-8")
            formatted = "SELECT\n    id FROM @yt_sql_fixture LIMIT 1\n"
            with patch("format_safely.format_checked", return_value=formatted):
                self.assertEqual(main(["--write", str(query)]), 0)
            self.assertEqual(query.read_text(encoding="utf-8"), formatted)

    def test_check_succeeds_for_unchanged_query(self) -> None:
        import tempfile
        from format_safely import main

        with tempfile.TemporaryDirectory() as directory:
            query = Path(directory) / "example.ysql"
            original = "SELECT id FROM @yt_sql_fixture LIMIT 1\n"
            query.write_text(original, encoding="utf-8")
            with patch("format_safely.format_checked", return_value=original):
                self.assertEqual(main(["--check", str(query)]), 0)


if __name__ == "__main__":
    unittest.main()
