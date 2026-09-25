from pathlib import Path

from yt_media_tools.discover_acquisition import _cached_or_refresh_metadata
from yt_media_tools.ytdlp import AcquisitionStats


def test_specialised_youtubejs_acquisition_returns_provenance_without_writing_partial_cache(monkeypatch) -> None:
    captured = {}

    def fake_acquire(project_root, video_ids, *, cookies_file=None):
        captured["project_root"] = project_root
        captured["video_ids"] = video_ids
        return (
            [
                {
                    "id": "abc",
                    "title": "Title",
                    "duration": 12,
                    "_yt_sql_metadata_provider": "youtubejs",
                    "_yt_sql_metadata_operation": "getBasicInfo",
                }
            ],
            AcquisitionStats(available=1),
        )

    monkeypatch.setattr("yt_media_tools.discover_acquisition.acquire_youtubejs_basic_info", fake_acquire)
    records, stats, cache_stats = _cached_or_refresh_metadata(
        cache=None,
        source_url="https://www.youtube.com/@example/videos",
        video_ids=["abc"],
        required_fields={"title", "duration"},
        verbose=0,
        cookies_file=None,
        specialised_provider="youtubejs",
        project_root=Path("/project"),
    )

    assert captured == {"project_root": Path("/project"), "video_ids": ["abc"]}
    assert records[0]["_yt_sql_metadata_provider"] == "youtubejs"
    assert records[0]["_yt_sql_metadata_operation"] == "getBasicInfo"
    assert stats.available == 1
    assert cache_stats.written == 0


def test_specialised_youtubejs_failure_falls_back_to_ytdlp(monkeypatch) -> None:
    from yt_media_tools.youtubejs import YouTubeJsError

    def fail(*args, **kwargs):
        raise YouTubeJsError("synthetic failure")

    def fake_load(command, *, progress=None):
        return ([{"id": "abc", "title": "Fallback"}], AcquisitionStats(available=1))

    monkeypatch.setattr("yt_media_tools.discover_acquisition.acquire_youtubejs_basic_info", fail)
    monkeypatch.setattr("yt_media_tools.discover_acquisition.load_metadata", fake_load)
    records, stats, _ = _cached_or_refresh_metadata(
        cache=None,
        source_url="https://www.youtube.com/@example/videos",
        video_ids=["abc"],
        required_fields={"title"},
        verbose=0,
        cookies_file=None,
        specialised_provider="youtubejs",
        project_root=Path("/project"),
    )

    assert records == [{"id": "abc", "title": "Fallback"}]
    assert stats.available == 1


def test_application_provider_selection_requires_complete_lowering() -> None:
    from yt_media_tools.acquisition_plan import PhysicalAcquisitionPlan, AcquisitionStage
    from yt_media_tools.discover_application import _specialised_metadata_provider
    from yt_media_tools.source_model import SourceSpec

    source = SourceSpec("youtube", "@example", "https://www.youtube.com/@example/videos")
    complete = AcquisitionStage("complete-metadata", True, frozenset({"title", "duration"}), "test")
    plan = PhysicalAcquisitionPlan(source, (complete,), "test")
    records = [{"extractor": "youtube:tab", "extractor_key": "YoutubeTab"}]
    assert (
        _specialised_metadata_provider(physical_plan=plan, resolution_records=records, cookies_file=None) == "youtubejs"
    )

    unsupported = AcquisitionStage("complete-metadata", True, frozenset({"title", "upload_date"}), "test")
    unsupported_plan = PhysicalAcquisitionPlan(source, (unsupported,), "test")
    assert (
        _specialised_metadata_provider(physical_plan=unsupported_plan, resolution_records=records, cookies_file=None)
        is None
    )


