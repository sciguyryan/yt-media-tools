"""Conformance coverage for TRUE, FALSE and NULL as reserved literal words."""

from __future__ import annotations

import pytest

from yt_media_tools.query_formatter import format_query
from yt_media_tools.query_model import Literal, QuerySyntaxError
from yt_media_tools.query_parser import parse_query, tokenise


@pytest.mark.parametrize(
    ("spelling", "value", "canonical"),
    [
        ("TRUE", True, "TRUE"),
        ("false", False, "FALSE"),
        ("Null", None, "NULL"),
    ],
)
def test_reserved_literal_words_have_dedicated_tokens_and_remain_literals(
    spelling: str, value: object, canonical: str
) -> None:
    token = tokenise(spelling)[0]
    assert token.kind == "LITERAL_WORD"

    query = parse_query(f"SELECT {spelling} FROM @fixture")
    expression = query.select[0].expression
    assert isinstance(expression, Literal)
    assert expression.value is value
    assert format_query(query) == f"SELECT {canonical} FROM @fixture"


@pytest.mark.parametrize(
    "query",
    [
        "SELECT id AS TRUE FROM @fixture",
        "SELECT id FROM @fixture AS FALSE",
        "WITH NULL AS (SELECT id FROM @fixture) SELECT id FROM @fixture",
        "SELECT id FROM @fixture OF TRUE",
        "SELECT FILTER(formats AS FALSE WHERE TRUE) FROM @fixture",
        "SELECT MAP(formats AS NULL SELECT id) FROM @fixture",
        "SELECT id FROM NULL",
        "SELECT raw.TRUE FROM @fixture",
    ],
)
def test_reserved_literal_words_are_rejected_in_identifier_only_positions(query: str) -> None:
    with pytest.raises(QuerySyntaxError):
        parse_query(query)


def test_reserved_literal_words_remain_available_to_predicate_grammar() -> None:
    query = parse_query("SELECT id FROM @fixture WHERE TRUE IS NOT FALSE AND title IS NOT NULL")
    assert format_query(query) == "SELECT id FROM @fixture WHERE ((TRUE) IS NOT FALSE AND title IS NOT NULL)"
