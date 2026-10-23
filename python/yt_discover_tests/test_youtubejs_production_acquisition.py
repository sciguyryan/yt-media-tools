from pathlib import Path

from yt_media_tools.discover_acquisition import _cached_or_refresh_metadata
from yt_media_tools.ytdlp import AcquisitionStats


def _fallback_metadata_loader(records, *, commands=None):
    """Return fixed yt-dlp records while retaining callback and command semantics."""

    def fake_load(command, *, progress=None, record_callback=None):
        if commands is not None:
            commands.append(command)
        if record_callback is not None:
            for record in records:
                record_callback(record)
        return records, AcquisitionStats(available=len(records))

    return fake_load


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

    fake_load = _fallback_metadata_loader([{"id": "abc", "title": "Fallback"}])

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

    unsupported = AcquisitionStage("complete-metadata", True, frozenset({"title", "release_timestamp"}), "test")
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

    fake_load = _fallback_metadata_loader([{"id": "b", "title": "B"}], commands=commands)

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
    project_root = Path(__file__).resolve().parents[2]
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

    fake_load = _fallback_metadata_loader([{"id": "b", "title": "B"}])

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


def test_minimum_sufficient_provider_uses_only_stale_required_subset(monkeypatch) -> None:
    from datetime import datetime, timedelta, timezone
    from yt_media_tools.cache import CachedMetadata

    now = datetime.now(timezone.utc)

    class Cache:
        def get_many(self, source_url, video_ids):
            return {
                "abc": CachedMetadata(
                    "abc",
                    {"id": "abc", "title": "Old title", "upload_date": "20260101"},
                    now - timedelta(days=8),
                )
            }

        def stale_fields(self, item, required_fields, *, now=None):
            from yt_media_tools.cache import field_max_age

            current = now or datetime.now(timezone.utc)
            age = current - item.fetched_at
            return frozenset(field for field in required_fields if age > field_max_age(field))

        def freshness_policy(self, field):
            from yt_media_tools.cache_v4_ytdlp import YTDLP_FRESHNESS_POLICIES

            resolved = YTDLP_FRESHNESS_POLICIES.field(field)
            assert resolved is not None
            return resolved

        def put_many(self, source_url, records):
            raise AssertionError("specialised partial refresh must not be misattributed to yt-dlp cache storage")

    def fake_acquire(project_root, video_ids, *, cookies_file=None):
        assert video_ids == ["abc"]
        return (
            [
                {
                    "id": "abc",
                    "title": "Fresh title",
                    "_yt_sql_metadata_provider": "youtubejs",
                    "_yt_sql_metadata_operation": "getBasicInfo",
                }
            ],
            AcquisitionStats(available=1),
        )

    def fail_ytdlp(*args, **kwargs):
        raise AssertionError("yt-dlp must not run when the unresolved field subset is covered exactly")

    monkeypatch.setattr("yt_media_tools.discover_acquisition.acquire_youtubejs_basic_info", fake_acquire)
    monkeypatch.setattr("yt_media_tools.discover_acquisition.load_metadata", fail_ytdlp)
    records, stats, cache_stats = _cached_or_refresh_metadata(
        cache=Cache(),
        source_url="https://www.youtube.com/@example/videos",
        video_ids=["abc"],
        required_fields={"title", "upload_date"},
        verbose=0,
        cookies_file=None,
        specialised_provider_coverage=(("youtubejs", frozenset({"title"})),),
        project_root=Path("/project"),
    )

    assert records[0]["title"] == "Fresh title"
    assert records[0]["upload_date"] == "20260101"
    assert stats.available == 1
    assert cache_stats.stale == 1
    assert cache_stats.refreshed == 1


def test_provider_coverage_retains_supported_subset_of_mixed_query_requirement() -> None:
    from yt_media_tools.acquisition_plan import AcquisitionStage, PhysicalAcquisitionPlan
    from yt_media_tools.discover_application import _specialised_provider_field_coverage
    from yt_media_tools.source_model import SourceSpec

    source = SourceSpec("youtube", "@example", "https://www.youtube.com/@example/videos")
    complete = AcquisitionStage("complete-metadata", True, frozenset({"title", "upload_date"}), "test")
    plan = PhysicalAcquisitionPlan(source, (complete,), "test")
    records = [{"extractor": "youtube:tab", "extractor_key": "YoutubeTab"}]

    coverage = _specialised_provider_field_coverage(
        physical_plan=plan,
        resolution_records=records,
        cookies_file=None,
    )

    assert coverage[0] == ("youtubejs", frozenset({"title", "upload_date"}))


def test_basic_info_upload_date_normalisation() -> None:
    from yt_media_tools.youtubejs import _basic_info_upload_date

    assert _basic_info_upload_date("2026-10-18") == "20261018"
    assert _basic_info_upload_date("20261018") == "20261018"
    assert _basic_info_upload_date("2026-02-30") is None
    assert _basic_info_upload_date("yesterday") is None
    assert _basic_info_upload_date(None) is None
    assert _basic_info_upload_date(20261018) is None
    assert _basic_info_upload_date("2026-10-18T00:00:00Z") is None
    assert _basic_info_upload_date("2026-1-18") is None
    assert _basic_info_upload_date("2026-10-18extra") is None
    assert _basic_info_upload_date("2026-10-1x") is None
    assert _basic_info_upload_date("2026-02-29") is None
    assert _basic_info_upload_date("2024-02-29") == "20240229"
    assert _basic_info_upload_date("２０２６１０１８") is None


