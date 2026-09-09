"""Typed playlist selection and traversal policy."""

from __future__ import annotations

from pathlib import Path

import pytest


def _plan(downloader, tmp_path: Path, monkeypatch, settings: dict[str, object], *, remove: bool = False):
    monkeypatch.setattr(downloader, "COOKIES_FILE", tmp_path / "missing-cookies.txt")
    return downloader.create_download_plan(
        executable="yt-dlp",
        resolved_parameters=downloader.ResolvedParameterSettings(settings=settings, sources={}),
        input_source=downloader.InputSource(direct_targets=("https://example.invalid/playlist",)),
        output_profile=None,
        defaults_file=tmp_path / "defaults.json",
        parameter_profile=None,
        remove_completed_ids=remove,
    )


def test_cli_playlist_selection_preserves_mixed_option_order(downloader) -> None:
    parser = downloader.build_parser()
    args = parser.parse_args(
        [
            "--playlist-range",
            "5",
            "8",
            "--playlist-index",
            "1",
            "--playlist-slice=-5::2",
            "--playlist-index",
            "-1",
            "PLAYLIST_URL",
        ]
    )
    assert downloader.explicit_parameter_settings(args)["playlist-items"] == [
        "5:8",
        "1",
        "-5::2",
        "-1",
    ]


@pytest.mark.parametrize(
    "argv",
    [
        ["--playlist-index", "0", "PLAYLIST_URL"],
        ["--playlist-range", "0", "4", "PLAYLIST_URL"],
        ["--playlist-range", "2", "0", "PLAYLIST_URL"],
        ["--playlist-slice", ":", "PLAYLIST_URL"],
        ["--playlist-slice", "1:5:0", "PLAYLIST_URL"],
        ["--playlist-slice", "1:two", "PLAYLIST_URL"],
    ],
)
def test_cli_playlist_selection_rejects_invalid_values(downloader, argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        downloader.build_parser().parse_args(argv)
    assert exc_info.value.code == 2


def test_playlist_profile_normalises_indices_and_slices(downloader, tmp_path: Path) -> None:
    path = tmp_path / "defaults.json"
    path.write_text(
        '{"version":1,"profiles":{"selected":{"playlist":true,"playlist-items":[3,"5:8","01:020:02",-1]}}}',
        encoding="utf-8",
    )
    profile = downloader.select_parameter_profile("selected", path, explicit_defaults=True)
    assert profile is not None
    assert profile.settings["playlist-items"] == ["3", "5:8", "1:20:2", "-1"]


@pytest.mark.parametrize(
    "items",
    [
        [],
        [0],
        [True],
        ["1:5:0"],
        ["1:bad"],
        [[1, 2]],
    ],
)
def test_playlist_profile_rejects_invalid_item_specs(downloader, tmp_path: Path, items: list[object]) -> None:
    with pytest.raises(ValueError, match="playlist-items"):
        downloader.validate_parameter_settings({"playlist-items": items}, profile_name="broken")


def test_explicit_playlist_selection_replaces_profile_selection(downloader, tmp_path: Path) -> None:
    args = downloader.build_parser().parse_args(
        ["--playlist-index", "9", "--playlist-slice", "20:30:2", "PLAYLIST_URL"]
    )
    profile = downloader.ParameterProfile(
        name="subset",
        source=tmp_path / "defaults.json",
        settings={"playlist": True, "playlist-items": ["1:5"]},
    )
    resolved = downloader.resolve_parameter_settings(profile, downloader.explicit_parameter_settings(args))
    assert resolved.settings["playlist-items"] == ["9", "20:30:2"]
    assert resolved.sources["playlist-items"] == "explicit CLI"


def test_playlist_profile_rejects_no_playlist_conflict(downloader) -> None:
    with pytest.raises(ValueError, match="playlist-items with playlist=false"):
        downloader.validate_parameter_settings(
            {"playlist": False, "playlist-items": [1, "3:5"]},
            profile_name="broken",
        )


def test_playlist_selection_compiles_to_single_yt_dlp_item_spec(downloader, tmp_path: Path, monkeypatch) -> None:
    plan = _plan(
        downloader,
        tmp_path,
        monkeypatch,
        {"playlist": True, "playlist-items": ["5:8", "1", "-5::2", "-1"]},
    )
    command = plan.command()
    assert command.count("-I") == 1
    assert command[command.index("-I") + 1] == "5:8,1,-5::2,-1"
    assert "--yes-playlist" in command
    assert "--download-archive" in command


def test_playlist_selection_can_combine_with_reverse_traversal(downloader, tmp_path: Path, monkeypatch) -> None:
    plan = _plan(
        downloader,
        tmp_path,
        monkeypatch,
        {"playlist-items": ["2:10:2"], "reverse-playlist": True},
    )
    command = plan.command()
    assert command[command.index("-I") + 1] == "2:10:2"
    assert "--playlist-reverse" in command


def test_playlist_forward_overrides_reverse_profile(downloader, tmp_path: Path) -> None:
    parser = downloader.build_parser()
    args = parser.parse_args(["--playlist-forward", "PLAYLIST_URL"])
    profile = downloader.ParameterProfile(
        name="reverse",
        source=tmp_path / "defaults.json",
        settings={"reverse-playlist": True},
    )
    resolved = downloader.resolve_parameter_settings(profile, downloader.explicit_parameter_settings(args))
    assert resolved.settings["reverse-playlist"] is False
    assert resolved.sources["reverse-playlist"] == "explicit CLI"


def test_resolved_policy_rejects_selection_with_no_playlist(downloader, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(downloader, "COOKIES_FILE", tmp_path / "missing-cookies.txt")
    with pytest.raises(ValueError, match="playlist item selection cannot be combined with --no-playlist"):
        downloader.resolve_parameter_policy({"playlist": False, "playlist-items": ["1:3"]})


def test_playlist_selection_is_visible_in_explain_output(downloader, tmp_path: Path, monkeypatch) -> None:
    plan = _plan(
        downloader,
        tmp_path,
        monkeypatch,
        {"playlist-items": ["1", "4:10", "20::2"]},
    )
    payload = downloader.explain_plan_payload(plan)
    assert payload["policy"]["playlist_items"] == ["1", "4:10", "20::2"]
    assert payload["policy"]["playlist_item_spec"] == "1,4:10,20::2"
    rendered = downloader.format_plan_explanation(plan)
    assert "Playlist items:    1,4:10,20::2" in rendered


def test_playlist_selection_rejects_completed_id_queue_mutation(downloader, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(downloader, "COOKIES_FILE", tmp_path / "missing-cookies.txt")
    queue = tmp_path / "queue.txt"
    queue.write_text("https://example.invalid/playlist\n", encoding="utf-8")
    with pytest.raises(ValueError, match="playlist item selection cannot be combined with --remove-completed-ids"):
        downloader.create_download_plan(
            executable="yt-dlp",
            resolved_parameters=downloader.ResolvedParameterSettings(
                settings={"playlist-items": ["1:3"]},
                sources={"playlist-items": "explicit CLI"},
            ),
            input_source=downloader.InputSource(batch_file=queue),
            output_profile=None,
            defaults_file=tmp_path / "defaults.json",
            parameter_profile=None,
            remove_completed_ids=True,
        )
