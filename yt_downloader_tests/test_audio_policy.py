"""First-class audio source-selection and conversion policy."""

from __future__ import annotations

import pytest


def _policy(downloader, settings: dict[str, object]):
    policy, cookies, browser = downloader.resolve_parameter_policy({**settings, "no-cookies": True})
    assert cookies is None
    assert browser is None
    return policy


def test_audio_only_selects_existing_best_audio_without_conversion(downloader) -> None:
    policy = _policy(downloader, {"audio-only": True})
    command = downloader.build_yt_dlp_command(
        "yt-dlp",
        policy,
        downloader.InputSource(direct_targets=("abc",)),
        None,
    )
    assert policy.effective_format_selector == "ba"
    assert policy.sort_selector == "lang,br,size"
    assert "--extract-audio" not in command
    assert "--audio-format" not in command


def test_audio_source_constraints_are_exact_when_fallback_is_disabled(downloader) -> None:
    policy = _policy(
        downloader,
        {
            "audio-only": True,
            "audio-source-codec": "opus",
            "audio-source-container": "webm",
            "audio-source-fallback": False,
        },
    )
    assert policy.effective_format_selector == "ba[acodec=opus][ext=webm]"


def test_audio_source_constraints_fall_back_to_any_audio_by_default(downloader) -> None:
    policy = _policy(
        downloader,
        {
            "audio-only": True,
            "audio-source-codec": "opus",
            "audio-source-container": "webm",
        },
    )
    assert policy.effective_format_selector == "ba[acodec=opus][ext=webm]/ba"


def test_audio_conversion_is_explicit_and_adds_extract_audio_options(downloader) -> None:
    policy = _policy(
        downloader,
        {
            "audio-format": "flac",
            "audio-quality": "0",
            "preferred-audio-codec": "opus",
            "preferred-audio-channels": 2,
        },
    )
    command = downloader.build_yt_dlp_command(
        "yt-dlp",
        policy,
        downloader.InputSource(direct_targets=("abc",)),
        None,
    )
    assert policy.effective_format_selector == "ba"
    assert policy.sort_selector == "acodec:opus,channels:2,lang,br,size"
    extract_index = command.index("--extract-audio")
    assert command[extract_index + 1 : extract_index + 5] == ["--audio-format", "flac", "--audio-quality", "0"]


def test_audio_quality_cannot_enable_conversion_implicitly(downloader) -> None:
    with pytest.raises(ValueError, match="audio-quality requires audio-format"):
        _policy(downloader, {"audio-only": True, "audio-quality": "128K"})


def test_audio_source_constraints_require_an_audio_workflow(downloader) -> None:
    with pytest.raises(ValueError, match="require --audio-only or --audio-format"):
        _policy(downloader, {"audio-source-codec": "opus"})


@pytest.mark.parametrize(
    "setting",
    [
        {"min-resolution": 720},
        {"max-fps": 60},
        {"preferred-fps": 60},
        {"preferred-video-codec": "av01"},
        {"preferred-hdr": "hdr"},
        {"merge-container": "mkv"},
    ],
)
def test_audio_workflows_reject_video_only_policy(downloader, setting: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="audio workflows cannot combine video-only settings"):
        _policy(downloader, {"audio-only": True, **setting})


def test_audio_workflows_reject_raw_format_authority(downloader) -> None:
    with pytest.raises(ValueError, match="cannot be combined with a raw --format selector"):
        _policy(downloader, {"audio-only": True, "format": "251/140"})


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, "0"), (10, "10"), ("5", "5"), ("128k", "128K"), ("1.5M", "1.5M")],
)
def test_audio_quality_validation_normalises_documented_forms(downloader, value: object, expected: str) -> None:
    assert downloader._validate_parameter_setting("audio-quality", value) == expected


@pytest.mark.parametrize("value", [-1, 11, "", "lossless", True, "128"])
def test_audio_quality_validation_rejects_ambiguous_or_invalid_values(downloader, value: object) -> None:
    with pytest.raises(ValueError, match="audio-quality"):
        downloader._validate_parameter_setting("audio-quality", value)


