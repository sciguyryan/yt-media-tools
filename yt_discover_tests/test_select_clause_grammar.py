"""Contract tests for ordinary SELECT clause ordering and slicing syntax."""

from __future__ import annotations

import re

import pytest

from yt_media_tools.query import QuerySyntaxError, parse_query
from yt_media_tools.query_formatter import format_query


@pytest.mark.parametrize(
    "query",
    (
        "SELECT id FROM @x",
        "SELECT id FROM @x WHERE title IS NOT NULL",
        "SELECT uploader, COUNT(*) AS n FROM @x GROUP BY uploader HAVING COUNT(*) > 0",
        "SELECT id FROM @x ORDER BY upload_date DESC",
        "SELECT id FROM @x LIMIT 10",
        "SELECT id FROM @x OFFSET 10",
        "SELECT id FROM @x LIMIT 10 OFFSET 2",
        "SELECT id FROM @x OFFSET 0",
    ),
)
def test_ordinary_select_clause_order_is_accepted(query: str) -> None:
    parse_query(query)


@pytest.mark.parametrize(
    ("query", "token"),
    (
        ("SELECT id FROM @x OFFSET 2 LIMIT 10", "LIMIT"),
        ("SELECT id FROM @x LIMIT 10 ORDER BY id", "ORDER"),
        ("SELECT id FROM @x ORDER BY id OFFSET 2 LIMIT 10", "LIMIT"),
        ("SELECT id FROM @x GROUP BY id WHERE id = 'x'", "WHERE"),
        ("SELECT id FROM @x GROUP BY id HAVING COUNT(*) > 0 GROUP BY id", "GROUP"),
        ("SELECT id FROM @x ORDER BY id ORDER BY title", "ORDER"),
        ("SELECT id FROM @x LIMIT 1 LIMIT 2", "LIMIT"),
        ("SELECT id FROM @x OFFSET 1 OFFSET 2", "OFFSET"),
    ),
)
def test_ordinary_select_clauses_cannot_be_reordered_or_repeated(query: str, token: str) -> None:
    with pytest.raises(
        QuerySyntaxError,
        match=rf"{token}(?: BY)? is repeated or appears outside the canonical SELECT clause order",
    ):
        parse_query(query)


def test_canonical_formatter_preserves_single_clause_order() -> None:
    query = parse_query(
        "SELECT uploader, COUNT(*) AS n FROM @x WHERE title IS NOT NULL "
        "GROUP BY uploader HAVING COUNT(*) > 0 ORDER BY n DESC LIMIT 10 OFFSET 2"
    )
    assert format_query(query) == (
        "SELECT uploader, COUNT(*) AS n FROM @x WHERE title IS NOT NULL "
        "GROUP BY uploader HAVING COUNT(*) > 0 ORDER BY n DESC LIMIT 10 OFFSET 2"
    )


def test_offset_without_limit_is_a_deliberate_supported_form() -> None:
    query = parse_query("SELECT id FROM @x OFFSET 2")
    assert query.limit is None
    assert query.offset == 2
    assert format_query(query) == "SELECT id FROM @x OFFSET 2"
