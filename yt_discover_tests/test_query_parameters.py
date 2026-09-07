"""Named yt-sql parameter binding and validation at the CLI boundary."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "yt-discover.py"


def test_parameter_binding_check_query() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--param",
            "start=2026-08-01",
            "--check-query",
            "SELECT id FROM @x WHERE upload_date >= :start",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "upload_date >= '2026-08-01'" in proc.stdout


def test_missing_parameter_is_an_error() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--check-query", "SELECT id FROM @x WHERE title = :name"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "missing value for query parameter" in proc.stderr


def test_parameters_do_not_expand_inside_quoted_strings() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--param",
            "name=unused",
            "--check-query",
            "SELECT id FROM @x WHERE title = ':name'",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "unused query parameter" in proc.stderr
