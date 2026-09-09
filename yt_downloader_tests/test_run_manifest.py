"""Run-manifest and primary-output integrity behaviour."""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest


def make_plan(downloader, tmp_path: Path, *, extractor_args: list[str] | None = None):
    settings: dict[str, object] = {"no-cookies": True}
    if extractor_args is not None:
        settings["extractor-args"] = extractor_args
    resolved = downloader.ResolvedParameterSettings(settings=settings, sources={})
    return downloader.create_download_plan(
        executable="yt-dlp",
        resolved_parameters=resolved,
        input_source=downloader.InputSource(direct_targets=("abc",)),
        output_profile=None,
        defaults_file=tmp_path / "defaults.json",
        parameter_profile=None,
        remove_completed_ids=False,
    )


def test_output_record_round_trip_is_stable_and_deduplicated(downloader, tmp_path: Path) -> None:
    ledger = tmp_path / "events.jsonl"
    first = tmp_path / "one video.mkv"
    second = tmp_path / "two.mkv"
    downloader.append_output_record(ledger, "one", str(first))
    downloader.append_output_record(ledger, "one", str(first))
    downloader.append_output_record(ledger, "two", str(second))
    assert downloader.read_output_records(ledger) == (
        {"id": "one", "path": str(first.resolve())},
        {"id": "two", "path": str(second.resolve())},
    )


def test_invalid_output_record_is_rejected(downloader, tmp_path: Path) -> None:
    ledger = tmp_path / "events.jsonl"
    ledger.write_text('{"wrong": "value"}\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="missing media ID"):
        downloader.read_output_records(ledger)


def test_sha256_file_matches_known_digest(downloader, tmp_path: Path) -> None:
    output = tmp_path / "output.bin"
    output.write_bytes(b"abc")
    assert downloader.sha256_file(output) == ("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


def test_output_manifest_entries_distinguish_present_and_missing_files(downloader, tmp_path: Path) -> None:
    present = tmp_path / "present.bin"
    missing = tmp_path / "missing.bin"
    present.write_bytes(b"payload")
    entries = downloader.output_manifest_entries(
        ({"id": "present", "path": str(present)}, {"id": "missing", "path": str(missing)}),
        hash_outputs=True,
    )
    assert entries[0]["id"] == "present"
    assert entries[0]["path"] == str(present)
    assert entries[0]["exists"] is True
    assert entries[0]["size_bytes"] == 7
    assert isinstance(entries[0]["sha256"], str)
    assert entries[1] == {"id": "missing", "path": str(missing), "exists": False, "sha256": None}


def test_run_manifest_reuses_redacted_plan_payload(downloader, tmp_path: Path) -> None:
    plan = make_plan(
        downloader,
        tmp_path,
        extractor_args=["youtube:player-client=tv;po_token=web.gvs+TOPSECRET;innertube_key=APISECRET"],
    )
    manifest = downloader.run_manifest_payload(
        plan=plan,
        yt_dlp_version_value="2026.09.01",
        started_at="2026-09-09T10:00:00Z",
        ended_at="2026-09-09T10:01:00Z",
        exit_status=0,
        targets=["abc"],
        outputs=[],
        queue_report=None,
        hash_outputs=False,
    )
    rendered = json.dumps(manifest)
    assert manifest["kind"] == "yt-download-run-manifest"
    assert manifest["schema_version"] == 1
    assert "TOPSECRET" not in rendered
    assert "APISECRET" not in rendered
    assert "po_token=<redacted>" in rendered
    assert "innertube_key=<redacted>" in rendered
    assert manifest["integrity"]["sha256_requested"] is False
    assert "not proof of authenticity or provenance" in manifest["integrity"]["meaning"]


def test_run_manifest_records_unknown_stdin_targets_without_consuming_input(downloader) -> None:
    source = downloader.InputSource(stdin=True)
    assert downloader.manifest_input_targets(source) is None


def test_yt_dlp_version_is_optional_on_failure(downloader, monkeypatch) -> None:
    monkeypatch.setattr(
        downloader.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="failure"),
    )
    assert downloader.yt_dlp_version("yt-dlp") is None


def test_yt_dlp_version_strips_successful_output(downloader, monkeypatch) -> None:
    monkeypatch.setattr(
        downloader.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="2026.09.01\n", stderr=""),
    )
    assert downloader.yt_dlp_version("yt-dlp") == "2026.09.01"


def test_hash_outputs_requires_run_manifest(downloader) -> None:
    with pytest.raises(SystemExit) as caught:
        downloader.main(["--hash-outputs", "--no-cookies", "abc"])
    assert caught.value.code == 2


