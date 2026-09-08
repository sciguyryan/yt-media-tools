"""UNION and UNION ALL coverage, including heterogeneous extractor-shaped fixtures."""

import pytest

from yt_media_tools.optimizer import optimise_query
from yt_media_tools.query import QuerySyntaxError, apply_query, parse_query, query_physical_sources, resolve_query
from yt_media_tools.schema import QuerySchema


def _heterogeneous_records() -> list[dict[str, object]]:
    return [
        {
            "id": "yt-channel-1",
            "title": "AMV Σ",
            "view_count": 1200,
            "duration": 210,
            "playlist_index": None,
            "_yt_sql_source": "@youtube_channel",
        },
        {
            "id": "yt-playlist-1",
            "title": "AMV e\u0301",
            "view_count": 800,
            "duration": 180,
            "playlist_index": 1,
            "_yt_sql_source": "@youtube_playlist",
        },
        {
            "id": "shared-id",
            "title": "Shared",
            "view_count": 50,
            "duration": 90,
            "playlist_index": 2,
            "_yt_sql_source": "@youtube_playlist",
        },
        {
            "id": "twitch-1",
            "title": "AMV stream",
            "view_count": None,
            "duration": 3600,
            "playlist_index": None,
            "_yt_sql_source": "@twitch_archive",
        },
        {
            "id": "shared-id",
            "title": "Shared",
            "view_count": None,
            "duration": 90,
            "playlist_index": None,
            "_yt_sql_source": "@twitch_archive",
        },
    ]


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