def test_audio_settings_are_profile_eligible_and_normalised(downloader) -> None:
    settings = downloader.validate_parameter_settings(
        {
            "audio-only": True,
            "audio-source-codec": "OPUS",
            "audio-source-container": "WEBM",
            "audio-source-fallback": False,
            "audio-format": "FLAC",
            "audio-quality": "128k",
        },
        profile_name="audio",
    )
    assert settings == {
        "audio-only": True,
        "audio-source-codec": "opus",
        "audio-source-container": "webm",
        "audio-source-fallback": False,
        "audio-format": "flac",
        "audio-quality": "128K",
    }


def test_profile_audio_quality_requires_profile_audio_format(downloader) -> None:
    with pytest.raises(ValueError, match="cannot set audio-quality without audio-format"):
        downloader.validate_parameter_settings({"audio-quality": "128K"}, profile_name="broken")


def test_audio_policy_is_visible_in_explain_payload(downloader, tmp_path) -> None:
    resolved = downloader.ResolvedParameterSettings(
        settings={
            "audio-only": True,
            "audio-source-codec": "opus",
            "audio-source-fallback": False,
            "no-cookies": True,
        },
        sources={"audio-only": "explicit CLI"},
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
    assert payload["policy"]["audio_only"] is True
    assert payload["policy"]["audio_source_codec"] == "opus"
    assert payload["policy"]["audio_source_fallback"] is False
    assert payload["policy"]["audio_conversion"] is False
    assert payload["policy"]["format"] == "ba[acodec=opus]"


def test_audio_command_omits_video_multistream_mode(downloader) -> None:
    policy = _policy(downloader, {"audio-only": True})
    command = downloader.build_yt_dlp_command(
        "yt-dlp",
        policy,
        downloader.InputSource(direct_targets=("abc",)),
        None,
    )
    assert "--video-multistreams" not in command
    assert "--audio-multistreams" in command


def test_audio_source_fallback_is_not_a_standalone_video_policy(downloader) -> None:
    with pytest.raises(ValueError, match="audio-source-fallback requires"):
        _policy(downloader, {"audio-source-fallback": False})


def test_audio_workflow_rejects_subtitle_embedding_but_allows_sidecars(downloader) -> None:
    with pytest.raises(ValueError, match="cannot embed subtitles"):
        _policy(downloader, {"audio-only": True, "embed-subs": True})

    policy = _policy(downloader, {"audio-only": True, "write-subs": True, "sub-langs": "en"})
    command = downloader.build_yt_dlp_command(
        "yt-dlp",
        policy,
        downloader.InputSource(direct_targets=("abc",)),
        None,
    )
    assert "--write-subs" in command
    assert "--embed-subs" not in command


def test_main_resolves_source_only_audio_without_conversion(downloader, monkeypatch) -> None:
    captured: list[str] = []
    monkeypatch.setattr(downloader, "validate_environment", lambda *, dry_run: "yt-dlp")

    def capture_run(command, *, dry_run):
        captured.extend(command)
        return 0

    monkeypatch.setattr(downloader, "run", capture_run)
    assert downloader.main([
        "--no-cookies",
        "--audio-only",
        "--audio-source-codec",
        "opus",
        "--no-audio-source-fallback",
        "abc",
    ]) == 0
    assert captured[captured.index("-f") + 1] == "ba[acodec=opus]"
    assert "--extract-audio" not in captured


def test_main_resolves_explicit_audio_conversion(downloader, monkeypatch) -> None:
    captured: list[str] = []
    monkeypatch.setattr(downloader, "validate_environment", lambda *, dry_run: "yt-dlp")

    def capture_run(command, *, dry_run):
        captured.extend(command)
        return 0

    monkeypatch.setattr(downloader, "run", capture_run)
    assert downloader.main([
        "--no-cookies",
        "--audio-format",
        "mp3",
        "--audio-quality",
        "192K",
        "abc",
    ]) == 0
    assert captured[captured.index("-f") + 1] == "ba"
    assert captured[captured.index("--audio-format") + 1] == "mp3"
    assert captured[captured.index("--audio-quality") + 1] == "192K"


@pytest.mark.parametrize("audio_format", sorted({"best", "aac", "alac", "flac", "m4a", "mp3", "opus", "vorbis", "wav"}))
def test_every_supported_audio_conversion_format_reaches_the_command(downloader, audio_format: str) -> None:
    policy = _policy(downloader, {"audio-format": audio_format})
    command = downloader.build_yt_dlp_command(
        "yt-dlp",
        policy,
        downloader.InputSource(direct_targets=("abc",)),
        None,
    )
    assert command[command.index("--audio-format") + 1] == audio_format
    assert command[command.index("-f") + 1] == "ba"


@pytest.mark.parametrize("audio_format", ["aac", "flac", "mp3", "opus", "wav"])
def test_audio_conversion_can_require_an_exact_source_without_fallback(downloader, audio_format: str) -> None:
    policy = _policy(
        downloader,
        {
            "audio-format": audio_format,
            "audio-source-codec": "opus",
            "audio-source-container": "webm",
            "audio-source-fallback": False,
        },
    )
    command = downloader.build_yt_dlp_command(
        "yt-dlp",
        policy,
        downloader.InputSource(direct_targets=("abc",)),
        None,
    )
    assert command[command.index("-f") + 1] == "ba[acodec=opus][ext=webm]"
    assert command[command.index("--audio-format") + 1] == audio_format


def test_audio_conversion_source_constraints_retain_default_fallback(downloader) -> None:
    policy = _policy(
        downloader,
        {
            "audio-format": "flac",
            "audio-source-codec": "opus",
            "audio-source-container": "webm",
        },
    )
    assert policy.effective_format_selector == "ba[acodec=opus][ext=webm]/ba"


@pytest.mark.parametrize(
    "settings",
    [
        {"audio-format": "flac", "format": "251/140"},
        {"audio-format": "flac", "max-resolution": 1080},
        {"audio-format": "flac", "preferred-video-codec": "av01"},
        {"audio-format": "flac", "embed-subs": True},
    ],
)
def test_conversion_workflow_enforces_the_same_audio_policy_boundaries(
    downloader,
    settings: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        _policy(downloader, settings)


def test_audio_profile_boolean_fallback_can_be_overridden_explicitly(downloader) -> None:
    profile = downloader.ParameterProfile(
        name="strict-audio",
        source=downloader.DEFAULTS_FILE,
        settings={
            "audio-only": True,
            "audio-source-codec": "opus",
            "audio-source-fallback": False,
        },
    )
    resolved = downloader.merge_parameter_settings(
        profile,
        {"audio-source-fallback": True},
    )
    assert resolved["audio-only"] is True
    assert resolved["audio-source-codec"] == "opus"
    assert resolved["audio-source-fallback"] is True


def test_audio_source_tokens_reject_format_expression_syntax(downloader) -> None:
    with pytest.raises(ValueError, match="audio-source-codec"):
        downloader._validate_parameter_setting("audio-source-codec", "opus/ba")
    with pytest.raises(ValueError, match="audio-source-container"):
        downloader._validate_parameter_setting("audio-source-container", "webm]/ba")


def test_audio_explain_reports_conversion_and_source_requirements(downloader, tmp_path) -> None:
    resolved = downloader.ResolvedParameterSettings(
        settings={
            "audio-format": "flac",
            "audio-quality": "0",
            "audio-source-codec": "opus",
            "audio-source-container": "webm",
            "audio-source-fallback": False,
            "no-cookies": True,
        },
        sources={"audio-format": "explicit CLI", "audio-quality": "explicit CLI"},
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
    assert payload["policy"]["audio_conversion"] is True
    assert payload["policy"]["audio_format"] == "flac"
    assert payload["policy"]["audio_quality"] == "0"
    assert payload["policy"]["audio_source_codec"] == "opus"
    assert payload["policy"]["audio_source_container"] == "webm"
    assert payload["policy"]["audio_source_fallback"] is False
    assert payload["policy"]["format"] == "ba[acodec=opus][ext=webm]"
