"""Direct-target, batch-file and standard-input source handling."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest


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
