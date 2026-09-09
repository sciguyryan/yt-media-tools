"""Deterministic tests for first-class live-media policy."""

from __future__ import annotations


import pytest


def parse(downloader, *args: str):
    return downloader.build_parser().parse_args(list(args))


def test_wait_interval_validation(downloader) -> None:
    assert downloader._validate_wait_for_video_setting("60") == "60"
    assert downloader._validate_wait_for_video_setting("60-300") == "60-300"
    for value in ("", "0", "300-60", "1.5", "60-", "--foo"):
        with pytest.raises(ValueError):
            downloader._validate_wait_for_video_setting(value)


def test_live_options_require_explicit_live_mode(downloader) -> None:
    for settings in (
        {"live-from-start": True},
        {"wait-for-video": "60"},
        {"write-live-chat": True},
    ):
        with pytest.raises(ValueError, match="require explicit live mode"):
            downloader.resolve_parameter_policy(settings)


def test_profile_rejects_live_options_without_live_mode(downloader) -> None:
    with pytest.raises(ValueError, match="requires live=true"):
        downloader.validate_parameter_settings({"wait-for-video": "60-300"}, profile_name="broken")


def test_live_policy_builds_explicit_yt_dlp_boundaries(downloader) -> None:
    policy, _, _ = downloader.resolve_parameter_policy(
        {"live": True, "live-from-start": True, "wait-for-video": "60-300"}
    )
    command = downloader.build_yt_dlp_command("yt-dlp", policy, downloader.InputSource(direct_targets=("abc",)), None)
    assert "--live-from-start" in command
    assert command[command.index("--wait-for-video") + 1] == "60-300"
    assert "--no-wait-for-video" not in command


def test_plain_live_mode_makes_edge_and_no_wait_explicit(downloader) -> None:
    policy, _, _ = downloader.resolve_parameter_policy({"live": True})
    command = downloader.build_yt_dlp_command("yt-dlp", policy, downloader.InputSource(direct_targets=("abc",)), None)
    assert "--no-live-from-start" in command
    assert "--no-wait-for-video" in command


def test_live_chat_is_requested_as_sidecar_without_overwriting_subtitle_policy(downloader) -> None:
    policy, _, _ = downloader.resolve_parameter_policy(
        {"live": True, "write-live-chat": True, "write-subs": True, "sub-langs": "en.*"}
    )
    command = downloader.build_yt_dlp_command("yt-dlp", policy, downloader.InputSource(direct_targets=("abc",)), None)
    assert command.count("--write-subs") == 1
    assert command[command.index("--sub-langs") + 1] == "en.*,live_chat"


def test_live_chat_rejects_explicit_exclusion(downloader) -> None:
    policy, _, _ = downloader.resolve_parameter_policy(
        {"live": True, "write-live-chat": True, "sub-langs": "all,-live_chat"}
    )
    with pytest.raises(ValueError, match="sub-langs exclusion"):
        downloader.build_yt_dlp_command("yt-dlp", policy, downloader.InputSource(direct_targets=("abc",)), None)


def test_no_live_clears_inherited_live_policy(downloader, tmp_path) -> None:
    profile = downloader.ParameterProfile(
        name="scheduled",
        source=tmp_path / "defaults.json",
        settings={
            "live": True,
            "live-from-start": True,
            "wait-for-video": "60",
            "write-live-chat": True,
        },
    )
    merged = downloader.merge_parameter_settings(profile, {"live": False})
    assert merged == {"live": False}


def test_no_wait_for_video_removes_profile_wait(downloader, tmp_path) -> None:
    profile = downloader.ParameterProfile(
        name="scheduled",
        source=tmp_path / "defaults.json",
        settings={"live": True, "wait-for-video": "60-300"},
    )
    args = parse(downloader, "-p", "scheduled", "--no-wait-for-video", "abc")
    cli = downloader.explicit_parameter_settings(args)
    assert cli["wait-for-video"] is None
    merged = downloader.merge_parameter_settings(profile, cli)
    assert merged == {"live": True}


def test_live_cli_values_are_profile_eligible(downloader) -> None:
    args = parse(
        downloader,
        "--live",
        "--live-from-start",
        "--wait-for-video",
        "30-90",
        "--write-live-chat",
        "abc",
    )
    settings = downloader.explicit_parameter_settings(args)
    assert settings["live"] is True
    assert settings["live-from-start"] is True
    assert settings["wait-for-video"] == "30-90"
    assert settings["write-live-chat"] is True


def test_explain_reports_live_policy(downloader, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(downloader, "resolve_cookies", lambda *_args, **_kwargs: None)
    args = parse(
        downloader,
        "--live",
        "--live-from-start",
        "--wait-for-video",
        "60",
        "--write-live-chat",
        "abc",
    )
    cli_settings = downloader.explicit_parameter_settings(args)
    resolved = downloader.resolve_parameter_settings(None, cli_settings)
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
    assert payload["policy"]["live"] is True
    assert payload["policy"]["live_from_start"] is True
    assert payload["policy"]["wait_for_video"] == "60"
    assert payload["policy"]["write_live_chat"] is True


def test_existing_retry_policy_composes_without_hidden_live_defaults(downloader) -> None:
    policy, _, _ = downloader.resolve_parameter_policy(
        {
            "live": True,
            "retries": "infinite",
            "fragment-retries": "20",
            "retry-sleep": ["fragment:exp=1:20"],
        }
    )
    assert policy.retries == "infinite"
    assert policy.fragment_retries == "20"
    assert policy.retry_sleep == ("fragment:exp=1:20",)
