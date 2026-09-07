"""Behavioural tests for yt-download 1.5.0."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest


def test_version_is_current(downloader) -> None:
    assert downloader.PROGRAM_VERSION == "1.5.0"


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


def test_direct_targets_are_preserved(downloader) -> None:
    args = argparse.Namespace(input_file=None, targets=["a", "b"])
    source = downloader.resolve_input(args)
    assert source.direct_targets == ("a", "b")
    command: list[str] = []
    source.append_to(command)
    assert command == ["a", "b"]


def test_stdin_is_exclusive(downloader) -> None:
    args = argparse.Namespace(input_file=None, targets=["-"])
    source = downloader.resolve_input(args)
    assert source.stdin is True
    command: list[str] = []
    source.append_to(command)
    assert command == ["--batch-file", "-"]


def test_stdin_cannot_be_combined_with_other_targets(downloader) -> None:
    args = argparse.Namespace(input_file=None, targets=["-", "abc"])
    with pytest.raises(ValueError, match="cannot be combined"):
        downloader.resolve_input(args)


def test_input_file_cannot_be_combined_with_targets(downloader, tmp_path: Path) -> None:
    input_file = tmp_path / "ids.txt"
    input_file.write_text("abc\n", encoding="utf-8")
    args = argparse.Namespace(input_file=input_file, targets=["abc"])
    with pytest.raises(ValueError, match="cannot be combined"):
        downloader.resolve_input(args)


def test_existing_single_positional_file_becomes_batch_input(downloader, tmp_path: Path) -> None:
    input_file = tmp_path / "ids.txt"
    input_file.write_text("abc\n", encoding="utf-8")
    args = argparse.Namespace(input_file=None, targets=[str(input_file)])
    source = downloader.resolve_input(args)
    assert source.batch_file == input_file


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


def test_remove_completed_id_preserves_unrelated_bytes(downloader, tmp_path: Path) -> None:
    queue = tmp_path / "ids.txt"
    original = b"# note\nabc\r\ndef\n\nhttps://example.invalid/abc\n"
    queue.write_bytes(original)
    assert downloader.remove_completed_id(queue, "abc") is True
    assert queue.read_bytes() == b"# note\ndef\n\nhttps://example.invalid/abc\n"


def test_remove_completed_id_returns_false_when_absent(downloader, tmp_path: Path) -> None:
    queue = tmp_path / "ids.txt"
    queue.write_bytes(b"abc\ndef\n")
    before = queue.read_bytes()
    assert downloader.remove_completed_id(queue, "xyz") is False
    assert queue.read_bytes() == before


def test_archived_video_ids_ignores_malformed_single_field_lines(downloader, tmp_path: Path) -> None:
    archive = tmp_path / "archive.txt"
    archive.write_text("youtube abc\nmalformed\nyoutube def extra\n\n", encoding="utf-8")
    assert downloader.archived_video_ids(archive) == {"abc", "extra"}


def test_remove_archived_ids_reconciles_queue(downloader, tmp_path: Path) -> None:
    queue = tmp_path / "ids.txt"
    archive = tmp_path / "archive.txt"
    queue.write_text("abc\ndef\nghi\n", encoding="utf-8")
    archive.write_text("youtube abc\nyoutube ghi\n", encoding="utf-8")
    assert downloader.remove_archived_ids(queue, archive) == 2
    assert queue.read_text(encoding="utf-8") == "def\n"


def test_remove_completed_ids_requires_file_input(downloader) -> None:
    args = argparse.Namespace(remove_completed_ids=True)
    source = downloader.InputSource(direct_targets=("abc",))
    with pytest.raises(ValueError, match="requires file input"):
        downloader.validate_remove_completed_ids(args, source)


def test_build_command_contains_core_policy(downloader) -> None:
    source = downloader.InputSource(direct_targets=("abc",))
    policy = downloader.DownloadPolicy(resolution="1080", reverse_playlist=True)
    command = downloader.build_yt_dlp_command("yt-dlp", policy, source, None)
    assert command[0] == "yt-dlp"
    assert "--download-archive" in command
    assert str(downloader.ARCHIVE_FILE) in command
    assert "--cookies" in command
    assert str(downloader.COOKIES_FILE) in command
    assert "--playlist-reverse" in command
    assert command[-1] == "abc"


def test_build_command_adds_after_move_callback_for_file_queue(downloader, tmp_path: Path) -> None:
    queue = tmp_path / "ids.txt"
    queue.write_text("abc\n", encoding="utf-8")
    source = downloader.InputSource(batch_file=queue)
    policy = downloader.DownloadPolicy(resolution="1440", reverse_playlist=False)
    command = downloader.build_yt_dlp_command("yt-dlp", policy, source, None, remove_completed_ids=True)
    exec_index = command.index("--exec")
    assert command[exec_index + 1].startswith("after_move:")
    assert "--_remove-completed-id" in command[exec_index + 1]
    assert command[-2:] == ["--batch-file", str(queue)]


def test_dry_run_environment_does_not_require_yt_dlp_or_cookies(downloader, monkeypatch) -> None:
    monkeypatch.setattr(downloader.shutil, "which", lambda _: None)
    assert downloader.validate_environment(dry_run=True) == "yt-dlp"
