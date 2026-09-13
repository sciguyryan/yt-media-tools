"""Downloader output-profile parsing and validation."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_profile_parser_accepts_path_and_output(downloader, tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    profile.write_text("@profile\npath=/tmp/media\noutput=%(id)s.%(ext)s\n", encoding="utf-8")
    parsed = downloader.parse_profile(profile)
    assert parsed.path == "/tmp/media"
    assert parsed.output == "%(id)s.%(ext)s"


def test_profile_parser_rejects_unknown_setting(downloader, tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    profile.write_text("@profile\nunknown=value\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown setting"):
        downloader.parse_profile(profile)


def test_profile_parser_rejects_duplicate_setting(downloader, tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    profile.write_text("@profile\npath=/a\npath=/b\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate setting"):
        downloader.parse_profile(profile)
