"""Portable fixture authoring must not depend on a Python execution oracle."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from materialise_torture import materialise
from validate_corpus import ROOT


class MaterialisationTests(unittest.TestCase):
    @staticmethod
    def _source_count() -> int:
        """Count approved source cases the materialiser must cover."""
        return sum(1 for path in (ROOT / "cases").rglob("test.json") if "torture-portable" not in path.parts)

    def test_committed_fixtures_match_reproducible_generator(self) -> None:
        self.assertEqual(materialise(ROOT, check=True), self._source_count())

    def test_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "cases" / "scalar" / "example"
            source.mkdir(parents=True)
            (source / "query.ysql").write_text("SELECT 1 FROM @fixture\n", encoding="utf-8")
            (source / "test.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "id": "scalar.example",
                        "datasets": ["example"],
                        "query": "query.ysql",
                        "expected": "expected.json",
                        "order": "ordered",
                    }
                ),
                encoding="utf-8",
            )
            (source / "expected.json").write_text(
                '{"version":1,"outcome":"rows","columns":["x"],"rows":[[1]]}\n', encoding="utf-8"
            )
            self.assertEqual(materialise(root), 1)
            self.assertEqual(materialise(root, check=True), 1)
            output = root / "cases" / "torture-portable" / "scalar" / "example" / "query.ysql"
            output.write_text("SELECT 2 FROM @fixture\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "drift"):
                materialise(root, check=True)

    def test_generation_does_not_use_engine_observations(self) -> None:
        with patch("torture_metamorphic.observe", side_effect=AssertionError("engine invoked")):
            self.assertEqual(materialise(ROOT, check=True), self._source_count())


if __name__ == "__main__":
    unittest.main()