def test_basic_info_date_mapping_does_not_substitute_publish_date(monkeypatch) -> None:
    from types import SimpleNamespace
    from yt_media_tools.youtubejs import acquire_basic_info

    monkeypatch.setattr("yt_media_tools.youtubejs.shutil.which", lambda executable: "/usr/bin/node")
    monkeypatch.setattr("yt_media_tools.youtubejs.emit_invocation", lambda invocation: None)
    monkeypatch.setattr(
        "yt_media_tools.youtubejs.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=(
                '{"ok":true,"id":"a","upload_date":"2026-10-17","publish_date":"2026-10-18"}\n'
                '{"ok":true,"id":"b","upload_date":null,"publish_date":"2026-10-18"}\n'
            ),
        ),
    )
    records, _stats = acquire_basic_info(Path(__file__).resolve().parents[2], ["a", "b"])
    assert records[0]["upload_date"] == "20261017"
    assert records[1]["upload_date"] is None
    assert [record["publish_date"] for record in records] == ["20261018", "20261018"]


def test_basic_info_upload_date_survives_bridge_record_mapping(monkeypatch) -> None:
    """Retain the normalised date without substituting the publication date."""
    import json
    from subprocess import CompletedProcess

    from yt_media_tools.youtubejs import acquire_basic_info

    payloads = [
        {"ok": True, "id": "first", "title": "First", "upload_date": "2026-10-17", "publish_date": "2026-10-18"},
        {"ok": True, "id": "second", "title": "Second", "upload_date": None, "publish_date": "2026-10-18"},
        {"ok": True, "id": "third", "title": "Third", "upload_date": "2026-02-30", "publish_date": "2026-03-01"},
    ]

    monkeypatch.setattr("yt_media_tools.youtubejs.shutil.which", lambda _: "/usr/bin/node")
    monkeypatch.setattr(
        "yt_media_tools.youtubejs.subprocess.run",
        lambda *args, **kwargs: CompletedProcess(args[0], 0, "\n".join(map(json.dumps, payloads)), ""),
    )
    records, stats = acquire_basic_info(Path(__file__).resolve().parents[2], ["first", "second", "third"])

    assert [record["upload_date"] for record in records] == ["20261017", None, None]
    assert [record["publish_date"] for record in records] == ["20261018", "20261018", "20260301"]
    assert stats.available == 3


def test_basic_info_date_remains_available_without_detailed_fallback(monkeypatch) -> None:
    """The specialised acquisition path must retain the date in its returned records."""
    calls = []

    def fake_acquire(project_root, video_ids, *, cookies_file=None):
        return (
            [
                {
                    "id": "abc",
                    "title": "Example",
                    "upload_date": "20261017",
                    "_yt_sql_metadata_provider": "youtubejs",
                    "_yt_sql_metadata_operation": "getBasicInfo",
                }
            ],
            AcquisitionStats(available=1),
        )

    monkeypatch.setattr("yt_media_tools.discover_acquisition.acquire_youtubejs_basic_info", fake_acquire)
    monkeypatch.setattr(
        "yt_media_tools.discover_acquisition.load_metadata",
        lambda *args, **kwargs: calls.append(args) or ([], AcquisitionStats()),
    )
    records, _, _ = _cached_or_refresh_metadata(
        cache=None,
        source_url="https://www.youtube.com/@example/videos",
        video_ids=["abc"],
        required_fields={"title", "upload_date"},
        verbose=0,
        cookies_file=None,
        specialised_provider="youtubejs",
        project_root=Path("/project"),
    )
    assert records[0]["upload_date"] == "20261017"
    assert calls == []


def test_missing_basic_info_upload_date_falls_back_to_detailed_metadata(monkeypatch) -> None:
    """An absent calendar date must not count as satisfying an exact requirement."""
    requested = []

    def fake_acquire(project_root, video_ids, *, cookies_file=None):
        return ([{"id": "abc", "title": "Example", "upload_date": None}], AcquisitionStats(available=1))

    def fake_load(command, **kwargs):
        requested.append(command)
        return ([{"id": "abc", "title": "Example", "upload_date": "20261016"}], AcquisitionStats(available=1))

    monkeypatch.setattr("yt_media_tools.discover_acquisition.acquire_youtubejs_basic_info", fake_acquire)
    monkeypatch.setattr("yt_media_tools.discover_acquisition.load_metadata", fake_load)
    records, _, _ = _cached_or_refresh_metadata(
        cache=None,
        source_url="https://www.youtube.com/@example/videos",
        video_ids=["abc"],
        required_fields={"title", "upload_date"},
        verbose=0,
        cookies_file=None,
        specialised_provider="youtubejs",
        project_root=Path("/project"),
    )
    assert records[0]["upload_date"] == "20261016"
    assert len(requested) == 1
