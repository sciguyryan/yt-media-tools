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


if __name__ == "__main__":
    unittest.main()
