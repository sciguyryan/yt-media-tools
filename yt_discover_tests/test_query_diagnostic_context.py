"""Structured diagnostic context and source-location coverage for yt-sql."""

from __future__ import annotations

import pytest

from yt_media_tools.query import (
    QueryLexicalError,
    QuerySemanticError,
    QuerySyntaxError,
    parse_query,
    resolve_query,
    tokenise,
)
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


def test_lexical_diagnostic_has_distinct_category_and_half_open_span() -> None:
    source = "SELECT id FROM @fixture WHERE id = 'unterminated"

    with pytest.raises(QueryLexicalError) as captured:
        parse_query(source)

    error = captured.value
    assert isinstance(error, QuerySyntaxError)
    assert error.context.category == "lexical"
    assert error.span.start.position == source.index("'")
    assert error.span.end.position == len(source)
    assert error.context.location == error.location


def test_token_retains_half_open_absolute_source_span() -> None:
    source = "SELECT `odd name`"
    token = tokenise(source)[1]

    assert token.text == "`odd name`"
    assert token.span == (7, len(source))


def test_curated_expected_tokens_are_structured_but_not_rendered_as_parser_internals() -> None:
    source = "SELECT id FROM @fixture WHERE id = 1 ORDER id"

    with pytest.raises(QuerySyntaxError) as captured:
        parse_query(source)

    error = captured.value
    assert error.context.category == "syntax"
    assert error.expected == ("BY",)
    assert error.context.expected == ("BY",)
    assert "expected=" not in error.format()


def test_semantic_diagnostic_exposes_zero_width_primary_span_when_only_a_start_is_known() -> None:
    source = "SELECT id FROM @fixture WHERE duraton < 1h"

    with pytest.raises(QuerySemanticError) as captured:
        resolve_query(parse_query(source), QuerySchema([{"id": "fixture"}]))

    error = captured.value
    assert error.span.start == error.location
    assert error.span.end == error.location


def test_expected_token_metadata_uses_yt_sql_vocabulary() -> None:
    source = "SELECT (id"

    with pytest.raises(QuerySyntaxError) as captured:
        parse_query(source)

    assert captured.value.expected == (")",)
    assert "RPAREN" not in repr(captured.value.context)


def test_malformed_numeric_literal_is_lexical_not_syntax() -> None:
    with pytest.raises(QueryLexicalError) as captured:
        parse_query("SELECT 0xGG")

    assert captured.value.context.category == "lexical"
