"""Downloader output-layout policy carried by unified JSON profiles."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_output_layout_requires_non_empty_strings(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    path.write_text('{"version":1,"profiles":{"broken":{"path":""}}}', encoding="utf-8")
    with pytest.raises(ValueError, match="path.*non-empty JSON string"):
        downloader.load_profiles(path, allow_missing=False)


def test_output_layout_is_absent_when_profile_has_no_layout(downloader, tmp_path: Path) -> None:
    assert downloader.output_profile_from_settings({"resolution": "1080p"}, tmp_path / "defaults.json") is None


def test_output_layout_uses_unified_profile_source(downloader, tmp_path: Path) -> None:
    source = tmp_path / "defaults.json"
    layout = downloader.output_profile_from_settings({"path": "/tmp/media", "output": "%(id)s.%(ext)s"}, source)
    assert layout is not None
    assert layout.source == source
    assert layout.path == "/tmp/media"
    assert layout.output == "%(id)s.%(ext)s"


def test_unified_profile_output_layout_reaches_command_builder(downloader, tmp_path: Path) -> None:
    source = tmp_path / "defaults.json"
    profile = downloader.Profile(
        name="archive",
        source=source,
        settings={"path": "/tmp/media", "output": "%(id)s.%(ext)s"},
    )
    resolved = downloader.resolve_profile_settings(profile, {})
    layout = downloader.output_profile_from_settings(resolved.settings, source)
    plan = downloader.create_download_plan(
        executable="yt-dlp",
        resolved_profile=resolved,
        input_source=downloader.InputSource(direct_targets=("abc",)),
        output_profile=layout,
        defaults_file=source,
        profile=profile,
        remove_completed_ids=False,
    )
    command = plan.command()
    assert command[command.index("--paths") + 1] == "home:/tmp/media"
    assert command[command.index("--output") + 1] == "%(id)s.%(ext)s"
