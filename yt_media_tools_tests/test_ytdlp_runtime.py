"""Deterministic tests for the shared yt-dlp runtime boundary."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from yt_media_tools import ytdlp_runtime


def test_resolve_executable_allows_unresolved_dry_run(monkeypatch) -> None:
    monkeypatch.setattr(ytdlp_runtime.shutil, "which", lambda _name: None)
    assert ytdlp_runtime.resolve_executable(dry_run=True) == "yt-dlp"


def test_resolve_executable_requires_runtime_for_execution(monkeypatch) -> None:
    monkeypatch.setattr(ytdlp_runtime.shutil, "which", lambda _name: None)
    with pytest.raises(ytdlp_runtime.YtDlpRuntimeError, match="yt-dlp was not found"):
        ytdlp_runtime.resolve_executable()


def test_probe_version_strips_successful_output(monkeypatch) -> None:
    monkeypatch.setattr(
        ytdlp_runtime.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="2026.09.01\n"),
    )
    assert ytdlp_runtime.probe_version("yt-dlp") == "2026.09.01"


def test_probe_version_is_optional_on_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        ytdlp_runtime.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=""),
    )
    assert ytdlp_runtime.probe_version("yt-dlp") is None


def test_resolve_cookie_file_prefers_explicit_file(tmp_path: Path) -> None:
    default = tmp_path / "default-cookies.txt"
    explicit = tmp_path / "explicit-cookies.txt"
    default.write_text("default", encoding="utf-8")
    explicit.write_text("explicit", encoding="utf-8")
    assert ytdlp_runtime.resolve_cookie_file(explicit, default_file=default) == explicit


def test_resolve_cookie_file_uses_optional_default(tmp_path: Path) -> None:
    default = tmp_path / "cookies.txt"
    default.write_text("cookie", encoding="utf-8")
    assert ytdlp_runtime.resolve_cookie_file(None, default_file=default) == default


def test_resolve_cookie_file_rejects_missing_explicit_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.txt"
    with pytest.raises(ValueError, match="cookies file not found"):
        ytdlp_runtime.resolve_cookie_file(missing, default_file=tmp_path / "cookies.txt")


def test_resolve_cookie_file_can_disable_default(tmp_path: Path) -> None:
    default = tmp_path / "cookies.txt"
    default.write_text("cookie", encoding="utf-8")
    assert ytdlp_runtime.resolve_cookie_file(None, default_file=default, disabled=True) is None


def test_authentication_options_prefer_cookie_file(tmp_path: Path) -> None:
    cookies = tmp_path / "cookies.txt"
    command = ["yt-dlp"]
    ytdlp_runtime.append_authentication_options(
        command,
        cookies_file=cookies,
        cookies_from_browser="firefox",
    )
    assert command == ["yt-dlp", "--cookies", str(cookies)]


def test_authentication_options_support_browser_cookie_source() -> None:
    command = ["yt-dlp"]
    ytdlp_runtime.append_authentication_options(command, cookies_from_browser="firefox")
    assert command == ["yt-dlp", "--cookies-from-browser", "firefox"]


def test_format_command_quotes_shell_sensitive_arguments() -> None:
    rendered = ytdlp_runtime.format_command(["yt-dlp", "--cookies", "/tmp/a b/cookies.txt"])
    assert rendered == "yt-dlp --cookies '/tmp/a b/cookies.txt'"
