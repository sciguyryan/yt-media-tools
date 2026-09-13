"""Deterministic tests for partial-media and section acquisition policy."""

from __future__ import annotations

from pathlib import Path

import pytest


def parse(downloader, *args: str):
    return downloader.build_parser().parse_args(list(args))


def test_time_range_validation_accepts_clock_seconds_negative_and_infinite(downloader) -> None:
    assert downloader._normalise_time_range(("10", "20")) == "10-20"
    assert downloader._normalise_time_range(("1:02", "2:03.5")) == "1:02-2:03.5"
    assert downloader._normalise_time_range(("-30", "inf")) == "-30-inf"
    assert downloader._normalise_time_range(("-60", "-10")) == "-60--10"


@pytest.mark.parametrize(
    "value",
    [
        ("20", "10"),
        ("1:60", "2:00"),
        ("00:59", "00:59"),
        ("not-time", "10"),
        ("10", "forever"),
    ],
)
def test_time_range_validation_rejects_invalid_ranges(downloader, value) -> None:
    with pytest.raises(ValueError):
        downloader._normalise_time_range(value)


def test_chapter_sections_are_regex_validated(downloader) -> None:
    assert downloader._validate_chapter_sections_setting(["^Intro$", "Part [12]"]) == [
        "^Intro$",
        "Part [12]",
    ]
    with pytest.raises(ValueError, match="regular expression"):
        downloader._validate_chapter_sections_setting(["["])


def test_partial_cli_settings_are_profile_eligible(downloader) -> None:
    args = parse(
        downloader,
        "--chapter-section",
        "^Intro$",
        "--time-range",
        "10",
        "1:20",
        "abc",
    )
    assert downloader.explicit_parameter_settings(args) == {
        "chapter-sections": ["^Intro$"],
        "time-ranges": ["10-1:20"],
    }


def test_whole_item_clears_inherited_partial_policy(downloader, tmp_path: Path) -> None:
    profile = downloader.ParameterProfile(
        name="extract",
        source=tmp_path / "defaults.json",
        settings={"chapter-sections": ["Intro"], "time-ranges": ["10-20"]},
    )
    args = parse(downloader, "-p", "extract", "--whole-item", "abc")
    cli = downloader.explicit_parameter_settings(args)
    assert downloader.merge_parameter_settings(profile, cli) == {}


def test_partial_media_rejects_live_mode(downloader) -> None:
    with pytest.raises(ValueError, match="cannot be combined with live mode"):
        downloader.resolve_parameter_policy({"live": True, "time-ranges": ["10-20"]})


def test_partial_command_disables_whole_item_archive_and_uses_section_naming(downloader) -> None:
    policy, _, _ = downloader.resolve_parameter_policy({"chapter-sections": ["^Intro$"], "time-ranges": ["10-20"]})
    command = downloader.build_yt_dlp_command(
        "yt-dlp",
        policy,
        downloader.InputSource(direct_targets=("abc",)),
        None,
    )
    assert "--no-download-archive" in command
    assert "--download-archive" not in command
    sections = [command[index + 1] for index, value in enumerate(command) if value == "--download-sections"]
    assert sections == ["^Intro$", "*10-20"]
    output = command[command.index("--output") + 1]
    assert "%(section_number)03d" in output
    assert "%(section_title)s" in output


def test_partial_output_naming_overrides_profile_filename_but_preserves_home(downloader, tmp_path: Path) -> None:
    policy, _, _ = downloader.resolve_parameter_policy({"time-ranges": ["10-20"]})
    profile = downloader.OutputProfile(
        source=tmp_path / "profile",
        path="/media/output",
        output="%(title)s.%(ext)s",
    )
    command = downloader.build_yt_dlp_command(
        "yt-dlp",
        policy,
        downloader.InputSource(direct_targets=("abc",)),
        profile,
    )
    assert "%(title)s.%(ext)s" not in command
    assert "home:/media/output" in command
    assert any("%(section_number)03d" in item for item in command)


def test_whole_item_command_keeps_archive_and_profile_output(downloader, tmp_path: Path) -> None:
    policy, _, _ = downloader.resolve_parameter_policy({})
    profile = downloader.OutputProfile(
        source=tmp_path / "profile",
        path="/media/output",
        output="%(title)s.%(ext)s",
    )
    command = downloader.build_yt_dlp_command(
        "yt-dlp", policy, downloader.InputSource(direct_targets=("abc",)), profile
    )
    assert "--download-archive" in command
    assert "--no-download-archive" not in command
    assert "%(title)s.%(ext)s" in command


def test_partial_media_rejects_completed_id_queue_mutation(downloader, tmp_path: Path) -> None:
    queue = tmp_path / "ids.txt"
    queue.write_text("abc\n", encoding="utf-8")
    resolved = downloader.ResolvedParameterSettings(settings={"time-ranges": ["10-20"]}, sources={})
    with pytest.raises(ValueError, match="does not establish completion"):
        downloader.create_download_plan(
            executable="yt-dlp",
            resolved_parameters=resolved,
            input_source=downloader.InputSource(batch_file=queue),
            output_profile=None,
            defaults_file=tmp_path / "defaults.json",
            parameter_profile=None,
            remove_completed_ids=True,
        )


def test_explain_reports_derivative_partial_policy(downloader, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(downloader, "resolve_cookies", lambda *_args, **_kwargs: None)
    resolved = downloader.ResolvedParameterSettings(
        settings={"chapter-sections": ["Intro"], "time-ranges": ["10-20"]},
        sources={"chapter-sections": "explicit CLI", "time-ranges": "explicit CLI"},
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
    payload = downloader.explain_plan_payload(plan)
    assert payload["policy"]["partial_media"] is True
    assert payload["policy"]["download_sections"] == ["Intro", "*10-20"]
    assert payload["paths"]["archive_enabled"] is False
