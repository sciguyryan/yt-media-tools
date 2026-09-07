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
    assert "0.20.0" in proc.stdout
