"""Machine-facing validation and capability reporting coverage."""

from __future__ import annotations

import json


def test_validate_config_uses_runtime_profile_validation(downloader, tmp_path, capsys) -> None:
    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps({"version": downloader.PARAMETER_PROFILE_VERSION, "profiles": {"audio": {"audio-only": True}}}),
        encoding="utf-8",
    )
    assert downloader.main(["--validate-config", str(path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["kind"] == "yt-download-config-validation"
    assert payload["schema_version"] == downloader.CONFIG_VALIDATION_SCHEMA_VERSION == 1
    assert payload["valid"] is True
    assert payload["profile_count"] == 1
    assert payload["profiles"] == ["audio"]


def test_validate_config_rejects_runtime_semantic_error(downloader, tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {"version": downloader.PARAMETER_PROFILE_VERSION, "profiles": {"bad": {"min-fps": 60, "max-fps": 30}}}
        ),
        encoding="utf-8",
    )
    try:
        downloader.main(["--validate-config", str(path)])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("invalid configuration unexpectedly passed validation")


def test_capabilities_json_is_versioned_and_conservative(downloader, monkeypatch, capsys) -> None:
    monkeypatch.setattr(downloader.shutil, "which", lambda name: None)
    assert downloader.main(["--capabilities-json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["kind"] == "yt-download-capabilities"
    assert payload["schema_version"] == downloader.CAPABILITIES_SCHEMA_VERSION == 1
    assert payload["contract_version"] == downloader.MACHINE_CONTRACT_VERSION
    assert payload["downloader"]["version"] == downloader.PROGRAM_VERSION
    assert payload["external_tools"]["yt-dlp"]["available"] is False
    assert payload["external_tools"]["ffmpeg"]["available"] is False
    assert payload["interfaces"]["execution_request_schema"] is False


def test_capabilities_reports_first_version_line(downloader, monkeypatch, capsys) -> None:
    class Completed:
        stdout = "yt-dlp 2099.01.01\nextra\n"
        stderr = ""

    monkeypatch.setattr(downloader.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(downloader.subprocess, "run", lambda *args, **kwargs: Completed())
    assert downloader.main(["--capabilities"]) == 0
    output = capsys.readouterr().out
    assert "yt-dlp: available - yt-dlp 2099.01.01" in output
    assert "ffmpeg: available - yt-dlp 2099.01.01" in output


def test_machine_contract_advertises_current_and_future_interfaces(downloader) -> None:
    contract = downloader.machine_contract()
    assert contract["machine_interfaces"]["config_validation"]["cli"] == "--validate-config [FILE]"
    assert contract["machine_interfaces"]["capabilities"]["stability"] == "versioned"
    assert contract["future_machine_interfaces"]["execution_request_schema"] == "planned"
    assert contract["future_machine_interfaces"]["manifest_retry"] == "depends-on-structured-outcomes"


def test_validate_config_handles_unicode_path_and_profile_name(downloader, tmp_path, capsys) -> None:
    directory = tmp_path / "設定"
    directory.mkdir()
    path = directory / "プロファイル.json"
    path.write_text(
        json.dumps(
            {"version": downloader.PARAMETER_PROFILE_VERSION, "profiles": {"audio": {"audio-only": True}}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert downloader.main(["--validate-config", str(path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["profiles"] == ["audio"]
    assert payload["path"].endswith("設定/プロファイル.json")


def test_capability_probe_failure_does_not_make_tool_unavailable(downloader, monkeypatch) -> None:
    monkeypatch.setattr(downloader.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fail(*args, **kwargs):
        raise downloader.subprocess.TimeoutExpired(args[0], 5)

    monkeypatch.setattr(downloader.subprocess, "run", fail)
    payload = downloader.capabilities_payload()
    assert payload["external_tools"]["yt-dlp"] == {
        "available": True,
        "executable": "/usr/bin/yt-dlp",
        "version": None,
    }
