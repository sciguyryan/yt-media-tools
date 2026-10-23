"""Ensure the combined fixture gate covers every committed fixture family."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "yt-sql/check_portable_fixtures.py"


def test_fixture_manifest_covers_all_families() -> None:
    import ast

    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    strings = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    for script in (
        "validate_portable_dataset.py",
        "validate_portable_topology.py",
        "validate_portable_facets.py",
        "export_portable_dataset.py",
        "export_portable_topology.py",
        "export_portable_facets.py",
        "build_unicode_fixture_audit.py",
        "check_fixture_relationships.py",
    ):
        assert script in strings


def test_all_portable_fixtures_current() -> None:
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("PASS ") == 8
