"""Versioned machine-contract and parameter-profile schema coverage."""

from __future__ import annotations

import json


def test_machine_contract_versions_are_explicit(downloader) -> None:
    contract = downloader.machine_contract()
    assert contract["contract_version"] == downloader.MACHINE_CONTRACT_VERSION == 4
    assert contract["downloader"] == {
        "name": downloader.PROGRAM_NAME,
        "version": downloader.PROGRAM_VERSION,
    }
    assert contract["json_schema_dialect"] == downloader.JSON_SCHEMA_DIALECT
    assert contract["profiles"]["format_version"] == downloader.PROFILE_VERSION == 3
    assert contract["profiles"]["references"]["namespace"] == "$values"
    assert contract["profiles"]["references"]["type_preserving"] is True


def test_settings_schema_covers_every_runtime_profile_key_exactly(downloader) -> None:
    schema = downloader.profile_setting_schema()
    assert schema["additionalProperties"] is False
    assert list(schema["properties"]) == list(downloader.PROFILE_KEYS)
    assert set(schema["properties"]) == set(downloader.PROFILE_KEYS)
    assert set(downloader.PROFILE_SETTING_DESCRIPTIONS) == set(downloader.PROFILE_KEYS)


def test_profile_file_schema_is_versioned_and_reuses_settings_definition(downloader) -> None:
    schema = downloader.profile_file_schema()
    assert schema["$schema"] == downloader.JSON_SCHEMA_DIALECT
    assert schema["properties"]["version"] == {"const": downloader.PROFILE_VERSION}
    assert schema["properties"]["profiles"]["additionalProperties"] == {"$ref": "#/$defs/profile"}
    assert schema["$defs"]["settings"]["additionalProperties"] is False
    assert "values" in schema["properties"]
    assert any(
        option.get("pattern") == downloader.VALUE_REFERENCE_RE.pattern
        for option in schema["$defs"]["settings"]["properties"]["path"]["anyOf"]
    )


def test_schema_exposes_canonical_values_for_finite_case_insensitive_settings(downloader) -> None:
    properties = downloader.profile_setting_schema()["properties"]
    assert properties["preferred-hdr"]["x-downloader-canonical-values"] == ["sdr", "hdr", "dv"]
    assert properties["merge-container"]["x-downloader-canonical-values"] == sorted(
        downloader.SUPPORTED_MERGE_CONTAINERS
    )
    assert properties["audio-format"]["x-downloader-canonical-values"] == sorted(downloader.SUPPORTED_AUDIO_FORMATS)


def test_schema_describes_cross_field_constraints(downloader) -> None:
    schema = downloader.profile_setting_schema()
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


def test_explain_json_contract_has_independent_schema_version(downloader, tmp_path) -> None:
    plan = downloader.create_download_plan(
        executable="yt-dlp",
        resolved_profile=downloader.resolve_profile_settings(None, {}),
        input_source=downloader.InputSource(direct_targets=("abc123",)),
        output_profile=None,
        defaults_file=tmp_path / "defaults.json",
        profile=None,
        remove_completed_ids=False,
    )
    payload = downloader.explain_plan_payload(plan)
    assert payload["kind"] == "yt-download-plan"
    assert payload["schema_version"] == downloader.PLAN_SCHEMA_VERSION == 3
    assert downloader.machine_contract()["machine_interfaces"]["explain"]["schema_version"] == 3


def test_every_public_cli_destination_has_an_explicit_persistence_class(downloader) -> None:
    parser = downloader.build_parser()
    public_destinations = {
        action.dest for action in parser._actions if action.dest != "help" and not action.dest.startswith("_")
    }
    classified = set().union(*downloader.CLI_DESTINATION_CLASSES.values())
    assert classified == public_destinations
    total_memberships = sum(len(destinations) for destinations in downloader.CLI_DESTINATION_CLASSES.values())
    assert total_memberships == len(classified)


def test_machine_contract_exposes_cli_persistence_classification(downloader) -> None:
    contract = downloader.machine_contract()
    classes = contract["profiles"]["cli_destination_classes"]
    assert "impersonate" in classes["profile-policy"]
    assert "run_manifest" in classes["reporting-side-effect"]
    assert "dry_run" in classes["execution-mode"]
    assert "targets" in classes["input"]


def test_profile_schema_describes_hierarchy(downloader) -> None:
    schema = downloader.profile_file_schema()
    assert schema["properties"]["$defaults"] == {"$ref": "#/$defs/settings"}
    assert schema["$defs"]["profile"]["properties"]["parent"] == {
        "type": "string",
        "pattern": downloader.PROFILE_NAME_RE.pattern,
    }
    inheritance = downloader.machine_contract()["profiles"]["inheritance"]
    assert inheritance == {
        "model": "single-parent",
        "implicit_root": "$defaults",
        "root_optional": True,
        "cycles": "error",
    }
