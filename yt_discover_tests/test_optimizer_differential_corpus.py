"""Full deterministic differential corpus for the 0.28 optimiser programme."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re

import pytest

from yt_discover_tests.conformance.multi_source_fixture import heterogeneous_records
from yt_media_tools.dates import DateContext
from yt_media_tools.optimizer import optimise_query
from yt_media_tools.query_properties import (
    NOT_ACQUIRED,
    STRUCTURALLY_UNAVAILABLE,
    knowledge_from_capability,
)
from yt_media_tools.query import (
    QuerySyntaxError,
    apply_query,
    format_query,
    parse_query,
    query_physical_sources,
    resolve_query,
)
from yt_media_tools.schema import QuerySchema
from yt_media_tools.source_capabilities import (
    STRUCTURALLY_UNSUPPORTED,
    FieldCapability,
    field_capability,
)


NOW = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
DATES = DateContext(date_order="dmy", now=NOW)


@dataclass(frozen=True)
class DifferentialCase:
    """One named deterministic optimiser-equivalence case."""

    category: str
    query: str


SINGLE_SOURCE_ROWS: list[dict[str, object]] = [
    {
        "id": "null",
        "title": None,
        "uploader": None,
        "duration": None,
        "view_count": None,
        "upload_date": None,
        "release_timestamp": None,
        "availability": None,
        "source_index": 1,
        "_yt_sql_source": "@fixture",
    },
    {
        "id": "cafe-composed",
        "title": "Café Science",
        "uploader": "Alpha",
        "duration": 90,
        "view_count": 10,
        "upload_date": "20240101",
        "release_timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp(),
        "availability": "public",
        "source_index": 2,
        "_yt_sql_source": "@fixture",
    },
    {
        "id": "cafe-decomposed",
        "title": "Cafe\u0301 science",
        "uploader": "Alpha",
        "duration": 600,
        "view_count": 20,
        "upload_date": "20250101",
        "release_timestamp": datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp(),
        "availability": "private",
        "source_index": 3,
        "_yt_sql_source": "@fixture",
    },
    {
        "id": "welsh",
        "title": "Cymru \U0001f3f4\U000e0067\U000e0062\U000e0077\U000e006c\U000e0073\U000e007f",
        "uploader": "Beta",
        "duration": 1800,
        "view_count": 100_000,
        "upload_date": "20260101",
        "release_timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp(),
        "availability": "public",
        "source_index": 4,
        "_yt_sql_source": "@fixture",
    },
    {
        "id": "emoji",
        "title": "Rocket \U0001f680 SCIENCE",
        "uploader": "Beta",
        "duration": 3600,
        "view_count": 1_000_000,
        "upload_date": "20260901",
        "release_timestamp": datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp(),
        "availability": "unlisted",
        "source_index": 5,
        "_yt_sql_source": "@fixture",
    },
]


CASES = (
    DifferentialCase(
        "null-and-three-valued-logic",
        "SELECT id FROM @fixture WHERE (view_count >= 10 AND view_count >= 20) OR title IS NULL ORDER BY id",
    ),
    DifferentialCase(
        "unicode",
        "SELECT id, LOWER(title) AS folded FROM @fixture "
        "WHERE title ILIKE '%science%' OR title = 'Café Science' ORDER BY id",
    ),
    DifferentialCase(
        "temporal-and-infinity",
        "SELECT id FROM @fixture WHERE "
        "upload_date > -INFINITY() AND upload_date >= TODAY() - 3yr "
        "AND release_timestamp < INFINITY() ORDER BY id",
    ),
    DifferentialCase(
        "numeric-literals",
        "SELECT id, (0x10 + 0b10 + 0o10 + 1_000) AS score FROM @fixture "
        "WHERE view_count >= 0x0A AND view_count <= 0b11110100001001000000 ORDER BY id",
    ),
    DifferentialCase(
        "case-and-scalars",
        "SELECT id, CASE WHEN duration IS NULL THEN COALESCE(title, 'missing') "
        "WHEN duration < 10m THEN UPPER(COALESCE(title, '')) "
        "ELSE LOWER(COALESCE(title, '')) END AS bucket FROM @fixture ORDER BY id",
    ),
    DifferentialCase(
        "aggregate-filter-group-having",
        "SELECT uploader, COUNT(*) AS n, "
        "COUNT(*) FILTER (WHERE view_count >= 20) AS popular, "
        "AVG(duration) AS avg_duration FROM @fixture GROUP BY uploader "
        "HAVING COUNT(*) >= 1 AND COUNT(*) >= 1 ORDER BY uploader",
    ),
    DifferentialCase(
        "cte",
        "WITH selected AS (SELECT id, uploader, duration, view_count FROM @fixture "
        "WHERE view_count >= 10 AND view_count >= 20), "
        "projected AS (SELECT id, uploader, duration FROM selected) "
        "SELECT uploader, COUNT(*) AS n, SUM(duration) AS total FROM projected "
        "GROUP BY uploader HAVING COUNT(*) >= 1 ORDER BY uploader",
    ),
    DifferentialCase(
        "distinct-limit-offset",
        "SELECT DISTINCT uploader FROM @fixture WHERE uploader IS NOT NULL ORDER BY uploader LIMIT 2 OFFSET 1",
    ),
    DifferentialCase(
        "seeded-random",
        "SELECT id, RANDOM(31415926) AS r FROM @fixture "
        "WHERE NOT NOT (view_count >= 10) ORDER BY r, id LIMIT 4 OFFSET 1",
    ),
)


def _resolve_single(text: str):
    schema = QuerySchema(SINGLE_SOURCE_ROWS)
    return resolve_query(
        parse_query(text),
        schema,
        DATES,
        source_schemas={("@fixture", None): schema},
    )


def _resolve_heterogeneous(text: str):
    rows = heterogeneous_records()
    parsed = parse_query(text)
    schemas = {
        (source, None): QuerySchema([row for row in rows if row.get("_yt_sql_source") == source])
        for source in query_physical_sources(parsed)
    }
    return rows, resolve_query(parsed, QuerySchema(rows), DATES, source_schemas=schemas)


def _assert_differential(rows: list[dict[str, object]], query) -> None:
    first = optimise_query(query)
    second = optimise_query(first.query)
    assert apply_query(rows, query) == apply_query(rows, first.query)
    assert second.query == first.query
    assert second.decisions == ()


def test_structural_unavailability_remains_distinct_from_not_yet_acquired_metadata() -> None:
    supported = knowledge_from_capability(field_capability("duration"))
    unsupported = knowledge_from_capability(
        FieldCapability(
            "synthetic",
            "unavailable",
            "unavailable",
            "unavailable",
            structural_support=STRUCTURALLY_UNSUPPORTED,
        )
    )

    assert supported.state == NOT_ACQUIRED
    assert unsupported.state == STRUCTURALLY_UNAVAILABLE
    assert supported.state != unsupported.state


def test_volatile_random_remains_an_execution_time_expression() -> None:
    query = _resolve_single("SELECT id, RANDOM() AS r FROM @fixture ORDER BY id")
    result = optimise_query(query)
    assert result.query.select[1].expression == query.select[1].expression
    assert all("random" not in decision.rule.casefold() for decision in result.decisions)


@pytest.mark.parametrize("case", CASES, ids=lambda item: item.category)
def test_mandatory_semantic_corpus_is_differential(case: DifferentialCase) -> None:
    query = _resolve_single(case.query)
    _assert_differential(SINGLE_SOURCE_ROWS, query)


@pytest.mark.parametrize(
    "query_text",
    (
        (
            "SELECT id, title, view_count FROM @youtube_channel "
            "UNION ALL SELECT id, title, view_count FROM @twitch_archive ORDER BY id"
        ),
        ("SELECT id, title FROM @youtube_playlist UNION SELECT id, title FROM @twitch_archive ORDER BY id"),
        (
            "WITH media AS (SELECT uploader, duration FROM @youtube_channel "
            "UNION ALL SELECT uploader, duration FROM @youtube_playlist "
            "UNION ALL SELECT uploader, duration FROM @twitch_archive) "
            "SELECT uploader, COUNT(*) AS n, SUM(duration) AS total FROM media "
            "GROUP BY uploader HAVING COUNT(*) >= 2 ORDER BY uploader"
        ),
        (
            "SELECT id, duration FROM @youtube_channel "
            "UNION ALL SELECT id, duration FROM @youtube_playlist "
            "UNION ALL SELECT id, duration FROM @twitch_archive "
            "ORDER BY duration DESC, id ASC LIMIT 3 OFFSET 1"
        ),
    ),
)
def test_union_and_heterogeneous_schema_corpus_is_differential(query_text: str) -> None:
    rows, query = _resolve_heterogeneous(query_text)
    _assert_differential(rows, query)


def test_source_and_facet_identity_remain_part_of_seeded_random_semantics() -> None:
    rows = [
        {
            "id": "shared",
            "title": "Long form",
            "source_index": 1,
            "_yt_sql_source": "@whatdamath",
            "_yt_sql_source_facet": "videos",
        },
        {
            "id": "shared",
            "title": "Short form",
            "source_index": 2,
            "_yt_sql_source": "@whatdamath",
            "_yt_sql_source_facet": "shorts",
        },
    ]
    schemas = {
        ("@whatdamath", "videos"): QuerySchema([rows[0]]),
        ("@whatdamath", "shorts"): QuerySchema([rows[1]]),
    }
    text = (
        "SELECT id, RANDOM(31415926) AS r FROM @whatdamath OF videos "
        "UNION ALL SELECT id, RANDOM(31415926) AS r FROM @whatdamath OF shorts "
        "ORDER BY r"
    )
    query = resolve_query(parse_query(text), QuerySchema(rows), DATES, source_schemas=schemas)
    _assert_differential(rows, query)
    result = apply_query(rows, optimise_query(query).query)
    assert len(result) == 2
    assert result[0]["r"] != result[1]["r"]


@pytest.mark.parametrize(
    "predicate",
    (
        "view_count >= 20",
        "title ILIKE '%science%'",
        "duration BETWEEN 1m AND 1h",
        "uploader IS NOT NULL",
    ),
)
def test_generated_equivalent_boolean_transformations_preserve_results(predicate: str) -> None:
    variants = (
        predicate,
        f"({predicate}) AND ({predicate})",
        f"({predicate}) OR ({predicate})",
        f"NOT NOT ({predicate})",
    )
    baseline = apply_query(
        SINGLE_SOURCE_ROWS,
        _resolve_single(f"SELECT id FROM @fixture WHERE {predicate} ORDER BY id"),
    )
    for transformed in variants:
        query = _resolve_single(f"SELECT id FROM @fixture WHERE {transformed} ORDER BY id")
        optimised = optimise_query(query).query
        assert apply_query(SINGLE_SOURCE_ROWS, query) == baseline
        assert apply_query(SINGLE_SOURCE_ROWS, optimised) == baseline


@pytest.mark.parametrize("case", CASES, ids=lambda item: item.category)
def test_canonical_formatting_round_trip_is_stable_for_semantic_corpus(case: DifferentialCase) -> None:
    first = _resolve_single(case.query)
    canonical = format_query(first)
    second = _resolve_single(canonical)
    assert format_query(second) == canonical
    assert apply_query(SINGLE_SOURCE_ROWS, second) == apply_query(SINGLE_SOURCE_ROWS, first)


@pytest.mark.parametrize(
    ("original", "mutant"),
    (
        (
            "SELECT id FROM @fixture WHERE view_count >= 20 ORDER BY id",
            "SELECT id FROM @fixture WHERE view_count > 20 ORDER BY id",
        ),
        (
            "SELECT id FROM @fixture WHERE view_count = 20 ORDER BY id",
            "SELECT id FROM @fixture WHERE view_count != 20 ORDER BY id",
        ),
        (
            "SELECT id FROM @fixture WHERE view_count >= 20 AND duration < 1h ORDER BY id",
            "SELECT id FROM @fixture WHERE view_count >= 20 OR duration < 1h ORDER BY id",
        ),
        (
            "SELECT id FROM @fixture WHERE title IS NULL ORDER BY id",
            "SELECT id FROM @fixture WHERE title IS NOT NULL ORDER BY id",
        ),
    ),
)
def test_semantic_corpus_detects_representative_unsafe_mutants(original: str, mutant: str) -> None:
    original_rows = apply_query(SINGLE_SOURCE_ROWS, _resolve_single(original))
    mutant_rows = apply_query(SINGLE_SOURCE_ROWS, _resolve_single(mutant))
    assert original_rows != mutant_rows


MALFORMED = (
    ("SELECT id FROM @fixture WHERE title IN ('a',, 'b')", "Expected a value."),
    ("SELECT id FROM @fixture ORDER BY id DESC ASC", "Unexpected token 'ASC'."),
    ("SELECT id FROM @fixture LIMIT 1 OFFSET 1 OFFSET 2", "Unexpected token"),
    ("SELECT CASE ELSE 1 END FROM @fixture", "Only searched CASE is supported"),
    ("SELECT COUNT(*) FILTER (WHERE) FROM @fixture", "Expected a field name."),
    ("SELECT RANDOM(1, 2) FROM @fixture", "RANDOM accepts zero or one seed argument"),
)


@pytest.mark.parametrize(("source", "message"), MALFORMED)
def test_malformed_inputs_have_deterministic_errors(source: str, message: str) -> None:
    errors: list[str] = []
    for _ in range(2):
        with pytest.raises(QuerySyntaxError) as caught:
            _resolve_single(source)
        errors.append(caught.value.format())
    assert errors[0] == errors[1]
    assert re.search(re.escape(message), errors[0])
