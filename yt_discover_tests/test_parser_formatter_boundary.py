"""Architectural regression coverage for the parser and formatter split."""

from __future__ import annotations

import pytest

from yt_discover_tests.conformance.cases import CASES
from yt_media_tools import query
from yt_media_tools.query_formatter import format_expression, format_query, format_scalar_expression
from yt_media_tools.query_model import QuerySyntaxError
from yt_media_tools.query_parser import Parser, parse_query, parse_where, tokenise


def test_query_module_preserves_parser_and_formatter_compatibility_exports() -> None:
    assert query.Parser is Parser
    assert query.tokenise is tokenise
    assert query.parse_query is parse_query
    assert query.parse_where is parse_where
    assert query.format_scalar_expression is format_scalar_expression
    assert query.format_expression is format_expression
    assert query.format_query is format_query


def test_complete_direct_conformance_corpus_round_trips_through_separated_modules() -> None:
    for case in CASES:
        if case.params:
            continue
        canonical = format_query(parse_query(case.query))
        assert format_query(parse_query(canonical)) == canonical, case.name


@pytest.mark.parametrize(
    ("source", "message"),
    (
        ("WITH RECURSIVE x AS (SELECT id FROM @x) SELECT id FROM x", "Recursive CTEs are not supported."),
        ("WITH x AS () SELECT id FROM x", "CTE query cannot be empty."),
        ("SELECT id FROM @x UNION", "UNION requires a SELECT query on both sides."),
        ("SELECT id FROM @x OF", "OF requires a collection/facet name."),
    ),
)
def test_malformed_composition_and_pattern_diagnostics_remain_deterministic(source: str, message: str) -> None:
    with pytest.raises(QuerySyntaxError) as exc_info:
        parse_query(source)
    assert exc_info.value.message == message
    assert exc_info.value.position >= 0


def test_unicode_and_line_separator_input_is_not_normalised_by_parser_formatter_split() -> None:
    source = "SELECT title FROM @cymru\u2028WHERE title = 'Cafe\u0301'"
    parsed = parse_query(source)
    canonical = format_query(parsed)
    assert "Cafe\u0301" in canonical
    assert "Café" not in canonical
    assert format_query(parse_query(canonical)) == canonical
