"""CLI metadata, runtime paths, option validation and environment checks."""

from __future__ import annotations

import pytest


def test_version_is_current(downloader) -> None:
    assert downloader.PROGRAM_VERSION == "1.6.0"


def test_runtime_files_are_script_relative(downloader) -> None:
    assert downloader.ARCHIVE_FILE == downloader.SCRIPT_DIR / "archive.txt"
    assert downloader.COOKIES_FILE == downloader.SCRIPT_DIR / "cookies.txt"
    assert downloader.PROFILES_DIR == downloader.SCRIPT_DIR / "profiles"


@pytest.mark.parametrize("value", ["1", "720", "1080", "1440", "2160"])
def test_validate_resolution_accepts_positive_integer_strings(downloader, value: str) -> None:
    assert downloader.validate_resolution(value) == value


@pytest.mark.parametrize("value", ["", "0", "-1", "1080p", "abc"])
def test_validate_resolution_rejects_invalid_values(downloader, value: str) -> None:
    with pytest.raises(ValueError):
        downloader.validate_resolution(value)


def test_dry_run_environment_does_not_require_yt_dlp_or_cookies(downloader, monkeypatch) -> None:
    monkeypatch.setattr(downloader.shutil, "which", lambda _: None)
    assert downloader.validate_environment(dry_run=True) == "yt-dlp"


def test_resolve_cookies_uses_script_local_file_when_present(downloader, tmp_path, monkeypatch) -> None:
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("cookie-data", encoding="utf-8")
    monkeypatch.setattr(downloader, "COOKIES_FILE", cookie_file)
    assert downloader.resolve_cookies(None, disabled=False) == cookie_file


def test_resolve_cookies_returns_none_when_automatic_file_is_absent(downloader, tmp_path, monkeypatch) -> None:
    cookie_file = tmp_path / "cookies.txt"
    monkeypatch.setattr(downloader, "COOKIES_FILE", cookie_file)
    assert downloader.resolve_cookies(None, disabled=False) is None


def test_resolve_cookies_explicit_missing_file_is_rejected(downloader, tmp_path) -> None:
    missing = tmp_path / "missing-cookies.txt"
    with pytest.raises(ValueError, match="cookies file not found"):
        downloader.resolve_cookies(missing, disabled=False)


def test_resolve_cookies_no_cookies_overrides_automatic_file(downloader, tmp_path, monkeypatch) -> None:
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("cookie-data", encoding="utf-8")
    monkeypatch.setattr(downloader, "COOKIES_FILE", cookie_file)
    assert downloader.resolve_cookies(None, disabled=True) is None
