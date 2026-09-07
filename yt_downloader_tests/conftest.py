"""Shared fixtures for the yt-download test suite."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
DOWNLOADER_PATH = ROOT / "yt-download.py"


@pytest.fixture()
def downloader():
    """Load a fresh yt-download module for a test."""
    spec = importlib.util.spec_from_file_location("run_downloader_under_test", DOWNLOADER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    return module
