"""Structured diagnostic context and source-location coverage for yt-sql."""

from __future__ import annotations

import pytest

from yt_media_tools.query import QuerySemanticError, QuerySyntaxError, parse_query, resolve_query
from yt_media_tools.schema import QuerySchema


def test_syntax_diagnostic_exposes_structured_source_location() -> None:
    source = "SELECT id\nFROM @fixture\nWHERE"

    with pytest.raises(QuerySyntaxError) as captured:
        parse_query(source)

    error = captured.value
    assert type(error) is QuerySyntaxError
    assert error.context.category == "syntax"
    assert error.location.position == len(source)
    assert error.location.line == 3
    assert error.location.column == 6
    assert "(line 3, column 6)" in error.format()


def test_semantic_diagnostic_preserves_offending_field_location() -> None:
    source = "SELECT id\nFROM @fixture\nWHERE duraton < 1h"

    with pytest.raises(QuerySemanticError) as captured:
        resolve_query(parse_query(source), QuerySchema([{"id": "fixture"}]))

    error = captured.value
    assert isinstance(error, QuerySyntaxError)
    assert error.context.category == "semantic"
    assert error.location.position == source.index("duraton")
    assert error.location.line == 3
    assert error.location.column == 7
    assert "Unknown field 'duraton'" in error.message


def test_semantic_comparison_diagnostic_uses_expression_location() -> None:
    source = "SELECT id FROM @fixture HAVING COUNT(*) = 'text'"

    with pytest.raises(QuerySemanticError) as captured:
        resolve_query(parse_query(source), QuerySchema([{"id": "fixture"}]))

    error = captured.value
    assert error.context.category == "semantic"
    assert error.location.position > 0
    assert error.location.line == 1
    assert error.location.column > source.index("HAVING") + 1
