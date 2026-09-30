"""Downloader consumption tests for the versioned collection interchange."""

from __future__ import annotations

import base64
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest


def _write_collection(path: Path, *, targets=("first", "second", "third")) -> Path:
    payload = {
        "schema": "yt-media-tools.collection",
        "version": 1,
        "collection": {
            "type": "playlist",
            "metadata": {
                "title": "Filtered collection",
                "id": "source-list",
                "uploader": "Example uploader",
            },
        },
        "entries": [{"target": target} for target in targets],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_collection_input_is_ordered_and_backend_agnostic(downloader, tmp_path: Path) -> None:
    collection = _write_collection(
        tmp_path / "collection.json", targets=("abc123", "custom:opaque", "https://example.invalid/x")
    )
    source = downloader.load_collection_input(collection)

    assert source.collection_file == collection
    assert source.direct_targets == ("abc123", "custom:opaque", "https://example.invalid/x")


def test_collection_command_loads_metadata_bridge_and_disables_remote_playlist_expansion(
    downloader, tmp_path: Path
) -> None:
    collection = _write_collection(tmp_path / "collection.json")
    source = downloader.load_collection_input(collection)
    command = downloader.build_yt_dlp_command(
        "yt-dlp",
        downloader.DownloadPolicy(resolution="best", format_selector="bv+ba/b", reverse_playlist=False),
        source,
        None,
    )

    assert "--no-playlist" in command
    plugin_index = command.index("--plugin-dirs")
    assert command[plugin_index + 1] == str(downloader.SCRIPT_DIR / "yt_dlp_plugin_packages")
    pp_index = command.index("--use-postprocessor")
    specification = command[pp_index + 1]
    assert specification.startswith("CollectionMetadata:when=pre_process;collection=")
    encoded = specification.split("collection=", 1)[1]
    assert base64.urlsafe_b64decode(encoded).decode("utf-8") == str(collection)
    assert command[-3:] == ["first", "second", "third"]


def test_collection_validation_rejects_unknown_metadata(downloader, tmp_path: Path) -> None:
    collection = _write_collection(tmp_path / "collection.json")
    payload = json.loads(collection.read_text(encoding="utf-8"))
    payload["collection"]["metadata"]["arbitrary"] = "not allowed"
    collection.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported collection metadata field"):
        downloader.load_collection_input(collection)


def test_collection_metadata_plugin_injects_typed_effective_playlist_fields(tmp_path: Path) -> None:
    collection = _write_collection(tmp_path / "collection.json")

    class FakePostProcessor:
        def __init__(self, downloader=None):
            self.downloader = downloader

    yt_dlp = types.ModuleType("yt_dlp")
    postprocessor = types.ModuleType("yt_dlp.postprocessor")
    common = types.ModuleType("yt_dlp.postprocessor.common")
    common.PostProcessor = FakePostProcessor
    sys.modules["yt_dlp"] = yt_dlp
    sys.modules["yt_dlp.postprocessor"] = postprocessor
    sys.modules["yt_dlp.postprocessor.common"] = common
    try:
        plugin_path = (
            Path(__file__).resolve().parents[1]
            / "yt_dlp_plugin_packages"
            / "yt_media_tools"
            / "yt_dlp_plugins"
            / "postprocessor"
            / "collection_metadata.py"
        )
        spec = importlib.util.spec_from_file_location("collection_metadata_test_plugin", plugin_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        encoded = base64.urlsafe_b64encode(str(collection).encode("utf-8")).decode("ascii")
        plugin = module.CollectionMetadataPP(collection=encoded)

        _, first = plugin.run({"original_url": "first", "playlist_title": "remote title"})
        _, second = plugin.run({"original_url": "second"})
    finally:
        sys.modules.pop("yt_dlp.postprocessor.common", None)
        sys.modules.pop("yt_dlp.postprocessor", None)
        sys.modules.pop("yt_dlp", None)

    assert first["playlist_title"] == "Filtered collection"
    assert first["playlist"] == "Filtered collection"
    assert first["playlist_index"] == 1
    assert first["playlist_autonumber"] == 1
    assert isinstance(first["playlist_autonumber"], int)
    assert first["playlist_count"] == first["n_entries"] == 3
    assert second["playlist_index"] == second["playlist_autonumber"] == 2


def test_collection_remove_completed_ids_warns_without_mutating_collection(
    downloader, tmp_path: Path, monkeypatch, capsys
) -> None:
    collection = _write_collection(tmp_path / "collection.json")
    monkeypatch.setattr(downloader, "validate_environment", lambda *, dry_run: "yt-dlp")

    result = downloader.main(["--collection-file", str(collection), "--remove-completed-ids", "--dry-run"])

    assert result == 0
    assert "does not modify collection files" in capsys.readouterr().err
    assert json.loads(collection.read_text(encoding="utf-8"))["entries"][0]["target"] == "first"
