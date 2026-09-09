"""Subtitle, metadata, thumbnail and SponsorBlock policy coverage."""

from __future__ import annotations

from pathlib import Path

import pytest


def _command(downloader, policy):
    return downloader.build_yt_dlp_command(
        "yt-dlp",
        policy,
        downloader.InputSource(direct_targets=("abc",)),
        None,
    )


def test_historical_metadata_chapter_and_sponsorblock_defaults_are_preserved(downloader) -> None:
    policy = downloader.DownloadPolicy(
        resolution="1440",
        format_selector=downloader.FORMAT_SELECTOR,
        reverse_playlist=False,
    )
    command = _command(downloader, policy)
    assert "--embed-metadata" in command
    assert "--embed-chapters" in command
    index = command.index("--sponsorblock-remove")
    assert command[index + 1] == "all"
    assert "--write-subs" not in command
    assert "--write-thumbnail" not in command
    assert "--write-info-json" not in command


def test_subtitle_policy_compiles_to_explicit_yt_dlp_options(downloader) -> None:
    policy = downloader.DownloadPolicy(
        resolution="1440",
        format_selector=downloader.FORMAT_SELECTOR,
        reverse_playlist=False,
        write_subtitles=True,
        write_auto_subtitles=True,
        subtitle_languages="en.*,cy",
        subtitle_format="srt/best",
        embed_subtitles=True,
    )
    command = _command(downloader, policy)
    assert "--write-subs" in command
    assert "--write-auto-subs" in command
    assert command[command.index("--sub-langs") + 1] == "en.*,cy"
    assert command[command.index("--sub-format") + 1] == "srt/best"
    assert "--embed-subs" in command


def test_thumbnail_and_info_json_sidecars_are_opt_in(downloader) -> None:
    policy = downloader.DownloadPolicy(
        resolution="1440",
        format_selector=downloader.FORMAT_SELECTOR,
        reverse_playlist=False,
        write_thumbnail=True,
        embed_thumbnail=True,
        write_info_json=True,
    )
    command = _command(downloader, policy)
    assert "--write-thumbnail" in command
    assert "--embed-thumbnail" in command
    assert "--write-info-json" in command


def test_metadata_and_chapter_defaults_can_be_explicitly_disabled(downloader) -> None:
    policy = downloader.DownloadPolicy(
        resolution="1440",
        format_selector=downloader.FORMAT_SELECTOR,
        reverse_playlist=False,
        embed_metadata=False,
        embed_chapters=False,
    )
    command = _command(downloader, policy)
    assert "--no-embed-metadata" in command
    assert "--no-embed-chapters" in command
    assert "--embed-metadata" not in command
    assert "--embed-chapters" not in command


def test_sponsorblock_policy_validates_mark_and_remove_categories(downloader) -> None:
    settings = downloader.validate_parameter_settings(
        {
            "sponsorblock-mark": "all,-preview",
            "sponsorblock-remove": "sponsor,selfpromo",
        },
        profile_name="chapters",
    )
    assert settings["sponsorblock-mark"] == "all,-preview"
    assert settings["sponsorblock-remove"] == "sponsor,selfpromo"

    with pytest.raises(ValueError, match="unsupported SponsorBlock category"):
        downloader.validate_parameter_settings(
            {"sponsorblock-remove": "chapter"},
            profile_name="broken",
        )


def test_sponsorblock_can_be_disabled_without_emitting_cut_policy(downloader) -> None:
    policy = downloader.DownloadPolicy(
        resolution="1440",
        format_selector=downloader.FORMAT_SELECTOR,
        reverse_playlist=False,
        sponsorblock=False,
    )
    command = _command(downloader, policy)
    assert "--no-sponsorblock" in command
    assert "--sponsorblock-mark" not in command
    assert "--sponsorblock-remove" not in command


def test_cli_false_values_override_parameter_profile_booleans(downloader, tmp_path: Path) -> None:
    parser = downloader.build_parser()
    args = parser.parse_args(
        [
            "-p",
            "rich",
            "--no-write-subs",
            "--no-embed-metadata",
            "--no-sponsorblock",
            "abc",
        ]
    )
    cli = downloader.explicit_parameter_settings(args)
    profile = downloader.ParameterProfile(
        name="rich",
        source=tmp_path / "defaults.json",
        settings={
            "write-subs": True,
            "embed-metadata": True,
            "sponsorblock": True,
        },
    )
    merged = downloader.merge_parameter_settings(profile, cli)
    assert merged["write-subs"] is False
    assert merged["embed-metadata"] is False
    assert merged["sponsorblock"] is False


def test_artifact_policy_is_visible_in_explain_payload(downloader, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(downloader, "COOKIES_FILE", tmp_path / "missing-cookies.txt")
    resolved = downloader.ResolvedParameterSettings(
        settings={
            "write-subs": True,
            "sub-langs": "en.*,cy",
            "embed-subs": True,
            "write-thumbnail": True,
            "write-info-json": True,
            "embed-chapters": False,
            "sponsorblock-mark": "sponsor,intro",
            "sponsorblock-remove": "selfpromo",
            "no-cookies": True,
        },
        sources={"write-subs": "explicit CLI"},
    )
    plan = downloader.create_download_plan(
        executable="yt-dlp",
        resolved_parameters=resolved,
        input_source=downloader.InputSource(direct_targets=("abc",)),
        output_profile=None,
        defaults_file=tmp_path / "defaults.json",
        parameter_profile=None,
        remove_completed_ids=False,
    )
    policy = downloader.explain_plan_payload(plan)["policy"]
    assert policy["write_subtitles"] is True
    assert policy["subtitle_languages"] == "en.*,cy"
    assert policy["embed_subtitles"] is True
    assert policy["write_thumbnail"] is True
    assert policy["write_info_json"] is True
    assert policy["embed_chapters"] is False
    assert policy["sponsorblock_mark"] == "sponsor,intro"
    assert policy["sponsorblock_remove"] == "selfpromo"


def test_explicit_sponsorblock_categories_reenable_profile_disabled_policy(downloader, tmp_path: Path) -> None:
    profile = downloader.ParameterProfile(
        name="quiet",
        source=tmp_path / "defaults.json",
        settings={"sponsorblock": False},
    )
    merged = downloader.merge_parameter_settings(profile, {"sponsorblock-mark": "sponsor"})
    policy, _, _ = downloader.resolve_parameter_policy({**merged, "no-cookies": True})
    assert policy.sponsorblock is True
    assert policy.sponsorblock_mark == "sponsor"


def test_explicit_no_sponsorblock_discards_profile_category_policy(downloader, tmp_path: Path) -> None:
    profile = downloader.ParameterProfile(
        name="cuts",
        source=tmp_path / "defaults.json",
        settings={"sponsorblock-mark": "sponsor", "sponsorblock-remove": "intro"},
    )
    merged = downloader.merge_parameter_settings(profile, {"sponsorblock": False})
    assert merged == {"sponsorblock": False}
