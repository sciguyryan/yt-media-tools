"""Conformance checks for the parser-neutral yt-sql grammar artefact."""

from __future__ import annotations

from pathlib import Path

import pytest

from yt_media_tools.query_formatter import format_query
from yt_media_tools.query_model import QuerySyntaxError
from yt_media_tools.query_parser import parse_query
from yt_media_tools.query_semantics import semantic_key


ROOT = Path(__file__).resolve().parents[1]
GRAMMAR = ROOT / "docs" / "YT-SQL-GRAMMAR.ebnf"
GRAMMAR_CONTRACT = ROOT / "docs" / "YT-SQL-GRAMMAR.md"
LANGUAGE_REFERENCE = ROOT / "docs" / "YT-SQL.md"


def test_formal_grammar_is_parser_neutral_and_versioned() -> None:
    text = GRAMMAR.read_text(encoding="utf-8")
    assert "Grammar revision: 2" in text
    assert "Revision 1 introduced by: yt-discover 0.29.15" in text
    assert "Revision 2 introduced by: yt-discover 0.31.0 development" in text
    assert "Lark" not in text
    assert "TatSu" not in text
    for production in (
        "query-expression",
        "select-query",
        "join-clause",
        "boolean-expression",
        "having-expression",
        "scalar-expression",
        "postfix-expression",
        "case-expression",
        "aggregate-function",
        "identifier",
        "number",
        "string",
    ):
        assert f"{production:<22}" in text


def test_language_reference_links_formal_grammar_and_authority_model() -> None:
    reference = LANGUAGE_REFERENCE.read_text(encoding="utf-8")
    contract = GRAMMAR_CONTRACT.read_text(encoding="utf-8")
    assert "[`YT-SQL-GRAMMAR.ebnf`](YT-SQL-GRAMMAR.ebnf)" in reference
    assert "[`YT-SQL-GRAMMAR.md`](YT-SQL-GRAMMAR.md)" in reference
    assert "authoritative parser-neutral grammar for yt-sql syntax" in contract
    assert "authoritative for semantics" in contract
    assert "Speculative future syntax does not belong" in contract


@pytest.mark.parametrize(
    "source",
    (
        "SELECT id FROM @fixture",
        "SELECT POSITION() AS position, id FROM @fixture ORDER BY id LIMIT 2 OFFSET 1",
        "duration > 10m AND title CONTAINS mars",
        "SELECT DISTINCT id, formats[0].height AS height FROM @fixture WHERE title ILIKE 'mars%' ORDER BY height DESC LIMIT 10 OFFSET 2",
        "WITH known AS (SELECT id FROM @known) SELECT l.id FROM @left AS l LEFT JOIN known AS k ON l.id = k.id WHERE l.id IS NOT NULL",
        "SELECT id FROM @fixture OF videos, shorts",
        "(SELECT id FROM @a ORDER BY id LIMIT 2) UNION ALL (SELECT id FROM @b OFFSET 1) ORDER BY id",
        "SELECT CASE WHEN duration < 10m THEN 'short' ELSE 'long' END AS class FROM @fixture",
        "SELECT MAP(formats AS f SELECT f.height) AS heights FROM @fixture WHERE ANY(formats AS f WHERE f.height >= 1080)",
        "SELECT COUNT(*) FILTER (WHERE duration > 10m) AS long_count FROM @fixture HAVING COUNT(*) > 0",
    ),
)
def test_major_formal_grammar_families_parse_and_round_trip(source: str) -> None:
    parsed = parse_query(source)
    canonical = format_query(parsed)
    reparsed = parse_query(canonical)
    assert semantic_key(reparsed) == semantic_key(parsed)
    assert format_query(reparsed) == canonical


@pytest.mark.parametrize(
    "source",
    (
        "SELECT id OFFSET 1 LIMIT 2",
        "WITH RECURSIVE x AS (SELECT id FROM @x) SELECT id FROM x",
        "SELECT id FROM @a RIGHT JOIN @b AS b ON id = b.id",
        "SELECT id FROM @a UNION",
        "SELECT id FROM @a OF",
        "SELECT LOWER() FROM @a",
        "SELECT NULLIF(id) FROM @a",
    ),
)
def test_formal_grammar_near_misses_remain_rejected(source: str) -> None:
    with pytest.raises(QuerySyntaxError):
        parse_query(source)
