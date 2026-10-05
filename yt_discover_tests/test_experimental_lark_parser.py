"""Initial grammar-recognition coverage for the experimental Lark parser."""

from __future__ import annotations

import pytest

from yt_discover_tests.parser_grammar_generation import generated_valid_queries
from yt_discover_tests.parser_migration_corpus import ACCEPTED_PARSER_CASES, REJECTED_PARSER_CASES
from yt_media_tools.experimental_lark_parser import recognise_lark_query
from yt_media_tools.query_model import QueryLexicalError, QuerySyntaxError


def test_lark_prototype_accepts_deterministic_reference_corpus() -> None:
    for case in ACCEPTED_PARSER_CASES:
        recognise_lark_query(case.query)


def test_lark_prototype_accepts_grammar_anchored_generated_corpus() -> None:
    for case in generated_valid_queries(rounds=3):
        recognise_lark_query(case.query)


def test_lark_prototype_rejects_deterministic_malformed_corpus() -> None:
    for case in REJECTED_PARSER_CASES:
        with pytest.raises(QuerySyntaxError):
            recognise_lark_query(case.query)


def test_lark_prototype_translates_native_failure_without_exposing_it() -> None:
    with pytest.raises(QueryLexicalError) as captured:
        recognise_lark_query("SELECT 'unterminated")

    assert captured.value.context.reason == "unterminated-string"
    assert captured.value.__cause__ is None


def test_lark_prototype_preserves_field_literal_comparison_boundary() -> None:
    source = "SELECT id FROM @fixture WHERE id = LOWER(title)"

    with pytest.raises(QuerySyntaxError) as captured:
        recognise_lark_query(source)

    assert captured.value.position == source.index("(", source.index("LOWER"))


@pytest.mark.parametrize(
    "source",
    (
        "SELECT DISTINCT id, formats[0].height AS height FROM @fixture WHERE title ILIKE 'mars%' ORDER BY height DESC LIMIT 10 OFFSET 2",
        "WITH known AS (SELECT id FROM @known) SELECT l.id FROM @left AS l LEFT JOIN known AS k ON l.id = k.id WHERE l.id IS NOT NULL",
        "SELECT id FROM @fixture OF videos, shorts",
        "(SELECT id FROM @a ORDER BY id LIMIT 2) UNION ALL (SELECT id FROM @b OFFSET 1) ORDER BY id",
        "SELECT CASE WHEN duration < 10m THEN 'short' ELSE 'long' END AS class FROM @fixture",
        "SELECT MAP(formats AS f SELECT f.height) AS heights FROM @fixture WHERE ANY(formats AS f WHERE f.height >= 1080)",
        "SELECT COUNT(*) FILTER (WHERE duration > 10m) AS long_count FROM @fixture HAVING COUNT(*) > 0",
    ),
)
def test_lark_prototype_recognises_major_grammar_families(source: str) -> None:
    recognise_lark_query(source)
