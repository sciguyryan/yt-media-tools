"""Resolved Downloader planning and explanation surfaces."""

from __future__ import annotations

import json
from pathlib import Path


def test_resolved_parameter_settings_record_cli_precedence(downloader, tmp_path: Path) -> None:
    profile = downloader.ParameterProfile(
        name="4k",
        settings={"resolution": "2160p", "format": "bv+ba/best", "playlist": True},
        source=tmp_path / "defaults.json",
    )
    resolved = downloader.resolve_parameter_settings(
        profile,
        {"resolution": "1080p", "playlist": False},
    )
    assert resolved.settings == {
        "resolution": "1080p",
        "format": "bv+ba/best",
        "playlist": False,
    }
    assert resolved.sources == {
        "resolution": "explicit CLI",
        "format": "parameter profile '4k'",
        "playlist": "explicit CLI",
    }


def test_download_plan_command_matches_existing_command_builder(downloader, tmp_path: Path, monkeypatch) -> None:
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("cookies", encoding="utf-8")
    monkeypatch.setattr(downloader, "COOKIES_FILE", cookie_file)
    resolved = downloader.ResolvedParameterSettings(
        settings={"resolution": "1440p", "format": "bv+ba/best", "playlist": False},
        sources={"resolution": "explicit CLI", "format": "explicit CLI", "playlist": "explicit CLI"},
    )
    source = downloader.InputSource(direct_targets=("abc",))
    plan = downloader.create_download_plan(
        executable="yt-dlp",
        resolved_parameters=resolved,
        input_source=source,
        output_profile=None,
        defaults_file=tmp_path / "defaults.json",
        parameter_profile=None,
        remove_completed_ids=False,
    )
    expected = downloader.build_yt_dlp_command(
        "yt-dlp",
        plan.policy,
        source,
        None,
        cookies_file=cookie_file,
        remove_completed_ids=False,
    )
    assert plan.command() == expected


def test_explain_payload_is_stable_and_machine_readable(downloader, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(downloader, "COOKIES_FILE", tmp_path / "missing-cookies.txt")
    profile = downloader.ParameterProfile(
        name="best",
        settings={"resolution": "best", "format": "bv+ba/best"},
        source=tmp_path / "defaults.json",
    )
    resolved = downloader.resolve_parameter_settings(profile, {"playlist": True})
    plan = downloader.create_download_plan(
        executable="yt-dlp",
        resolved_parameters=resolved,
        input_source=downloader.InputSource(direct_targets=("abc", "def")),
        output_profile=None,
        defaults_file=profile.source,
        parameter_profile=profile,
        remove_completed_ids=False,
    )
    payload = downloader.explain_plan_payload(plan)
    assert payload["kind"] == "yt-download-plan"
    assert payload["version"] == "1.19.1"
    assert payload["parameter_profile"]["name"] == "best"
    assert payload["policy"]["resolution"] == "best"
    assert payload["policy"]["playlist"] is True
    assert payload["authentication"] == {
        "source": "none available",
        "cookies_file": None,
        "cookies_from_browser": None,
    }
    assert payload["input"] == {"kind": "direct", "targets": ["abc", "def"]}
    assert json.loads(json.dumps(payload)) == payload


def test_human_explanation_includes_value_sources(downloader, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(downloader, "COOKIES_FILE", tmp_path / "missing-cookies.txt")
    resolved = downloader.ResolvedParameterSettings(
        settings={"resolution": "1080p", "format": "bv+ba/best", "no-cookies": True},
        sources={
            "resolution": "explicit CLI",
            "format": "parameter profile 'archive'",
            "no-cookies": "parameter profile 'archive'",
        },
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
    rendered = downloader.format_plan_explanation(plan)
    assert "resolved download plan" in rendered
    assert "Resolution:        1080" in rendered
    assert "Cookies:           disabled" in rendered
    assert "resolution: explicit CLI" in rendered
    assert "format: parameter profile 'archive'" in rendered


def test_operational_policy_compiles_to_yt_dlp_command(downloader, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(downloader, "COOKIES_FILE", tmp_path / "missing-cookies.txt")
    resolved = downloader.ResolvedParameterSettings(
        settings={
            "limit-rate": "12M",
            "throttled-rate": "500K",
            "concurrent-fragments": 4,
            "retries": "infinite",
            "fragment-retries": "7",
            "file-access-retries": "2",
            "extractor-retries": "5",
            "retry-sleep": ["linear=1:5", "fragment:exp=1:20"],
            "archive": str(tmp_path / "archive.txt"),
            "temp-path": str(tmp_path / "temp"),
            "extractor-args": ["youtube:player-client=tv", "twitter:api=syndication"],
            "cookies-from-browser": "firefox",
        },
        sources={},
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
    command = plan.command()
    assert command[command.index("-r") + 1] == "12M"
    assert command[command.index("--throttled-rate") + 1] == "500K"
    assert command[command.index("--concurrent-fragments") + 1] == "4"
    assert command[command.index("--retries") + 1] == "infinite"
    assert command[command.index("--fragment-retries") + 1] == "7"
    assert command[command.index("--file-access-retries") + 1] == "2"
    assert command[command.index("--extractor-retries") + 1] == "5"
    assert command.count("--retry-sleep") == 2
    assert command[command.index("--cookies-from-browser") + 1] == "firefox"
    assert str(tmp_path / "archive.txt") in command
    assert f"temp:{tmp_path / 'temp'}" in command
    assert command.count("--extractor-args") == 2


def test_explain_payload_reports_operational_policy(downloader, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(downloader, "COOKIES_FILE", tmp_path / "missing-cookies.txt")
    resolved = downloader.ResolvedParameterSettings(
        settings={
            "limit-rate": "9M",
            "concurrent-fragments": 3,
            "archive": str(tmp_path / "archive.txt"),
            "temp-path": str(tmp_path / "temp"),
            "cookies-from-browser": "chromium+kwallet6:Default",
        },
        sources={"limit-rate": "explicit CLI"},
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
    assert payload["policy"]["limit_rate"] == "9M"
    assert payload["policy"]["concurrent_fragments"] == 3
    assert payload["authentication"]["cookies_from_browser"] == "chromium+kwallet6:Default"
    assert payload["paths"] == {
        "archive": str(tmp_path / "archive.txt"),
        "archive_enabled": True,
        "temporary": str(tmp_path / "temp"),
    }


def test_explain_redacts_sensitive_extractor_argument_values(downloader, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(downloader, "COOKIES_FILE", tmp_path / "missing-cookies.txt")
    resolved = downloader.ResolvedParameterSettings(
        settings={
            "extractor-args": [
                "youtube:player-client=tv;po_token=web.gvs+TOPSECRET;innertube_key=APISECRET",
                "twitter:api=syndication",
            ]
        },
        sources={"extractor-args": "explicit CLI"},
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
    rendered = json.dumps(payload)
    assert "TOPSECRET" not in rendered
    assert "APISECRET" not in rendered
    assert "po_token=<redacted>" in rendered
    assert "innertube_key=<redacted>" in rendered
    assert "player-client=tv" in rendered
    assert "twitter:api=syndication" in rendered
    exact = downloader.format_command(plan.command())
    assert "TOPSECRET" in exact
    assert "APISECRET" in exact
