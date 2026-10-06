"""Part 1 boundary checks for the optional Tree-sitter experiment."""

from __future__ import annotations

import pytest

from yt_media_tools.experimental_tree_sitter_parser import (
    _character_offset,
    recognise_tree_sitter_query,
    tree_sitter_available,
)
from yt_media_tools.query_model import QuerySyntaxError

_REPRESENTATIVE_QUERIES = (
    "SELECT id WHERE view_count >= 1000",
    (
        "SELECT id, title, COALESCE(view_count, 0) AS views "
        "WHERE (view_count >= 1000 AND title ILIKE '%video%') "
        "OR (duration >= 60s AND upload_date >= 2025-01-01) "
        "ORDER BY view_count DESC, title ASC LIMIT 100 OFFSET 5"
    ),
    (
        "SELECT id, MAP(FILTER(tags AS tag WHERE tag IS NOT NULL) AS tag SELECT UPPER(tag)) "
        "AS normalised_tags WHERE ANY(tags AS tag WHERE tag = 'group-1')"
    ),
)


def test_tree_sitter_byte_offsets_convert_to_python_character_offsets() -> None:
    source = "Δelta SELECT"
    encoded = source.encode("utf-8")

    assert _character_offset(encoded, encoded.index(b"S")) == source.index("S")
    assert _character_offset(encoded, len(encoded)) == len(source)


@pytest.mark.skipif(not tree_sitter_available(), reason="optional Tree-sitter experiment is not installed")
def test_tree_sitter_smoke_grammar_accepts_a_projection() -> None:
    recognise_tree_sitter_query("SELECT id")
    recognise_tree_sitter_query("select title")


@pytest.mark.skipif(not tree_sitter_available(), reason="optional Tree-sitter experiment is not installed")
@pytest.mark.parametrize("source", _REPRESENTATIVE_QUERIES, ids=("simple", "complex", "collection"))
def test_tree_sitter_feasibility_grammar_accepts_representative_queries(source: str) -> None:
    recognise_tree_sitter_query(source)


@pytest.mark.skipif(not tree_sitter_available(), reason="optional Tree-sitter experiment is not installed")
def test_tree_sitter_smoke_grammar_rejects_recovery_nodes() -> None:
    source = "SELECT"

    with pytest.raises(QuerySyntaxError) as captured:
        recognise_tree_sitter_query(source)

    assert captured.value.position == len(source)
