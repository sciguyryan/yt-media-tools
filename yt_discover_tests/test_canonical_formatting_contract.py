"""Canonical yt-sql formatting and round-trip contract for issue #16."""

from __future__ import annotations

import pytest

from yt_media_tools.query_formatter import format_query
from yt_media_tools.query_parser import parse_query
from yt_media_tools.query_semantics import semantic_key


def _assert_canonical_round_trip(source: str) -> str:
    parsed = parse_query(source)
    canonical = format_query(parsed)
    reparsed = parse_query(canonical)
    assert semantic_key(reparsed) == semantic_key(parsed)
    assert format_query(reparsed) == canonical
    return canonical


@pytest.mark.parametrize(
    "source",
    (
        'select id from @example where title = "Mars"',
        "SELECT formats[0].height FROM @example WHERE formats[0].height >= 1080",
        "SELECT 0XFF, 0o7_55, 0B1010_0101 FROM @example",
        "SELECT id FROM @a UNION ALL (SELECT id FROM @b ORDER BY id DESC LIMIT 2) ORDER BY id",
        "WITH known AS (SELECT id FROM @known) SELECT l.id FROM @left AS l JOIN known AS k ON l.id = k.id",
    ),
)
def test_canonical_formatting_preserves_semantics_and_is_idempotent(source: str) -> None:
    _assert_canonical_round_trip(source)


def test_canonical_strings_use_one_quote_style_and_escape_by_value() -> None:
    canonical = _assert_canonical_round_trip('SELECT "can\'t", "line\\nnext", "slash\\\\n" FROM @example')
    assert canonical == "SELECT 'can''t', 'line\\nnext', 'slash\\\\n' FROM @example"


def test_like_pattern_backslashes_remain_pattern_syntax() -> None:
    canonical = _assert_canonical_round_trip(r'SELECT id FROM @example WHERE title LIKE "100\\%"')
    assert canonical == r"SELECT id FROM @example WHERE title LIKE '100\\%'"


def test_numeric_bases_are_preserved_while_incidental_spelling_is_normalised() -> None:
    canonical = _assert_canonical_round_trip("SELECT 0XFF, 0o7_55, 0B1010_0101, 1_000 FROM @example")
    assert canonical == "SELECT 0xff, 0o755, 0b10100101, 1000 FROM @example"


def test_postfix_chains_are_compact() -> None:
    canonical = _assert_canonical_round_trip("SELECT formats [ 0 ] . height FROM @example")
    assert canonical == "SELECT formats[0].height FROM @example"


def test_join_layout_is_multiline_and_normalises_inner_and_outer_spelling() -> None:
    canonical = _assert_canonical_round_trip(
        'SELECT l.id FROM @left AS l INNER JOIN @right OF videos AS r ON l.id=r.id WHERE r.title="Mars"'
    )
    assert canonical == (
        "SELECT l.id\nFROM @left AS l\nJOIN @right OF videos AS r\n  ON l.id = r.id\nWHERE r.title = 'Mars'"
    )


def test_cte_and_compound_layout_exposes_relation_boundaries() -> None:
    canonical = _assert_canonical_round_trip(
        "WITH known AS (SELECT id FROM @known) "
        "SELECT id FROM known UNION ALL (SELECT id FROM @other ORDER BY id DESC LIMIT 2) ORDER BY id"
    )
    assert canonical == (
        "WITH known AS (\n"
        "  SELECT id FROM @known\n"
        ")\n"
        "SELECT id\n"
        "FROM known\n"
        "UNION ALL\n"
        "(\n"
        "  SELECT id FROM @other ORDER BY id DESC LIMIT 2\n"
        ")\n"
        "ORDER BY id ASC"
    )


def test_grouping_parentheses_survive_when_they_define_compound_scope() -> None:
    left = _assert_canonical_round_trip(
        "(SELECT id FROM @a ORDER BY id DESC LIMIT 1) UNION ALL SELECT id FROM @b ORDER BY id"
    )
    right = _assert_canonical_round_trip(
        "SELECT id FROM @a UNION ALL (SELECT id FROM @b ORDER BY id DESC LIMIT 1) ORDER BY id"
    )
    assert left.startswith("(\n  SELECT id FROM @a ORDER BY id DESC LIMIT 1\n)\nUNION ALL")
    assert "UNION ALL\n(\n  SELECT id FROM @b ORDER BY id DESC LIMIT 1\n)" in right


def test_semantic_round_trip_oracle_includes_relational_structure() -> None:
    inner = parse_query("SELECT l.id FROM @left AS l JOIN @right AS r ON l.id = r.id")
    left = parse_query("SELECT l.id FROM @left AS l LEFT JOIN @right AS r ON l.id = r.id")
    renamed = parse_query("SELECT x.id FROM @left AS x JOIN @right AS r ON x.id = r.id")
    assert semantic_key(inner) != semantic_key(left)
    assert semantic_key(inner) != semantic_key(renamed)
