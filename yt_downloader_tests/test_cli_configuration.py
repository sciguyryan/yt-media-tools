"""CLI metadata, runtime paths, option validation and environment checks."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_version_is_current(downloader) -> None:
    assert downloader.PROGRAM_VERSION == "1.14.0"


def test_runtime_files_are_script_relative(downloader) -> None:
    assert downloader.ARCHIVE_FILE == downloader.SCRIPT_DIR / "archive.txt"
    assert downloader.COOKIES_FILE == downloader.SCRIPT_DIR / "cookies.txt"
    assert downloader.PROFILES_DIR == downloader.SCRIPT_DIR / "profiles"
    assert downloader.DEFAULTS_FILE == downloader.SCRIPT_DIR / "defaults.json"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1", "1"),
        ("720", "720"),
        ("1080", "1080"),
        ("1080p", "1080"),
        ("1440", "1440"),
        ("1440p", "1440"),
        ("2160", "2160"),
        ("2160p", "2160"),
        ("BEST", "best"),
        ("best", "best"),
    ],
)
def test_validate_resolution_accepts_supported_forms(downloader, value: str, expected: str) -> None:
    assert downloader.validate_resolution(value) == expected


@pytest.mark.parametrize("value", ["", "0", "-1", "1080px", "p1080", "abc"])
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


def test_normal_environment_requires_yt_dlp(downloader, monkeypatch) -> None:
    monkeypatch.setattr(downloader.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="yt-dlp was not found"):
        downloader.validate_environment(dry_run=False)


def test_dry_run_rejects_queue_report_output(downloader, tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc_info:
        downloader.main(
            [
                "--dry-run",
                "--queue-report",
                str(tmp_path / "report.json"),
                "abc",
            ]
        )
    assert exc_info.value.code == 2


def test_examples_are_available_without_external_environment(downloader, capsys) -> None:
    assert downloader.main(["--examples"]) == 0
    output = capsys.readouterr().out
    assert "--remove-completed-ids" in output
    assert "--explain" in output
    assert "--write-subs" in output
    assert "--audio-only" in output
    assert "--audio-format" in output
