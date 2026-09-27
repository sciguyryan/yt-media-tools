"""Same-source cross-facet composition and identity hardening."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from yt_media_tools.dates import DateContext
from yt_media_tools.query import QuerySyntaxError, apply_query, parse_query, resolve_query
from yt_media_tools.schema import QuerySchema


SOURCE = "@whatdamath"
VIDEOS = "videos"
SHORTS = "shorts"


def _records() -> list[dict[str, object]]:
    return [
        {
            "id": "shared",
            "title": "Long form",
            "duration": 600,
            "source_index": 1,
            "_yt_sql_source": SOURCE,
            "_yt_sql_source_facet": VIDEOS,
        },
        {
            "id": "video-only",
            "title": "Cymru 🏴󠁧󠁢󠁷󠁬󠁳󠁿",
            "duration": 300,
            "source_index": 2,
            "_yt_sql_source": SOURCE,
            "_yt_sql_source_facet": VIDEOS,
        },
        {
            "id": "shared",
            "title": "Short form",
            "duration": 45,
            "source_index": 3,
            "_yt_sql_source": SOURCE,
            "_yt_sql_source_facet": SHORTS,
        },
        {
            "id": "short-only",
            "title": "AMV e\u0301",
            "duration": 30,
            "source_index": 4,
            "_yt_sql_source": SOURCE,
            "_yt_sql_source_facet": SHORTS,
        },
    ]


def _resolve(text: str):
    records = _records()
    schemas = {
        (SOURCE, VIDEOS): QuerySchema([row for row in records if row["_yt_sql_source_facet"] == VIDEOS]),
        (SOURCE, SHORTS): QuerySchema([row for row in records if row["_yt_sql_source_facet"] == SHORTS]),
    }
    query = resolve_query(
        parse_query(text),
        QuerySchema(records),
        DateContext(date_order="dmy", now=datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)),
        source_schemas=schemas,
    )
    return records, query


def test_union_all_keeps_same_source_facets_independent() -> None:
    records, query = _resolve(
        "SELECT id, title FROM @whatdamath OF videos "
        "UNION ALL SELECT id, title FROM @whatdamath OF shorts ORDER BY id, title"
    )
    assert apply_query(records, query) == [
        {"id": "shared", "title": "Long form"},
        {"id": "shared", "title": "Short form"},
        {"id": "short-only", "title": "AMV e\u0301"},
        {"id": "video-only", "title": "Cymru 🏴󠁧󠁢󠁷󠁬󠁳󠁿"},
    ]


def test_plain_union_deduplicates_only_projected_logical_rows() -> None:
    records, query = _resolve(
        "SELECT id FROM @whatdamath OF videos UNION SELECT id FROM @whatdamath OF shorts ORDER BY id"
    )
    assert apply_query(records, query) == [
        {"id": "shared"},
        {"id": "short-only"},
        {"id": "video-only"},
    ]


def test_ctes_can_materialise_different_facets_of_same_source() -> None:
    records, query = _resolve(
        "WITH longform AS (SELECT id FROM @whatdamath OF videos), "
        "shortform AS (SELECT id FROM @whatdamath OF shorts) "
        "SELECT id FROM longform UNION ALL SELECT id FROM shortform ORDER BY id"
    )
    assert apply_query(records, query) == [
        {"id": "shared"},
        {"id": "shared"},
        {"id": "short-only"},
        {"id": "video-only"},
    ]


def test_per_facet_schema_rejects_field_missing_from_selected_facet() -> None:
    records = _records()
    records[0]["video_metric"] = 7
    schemas = {
        (SOURCE, VIDEOS): QuerySchema([row for row in records if row["_yt_sql_source_facet"] == VIDEOS]),
        (SOURCE, SHORTS): QuerySchema([row for row in records if row["_yt_sql_source_facet"] == SHORTS]),
    }
    query = parse_query("SELECT video_metric FROM @whatdamath OF shorts")
    with pytest.raises(QuerySyntaxError, match="Unknown field 'video_metric'"):
        resolve_query(query, QuerySchema(records), source_schemas=schemas)


def test_cross_facet_union_respects_global_limit_and_offset() -> None:
    records, query = _resolve(
        "SELECT id FROM @whatdamath OF videos "
        "UNION ALL SELECT id FROM @whatdamath OF shorts "
        "ORDER BY id LIMIT 2 OFFSET 1"
    )
    assert apply_query(records, query) == [{"id": "shared"}, {"id": "short-only"}]


def test_cross_facet_union_can_feed_outer_aggregate() -> None:
    records, query = _resolve(
        "WITH everything AS ("
        "SELECT id FROM @whatdamath OF videos "
        "UNION ALL SELECT id FROM @whatdamath OF shorts"
        ") SELECT COUNT(*) AS total FROM everything"
    )
    assert apply_query(records, query) == [{"total": 4}]


def test_seeded_random_identity_includes_facet() -> None:
    records, query = _resolve(
        "SELECT id, RANDOM(31415926) AS r FROM @whatdamath OF videos "
        "UNION ALL SELECT id, RANDOM(31415926) AS r FROM @whatdamath OF shorts "
        "ORDER BY id, r"
    )
    first = apply_query(records, query)
    second = apply_query(list(reversed(records)), query)
    assert first == second
    shared = [row["r"] for row in first if row["id"] == "shared"]
    assert len(shared) == 2
    assert shared[0] != shared[1]
