"""Declarative Downloader format-policy validation and command compilation."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_hard_format_constraints_compile_into_video_and_combined_fallbacks(downloader) -> None:
    policy = downloader.DownloadPolicy(
        resolution="1440",
        format_selector=downloader.FORMAT_SELECTOR,
        reverse_playlist=False,
        min_resolution=1080,
        max_resolution=2160,
        min_fps=30,
        max_fps=60,
    )
    assert policy.effective_format_selector == (
        "bv[height>=1080][height<=2160][fps>=30][fps<=60]+ba/b[height>=1080][height<=2160][fps>=30][fps<=60]"
    )


def test_format_preferences_compile_to_sort_order_without_becoming_filters(downloader) -> None:
    policy = downloader.DownloadPolicy(
        resolution="2160",
        format_selector=downloader.FORMAT_SELECTOR,
        reverse_playlist=False,
        preferred_video_codec="av01",
        preferred_audio_codec="opus",
        preferred_fps=60,
        preferred_hdr="hdr",
        preferred_audio_channels=6,
    )
    assert policy.effective_format_selector == downloader.FORMAT_SELECTOR
    assert policy.sort_selector == "vcodec:av01,acodec:opus,channels:6,fps:60,hdr:12,res:2160,lang,fps,size"


@pytest.mark.parametrize(
    ("preference", "expected"),
    [("sdr", "+hdr"), ("hdr", "hdr:12"), ("dv", "hdr")],
)
def test_hdr_preferences_map_to_documented_yt_dlp_sort_semantics(downloader, preference: str, expected: str) -> None:
    policy = downloader.DownloadPolicy(
        resolution="best",
        format_selector=downloader.FORMAT_SELECTOR,
        reverse_playlist=False,
        preferred_hdr=preference,
    )
    assert policy.sort_selector.startswith(f"{expected},")


def test_merge_container_is_only_added_for_merge_output_policy(downloader) -> None:
    policy = downloader.DownloadPolicy(
        resolution="1440",
        format_selector=downloader.FORMAT_SELECTOR,
        reverse_playlist=False,
        merge_container="mkv",
    )
    command = downloader.build_yt_dlp_command(
        "yt-dlp",
        policy,
        downloader.InputSource(direct_targets=("abc",)),
        None,
    )
    index = command.index("--merge-output-format")
    assert command[index + 1] == "mkv"
    assert "--remux-video" not in command
    assert "--recode-video" not in command


def test_format_profile_accepts_typed_constraints_and_preferences(downloader, tmp_path: Path) -> None:
    settings = downloader.validate_parameter_settings(
        {
            "min-resolution": 1080,
            "max-resolution": "2160p",
            "min-fps": 30,
            "max-fps": 60,
            "preferred-fps": 60,
            "preferred-video-codec": "AV01",
            "preferred-audio-codec": "opus",
            "preferred-hdr": "HDR",
            "preferred-audio-channels": 6,
            "merge-container": "MKV",
        },
        profile_name="cinema",
    )
    assert settings == {
        "min-resolution": 1080,
        "max-resolution": 2160,
        "min-fps": 30,
        "max-fps": 60,
        "preferred-fps": 60,
        "preferred-video-codec": "av01",
        "preferred-audio-codec": "opus",
        "preferred-hdr": "hdr",
        "preferred-audio-channels": 6,
        "merge-container": "mkv",
    }


def test_format_profile_rejects_inverted_hard_bounds(downloader) -> None:
    with pytest.raises(ValueError, match="min-resolution above max-resolution"):
        downloader.validate_parameter_settings(
            {"min-resolution": 2160, "max-resolution": 1080},
            profile_name="broken",
        )
    with pytest.raises(ValueError, match="min-fps above max-fps"):
        downloader.validate_parameter_settings(
            {"min-fps": 60, "max-fps": 30},
            profile_name="broken",
        )


def test_resolved_cli_and_profile_bounds_are_revalidated_after_merge(downloader, tmp_path: Path) -> None:
    profile = downloader.ParameterProfile(
        name="bounded",
        source=tmp_path / "defaults.json",
        settings={"min-resolution": 2160},
    )
    resolved = downloader.resolve_parameter_settings(profile, {"max-resolution": 1080})
    with pytest.raises(ValueError, match="min-resolution cannot be greater"):
        downloader.resolve_parameter_policy(resolved.settings)


def test_raw_format_selector_cannot_be_silently_reinterpreted_by_hard_constraints(downloader) -> None:
    with pytest.raises(ValueError, match="raw format selection cannot be combined"):
        downloader.resolve_parameter_policy(
            {
                "format": "137+140/22",
                "max-resolution": 1080,
                "no-cookies": True,
            }
        )


def test_raw_format_selector_can_coexist_with_preferences_without_being_rewritten(
    downloader, monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(downloader, "COOKIES_FILE", tmp_path / "missing-cookies.txt")
    policy, cookies, browser = downloader.resolve_parameter_policy(
        {
            "format": "137+140/22",
            "preferred-video-codec": "h264",
            "preferred-audio-codec": "mp4a",
            "merge-container": "mp4",
            "no-cookies": True,
        }
    )
    assert policy.effective_format_selector == "137+140/22"
    assert policy.sort_selector.startswith("vcodec:h264,acodec:mp4a,")
    assert policy.merge_container == "mp4"
    assert cookies is None
    assert browser is None


def test_declarative_format_policy_is_visible_in_explain_payload(downloader, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(downloader, "COOKIES_FILE", tmp_path / "missing-cookies.txt")
    resolved = downloader.ResolvedParameterSettings(
        settings={
            "max-resolution": 2160,
            "preferred-video-codec": "av01",
            "preferred-hdr": "hdr",
            "merge-container": "mkv",
            "no-cookies": True,
        },
        sources={"preferred-video-codec": "explicit CLI"},
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
    assert payload["policy"]["format"] == "bv[height<=2160]+ba/b[height<=2160]"
    assert payload["policy"]["max_resolution"] == 2160
    assert payload["policy"]["preferred_video_codec"] == "av01"
    assert payload["policy"]["preferred_hdr"] == "hdr"
    assert payload["policy"]["merge_container"] == "mkv"
