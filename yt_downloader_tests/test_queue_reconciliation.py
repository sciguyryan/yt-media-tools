"""Persistent queue completion and download-archive reconciliation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

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


def test_queue_targets_ignores_comments_blanks_and_duplicates(downloader, tmp_path: Path) -> None:
    queue = tmp_path / "ids.txt"
    queue.write_text("# note\nabc\n\nabc\ndef\n", encoding="utf-8")
    assert downloader.queue_targets(queue) == ("abc", "def")


def test_queue_run_report_distinguishes_archived_completed_and_unresolved(downloader, tmp_path: Path) -> None:
    queue = tmp_path / "ids.txt"
    archive = tmp_path / "archive.txt"
    report = downloader.queue_run_report(
        queue_file=queue,
        archive_file=archive,
        requested=("archived", "done", "failed"),
        archived_before={"archived"},
        remaining=("failed",),
        exit_status=1,
    )
    assert report["counts"] == {
        "requested": 3,
        "already_archived": 1,
        "completed": 1,
        "unresolved": 1,
    }
    assert report["targets"]["already_archived"] == ["archived"]
    assert report["targets"]["completed"] == ["done"]
    assert report["targets"]["unresolved"] == ["failed"]
    assert report["interrupted"] is False


def test_queue_run_report_marks_interruption(downloader, tmp_path: Path) -> None:
    report = downloader.queue_run_report(
        queue_file=tmp_path / "ids.txt",
        archive_file=tmp_path / "archive.txt",
        requested=("abc",),
        archived_before=set(),
        remaining=("abc",),
        exit_status=130,
    )
    assert report["interrupted"] is True
    assert report["targets"]["unresolved"] == ["abc"]


def test_write_failed_targets_is_reusable_batch_file(downloader, tmp_path: Path) -> None:
    failed = tmp_path / "failed.txt"
    downloader.write_failed_targets(failed, ("abc", "def"))
    assert failed.read_text(encoding="utf-8") == "abc\ndef\n"


def test_write_queue_report_is_deterministic_json(downloader, tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    report = {"kind": "yt-download-queue-report", "version": downloader.PROGRAM_VERSION}
    downloader.write_queue_report(output, report)
    assert output.read_text(encoding="utf-8") == (
        '{\n  "kind": "yt-download-queue-report",\n  "version": "1.16.0"\n}\n'
    )


def test_queue_outputs_require_remove_completed_ids(downloader) -> None:
    args = argparse.Namespace(remove_completed_ids=False, queue_report=Path("report.json"), failed_targets=None)
    source = downloader.InputSource(batch_file=Path("ids.txt"))
    with pytest.raises(ValueError, match="require --remove-completed-ids"):
        downloader.validate_remove_completed_ids(args, source)


def test_atomic_report_write_failure_leaves_existing_file_intact(downloader, tmp_path: Path, monkeypatch) -> None:
    report = tmp_path / "report.json"
    report.write_text("old\n", encoding="utf-8")

    def fail_replace(source, destination):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(downloader.os, "replace", fail_replace)
    with pytest.raises(RuntimeError, match="unable to write"):
        downloader.write_queue_report(report, {"kind": "test"})
    assert report.read_text(encoding="utf-8") == "old\n"
    assert not list(tmp_path.glob(".report.json.tmp-*"))


def test_run_reports_keyboard_interruption_without_raising(downloader, monkeypatch) -> None:
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(downloader.subprocess, "run", interrupt)
    assert downloader.run(["yt-dlp", "abc"], dry_run=False) == 130



def test_main_generates_queue_report_and_retry_file_from_simulated_partial_run(
    downloader, tmp_path: Path, monkeypatch
) -> None:
    queue = tmp_path / "ids.txt"
    archive = tmp_path / "archive.txt"
    report_path = tmp_path / "queue-report.json"
    failed_path = tmp_path / "retry.txt"
    queue.write_text("archived\ndone\nfailed\n", encoding="utf-8")
    archive.write_text("youtube archived\n", encoding="utf-8")

    monkeypatch.setattr(downloader, "validate_environment", lambda *, dry_run: "yt-dlp")

    def simulated_yt_dlp(command, check=False):
        assert check is False
        assert "--exec" in command
        assert downloader.remove_completed_id(queue, "done") is True
        with archive.open("a", encoding="utf-8") as handle:
            handle.write("youtube done\n")
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(downloader.subprocess, "run", simulated_yt_dlp)

    result = downloader.main([
        "--no-cookies",
        "--archive",
        str(archive),
        "--remove-completed-ids",
        "--queue-report",
        str(report_path),
        "--failed-targets",
        str(failed_path),
        str(queue),
    ])

    assert result == 1
    assert queue.read_text(encoding="utf-8") == "failed\n"
    assert failed_path.read_text(encoding="utf-8") == "failed\n"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["counts"] == {
        "requested": 3,
        "already_archived": 1,
        "completed": 1,
        "unresolved": 1,
    }
    assert report["targets"] == {
        "requested": ["archived", "done", "failed"],
        "already_archived": ["archived"],
        "completed": ["done"],
        "unresolved": ["failed"],
    }
    assert report["exit_status"] == 1
    assert report["interrupted"] is False


def test_main_generates_interrupted_queue_report_from_simulated_keyboard_interrupt(
    downloader, tmp_path: Path, monkeypatch
) -> None:
    queue = tmp_path / "ids.txt"
    archive = tmp_path / "archive.txt"
    report_path = tmp_path / "queue-report.json"
    failed_path = tmp_path / "retry.txt"
    queue.write_text("done\nremaining\n", encoding="utf-8")

    monkeypatch.setattr(downloader, "validate_environment", lambda *, dry_run: "yt-dlp")

    def simulated_interrupt(command, check=False):
        assert check is False
        assert downloader.remove_completed_id(queue, "done") is True
        with archive.open("a", encoding="utf-8") as handle:
            handle.write("youtube done\n")
        raise KeyboardInterrupt

    monkeypatch.setattr(downloader.subprocess, "run", simulated_interrupt)

    result = downloader.main([
        "--no-cookies",
        "--archive",
        str(archive),
        "--remove-completed-ids",
        "--queue-report",
        str(report_path),
        "--failed-targets",
        str(failed_path),
        str(queue),
    ])

    assert result == 130
    assert queue.read_text(encoding="utf-8") == "remaining\n"
    assert failed_path.read_text(encoding="utf-8") == "remaining\n"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["targets"]["completed"] == ["done"]
    assert report["targets"]["unresolved"] == ["remaining"]
    assert report["exit_status"] == 130
    assert report["interrupted"] is True


def test_main_keeps_target_unresolved_after_simulated_postprocessing_failure(
    downloader, tmp_path: Path, monkeypatch
) -> None:
    queue = tmp_path / "ids.txt"
    archive = tmp_path / "archive.txt"
    report_path = tmp_path / "queue-report.json"
    failed_path = tmp_path / "retry.txt"
    queue.write_text("postprocess-failed\n", encoding="utf-8")

    monkeypatch.setattr(downloader, "validate_environment", lambda *, dry_run: "yt-dlp")
    monkeypatch.setattr(
        downloader.subprocess,
        "run",
        lambda command, check=False: SimpleNamespace(returncode=1),
    )

    result = downloader.main([
        "--no-cookies",
        "--archive",
        str(archive),
        "--remove-completed-ids",
        "--queue-report",
        str(report_path),
        "--failed-targets",
        str(failed_path),
        str(queue),
    ])

    assert result == 1
    assert queue.read_text(encoding="utf-8") == "postprocess-failed\n"
    assert failed_path.read_text(encoding="utf-8") == "postprocess-failed\n"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["targets"]["completed"] == []
    assert report["targets"]["unresolved"] == ["postprocess-failed"]


def test_main_keeps_current_run_unresolved_when_completion_callback_does_not_rewrite_queue(
    downloader, tmp_path: Path, monkeypatch
) -> None:
    queue = tmp_path / "ids.txt"
    archive = tmp_path / "archive.txt"
    report_path = tmp_path / "queue-report.json"
    failed_path = tmp_path / "retry.txt"
    queue.write_text("callback-failed\n", encoding="utf-8")

    monkeypatch.setattr(downloader, "validate_environment", lambda *, dry_run: "yt-dlp")

    def simulated_callback_failure(command, check=False):
        assert check is False
        with archive.open("a", encoding="utf-8") as handle:
            handle.write("youtube callback-failed\n")
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(downloader.subprocess, "run", simulated_callback_failure)

    result = downloader.main([
        "--no-cookies",
        "--archive",
        str(archive),
        "--remove-completed-ids",
        "--queue-report",
        str(report_path),
        "--failed-targets",
        str(failed_path),
        str(queue),
    ])

    assert result == 1
    assert queue.read_text(encoding="utf-8") == "callback-failed\n"
    assert failed_path.read_text(encoding="utf-8") == "callback-failed\n"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["targets"]["completed"] == []
    assert report["targets"]["unresolved"] == ["callback-failed"]

    assert downloader.remove_archived_ids(queue, archive) == 1
    assert queue.read_text(encoding="utf-8") == ""


def test_internal_completion_callback_atomic_rewrite_failure_preserves_queue(
    downloader, tmp_path: Path, monkeypatch
) -> None:
    queue = tmp_path / "ids.txt"
    queue.write_text("abc\ndef\n", encoding="utf-8")

    def fail_replace(source, destination):
        raise OSError("simulated queue replace failure")

    monkeypatch.setattr(downloader.os, "replace", fail_replace)

    result = downloader.main(["--_remove-completed-id", str(queue), "abc"])

    assert result == 1
    assert queue.read_text(encoding="utf-8") == "abc\ndef\n"
    assert not list(tmp_path.glob(".ids.txt.tmp-*"))


def test_run_reports_process_start_failure_without_raising(downloader, monkeypatch) -> None:
    def fail_to_start(*args, **kwargs):
        raise OSError("simulated exec failure")

    monkeypatch.setattr(downloader.subprocess, "run", fail_to_start)
    assert downloader.run(["yt-dlp", "abc"], dry_run=False) == 1
