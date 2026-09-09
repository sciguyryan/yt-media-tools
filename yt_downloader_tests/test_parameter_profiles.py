"""Named Downloader parameter-profile loading, merging and generation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def write_defaults(path: Path, profiles: dict[str, dict[str, object]]) -> None:
    path.write_text(json.dumps({"version": 1, "profiles": profiles}), encoding="utf-8")


def test_shipped_defaults_include_expected_profiles(downloader) -> None:
    profiles = downloader.load_parameter_profiles(downloader.DEFAULTS_FILE, allow_missing=False)
    assert set(profiles) == {"best", "4k", "1440p", "playlist"}
    assert profiles["best"].settings == {"resolution": "best", "format": "bv+ba/best"}
    assert profiles["4k"].settings == {"resolution": "2160p", "format": "bv+ba/best"}
    assert profiles["1440p"].settings == {"resolution": "1440p", "format": "bv+ba/best"}
    assert profiles["playlist"].settings == {
        "resolution": "1080p",
        "format": "bv+ba/best",
        "playlist": True,
    }


def test_parameter_profile_rejects_unknown_setting(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_defaults(path, {"broken": {"resoluton": "1080p"}})
    with pytest.raises(ValueError, match="unknown option 'resoluton'"):
        downloader.load_parameter_profiles(path, allow_missing=False)


def test_parameter_profile_preserves_yt_dlp_format_expression(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    selector = "bv*[height<=1080]+ba/b"
    write_defaults(path, {"custom": {"format": selector}})
    profile = downloader.select_parameter_profile("custom", path, explicit_defaults=True)
    assert profile is not None
    assert profile.settings["format"] == selector


def test_parameter_profile_requires_native_json_boolean(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_defaults(path, {"broken": {"no-cookies": "true"}})
    with pytest.raises(ValueError, match="JSON Boolean"):
        downloader.load_parameter_profiles(path, allow_missing=False)


def test_parameter_profile_rejects_cookie_conflict(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_defaults(path, {"broken": {"cookies": "/tmp/cookies.txt", "no-cookies": True}})
    with pytest.raises(ValueError, match="cannot combine cookie settings"):
        downloader.load_parameter_profiles(path, allow_missing=False)


def test_cli_settings_override_selected_profile(downloader, tmp_path: Path) -> None:
    source = downloader.ParameterProfile(
        name="source",
        source=tmp_path / "defaults.json",
        settings={
            "resolution": "2160p",
            "format": "bv+ba/best",
            "no-cookies": True,
            "playlist": True,
        },
    )
    merged = downloader.merge_parameter_settings(
        source,
        {
            "resolution": "1080p",
            "format": "bv*[height<=1080]+ba/b",
            "cookies": "/tmp/cookies.txt",
            "playlist": False,
        },
    )
    assert merged == {
        "resolution": "1080p",
        "format": "bv*[height<=1080]+ba/b",
        "cookies": "/tmp/cookies.txt",
        "playlist": False,
    }


def test_generation_without_source_captures_only_explicit_settings(downloader) -> None:
    generated = downloader.generated_profile_settings(
        None,
        {"resolution": "1440p", "format": "bv+ba/best", "no-cookies": True},
    )
    assert generated == {"resolution": "1440p", "format": "bv+ba/best", "no-cookies": True}


def test_generation_from_source_clones_then_overrides(downloader, tmp_path: Path) -> None:
    source = downloader.ParameterProfile(
        name="source",
        source=tmp_path / "defaults.json",
        settings={"resolution": "1440p", "format": "bv+ba/best", "no-cookies": True},
    )
    generated = downloader.generated_profile_settings(source, {"resolution": "2160p"})
    assert generated == {"resolution": "2160p", "format": "bv+ba/best", "no-cookies": True}


def test_write_profile_refuses_implicit_overwrite(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_defaults(path, {"existing": {"resolution": "1080p"}})
    with pytest.raises(ValueError, match="already exists"):
        downloader.write_parameter_profile(
            path,
            "existing",
            {"resolution": "1440p"},
            overwrite=False,
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["profiles"]["existing"] == {"resolution": "1080p"}


def test_write_profile_requires_explicit_overwrite_and_preserves_others(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_defaults(
        path,
        {
            "existing": {"resolution": "1080p"},
            "untouched": {"format": "ba/b"},
        },
    )
    downloader.write_parameter_profile(
        path,
        "existing",
        {"resolution": "2160p", "format": "bv+ba/best"},
        overwrite=True,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["profiles"]["existing"] == {"resolution": "2160p", "format": "bv+ba/best"}
    assert payload["profiles"]["untouched"] == {"format": "ba/b"}


def test_list_parameter_profiles_is_sorted_case_insensitively(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_defaults(path, {"Zulu": {}, "alpha": {}, "4k": {}})
    assert downloader.list_parameter_profiles(path, explicit_defaults=True) == ["4k", "alpha", "Zulu"]


def test_resolve_parameter_policy_uses_profile_format(downloader, monkeypatch) -> None:
    monkeypatch.setattr(downloader, "COOKIES_FILE", Path("/definitely/missing/cookies.txt"))
    policy, cookies, browser_cookies = downloader.resolve_parameter_policy(
        {
            "resolution": "1080p",
            "format": "bv*[height<=1080]+ba/b",
            "no-cookies": True,
            "playlist": True,
        }
    )
    assert policy.resolution == "1080"
    assert policy.format_selector == "bv*[height<=1080]+ba/b"
    assert policy.playlist is True
    assert cookies is None
    assert browser_cookies is None


def test_operational_profile_settings_are_strictly_typed(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_defaults(
        path,
        {
            "network": {
                "limit-rate": "12M",
                "throttled-rate": "500K",
                "concurrent-fragments": 4,
                "retries": "infinite",
                "fragment-retries": 7,
                "file-access-retries": 2,
                "extractor-retries": 5,
                "retry-sleep": ["linear=1:5", "fragment:exp=1:20"],
                "archive": "~/archive.txt",
                "temp-path": "~/tmp",
                "extractor-args": ["youtube:player-client=tv", "twitter:api=syndication"],
                "cookies-from-browser": "firefox",
            }
        },
    )
    profile = downloader.select_parameter_profile("network", path, explicit_defaults=True)
    assert profile is not None
    assert profile.settings["limit-rate"] == "12M"
    assert profile.settings["concurrent-fragments"] == 4
    assert profile.settings["retries"] == "infinite"
    assert profile.settings["fragment-retries"] == "7"
    assert profile.settings["retry-sleep"] == ["linear=1:5", "fragment:exp=1:20"]


def test_operational_profile_rejects_invalid_values(downloader, tmp_path: Path) -> None:
    invalid_settings = (
        ({"limit-rate": "fast"}, "byte rate"),
        ({"concurrent-fragments": 0}, "positive JSON integer"),
        ({"retries": -1}, "must not be negative"),
        ({"retry-sleep": "linear=1:5"}, "JSON array"),
        ({"extractor-args": []}, "non-empty JSON array"),
    )
    for index, (settings, message) in enumerate(invalid_settings):
        path = tmp_path / f"defaults-{index}.json"
        write_defaults(path, {"broken": settings})
        with pytest.raises(ValueError, match=message):
            downloader.load_parameter_profiles(path, allow_missing=False)


def test_browser_cookie_setting_conflicts_with_file_cookie_policy(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_defaults(
        path,
        {"broken": {"cookies": "/tmp/cookies.txt", "cookies-from-browser": "firefox"}},
    )
    with pytest.raises(ValueError, match="cannot combine cookie settings"):
        downloader.load_parameter_profiles(path, allow_missing=False)


def test_cli_operational_settings_override_profile_values(downloader, tmp_path: Path) -> None:
    profile = downloader.ParameterProfile(
        name="network",
        source=tmp_path / "defaults.json",
        settings={
            "limit-rate": "20M",
            "concurrent-fragments": 2,
            "retries": "10",
            "extractor-args": ["youtube:player-client=default"],
            "cookies-from-browser": "firefox",
        },
    )
    resolved = downloader.resolve_parameter_settings(
        profile,
        {
            "limit-rate": "8M",
            "concurrent-fragments": 6,
            "retries": "infinite",
            "extractor-args": ["youtube:player-client=tv"],
            "no-cookies": True,
        },
    )
    assert resolved.settings["limit-rate"] == "8M"
    assert resolved.settings["concurrent-fragments"] == 6
    assert resolved.settings["retries"] == "infinite"
    assert resolved.settings["extractor-args"] == ["youtube:player-client=tv"]
    assert resolved.settings["no-cookies"] is True
    assert "cookies-from-browser" not in resolved.settings


def test_browser_cookie_setting_rejects_unknown_browser(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_defaults(path, {"broken": {"cookies-from-browser": "netscape"}})
    with pytest.raises(ValueError, match="unsupported browser"):
        downloader.load_parameter_profiles(path, allow_missing=False)
