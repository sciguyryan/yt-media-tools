"""Stable command-line metadata exposed by yt-discover."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "yt-discover.py"


def test_cli_reports_current_version() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--version"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert "0.25.2" in proc.stdout


def test_no_arguments_include_easter_egg_without_changing_error_status() -> None:
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, str(root / "yt-discover.py")], cwd=root, text=True, capture_output=True, check=False
    )
    assert proc.returncode == 2
    assert "El Psy Kongroo." in proc.stderr
    assert "SOURCE_OR_QUERY is required" in proc.stderr
    assert proc.stdout == ""
