"""Shared pytest fixtures for downloader tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def downloader():
    """Load the downloader entry point as a module once per test session."""
    path = Path(__file__).resolve().parents[1] / "yt-download.py"
    spec = importlib.util.spec_from_file_location("yt_download", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load downloader module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
