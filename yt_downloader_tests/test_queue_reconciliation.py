"""Persistent queue completion and download-archive reconciliation."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest


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
