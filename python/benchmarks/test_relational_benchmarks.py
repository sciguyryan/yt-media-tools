"""Deterministic local benchmarks for yt-sql relational execution."""

from __future__ import annotations

import pytest

from yt_media_tools.query import apply_query, parse_query, resolve_query
from yt_media_tools.schema import QuerySchema


def _relations(left_count: int, right_count: int, *, fanout: int = 1, no_match: bool = False):
    left = [
        {"id": f"k-{index}", "bucket": index % 17, "_yt_sql_source": "@left", "_yt_sql_source_facet": None}
        for index in range(left_count)
    ]
    right = []
    for index in range(right_count):
        key_index = index // max(fanout, 1)
        key = f"missing-{key_index}" if no_match else f"k-{key_index}"
        right.append(
            {
                "id": key,
                "bucket": key_index % 17,
                "value": index,
                "_yt_sql_source": "@right",
                "_yt_sql_source_facet": None,
            }
        )
    records = [*left, *right]
    schemas = {
        ("@left", None): QuerySchema(left),
        ("@right", None): QuerySchema(right),
    }
    return records, schemas


def _resolved(records, schemas, join: str):
    return resolve_query(parse_query(join), QuerySchema(records), source_schemas=schemas)


@pytest.mark.benchmark(group="relational")
@pytest.mark.parametrize(
    "left_count,right_count,fanout,no_match,benchmark_id",
    (
        (200, 200, 1, False, "relational.join.one_to_one"),
        (200, 800, 4, False, "relational.join.one_to_many"),
        (500, 500, 1, True, "relational.join.no_match"),
        (2_000, 20, 1, False, "relational.join.asymmetric.left_large"),
        (20, 2_000, 1, False, "relational.join.asymmetric.right_large"),
    ),
    ids=("one-to-one", "one-to-many", "no-match", "left-large", "right-large"),
)
def test_inner_equality_join(benchmark, left_count, right_count, fanout, no_match, benchmark_id) -> None:
    records, schemas = _relations(left_count, right_count, fanout=fanout, no_match=no_match)
    query = _resolved(records, schemas, "SELECT l.id, r.value FROM @left AS l INNER JOIN @right AS r ON l.id = r.id")
    benchmark.extra_info["benchmark_id"] = benchmark_id
    result = benchmark(apply_query, records, query)
    assert isinstance(result, list)


@pytest.mark.benchmark(group="relational")
def test_inner_compound_equality_join(benchmark) -> None:
    records, schemas = _relations(500, 500)
    query = _resolved(
        records,
        schemas,
        "SELECT l.id, r.value FROM @left AS l INNER JOIN @right AS r ON l.id = r.id AND l.bucket = r.bucket",
    )
    benchmark.extra_info["benchmark_id"] = "relational.join.compound_equality"
    result = benchmark(apply_query, records, query)
    assert isinstance(result, list)


@pytest.mark.benchmark(group="relational")
def test_semi_equality_join(benchmark) -> None:
    records, schemas = _relations(1_000, 1_000)
    query = _resolved(records, schemas, "SELECT l.id FROM @left AS l SEMI JOIN @right AS r ON l.id = r.id")
    benchmark.extra_info["benchmark_id"] = "relational.join.semi"
    result = benchmark(apply_query, records, query)
    assert len(result) == 1_000


@pytest.mark.benchmark(group="relational")
def test_join_acquisition_planning(benchmark) -> None:
    from yt_media_tools.discover_explain import explain_user_query_json

    query = (
        "SELECT l.id, r.title AS related_title FROM @left AS l "
        "INNER JOIN @right AS r ON l.id = r.id "
        "WHERE l.upload_date >= 2026-01-01 AND r.duration < 1h LIMIT 50"
    )
    benchmark.extra_info["benchmark_id"] = "relational.planning.join_acquisition"
    result = benchmark(
        explain_user_query_json,
        query,
        source_type="auto",
        tab="all",
        date_format="YMD",
    )
    assert result["relational_joins"]
