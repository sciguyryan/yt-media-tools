"""Versioned machine-contract and parameter-profile schema coverage."""

from __future__ import annotations

import json


def test_machine_contract_versions_are_explicit(downloader) -> None:
    contract = downloader.machine_contract()
    assert contract["contract_version"] == downloader.MACHINE_CONTRACT_VERSION == 1
    assert contract["downloader"] == {
        "name": downloader.PROGRAM_NAME,
        "version": downloader.PROGRAM_VERSION,
    }
    assert contract["json_schema_dialect"] == downloader.JSON_SCHEMA_DIALECT
    assert contract["parameter_profiles"]["format_version"] == downloader.PARAMETER_PROFILE_VERSION


def test_settings_schema_covers_every_runtime_profile_key_exactly(downloader) -> None:
    schema = downloader.parameter_profile_setting_schema()
    assert schema["additionalProperties"] is False
    assert list(schema["properties"]) == list(downloader.PARAMETER_PROFILE_KEYS)
    assert set(schema["properties"]) == set(downloader.PARAMETER_PROFILE_KEYS)
    assert set(downloader.PARAMETER_SETTING_DESCRIPTIONS) == set(downloader.PARAMETER_PROFILE_KEYS)


def test_profile_file_schema_is_versioned_and_reuses_settings_definition(downloader) -> None:
    schema = downloader.parameter_profile_file_schema()
    assert schema["$schema"] == downloader.JSON_SCHEMA_DIALECT
    assert schema["properties"]["version"] == {"const": downloader.PARAMETER_PROFILE_VERSION}
    assert schema["properties"]["profiles"]["additionalProperties"] == {"$ref": "#/$defs/settings"}
    assert schema["$defs"]["settings"]["additionalProperties"] is False


def test_schema_exposes_canonical_values_for_finite_case_insensitive_settings(downloader) -> None:
    properties = downloader.parameter_profile_setting_schema()["properties"]
    assert properties["preferred-hdr"]["x-downloader-canonical-values"] == ["sdr", "hdr", "dv"]
    assert properties["merge-container"]["x-downloader-canonical-values"] == sorted(
        downloader.SUPPORTED_MERGE_CONTAINERS
    )
    assert properties["audio-format"]["x-downloader-canonical-values"] == sorted(downloader.SUPPORTED_AUDIO_FORMATS)


def test_schema_describes_cross_field_constraints(downloader) -> None:
    schema = downloader.parameter_profile_setting_schema()
    rendered = json.dumps(schema["allOf"], sort_keys=True)
    assert "audio-quality" in rendered
    assert "audio-format" in rendered
    assert "cookies-from-browser" in rendered
    assert "playlist-items" in rendered
    assert "live-from-start" in rendered
    assert "wait-for-video" in rendered
    assert "write-live-chat" in rendered


def test_schema_json_is_available_without_yt_dlp_or_configuration(downloader, monkeypatch, capsys) -> None:
    monkeypatch.setattr(downloader.shutil, "which", lambda _: None)
    assert downloader.main(["--schema-json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == downloader.machine_contract()


def test_schema_json_rejects_other_arguments(downloader) -> None:
    for argv in (["--schema-json", "abc123"], ["--schema-json", "--resolution", "1080"]):
        try:
            downloader.main(argv)
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError(f"--schema-json unexpectedly accepted additional arguments: {argv!r}")


def test_machine_contract_serialisation_is_deterministic(downloader) -> None:
    first = json.dumps(downloader.machine_contract(), indent=2, sort_keys=True)
    second = json.dumps(downloader.machine_contract(), indent=2, sort_keys=True)
    assert first == second
