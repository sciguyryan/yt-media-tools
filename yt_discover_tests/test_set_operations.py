"""UNION and UNION ALL coverage, including heterogeneous extractor-shaped fixtures."""

import pytest

from yt_media_tools.optimizer import optimise_query
from yt_media_tools.query import QuerySyntaxError, apply_query, parse_query, query_physical_sources, resolve_query
from yt_media_tools.schema import QuerySchema
from yt_discover_tests.conformance.multi_source_fixture import (
    TWITCH_ARCHIVE,
    YOUTUBE_CHANNEL,
    YOUTUBE_PLAYLIST,
    heterogeneous_records,
)


def _heterogeneous_records() -> list[dict[str, object]]:
    return heterogeneous_records()


def _resolve(text: str, records: list[dict[str, object]]):
    query = parse_query(text)
    source_schemas = {
        source: QuerySchema([record for record in records if record.get("_yt_sql_source") == source])
        for source in query_physical_sources(query)
    }
    return resolve_query(query, QuerySchema(records), source_schemas=source_schemas)


def test_union_all_composes_heterogeneous_sources_positionally() -> None:
    records = _heterogeneous_records()
    query = _resolve(
        "SELECT id AS media_id, title, view_count FROM @youtube_channel "
        "UNION ALL SELECT id AS ignored_name, title, view_count FROM @twitch_archive "
        "ORDER BY media_id",
        records,
    )
    rows = apply_query(records, query)
    assert [(row["media_id"], row["view_count"]) for row in rows] == [
        ("shared-id", None),
        ("twitch-1", None),
        ("yt-channel-1", 1200),
        ("yt-channel-2", 800),
    ]


def test_union_eliminates_duplicates_across_source_families() -> None:
    records = _heterogeneous_records()
    query = _resolve(
        "SELECT id, title FROM @youtube_playlist UNION SELECT id, title FROM @twitch_archive ORDER BY id",
        records,
    )
    rows = apply_query(records, query)
    assert [(row["id"], row["title"]) for row in rows] == [
        ("shared-id", "Shared"),
        ("twitch-1", "AMV stream"),
        ("yt-playlist-1", "AMV e\u0301"),
    ]


def test_union_inside_cte_exports_first_branch_schema() -> None:
    records = _heterogeneous_records()
    query = _resolve(
        "WITH media AS ("
        "SELECT id AS media_id, title FROM @youtube_playlist "
        "UNION ALL SELECT id AS other_id, title FROM @twitch_archive"
        ") SELECT media_id, title FROM media ORDER BY media_id",
        records,
    )
    rows = apply_query(records, query)
    assert [row["media_id"] for row in rows] == ["shared-id", "shared-id", "twitch-1", "yt-playlist-1"]


def test_union_requires_equal_projection_cardinality() -> None:
    records = _heterogeneous_records()
    with pytest.raises(QuerySyntaxError, match="same number of columns"):
        _resolve("SELECT id FROM @youtube_channel UNION ALL SELECT id, title FROM @twitch_archive", records)


def test_union_rejects_incompatible_per_source_dynamic_types() -> None:
    records = [
        {"id": "a", "extractor_value": 3, "_yt_sql_source": "@numeric"},
        {"id": "b", "extractor_value": "three", "_yt_sql_source": "@text"},
    ]
    with pytest.raises(QuerySyntaxError, match="incompatible kinds integer and string"):
        _resolve("SELECT extractor_value FROM @numeric UNION ALL SELECT extractor_value FROM @text", records)


def test_union_optimiser_is_differentially_equivalent() -> None:
    records = _heterogeneous_records()
    resolved = _resolve(
        "SELECT id, 0x10 + 0b10 AS score FROM @youtube_playlist "
        "UNION ALL SELECT id, 18 AS score FROM @twitch_archive ORDER BY id",
        records,
    )
    optimised = optimise_query(resolved).query
    assert apply_query(records, resolved) == apply_query(records, optimised)


def test_union_reports_physical_sources_in_first_use_order() -> None:
    query = parse_query(
        "SELECT id FROM @youtube_channel UNION ALL SELECT id FROM @twitch_archive "
        "UNION SELECT id FROM @youtube_playlist"
    )
    assert query_physical_sources(query) == ("@youtube_channel", "@twitch_archive", "@youtube_playlist")


