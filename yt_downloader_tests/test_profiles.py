"""Named Downloader parameter-profile loading, merging and generation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def write_defaults(
    path: Path, profiles: dict[str, dict[str, object]], *, values: dict[str, object] | None = None
) -> None:
    payload: dict[str, object] = {"version": 2, "profiles": profiles}
    if values is not None:
        payload["values"] = values
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_shipped_defaults_include_expected_profiles(downloader) -> None:
    profiles = downloader.load_profiles(downloader.DEFAULTS_FILE, allow_missing=False)
    assert set(profiles) == {"default", "best", "4k", "1440p", "playlist"}
    standard_path = "/mnt/storage/Storage/YouTube/YouTube/"
    standard_output = "%(title)s [%(id)s] [%(uploader)s].%(ext)s"
    assert profiles["default"].settings == {"path": standard_path, "output": standard_output}
    assert profiles["1440p"].settings == {
        "path": standard_path,
        "output": standard_output,
        "resolution": "1440p",
    }
    assert profiles["playlist"].settings["playlist"] is True
    assert profiles["playlist"].settings["path"].endswith("YouTube Playlists/")


def test_default_profile_is_selected_implicitly(downloader) -> None:
    profile = downloader.select_profile(None, downloader.DEFAULTS_FILE, explicit_defaults=False)
    assert profile is not None
    assert profile.name == "default"


def test_profile_accepts_output_layout(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_defaults(path, {"custom": {"path": "/tmp/media", "output": "%(id)s.%(ext)s"}})
    profile = downloader.select_profile("custom", path, explicit_defaults=True)
    assert profile is not None
    layout = downloader.output_profile_from_settings(profile.settings, path)
    assert layout is not None
    assert layout.path == "/tmp/media"
    assert layout.output == "%(id)s.%(ext)s"


def test_profile_rejects_unknown_setting(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_defaults(path, {"broken": {"resoluton": "1080p"}})
    with pytest.raises(ValueError, match="unknown option 'resoluton'"):
        downloader.load_profiles(path, allow_missing=False)


def test_profile_preserves_yt_dlp_format_expression(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    selector = "bv*[height<=1080]+ba/b"
    write_defaults(path, {"custom": {"format": selector}})
    profile = downloader.select_profile("custom", path, explicit_defaults=True)
    assert profile is not None
    assert profile.settings["format"] == selector


def test_profile_requires_native_json_boolean(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_defaults(path, {"broken": {"no-cookies": "true"}})
    with pytest.raises(ValueError, match="JSON Boolean"):
        downloader.load_profiles(path, allow_missing=False)


def test_profile_rejects_cookie_conflict(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_defaults(path, {"broken": {"cookies": "/tmp/cookies.txt", "no-cookies": True}})
    with pytest.raises(ValueError, match="cannot combine cookie settings"):
        downloader.load_profiles(path, allow_missing=False)


def test_cli_settings_override_selected_profile(downloader, tmp_path: Path) -> None:
    source = downloader.Profile(
        name="source",
        source=tmp_path / "defaults.json",
        settings={
            "resolution": "2160p",
            "format": "bv+ba/best",
            "no-cookies": True,
            "playlist": True,
        },
    )
    merged = downloader.merge_profile_settings(
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


def test_list_profiles_is_sorted_case_insensitively(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_defaults(path, {"Zulu": {}, "alpha": {}, "4k": {}})
    assert downloader.list_profiles(path, explicit_defaults=True) == ["4k", "alpha", "Zulu"]


def test_resolve_profile_policy_uses_profile_format(downloader, monkeypatch) -> None:
    monkeypatch.setattr(downloader, "COOKIES_FILE", Path("/definitely/missing/cookies.txt"))
    policy, cookies, browser_cookies = downloader.resolve_profile_policy(
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
    profile = downloader.select_profile("network", path, explicit_defaults=True)
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
            downloader.load_profiles(path, allow_missing=False)


def test_browser_cookie_setting_conflicts_with_file_cookie_policy(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_defaults(
        path,
        {"broken": {"cookies": "/tmp/cookies.txt", "cookies-from-browser": "firefox"}},
    )
    with pytest.raises(ValueError, match="cannot combine cookie settings"):
        downloader.load_profiles(path, allow_missing=False)


def test_cli_operational_settings_override_profile_values(downloader, tmp_path: Path) -> None:
    profile = downloader.Profile(
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
    resolved = downloader.resolve_profile_settings(
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
        downloader.load_profiles(path, allow_missing=False)


def test_profile_references_preserve_json_types(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_defaults(
        path,
        {
            "typed": {
                "path": "$values.layout.path",
                "playlist": "$values.policy.playlist",
                "concurrent-fragments": "$values.policy.fragments",
                "extractor-args": "$values.policy.extractor_args",
            }
        },
        values={
            "layout": {"path": "/srv/media"},
            "policy": {"playlist": True, "fragments": 4, "extractor_args": ["youtube:player-client=tv"]},
        },
    )
    profile = downloader.select_profile("typed", path, explicit_defaults=True)
    assert profile is not None
    assert profile.settings == {
        "path": "/srv/media",
        "playlist": True,
        "concurrent-fragments": 4,
        "extractor-args": ["youtube:player-client=tv"],
    }


def test_profile_references_can_chain(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_defaults(
        path,
        {"custom": {"path": "$values.layout.path"}},
        values={"root": "/srv/media", "layout": {"path": "$values.root"}},
    )
    profile = downloader.select_profile("custom", path, explicit_defaults=True)
    assert profile is not None
    assert profile.settings["path"] == "/srv/media"


def test_profile_reference_escape_preserves_literal_dollar(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_defaults(path, {"custom": {"output": "$$literal.%(ext)s"}})
    profile = downloader.select_profile("custom", path, explicit_defaults=True)
    assert profile is not None
    assert profile.settings["output"] == "$literal.%(ext)s"


def test_profile_reference_rejects_unknown_value(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_defaults(path, {"custom": {"path": "$values.missing.path"}}, values={})
    with pytest.raises(ValueError, match="references unknown value"):
        downloader.load_profiles(path, allow_missing=False)


def test_profile_reference_rejects_invalid_reference_syntax(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_defaults(path, {"custom": {"path": "$value.single.path"}}, values={})
    with pytest.raises(ValueError, match="invalid value reference"):
        downloader.load_profiles(path, allow_missing=False)


def test_profile_reference_rejects_cycles(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_defaults(path, {"custom": {"path": "$values.a"}}, values={"a": "$values.b", "b": "$values.a"})
    with pytest.raises(ValueError, match="cyclic profile value reference"):
        downloader.load_profiles(path, allow_missing=False)


def test_profile_reference_value_is_validated_for_destination_setting(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_defaults(
        path, {"custom": {"concurrent-fragments": "$values.bad.fragments"}}, values={"bad": {"fragments": "four"}}
    )
    with pytest.raises(ValueError, match="positive JSON integer"):
        downloader.load_profiles(path, allow_missing=False)


def test_request_policy_is_profileable_and_type_checked(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_defaults(
        path,
        {
            "network": {
                "user-agent": "ExampleBrowser/1.0",
                "referer": "https://example.test/watch",
                "headers": ["X-Test:value"],
                "proxy": "socks5://127.0.0.1:1080/",
                "socket-timeout": 15.5,
                "source-address": "192.0.2.10",
                "ip-family": "ipv6",
            }
        },
    )
    profile = downloader.select_profile("network", path, explicit_defaults=True)
    assert profile is not None
    policy, _, _ = downloader.resolve_profile_policy(profile.settings)
    assert policy.user_agent == "ExampleBrowser/1.0"
    assert policy.referer == "https://example.test/watch"
    assert policy.headers == ("X-Test:value",)
    assert policy.proxy == "socks5://127.0.0.1:1080/"
    assert policy.socket_timeout == 15.5
    assert policy.source_address == "192.0.2.10"
    assert policy.ip_family == "ipv6"


def test_request_policy_rejects_malformed_headers(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_defaults(path, {"broken": {"headers": ["missing-value:"]}})
    with pytest.raises(ValueError, match="FIELD:VALUE"):
        downloader.load_profiles(path, allow_missing=False)


def test_request_policy_rejects_non_positive_socket_timeout(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_defaults(path, {"broken": {"socket-timeout": 0}})
    with pytest.raises(ValueError, match="positive JSON number"):
        downloader.load_profiles(path, allow_missing=False)


def test_request_policy_rejects_invalid_ip_family(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_defaults(path, {"broken": {"ip-family": "auto"}})
    with pytest.raises(ValueError, match="ipv4, ipv6"):
        downloader.load_profiles(path, allow_missing=False)


def test_dedicated_user_agent_rejects_duplicate_generic_header(downloader) -> None:
    with pytest.raises(ValueError, match="User-Agent entry"):
        downloader.resolve_profile_policy({"user-agent": "Example/1.0", "headers": ["User-Agent:Other/2.0"]})


def test_dedicated_referer_rejects_duplicate_generic_header(downloader) -> None:
    with pytest.raises(ValueError, match="Referer entry"):
        downloader.resolve_profile_policy(
            {"referer": "https://example.test", "headers": ["Referer:https://other.test"]}
        )
