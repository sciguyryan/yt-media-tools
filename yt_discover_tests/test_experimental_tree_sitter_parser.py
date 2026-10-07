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

_DERIVED_RELATION_QUERIES = (
    ("SELECT CONCAT(id, ' # ', title) FROM (SELECT id, title FROM @a UNION SELECT id, title FROM @b)"),
    "SELECT outer_id FROM (SELECT inner_id AS outer_id FROM (SELECT id AS inner_id FROM @a)) AS combined",
    "SELECT id FROM (id = 'a')",
    ("SELECT a.id FROM @a AS a JOIN (SELECT id FROM @b UNION ALL SELECT id FROM @c) AS combined ON a.id = combined.id"),
)

_MALFORMED_DERIVED_RELATIONS = (
    "SELECT id FROM ()",
    "SELECT id FROM (SELECT id FROM @a",
    "SELECT id FROM (SELECT id FROM @a) OF videos",
)

_COMMENT_QUERIES = (
    "# leading\nSELECT id",
    "SELECT id # trailing without newline",
    "SELECT # projection\n id FROM # relation\n @a",
    "SELECT '# string' FROM (SELECT id FROM @a # nested\n)",
)

_SLICING_INTEGER_QUERIES = (
    "SELECT id LIMIT 0xff",
    "SELECT id LIMIT 0o7_55 OFFSET 0B10",
    "SELECT id OFFSET 0x0",
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
@pytest.mark.parametrize("source", _DERIVED_RELATION_QUERIES, ids=("union", "nested", "predicate-only", "join"))
def test_tree_sitter_revision_2_slice_accepts_derived_relations(source: str) -> None:
    recognise_tree_sitter_query(source)


@pytest.mark.skipif(not tree_sitter_available(), reason="optional Tree-sitter experiment is not installed")
@pytest.mark.parametrize("source", _MALFORMED_DERIVED_RELATIONS, ids=("empty", "unclosed", "of-clause"))
def test_tree_sitter_revision_2_slice_rejects_malformed_derived_relations(source: str) -> None:
    with pytest.raises(QuerySyntaxError):
        recognise_tree_sitter_query(source)


@pytest.mark.skipif(not tree_sitter_available(), reason="optional Tree-sitter experiment is not installed")
@pytest.mark.parametrize("source", _COMMENT_QUERIES, ids=("leading", "trailing", "between", "nested-string"))
def test_tree_sitter_revision_2_slice_accepts_line_comments(source: str) -> None:
    recognise_tree_sitter_query(source)


@pytest.mark.skipif(not tree_sitter_available(), reason="optional Tree-sitter experiment is not installed")
@pytest.mark.parametrize("source", _SLICING_INTEGER_QUERIES, ids=("hex", "octal-binary", "zero-offset"))
def test_tree_sitter_revision_2_slice_accepts_integer_base_slicing(source: str) -> None:
    recognise_tree_sitter_query(source)


@pytest.mark.skipif(not tree_sitter_available(), reason="optional Tree-sitter experiment is not installed")
@pytest.mark.parametrize(
    "source",
    (
        "SELECT id LIMIT 0x0",
        "SELECT id LIMIT 0xGG",
        "SELECT id OFFSET 0b102",
        "SELECT id LIMIT 0x",
        "SELECT id LIMIT 1.5",
        "SELECT id LIMIT 1k",
    ),
)
def test_tree_sitter_revision_2_slice_rejects_invalid_integer_slicing(source: str) -> None:
    with pytest.raises(QuerySyntaxError):
        recognise_tree_sitter_query(source)


@pytest.mark.skipif(not tree_sitter_available(), reason="optional Tree-sitter experiment is not installed")
def test_tree_sitter_smoke_grammar_rejects_recovery_nodes() -> None:
    source = "SELECT"

    with pytest.raises(QuerySyntaxError) as captured:
        recognise_tree_sitter_query(source)

    assert captured.value.position == len(source)
