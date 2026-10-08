"""Downloader consumption tests for the versioned collection interchange."""

from __future__ import annotations

import base64
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

from yt_media_tools.collection_export import build_playlist_collection, write_collection
from yt_media_tools.query import parse_query
from yt_media_tools.source_model import SourceSpec


def _write_collection(
    path: Path,
    *,
    targets=("first", "second", "third"),
    metadata=None,
    entry_metadata=None,
) -> Path:
    if metadata is None:
        metadata = {
            "title": "Filtered collection",
            "id": "source-list",
            "uploader": "Example uploader",
        }
    payload = {
        "schema": "yt-media-tools.collection",
        "version": 1,
        "collection": {
            "type": "playlist",
            "metadata": metadata,
        },
        "entries": [
            {
                "target": target,
                **({"metadata": entry_metadata[index]} if entry_metadata is not None else {}),
            }
            for index, target in enumerate(targets)
        ],
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
    assert command[-4:] == ["--", "first", "second", "third"]


def test_collection_command_separates_leading_dash_target_from_options(downloader, tmp_path: Path) -> None:
    collection = _write_collection(tmp_path / "collection.json", targets=("-ttxL2vaB3Q", "ordinary"))
    source = downloader.load_collection_input(collection)
    policy = downloader.DownloadPolicy(resolution="1080", format_selector="bv+ba/best", reverse_playlist=False)
    command = downloader.build_yt_dlp_command("yt-dlp", policy, source, None)
    assert command[-3:] == ["--", "-ttxL2vaB3Q", "ordinary"]


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


def _load_collection_plugin(collection: Path):
    """Load the bundled bridge without requiring yt-dlp in the test environment."""

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
        spec = importlib.util.spec_from_file_location("collection_metadata_hardening_plugin", plugin_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        encoded = base64.urlsafe_b64encode(str(collection).encode("utf-8")).decode("ascii")
        return module.CollectionMetadataPP(collection=encoded)
    finally:
        sys.modules.pop("yt_dlp.postprocessor.common", None)
        sys.modules.pop("yt_dlp.postprocessor", None)
        sys.modules.pop("yt_dlp", None)


def _discover_collection(path: Path, *, title: str) -> Path:
    source = SourceSpec(
        "playlist",
        "PLexample123",
        "https://www.youtube.com/playlist?list=PLexample123",
        "PLexample123",
    )
    records = [
        {"id": "first", "title": "First video"},
        {"id": "second", "title": "Second video"},
    ]
    query = parse_query("SELECT id, title FROM PLexample123 ORDER BY source_index")
    payload = build_playlist_collection(
        source,
        records,
        records,
        query,
        collection_title=title,
    )
    write_collection(path, payload)
    return path


def test_discover_title_reaches_downloader_template_and_hook_metadata(downloader, tmp_path: Path) -> None:
    collection = _discover_collection(tmp_path / "discover.json", title="Discover collection")

    source = downloader.load_collection_input(collection)
    assert source.direct_targets == ("first", "second")
    command = downloader.build_yt_dlp_command(
        "yt-dlp",
        downloader.DownloadPolicy(resolution="best", format_selector="bv+ba/b", reverse_playlist=False),
        source,
        None,
    )
    assert any(value.startswith("CollectionMetadata:when=pre_process;") for value in command)

    plugin = _load_collection_plugin(collection)
    _, info = plugin.run(
        {
            "original_url": "first",
            "title": "First video",
            "ext": "webm",
            "playlist_title": "Remote title",
        }
    )

    assert "%(playlist_title)s/%(title)s.%(ext)s" % info == "Discover collection/First video.webm"
    hook_event = {"status": "finished", "info_dict": info}
    assert hook_event["info_dict"]["playlist_title"] == "Discover collection"
    assert hook_event["info_dict"]["playlist"] == "Discover collection"


def test_title_only_changes_preserve_collection_targets_and_positions(downloader, tmp_path: Path) -> None:
    first_path = _discover_collection(tmp_path / "first.json", title="First title")
    second_path = _discover_collection(tmp_path / "second.json", title="Renamed collection")

    first_source = downloader.load_collection_input(first_path)
    second_source = downloader.load_collection_input(second_path)
    assert first_source.direct_targets == second_source.direct_targets == ("first", "second")

    first_plugin = _load_collection_plugin(first_path)
    second_plugin = _load_collection_plugin(second_path)
    _, first_info = first_plugin.run({"original_url": "second"})
    _, second_info = second_plugin.run({"original_url": "second"})

    positional_fields = ("playlist_index", "playlist_autonumber", "playlist_count", "n_entries")
    assert (
        tuple(first_info[field] for field in positional_fields)
        == tuple(second_info[field] for field in positional_fields)
        == (2, 2, 2, 2)
    )


def test_constructed_collection_needs_no_remote_playlist_identity(tmp_path: Path) -> None:
    collection = _write_collection(
        tmp_path / "constructed.json",
        targets=("custom:first", "custom:second"),
        metadata={},
    )
    plugin = _load_collection_plugin(collection)

    _, second = plugin.run({"original_url": "custom:second", "title": "Extractor title"})

    assert second["title"] == "Extractor title"
    assert "playlist" not in second
    assert "playlist_id" not in second
    assert second["playlist_index"] == second["playlist_autonumber"] == 2
    assert second["playlist_count"] == second["n_entries"] == 2


def test_archive_skipped_prefix_does_not_renumber_later_collection_entry(tmp_path: Path) -> None:
    collection = _write_collection(tmp_path / "collection.json")
    plugin = _load_collection_plugin(collection)

    # yt-dlp may reject an archived target before pre_process.  The bridge must
    # therefore derive position from collection identity rather than call count.
    _, third = plugin.run({"original_url": "third"})

    assert third["playlist_index"] == third["playlist_autonumber"] == 3
    assert third["playlist_count"] == third["n_entries"] == 3


def test_duplicate_targets_retain_distinct_ordered_positions(tmp_path: Path) -> None:
    collection = _write_collection(
        tmp_path / "duplicates.json",
        targets=("same", "middle", "same"),
    )
    plugin = _load_collection_plugin(collection)

    _, first = plugin.run({"original_url": "same"})
    _, third = plugin.run({"original_url": "same"})

    assert first["playlist_index"] == first["playlist_autonumber"] == 1
    assert third["playlist_index"] == third["playlist_autonumber"] == 3


def test_collection_command_keeps_download_archive_authoritative(downloader, tmp_path: Path) -> None:
    collection = _write_collection(tmp_path / "collection.json")
    source = downloader.load_collection_input(collection)
    archive = tmp_path / "archive.txt"
    policy = downloader.DownloadPolicy(
        resolution="best",
        format_selector="bv+ba/b",
        reverse_playlist=False,
        archive_file=archive,
    )

    command = downloader.build_yt_dlp_command("yt-dlp", policy, source, None)

    archive_index = command.index("--download-archive")
    assert command[archive_index + 1] == str(archive)
    assert "--no-download-archive" not in command


def test_collection_remove_completed_rows_is_rejected_without_mutation(
    downloader,
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    collection = _write_collection(tmp_path / "collection.json")
    before = collection.read_bytes()
    monkeypatch.setattr(downloader, "validate_environment", lambda *, dry_run: "yt-dlp")

    with pytest.raises(SystemExit) as exc:
        downloader.main(["--collection-file", str(collection), "--remove-completed-rows", "--dry-run"])

    assert exc.value.code == 2
    assert "--remove-completed-rows does not operate on collection files" in capsys.readouterr().err
    assert collection.read_bytes() == before


def test_collection_entry_metadata_is_accepted_but_not_injected(tmp_path: Path) -> None:
    collection = _write_collection(
        tmp_path / "metadata.json",
        targets=("first",),
        entry_metadata=({"uploader": "Projected impostor", "custom": 0, "missing": None},),
    )
    plugin = _load_collection_plugin(collection)

    _, info = plugin.run({"original_url": "first", "uploader": "Extractor uploader"})

    assert info["uploader"] == "Extractor uploader"
    assert "custom" not in info
    assert "missing" not in info
    assert info["playlist_uploader"] == "Example uploader"


def test_collection_entry_metadata_must_be_an_object(downloader, tmp_path: Path) -> None:
    collection = _write_collection(tmp_path / "invalid.json")
    payload = json.loads(collection.read_text(encoding="utf-8"))
    payload["entries"][0]["metadata"] = ["not", "an", "object"]
    collection.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="metadata must be a JSON object"):
        downloader.load_collection_input(collection)


def test_continuation_reconciliation_preserves_order_duplicates_and_original_file(downloader, tmp_path: Path) -> None:
    collection = _write_collection(tmp_path / "collection.json", targets=("A", "B", "A", "X", "C"))
    original = collection.read_bytes()
    source = downloader.load_collection_input(collection)
    reconciled = downloader.reconcile_collection_targets(source, {"A", "C"})
    assert reconciled.direct_targets == ("B", "X")
    assert reconciled.collection_file == source.collection_file
    assert source.direct_targets == ("A", "B", "A", "X", "C")
    assert collection.read_bytes() == original
    command = downloader.build_yt_dlp_command(
        "yt-dlp",
        downloader.DownloadPolicy(resolution="best", format_selector="bv+ba/b", reverse_playlist=False),
        reconciled,
        None,
    )
    assert command[-3:] == ["--", "B", "X"]
    assert "CollectionMetadata:when=pre_process" in " ".join(command)


def test_continuation_reconciliation_handles_all_completed_and_unidentified(downloader, tmp_path: Path) -> None:
    source = downloader.load_collection_input(_write_collection(tmp_path / "collection.json"))
    assert source.collection_identity is None
    assert downloader.reconcile_collection_targets(source, set()).direct_targets == source.direct_targets
    assert downloader.reconcile_collection_targets(source, set(source.direct_targets)).direct_targets == ()
