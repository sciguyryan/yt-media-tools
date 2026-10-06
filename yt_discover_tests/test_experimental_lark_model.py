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
        "NOT\t(title IS NULL\nOR duration < 60)",
        "SELECT DISTINCT id FROM @fixture ORDER BY id DESC LIMIT 5 OFFSET 1",
        "SELECT\nDISTINCT\ttitle, duration FROM @fixture",
        "SELECT 0xff + 0b10 + 0o7 FROM @fixture",
        "SELECT LOWER(title), COALESCE(title, 'untitled') FROM @fixture",
        "SELECT CASE WHEN duration > 10 THEN 'long' ELSE 'short' END AS bucket FROM @fixture",
        "FROM @fixture WHERE duration BETWEEN 10 AND 20",
        "FROM @fixture WHERE id IN (1, 2, 3)",
        "FROM @fixture WHERE title ILIKE 'demo%'",
        "FROM @fixture WHERE title IS NOT DISTINCT FROM other",
        "SELECT uploader_id, COUNT(*) AS n FROM @fixture GROUP BY uploader_id HAVING COUNT(*) > 1",
    ),
)
def test_lark_model_matches_reference_parser_for_initial_model_slice(source: str) -> None:
    expected = parse_query(source)
    actual = parse_lark_query(source)

    assert normalised_parser_model(actual) == normalised_parser_model(expected)
    assert user_origin_positions(actual) == user_origin_positions(expected)


@pytest.mark.parametrize(
    "source",
    (
        "WITH x AS (SELECT id FROM @a) SELECT id FROM x",
        "WITH x AS (SELECT id FROM @a), y AS (SELECT id FROM @b) SELECT id FROM x",
        "SELECT id FROM @a UNION SELECT id FROM @b",
        "SELECT id FROM @a UNION ALL SELECT id FROM @b",
        "SELECT id FROM @a OF videos, shorts",
        "SELECT a.id FROM @a AS a JOIN @b AS b ON a.id = b.id",
        "SELECT a.id FROM @a AS a LEFT JOIN @b OF videos AS b ON a.id = b.id",
        "SELECT a.id FROM @a AS a SEMI JOIN @b AS b ON a.id = b.id",
        "SELECT a.id FROM @a AS a ANTI JOIN @b AS b ON a.id = b.id",
    ),
)
def test_lark_model_matches_reference_parser_for_structural_query_families(source: str) -> None:
    expected = parse_query(source)
    actual = parse_lark_query(source)

    assert normalised_parser_model(actual) == normalised_parser_model(expected)
    assert user_origin_positions(actual) == user_origin_positions(expected)


@pytest.mark.parametrize(
    "source",
    (
        "SELECT id FROM (SELECT id FROM @a)",
        "SELECT combined.id FROM (SELECT id FROM @a UNION SELECT id FROM @b) AS combined",
        "SELECT outer_id FROM (SELECT inner_id AS outer_id FROM (SELECT id AS inner_id FROM @a))",
        "SELECT a.id FROM (SELECT id FROM @a) AS a JOIN @b AS b ON a.id = b.id",
        "SELECT a.id FROM @a AS a LEFT JOIN (SELECT id FROM @b) AS b ON a.id = b.id",
        (
            "SELECT a.id FROM (SELECT id FROM @a UNION ALL SELECT id FROM @b) AS a "
            "JOIN (SELECT id FROM @c) AS c ON a.id = c.id"
        ),
        (
            "SELECT stats.uploader_id FROM (SELECT uploader_id, COUNT(*) AS n FROM @a "
            "GROUP BY uploader_id HAVING COUNT(*) > 1) AS stats WHERE stats.uploader_id IS NOT NULL"
        ),
    ),
)
def test_lark_model_matches_reference_parser_for_derived_relations(source: str) -> None:
    expected = parse_query(source)
    actual = parse_lark_query(source)

    assert normalised_parser_model(actual) == normalised_parser_model(expected)
    assert user_origin_positions(actual) == user_origin_positions(expected)
