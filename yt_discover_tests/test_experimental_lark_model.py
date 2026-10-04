"""Model-construction checks for the experimental declarative parser."""

from __future__ import annotations

import pytest

from yt_media_tools.experimental_lark_parser import parse_lark_query
from yt_media_tools.parser_equivalence import normalised_parser_model, user_origin_positions
from yt_media_tools.query_parser import parse_query


@pytest.mark.parametrize(
    "source",
    (
        "SELECT Δelta, δelta FROM @fixture",
        "SELECT alpha + beta * gamma FROM @fixture",
        "SELECT formats[0].height FROM @fixture",
        "FROM @fixture WHERE duration < 1h",
        "duration < 1h AND title IS NOT NULL",
        "SELECT DISTINCT id FROM @fixture ORDER BY id DESC LIMIT 5 OFFSET 1",
        "SELECT 0xff + 0b10 + 0o7 FROM @fixture",
    ),
)
def test_lark_model_matches_reference_parser_for_initial_model_slice(source: str) -> None:
    expected = parse_query(source)
    actual = parse_lark_query(source)

    assert normalised_parser_model(actual) == normalised_parser_model(expected)
    assert user_origin_positions(actual) == user_origin_positions(expected)
