"""Independent-oracle conformance for executable SEMI and ANTI joins."""

from __future__ import annotations

import pytest

from yt_discover_tests.conformance.relation_oracle import OracleRelation, oracle_existence_join
from yt_media_tools.query import apply_query, parse_query, resolve_query
from yt_media_tools.schema import QuerySchema


def _sql_equal(left: object, right: object) -> bool | None:
    """Independent SQL equality sufficient for the deterministic relation fixture."""
    if left is None or right is None:
        return None
    return left == right


def _rows() -> list[dict[str, object]]:
    return [
        {"id": "a", "title": "Alpha", "_yt_sql_source": "@catalog", "_yt_sql_source_facet": "videos"},
        {"id": "b", "title": "Beta", "_yt_sql_source": "@catalog", "_yt_sql_source_facet": "videos"},
        {"id": None, "title": "Null left", "_yt_sql_source": "@catalog", "_yt_sql_source_facet": "videos"},
        {"id": "b", "tag": "first", "_yt_sql_source": "@catalog", "_yt_sql_source_facet": "shorts"},
        {"id": "b", "tag": "second", "_yt_sql_source": "@catalog", "_yt_sql_source_facet": "shorts"},
        {"id": None, "tag": "null", "_yt_sql_source": "@catalog", "_yt_sql_source_facet": "shorts"},
    ]


def _schemas(records: list[dict[str, object]]) -> dict[tuple[str, str | None], QuerySchema]:
    return {
        ("@catalog", "videos"): QuerySchema([row for row in records if row["_yt_sql_source_facet"] == "videos"]),
        ("@catalog", "shorts"): QuerySchema([row for row in records if row["_yt_sql_source_facet"] == "shorts"]),
    }


def _oracle_ids(records: list[dict[str, object]], *, anti: bool) -> list[object]:
    left = OracleRelation.from_rows(
        "@catalog", (row for row in records if row["_yt_sql_source_facet"] == "videos"), facet="videos"
    )
    right = OracleRelation.from_rows(
        "@catalog", (row for row in records if row["_yt_sql_source_facet"] == "shorts"), facet="shorts"
    )
    selected = oracle_existence_join(
        left, right, lambda lrow, rrow: _sql_equal(lrow.get("id"), rrow.get("id")), anti=anti
    )
    return [row.get("id") for row in selected]


@pytest.mark.parametrize(("syntax", "anti"), (("SEMI JOIN", False), ("ANTI JOIN", True)))
def test_direct_facet_existence_execution_matches_independent_oracle(syntax: str, anti: bool) -> None:
    records = _rows()
    query = resolve_query(
        parse_query(f"SELECT l.id FROM @catalog OF videos AS l {syntax} @catalog OF shorts AS r ON l.id = r.id"),
        QuerySchema(records),
        source_schemas=_schemas(records),
    )
    assert [row["id"] for row in apply_query(records, query)] == _oracle_ids(records, anti=anti)


@pytest.mark.parametrize(("syntax", "anti"), (("SEMI JOIN", False), ("ANTI JOIN", True)))
def test_cte_backed_right_existence_execution_matches_independent_oracle(syntax: str, anti: bool) -> None:
    records = _rows()
    text = (
        "WITH candidates AS (SELECT id FROM @catalog OF shorts) "
        f"SELECT l.id FROM @catalog OF videos AS l {syntax} candidates AS r ON l.id = r.id"
    )
    query = resolve_query(parse_query(text), QuerySchema(records), source_schemas=_schemas(records))
    assert [row["id"] for row in apply_query(records, query)] == _oracle_ids(records, anti=anti)


@pytest.mark.parametrize(("syntax", "anti"), (("SEMI JOIN", False), ("ANTI JOIN", True)))
def test_cte_backed_left_existence_execution_matches_independent_oracle(syntax: str, anti: bool) -> None:
    records = _rows()
    text = (
        "WITH primary_rows AS (SELECT id, title FROM @catalog OF videos) "
        f"SELECT l.id FROM primary_rows AS l {syntax} @catalog OF shorts AS r ON l.id = r.id"
    )
    query = resolve_query(parse_query(text), QuerySchema(records), source_schemas=_schemas(records))
    assert [row["id"] for row in apply_query(records, query)] == _oracle_ids(records, anti=anti)


def test_oracle_relation_identity_distinguishes_facets_of_same_source() -> None:
    records = _rows()
    left = OracleRelation.from_rows("@catalog", records[:3], facet="videos")
    right = OracleRelation.from_rows("@catalog", records[3:], facet="shorts")
    assert left.identity.key != right.identity.key


def test_direct_existence_join_preserves_left_acquisition_provenance() -> None:
    records = _rows()
    query = resolve_query(
        parse_query("SELECT * FROM @catalog OF videos AS l SEMI JOIN @catalog OF shorts AS r ON l.id = r.id"),
        QuerySchema(records),
        source_schemas=_schemas(records),
    )
    result = apply_query(records, query)
    assert len(result) == 1
    assert result[0]["id"] == "b"
    assert result[0]["_yt_sql_source"] == "@catalog"
    assert result[0]["_yt_sql_source_facet"] == "videos"
