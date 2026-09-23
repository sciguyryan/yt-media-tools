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
    assert set(profiles) == {"default", "best", "4k", "1440p", "1440p-slow", "playlist"}
    standard_path = "/mnt/storage/Storage/YouTube/YouTube/"
    standard_output = "%(title)s [%(id)s] [%(uploader)s].%(ext)s"
    default_user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:147.0) Gecko/20100101 Firefox/147.0"
    assert profiles["default"].settings == {
        "path": standard_path,
        "output": standard_output,
        "user-agent": default_user_agent,
        "impersonate": "Firefox-147:Macos-26",
    }
    assert profiles["1440p"].settings == {
        "path": standard_path,
        "output": standard_output,
        "resolution": "1440p",
        "user-agent": default_user_agent,
        "impersonate": "Firefox-147:Macos-26",
    }
    assert profiles["1440p-slow"].settings["limit-rate"] == "2.5M"
    assert profiles["1440p-slow"].settings["user-agent"] == default_user_agent
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


def test_impersonate_is_profileable_and_type_checked(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_defaults(path, {"browser": {"impersonate": "Firefox-147:Macos-26"}})
    profile = downloader.select_profile("browser", path, explicit_defaults=True)
    assert profile is not None
    policy, _, _ = downloader.resolve_profile_policy(profile.settings)
    assert policy.impersonate == "Firefox-147:Macos-26"


def test_impersonate_rejects_empty_profile_value(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_defaults(path, {"broken": {"impersonate": ""}})
    with pytest.raises(ValueError, match="non-empty JSON string"):
        downloader.load_profiles(path, allow_missing=False)


def test_no_impersonate_removes_profile_value(downloader) -> None:
    args = downloader.build_parser().parse_args(["--no-impersonate", "abc"])
    cli_settings = downloader.explicit_profile_settings(args)
    profile = downloader.Profile(
        name="browser",
        source=Path("defaults.json"),
        settings={"impersonate": "chrome"},
    )
    resolved = downloader.resolve_profile_settings(profile, cli_settings)
    assert "impersonate" not in resolved.settings
    assert "impersonate" not in resolved.sources


def write_hierarchical_defaults(
    path: Path, profiles: dict[str, dict[str, object]], *, defaults=None, values=None
) -> None:
    payload: dict[str, object] = {"version": 3, "profiles": profiles}
    if defaults is not None:
        payload["$defaults"] = defaults
    if values is not None:
        payload["values"] = values
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_hierarchy_resolves_defaults_and_deep_single_parent_chain(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_hierarchical_defaults(
        path,
        {
            "high-quality": {"resolution": "2160p"},
            "archive": {"parent": "high-quality", "merge-container": "mkv"},
            "special": {"parent": "archive", "impersonate": "firefox"},
        },
        defaults={"user-agent": "Shared Agent", "impersonate": "chrome"},
    )
    profile = downloader.select_profile("special", path, explicit_defaults=True)
    assert profile is not None
    assert profile.ancestry == ("high-quality", "archive")
    assert profile.settings["resolution"] == "2160p"
    assert profile.settings["merge-container"] == "mkv"
    assert profile.settings["impersonate"] == "firefox"
    assert profile.settings["user-agent"] == "Shared Agent"
    assert profile.setting_sources["user-agent"] == "$defaults"
    assert profile.setting_sources["resolution"] == "profile 'high-quality'"
    assert profile.setting_sources["merge-container"] == "profile 'archive'"
    assert profile.setting_sources["impersonate"] == "profile 'special'"


def test_hierarchy_without_defaults_has_independent_roots(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_hierarchical_defaults(
        path, {"root": {"resolution": "1080p"}, "child": {"parent": "root", "format": "best"}, "other": {}}
    )
    assert downloader.select_profile("child", path, explicit_defaults=True).settings == {
        "resolution": "1080p",
        "format": "best",
    }
    assert downloader.profile_tree(path) == "other\n\nroot\n└── child"


def test_hierarchy_rejects_missing_parent_and_cycles(downloader, tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    write_hierarchical_defaults(missing, {"child": {"parent": "absent"}})
    with pytest.raises(ValueError, match="profile 'child' refers to missing parent 'absent'"):
        downloader.load_profiles(missing, allow_missing=False)
    cycle = tmp_path / "cycle.json"
    write_hierarchical_defaults(cycle, {"a": {"parent": "b"}, "b": {"parent": "c"}, "c": {"parent": "a"}})
    with pytest.raises(ValueError, match=r"profile inheritance cycle: a -> b -> c -> a"):
        downloader.load_profiles(cycle, allow_missing=False)


def test_hierarchy_is_independent_of_json_declaration_order(downloader, tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    profiles = {
        "root": {"resolution": "1080p"},
        "middle": {"parent": "root", "limit-rate": "2M"},
        "leaf": {"parent": "middle", "resolution": "2160p"},
    }
    write_hierarchical_defaults(first, profiles, defaults={"user-agent": "Agent"})
    write_hierarchical_defaults(second, dict(reversed(list(profiles.items()))), defaults={"user-agent": "Agent"})
    assert (
        downloader.select_profile("leaf", first, explicit_defaults=True).settings
        == downloader.select_profile("leaf", second, explicit_defaults=True).settings
    )
    assert downloader.profile_tree(first) == downloader.profile_tree(second)


def test_hierarchy_preserves_values_references_and_validates_effective_settings(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_hierarchical_defaults(
        path,
        {"audio": {"audio-quality": 0}},
        defaults={"audio-format": "$values.audio.format"},
        values={"audio": {"format": "flac"}},
    )
    assert downloader.select_profile("audio", path, explicit_defaults=True).settings["audio-format"] == "flac"


def test_profile_tree_renders_defaults_and_focused_ancestry(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_hierarchical_defaults(
        path,
        {"mobile": {}, "archive": {"parent": "high-quality"}, "high-quality": {}, "special": {"parent": "archive"}},
        defaults={},
    )
    assert (
        downloader.profile_tree(path) == "$defaults\n├── high-quality\n│   └── archive\n│       └── special\n└── mobile"
    )
    assert (
        downloader.profile_tree(path, focus="special")
        == "$defaults\n└── high-quality\n    └── archive\n        └── special"
    )
    assert downloader.profile_tree(path, ascii_only=True).startswith("$defaults\n|-- high-quality")


def test_legacy_version_two_profiles_remain_supported(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_defaults(path, {"legacy": {"resolution": "1080p"}})
    assert downloader.select_profile("legacy", path, explicit_defaults=True).settings["resolution"] == "1080p"


def test_cli_overrides_inherited_profile_value(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_hierarchical_defaults(path, {"leaf": {}}, defaults={"impersonate": "chrome"})
    profile = downloader.select_profile("leaf", path, explicit_defaults=True)
    resolved = downloader.resolve_profile_settings(profile, {"impersonate": "firefox"})
    assert resolved.settings["impersonate"] == "firefox"
    assert resolved.sources["impersonate"] == "explicit CLI"


def test_profile_tree_cli_prints_complete_and_focused_hierarchy(downloader, tmp_path: Path, capsys) -> None:
    path = tmp_path / "defaults.json"
    write_hierarchical_defaults(path, {"root": {}, "child": {"parent": "root"}}, defaults={})
    assert downloader.main(["--defaults", str(path), "--profile-tree"]) == 0
    assert capsys.readouterr().out == "$defaults\n└── root\n    └── child\n"
    assert downloader.main(["--defaults", str(path), "--profile-tree", "child"]) == 0
    assert capsys.readouterr().out == "$defaults\n└── root\n    └── child\n"


def test_deep_hierarchy_resolves_without_order_dependence(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    profiles: dict[str, dict[str, object]] = {"level-00": {"resolution": "720p"}}
    for index in range(1, 40):
        profiles[f"level-{index:02d}"] = {"parent": f"level-{index - 1:02d}"}
    profiles["level-39"]["resolution"] = "2160p"
    write_hierarchical_defaults(path, dict(reversed(list(profiles.items()))), defaults={"user-agent": "Agent"})
    leaf = downloader.select_profile("level-39", path, explicit_defaults=True)
    assert leaf is not None
    assert len(leaf.ancestry) == 39
    assert leaf.settings == {"user-agent": "Agent", "resolution": "2160p"}


def test_list_profiles_excludes_structural_defaults(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    write_hierarchical_defaults(path, {"b": {}, "a": {}}, defaults={"user-agent": "Agent"})
    assert downloader.list_profiles(path, explicit_defaults=True) == ["a", "b"]