def test_specialised_youtubejs_partial_result_falls_back_only_for_missing_ids(monkeypatch) -> None:
    commands = []

    def fake_acquire(project_root, video_ids, *, cookies_file=None):
        return (
            [
                {
                    "id": "a",
                    "title": "A",
                    "_yt_sql_metadata_provider": "youtubejs",
                    "_yt_sql_metadata_operation": "getBasicInfo",
                }
            ],
            AcquisitionStats(available=1),
        )

    def fake_load(command, *, progress=None):
        commands.append(command)
        return ([{"id": "b", "title": "B"}], AcquisitionStats(available=1))

    monkeypatch.setattr("yt_media_tools.discover_acquisition.acquire_youtubejs_basic_info", fake_acquire)
    monkeypatch.setattr("yt_media_tools.discover_acquisition.load_metadata", fake_load)
    records, stats, _ = _cached_or_refresh_metadata(
        cache=None,
        source_url="https://www.youtube.com/@example/videos",
        video_ids=["a", "b"],
        required_fields={"title"},
        verbose=0,
        cookies_file=None,
        specialised_provider="youtubejs",
        project_root=Path("/project"),
    )

    assert [record["id"] for record in records] == ["a", "b"]
    assert stats.available == 2
    assert len(commands) == 1
    rendered = " ".join(commands[0])
    assert "watch?v=b" in rendered
    assert "watch?v=a" not in rendered


def test_production_youtubejs_batches_requested_ids_into_one_bridge_invocation(monkeypatch) -> None:
    """One production batch should share one bridge process and therefore one Innertube session."""
    from types import SimpleNamespace

    from yt_media_tools.youtubejs import acquire_basic_info

    captured = []

    monkeypatch.setattr("yt_media_tools.youtubejs.shutil.which", lambda executable: "/usr/bin/node")
    monkeypatch.setattr("yt_media_tools.youtubejs.emit_invocation", lambda invocation: None)

    def fake_run(command, **kwargs):
        captured.append(command)
        return SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=(
                '{"ok":true,"id":"a","title":"A","channel_id":"c","duration":1,"view_count":2}\n'
                '{"ok":true,"id":"b","title":"B","channel_id":"c","duration":3,"view_count":4}\n'
            ),
        )

    monkeypatch.setattr("yt_media_tools.youtubejs.subprocess.run", fake_run)
    project_root = Path(__file__).resolve().parents[1]
    records, stats = acquire_basic_info(project_root, ["a", "b"])

    assert len(captured) == 1
    assert captured[0][-3:] == ["--basic-info", "a", "b"]
    assert [record["id"] for record in records] == ["a", "b"]
    assert stats.available == 2


def test_specialised_youtubejs_success_and_ytdlp_fallback_preserve_requested_order(monkeypatch) -> None:
    """Mixed provider completion must remain observationally ordered by requested IDs."""

    def fake_acquire(project_root, video_ids, *, cookies_file=None):
        return (
            [
                {
                    "id": "c",
                    "title": "C",
                    "_yt_sql_metadata_provider": "youtubejs",
                    "_yt_sql_metadata_operation": "getBasicInfo",
                },
                {
                    "id": "a",
                    "title": "A",
                    "_yt_sql_metadata_provider": "youtubejs",
                    "_yt_sql_metadata_operation": "getBasicInfo",
                },
            ],
            AcquisitionStats(available=2),
        )

    def fake_load(command, *, progress=None):
        return ([{"id": "b", "title": "B"}], AcquisitionStats(available=1))

    monkeypatch.setattr("yt_media_tools.discover_acquisition.acquire_youtubejs_basic_info", fake_acquire)
    monkeypatch.setattr("yt_media_tools.discover_acquisition.load_metadata", fake_load)
    records, stats, _ = _cached_or_refresh_metadata(
        cache=None,
        source_url="https://www.youtube.com/@example/videos",
        video_ids=["a", "b", "c"],
        required_fields={"title"},
        verbose=0,
        cookies_file=None,
        specialised_provider="youtubejs",
        project_root=Path("/project"),
    )

    assert [record["id"] for record in records] == ["a", "b", "c"]
    assert [record["title"] for record in records] == ["A", "B", "C"]
    assert stats.available == 3
