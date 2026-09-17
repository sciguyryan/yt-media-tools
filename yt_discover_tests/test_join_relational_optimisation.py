"""Differential coverage for conservative relational JOIN optimisation."""

from __future__ import annotations

import pytest

from yt_media_tools.query import apply_query, parse_query, resolve_query
from yt_media_tools.schema import QuerySchema
from yt_media_tools.query_evaluator import _equality_join_fields


def _records() -> list[dict[str, object]]:
    return [
        {"id": "a", "score": 1, "title": "Alpha", "_yt_sql_source": "@left", "_yt_sql_source_facet": None},
        {"id": "b", "score": 2, "title": "Beta", "_yt_sql_source": "@left", "_yt_sql_source_facet": None},
        {"id": None, "score": 3, "title": "Null", "_yt_sql_source": "@left", "_yt_sql_source_facet": None},
        {"id": "b", "score": 20, "tag": "first", "_yt_sql_source": "@right", "_yt_sql_source_facet": None},
        {"id": "b", "score": 21, "tag": "second", "_yt_sql_source": "@right", "_yt_sql_source_facet": None},
        {"id": "c", "score": 30, "tag": "third", "_yt_sql_source": "@right", "_yt_sql_source_facet": None},
        {"id": None, "score": 40, "tag": "null", "_yt_sql_source": "@right", "_yt_sql_source_facet": None},
    ]


def _resolve(text: str):
    records = _records()
    schemas = {
        ("@left", None): QuerySchema([row for row in records if row["_yt_sql_source"] == "@left"]),
        ("@right", None): QuerySchema([row for row in records if row["_yt_sql_source"] == "@right"]),
    }
    return records, resolve_query(parse_query(text), QuerySchema(records), source_schemas=schemas)


@pytest.mark.parametrize(
    "syntax,projection",
    (
        ("SEMI JOIN", "l.id"),
        ("ANTI JOIN", "l.id"),
        ("INNER JOIN", "l.id, r.tag"),
        ("LEFT JOIN", "l.id, r.tag"),
    ),
)
def test_hash_equality_join_matches_reference_execution(syntax: str, projection: str) -> None:
    records, query = _resolve(f"SELECT {projection} FROM @left AS l {syntax} @right AS r ON l.id = r.id")
    assert apply_query(records, query, relational_optimisation=True) == apply_query(
        records, query, relational_optimisation=False
    )


def test_non_equality_join_remains_equivalent_to_reference_execution() -> None:
    records, query = _resolve(
        "SELECT l.id, r.tag FROM @left AS l INNER JOIN @right AS r ON l.score < r.score WHERE r.id IS NOT NULL"
    )
    assert apply_query(records, query, relational_optimisation=True) == apply_query(
        records, query, relational_optimisation=False
    )


def test_cte_backed_hash_join_matches_reference_execution() -> None:
    records, query = _resolve(
        "WITH candidates AS (SELECT id, tag FROM @right) "
        "SELECT l.id, r.tag FROM @left AS l LEFT JOIN candidates AS r ON l.id = r.id"
    )
    assert apply_query(records, query, relational_optimisation=True) == apply_query(
        records, query, relational_optimisation=False
    )


def test_union_branch_hash_join_matches_reference_execution() -> None:
    records, query = _resolve(
        "SELECT l.id FROM @left AS l SEMI JOIN @right AS r ON l.id = r.id "
        "UNION ALL SELECT l.id FROM @left AS l ANTI JOIN @right AS r ON l.id = r.id"
    )
    assert apply_query(records, query, relational_optimisation=True) == apply_query(
        records, query, relational_optimisation=False
    )


def test_empty_right_relation_matches_reference_execution() -> None:
    records, query = _resolve("SELECT l.id, r.tag FROM @left AS l LEFT JOIN @right AS r ON l.id = r.id")
    left_only = [row for row in records if row["_yt_sql_source"] == "@left"]
    assert apply_query(left_only, query, relational_optimisation=True) == apply_query(
        left_only, query, relational_optimisation=False
    )


def test_equality_join_shape_is_recognised_for_hash_execution() -> None:
    _records_value, query = _resolve("SELECT l.id, r.tag FROM @left AS l INNER JOIN @right AS r ON l.id = r.id")
    fields = _equality_join_fields(query)
    assert fields is not None
    assert (fields[0].qualifier, fields[0].name) == ("l", "id")
    assert (fields[1].qualifier, fields[1].name) == ("r", "id")
