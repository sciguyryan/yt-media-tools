"""Fast in-process harness for yt-discover CLI behaviour tests.

Use real subprocesses only where the process boundary itself is part of the
contract. Most CLI behaviour can exercise the same application entry point
without repeatedly starting a second Python interpreter.
"""

from __future__ import annotations

import io
import os
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from yt_media_tools.discover_application import main

ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run the real Discover application entry point with process-like isolation."""

    stdout = io.StringIO()
    stderr = io.StringIO()
    previous_cwd = Path.cwd()
    returncode = 0
    try:
        os.chdir(ROOT)
        environment = os.environ.copy() if env is None else env
        with patch.dict(os.environ, environment, clear=True), redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                result = main(list(args))
                returncode = 0 if result is None else int(result)
            except SystemExit as exc:
                returncode = exc.code if isinstance(exc.code, int) else 1
    finally:
        os.chdir(previous_cwd)

    return subprocess.CompletedProcess(
        args=["yt-discover.py", *args],
        returncode=returncode,
        stdout=stdout.getvalue(),
        stderr=stderr.getvalue(),
    )
