"""Conformance tests for case-sensitive yt-sql identifier resolution."""

from __future__ import annotations

import pytest

from yt_media_tools.query import QuerySemanticError, parse_query, resolve_query
from yt_media_tools.schema import QuerySchema


def _resolve(source: str, rows: list[dict] | None = None):
    records = rows or [{"id": "a", "title": "lower", "Title": "upper"}]
    return resolve_query(parse_query(source), QuerySchema(records))


def test_schema_fields_that_differ_only_by_case_are_distinct() -> None:
    query = _resolve("SELECT title, Title FROM @fixture")
    assert [term.field for term in query.select] == ["title", "Title"]


def test_field_resolution_does_not_case_fold() -> None:
    with pytest.raises(QuerySemanticError, match="Unknown field 'TITLE'"):
        _resolve("SELECT TITLE FROM @fixture")


def test_select_aliases_that_differ_only_by_case_are_distinct() -> None:
    query = _resolve("SELECT title AS value, Title AS Value FROM @fixture ORDER BY Value")
    assert [term.output_name for term in query.select] == ["value", "Value"]
    assert query.order_by[0].field == "Title"


def test_order_by_alias_resolution_is_case_sensitive() -> None:
    with pytest.raises(QuerySemanticError, match="Unknown field 'VALUE'"):
        _resolve("SELECT title AS value FROM @fixture ORDER BY VALUE")


def test_contextual_keyword_spelling_remains_legal_as_identifier() -> None:
    query = _resolve("SELECT select, title AS format FROM @fixture", [{"select": "x", "title": "t"}])
    assert [term.output_name for term in query.select] == ["select", "format"]


def test_cte_names_are_case_sensitive() -> None:
    query = _resolve("WITH Base AS (SELECT id, title AS projected FROM @fixture) SELECT projected FROM Base")
    assert query.from_source == "Base"
    with pytest.raises(QuerySemanticError):
        _resolve("WITH Base AS (SELECT id, title AS projected FROM @fixture) SELECT projected FROM base")