def test_mixed_union_boundaries_are_left_associative() -> None:
    records = _heterogeneous_records()
    query = _resolve(
        "SELECT id, title FROM @youtube_playlist "
        "UNION SELECT id, title FROM @twitch_archive "
        "UNION ALL SELECT id, title FROM @twitch_archive ORDER BY id, title",
        records,
    )
    rows = apply_query(records, query)
    assert [(row["id"], row["title"]) for row in rows] == [
        ("shared-id", "Shared"),
        ("shared-id", "Shared"),
        ("twitch-1", "AMV stream"),
        ("twitch-1", "AMV stream"),
        ("yt-playlist-1", "AMV e\u0301"),
    ]


def test_union_preserves_unicode_normalisation_distinctions() -> None:
    records = _heterogeneous_records()
    query = _resolve(
        "SELECT title FROM @youtube_channel WHERE id = 'yt-channel-2' "
        "UNION SELECT title FROM @youtube_playlist WHERE id = 'yt-playlist-1' ORDER BY title",
        records,
    )
    rows = apply_query(records, query)
    assert len(rows) == 2
    assert {row["title"] for row in rows} == {"AMV é", "AMV e\u0301"}


def test_union_branches_may_aggregate_independently() -> None:
    records = _heterogeneous_records()
    query = _resolve(
        "SELECT uploader, COUNT(*) AS item_count, AVG(duration) AS average_duration "
        "FROM @youtube_channel GROUP BY uploader "
        "UNION ALL "
        "SELECT uploader, COUNT(*) AS item_count, AVG(duration) AS average_duration "
        "FROM @twitch_archive GROUP BY uploader ORDER BY uploader",
        records,
    )
    rows = apply_query(records, query)
    assert rows == [
        {"uploader": "Channel A", "item_count": 2, "average_duration": 210.0},
        {"uploader": "Streamer", "item_count": 2, "average_duration": 1845.0},
    ]


def test_union_cte_can_be_aggregated_by_outer_query() -> None:
    records = _heterogeneous_records()
    query = _resolve(
        "WITH media AS ("
        "SELECT uploader, duration FROM @youtube_channel "
        "UNION ALL SELECT uploader, duration FROM @youtube_playlist "
        "UNION ALL SELECT uploader, duration FROM @twitch_archive"
        ") SELECT uploader, COUNT(*) AS item_count, SUM(duration) AS total_duration "
        "FROM media GROUP BY uploader HAVING COUNT(*) >= 2 ORDER BY uploader",
        records,
    )
    rows = apply_query(records, query)
    assert rows == [
        {"uploader": "Channel A", "item_count": 2, "total_duration": 210},
        {"uploader": "Channel B", "item_count": 2, "total_duration": 270},
        {"uploader": "Streamer", "item_count": 2, "total_duration": 3690},
    ]


def test_union_global_limit_applies_after_all_sources() -> None:
    records = _heterogeneous_records()
    query = _resolve(
        "SELECT id, duration FROM @youtube_channel "
        "UNION ALL SELECT id, duration FROM @youtube_playlist "
        "UNION ALL SELECT id, duration FROM @twitch_archive "
        "ORDER BY duration DESC, id ASC LIMIT 3 OFFSET 1",
        records,
    )
    rows = apply_query(records, query)
    assert [(row["id"], row["duration"]) for row in rows] == [
        ("yt-channel-1", 210),
        ("yt-playlist-1", 180),
        ("shared-id", 90),
    ]


def test_heterogeneous_fixture_has_intentionally_incompatible_dynamic_kind() -> None:
    records = _heterogeneous_records()
    assert {record["_yt_sql_source"] for record in records} == {
        YOUTUBE_CHANNEL,
        YOUTUBE_PLAYLIST,
        TWITCH_ARCHIVE,
    }
    with pytest.raises(QuerySyntaxError, match="incompatible kinds integer and string"):
        _resolve(
            "SELECT extractor_value FROM @youtube_channel UNION ALL SELECT extractor_value FROM @twitch_archive",
            records,
        )
