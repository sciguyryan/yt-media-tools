"""Tests for registered yt-dlp metadata normalisation and migration accounting."""

from datetime import datetime, timezone

from yt_media_tools.cache import MetadataCache
from yt_media_tools.cache_v4_ytdlp import YTDLP_PROVIDER, normalise_registered_metadata


NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def test_normalisation_separates_registered_stable_and_discarded_material() -> None:
    values, accounting = normalise_registered_metadata(
        {
            "id": "abc",
            "title": "Example",
            "view_count": 0,
            "tags": ["one", "two"],
            "formats": [{"format_id": "18"}],
            "backend_internal": {"opaque": True},
            "_yt_sql_source": "ignored-provenance",
        }
    )

    assert values["id"] == "abc"
    assert values["view_count"] == 0
    assert "tags" not in values
    assert accounting.stable_equivalent_fields == ("formats", "tags")
    assert accounting.discarded_backend_fields == ("backend_internal",)
    assert "_yt_sql_source" not in accounting.discarded_backend_fields


def test_put_many_writes_registered_metadata_and_accounting_without_removing_raw_json(tmp_path) -> None:
    path = tmp_path / "cache.sqlite"
    record = {
        "id": "abc",
        "title": "Example",
        "timestamp": 1_700_000_000,
        "tags": ["one"],
        "backend_internal": {"opaque": True},
    }
    with MetadataCache(path) as cache:
        assert cache.put_many("https://example.invalid/source", [record], fetched_at=NOW) == 1
        db = cache._db()
        entity_id = db.execute(
            "SELECT entity_id FROM cache_v4_media_entities WHERE service='youtube' AND external_id='abc'"
        ).fetchone()[0]
        row = db.execute(
            "SELECT title, timestamp FROM cache_v4_ytdlp_metadata WHERE entity_id=?",
            (entity_id,),
        ).fetchone()
        assert tuple(row) == ("Example", "1700000000")
        accounting = db.execute(
            """
            SELECT registered_fields, stable_equivalent_fields, discarded_backend_fields
            FROM cache_v4_raw_migration_accounting
            WHERE source_url=? AND video_id='abc'
            """,
            ("https://example.invalid/source",),
        ).fetchone()
        assert accounting[0] > 0
        assert accounting[1] == 1
        assert accounting[2] == 1
        assert db.execute("SELECT raw_json FROM metadata_records WHERE video_id='abc'").fetchone() is not None


def test_registered_provider_owns_types_acquisition_group_and_freshness() -> None:
    assert YTDLP_PROVIDER.key == "yt-dlp"
    assert {group.key for group in YTDLP_PROVIDER.acquisition_groups} == {"detailed"}
    title = YTDLP_PROVIDER.field("title")
    timestamp = YTDLP_PROVIDER.field("timestamp")
    assert title is not None and title.value_type.kind == "string"
    assert timestamp is not None and timestamp.value_type.kind == "datetime"
    assert title.acquisition_group == "detailed"
    assert title.freshness.max_age_seconds == 7 * 86400