def test_run_manifest_is_rejected_for_dry_run(downloader, tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as caught:
        downloader.main(["--dry-run", "--run-manifest", str(tmp_path / "run.json"), "abc"])
    assert caught.value.code == 2


def test_instrumented_command_records_outputs_before_queue_callback(downloader, tmp_path: Path) -> None:
    queue = tmp_path / "ids.txt"
    queue.write_text("abc\n", encoding="utf-8")
    resolved = downloader.ResolvedParameterSettings(settings={"no-cookies": True}, sources={})
    plan = downloader.create_download_plan(
        executable="yt-dlp",
        resolved_parameters=resolved,
        input_source=downloader.InputSource(batch_file=queue),
        output_profile=None,
        defaults_file=tmp_path / "defaults.json",
        parameter_profile=None,
        remove_completed_ids=True,
    )
    ledger = tmp_path / "events.jsonl"
    command = plan.command(output_event_file=ledger)
    callbacks = [command[index + 1] for index, value in enumerate(command) if value == "--exec"]
    assert len(callbacks) == 2
    assert "--_record-output" in callbacks[0]
    assert "--_remove-completed-id" in callbacks[1]


def test_main_writes_hashed_manifest_from_simulated_after_move_event(downloader, tmp_path: Path, monkeypatch) -> None:
    manifest_path = tmp_path / "run.json"
    output = tmp_path / "media output.mkv"
    output.write_bytes(b"completed media")
    event_ledgers: list[Path] = []

    monkeypatch.setattr(downloader, "validate_environment", lambda *, dry_run: "yt-dlp")
    times = iter(("2026-09-09T10:00:00Z", "2026-09-09T10:01:00Z"))
    monkeypatch.setattr(downloader, "utc_timestamp", lambda: next(times))

    def simulated_process(command, check=False, **kwargs):
        assert check is False
        if command == ["yt-dlp", "--version"]:
            return SimpleNamespace(returncode=0, stdout="2026.09.01\n", stderr="")
        callbacks = [command[index + 1] for index, value in enumerate(command) if value == "--exec"]
        output_callback = next(value for value in callbacks if "--_record-output" in value)
        match = re.search(r"--_record-output\s+([^ ]+)", output_callback)
        assert match is not None
        ledger = Path(match.group(1).strip("'\""))
        event_ledgers.append(ledger)
        assert downloader.main(["--_record-output", str(ledger), "abc", str(output)]) == 0
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(downloader.subprocess, "run", simulated_process)
    result = downloader.main(
        [
            "--no-cookies",
            "--extractor-args",
            "youtube:po_token=web.gvs+TOPSECRET",
            "--run-manifest",
            str(manifest_path),
            "--hash-outputs",
            "abc",
        ]
    )

    assert result == 0
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["downloader"]["version"] == "1.15.0"
    assert manifest["yt_dlp"] == {"version": "2026.09.01", "exit_status": 0}
    assert manifest["run"] == {
        "started_at": "2026-09-09T10:00:00Z",
        "ended_at": "2026-09-09T10:01:00Z",
        "interrupted": False,
    }
    assert manifest["input"] == {"targets": ["abc"], "targets_known": True}
    assert manifest["outputs"]["primary"] == [
        {
            "id": "abc",
            "path": str(output.resolve()),
            "exists": True,
            "size_bytes": len(b"completed media"),
            "sha256": downloader.sha256_file(output),
        }
    ]
    rendered = manifest_path.read_text(encoding="utf-8")
    assert "TOPSECRET" not in rendered
    assert event_ledgers and all(not path.exists() for path in event_ledgers)


def test_main_writes_manifest_after_simulated_interruption(downloader, tmp_path: Path, monkeypatch) -> None:
    manifest_path = tmp_path / "run.json"
    monkeypatch.setattr(downloader, "validate_environment", lambda *, dry_run: "yt-dlp")
    monkeypatch.setattr(downloader, "yt_dlp_version", lambda executable: "2026.09.01")
    times = iter(("2026-09-09T10:00:00Z", "2026-09-09T10:00:05Z"))
    monkeypatch.setattr(downloader, "utc_timestamp", lambda: next(times))

    def interrupt(command, check=False):
        raise KeyboardInterrupt

    monkeypatch.setattr(downloader.subprocess, "run", interrupt)
    assert downloader.main(["--no-cookies", "--run-manifest", str(manifest_path), "abc"]) == 130
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["yt_dlp"]["exit_status"] == 130
    assert manifest["run"]["interrupted"] is True
    assert manifest["outputs"]["primary"] == []


def test_manifest_write_failure_does_not_mask_download_failure(downloader, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(downloader, "validate_environment", lambda *, dry_run: "yt-dlp")
    monkeypatch.setattr(downloader, "yt_dlp_version", lambda executable: None)
    monkeypatch.setattr(downloader, "run", lambda command, *, dry_run: 7)

    def fail_manifest(path, manifest):
        raise RuntimeError("boom")

    monkeypatch.setattr(downloader, "write_run_manifest", fail_manifest)
    result = downloader.main(["--no-cookies", "--run-manifest", str(tmp_path / "run.json"), "abc"])
    assert result == 7
