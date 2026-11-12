"""Ensure pre-commit exposes conformance without running the corpus twice."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


class PrecommitConformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        spec = importlib.util.spec_from_file_location("project_precommit", ROOT / "pre-commit.py")
        assert spec and spec.loader
        import sys

        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        cls.module = module

    def test_dedicated_check_is_available(self) -> None:
        checks = {check.name: check.command for check in self.module.checks()}
        self.assertIn("ysql-conformance", checks)
        self.assertIn("ytsql_unittest.py", " ".join(checks["ysql-conformance"]))
        self.assertIn("--workers", checks["ysql-conformance"])

    def test_default_gate_does_not_duplicate_normative_corpus(self) -> None:
        module = self.module
        recorded = []

        def execute(check, **kwargs):
            recorded.append(check.name)
            return True, 0.0, ""

        with (
            patch.object(module, "execute", side_effect=execute),
            patch.object(module, "load_cache", return_value={"version": 1, "checks": {}}),
            patch.object(module, "save_cache"),
            patch.object(module, "ROOT", Path.cwd()),
            patch.object(module.sys, "prefix", str(Path.cwd() / ".venv")),
            patch.object(module.Path, "is_file", return_value=True),
            patch.dict("sys.modules", {"pytest": unittest, "xdist": unittest}),
        ):
            module.main(["--only", "python-tests", "--only", "ysql-conformance"])
        self.assertEqual(recorded, ["python-tests"])
