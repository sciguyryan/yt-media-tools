"""Boundary and conformance checks for the optional Tree-sitter experiment."""

from __future__ import annotations

import pytest

from yt_discover_tests.conformance.cases import CASES
from yt_discover_tests.parser_grammar_generation import generated_valid_queries
from yt_discover_tests.parser_migration_corpus import ACCEPTED_PARSER_CASES, REJECTED_PARSER_CASES
from yt_discover_tests.parser_migration_harness import compare_parsers
from yt_discover_tests.parser_mutation import malformed_neighbours
from yt_discover_tests.test_parser_differential_conformance import MAXIMAL_DERIVED_RELATION_TORTURE_QUERY
from yt_media_tools.discover_cli import bind_query_parameters
from yt_media_tools.experimental_tree_sitter_parser import (
    _character_offset,
    parse_tree_sitter_query,
    recognise_tree_sitter_query,
    tree_sitter_available,
)
from yt_media_tools.parser_equivalence import normalised_parser_model, user_origin_positions
from yt_media_tools.query_model import QuerySyntaxError
from yt_media_tools.query_parser import parse_query

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


def _complete_accepted_inventory() -> tuple[tuple[str, str], ...]:
    cases = [(f"migration:{case.name}", case.query) for case in ACCEPTED_PARSER_CASES]
    for case in CASES:
        values = dict(parameter.split("=", 1) for parameter in case.params)
        cases.append((f"conformance:{case.name}", bind_query_parameters(case.query, values)))
    cases.extend(
        (f"generated:{index}:{case.production}", case.query)
        for index, case in enumerate(generated_valid_queries(rounds=3))
    )
    return tuple(cases)


def _malformed_mutation_inventory() -> tuple[tuple[str, str], ...]:
    cases = {
        mutation.source: mutation.name
        for generated in generated_valid_queries(rounds=3)
        for mutation in malformed_neighbours(generated.query)
    }
    return tuple((name, source) for source, name in cases.items())


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
def test_tree_sitter_complete_grammar_accepts_established_inventory() -> None:
    cases = _complete_accepted_inventory()
    assert len(cases) >= 220

    for name, source in cases:
        try:
            recognise_tree_sitter_query(source)
        except QuerySyntaxError as error:
            pytest.fail(f"{name}: {error}")


@pytest.mark.skipif(not tree_sitter_available(), reason="optional Tree-sitter experiment is not installed")
def test_tree_sitter_complete_grammar_rejects_established_malformed_inventory() -> None:
    for case in REJECTED_PARSER_CASES:
        with pytest.raises(QuerySyntaxError):
            recognise_tree_sitter_query(case.query)


@pytest.mark.skipif(not tree_sitter_available(), reason="optional Tree-sitter experiment is not installed")
def test_tree_sitter_malformed_inventory_has_equivalent_diagnostics() -> None:
    for case in REJECTED_PARSER_CASES:
        comparison = compare_parsers(parse_query, parse_tree_sitter_query, case.query)

        assert comparison.reference.kind == "rejected", case.name
        assert comparison.candidate.kind == "rejected", case.name
        assert comparison.equivalent, f"{case.name}: {comparison.describe()}"


@pytest.mark.skipif(not tree_sitter_available(), reason="optional Tree-sitter experiment is not installed")
def test_tree_sitter_controlled_malformed_neighbours_have_equivalent_diagnostics() -> None:
    cases = _malformed_mutation_inventory()
    assert len(cases) >= 39

    for name, source in cases:
        comparison = compare_parsers(parse_query, parse_tree_sitter_query, source)

        assert comparison.reference.kind == "rejected", name
        assert comparison.candidate.kind == "rejected", name
        assert comparison.equivalent, f"{name}: {comparison.describe()} for {source!r}"


@pytest.mark.skipif(not tree_sitter_available(), reason="optional Tree-sitter experiment is not installed")
@pytest.mark.parametrize(
    "source",
    (
        "SELECT 'unterminated",
        "SELECT 'incomplete\\",
        "SELECT `unterminated",
        "SELECT ``",
        "SELECT 0xGG",
        "SELECT 0o9",
        "SELECT 0b102",
        "SELECT 💩",
        "SELECT Δelta\nWHERE 💩",
        "SELECT id LIMIT 0x0",
        "SELECT id LIMIT 1.5",
    ),
)
def test_tree_sitter_lexical_and_slicing_failures_have_equivalent_diagnostics(source: str) -> None:
    comparison = compare_parsers(parse_query, parse_tree_sitter_query, source)

    assert comparison.reference.kind == "rejected"
    assert comparison.candidate.kind == "rejected"
    assert comparison.equivalent, comparison.describe()


@pytest.mark.skipif(not tree_sitter_available(), reason="optional Tree-sitter experiment is not installed")
@pytest.mark.parametrize("name", ("future_function", "`future function`"))
def test_tree_sitter_function_syntax_does_not_embed_the_runtime_registry(name: str) -> None:
    recognise_tree_sitter_query(f"SELECT {name}(id)")

    with pytest.raises(QuerySyntaxError):
        parse_tree_sitter_query(f"SELECT {name}(id)")


@pytest.mark.skipif(not tree_sitter_available(), reason="optional Tree-sitter experiment is not installed")
@pytest.mark.parametrize(
    "source",
    (
        "SELECT id WHERE upload_date >= TODAY() - 1 year",
        "SELECT id WHERE duration < 1μέρα",
    ),
)
def test_tree_sitter_complete_grammar_accepts_spaced_and_unicode_units(source: str) -> None:
    reference = parse_query(source)
    candidate = parse_tree_sitter_query(source)

    assert normalised_parser_model(candidate) == normalised_parser_model(reference)
    assert user_origin_positions(candidate) == user_origin_positions(reference)


@pytest.mark.skipif(not tree_sitter_available(), reason="optional Tree-sitter experiment is not installed")
def test_tree_sitter_complete_grammar_accepts_maximal_revision_2_torture_query() -> None:
    recognise_tree_sitter_query(MAXIMAL_DERIVED_RELATION_TORTURE_QUERY)


@pytest.mark.skipif(not tree_sitter_available(), reason="optional Tree-sitter experiment is not installed")
def test_tree_sitter_models_and_origins_match_the_complete_accepted_inventory() -> None:
    for name, source in _complete_accepted_inventory():
        reference = parse_query(source)
        candidate = parse_tree_sitter_query(source)

        assert normalised_parser_model(candidate) == normalised_parser_model(reference), name
        assert user_origin_positions(candidate) == user_origin_positions(reference), name


@pytest.mark.skipif(not tree_sitter_available(), reason="optional Tree-sitter experiment is not installed")
def test_tree_sitter_models_and_origins_match_the_maximal_revision_2_query() -> None:
    reference = parse_query(MAXIMAL_DERIVED_RELATION_TORTURE_QUERY)
    candidate = parse_tree_sitter_query(MAXIMAL_DERIVED_RELATION_TORTURE_QUERY)

    assert normalised_parser_model(candidate) == normalised_parser_model(reference)
    assert user_origin_positions(candidate) == user_origin_positions(reference)


@pytest.mark.skipif(not tree_sitter_available(), reason="optional Tree-sitter experiment is not installed")
@pytest.mark.parametrize("source", _COMMENT_QUERIES)
def test_tree_sitter_comments_preserve_model_source_origins(source: str) -> None:
    reference = parse_query(source)
    candidate = parse_tree_sitter_query(source)

    assert normalised_parser_model(candidate) == normalised_parser_model(reference)
    assert user_origin_positions(candidate) == user_origin_positions(reference)


@pytest.mark.skipif(not tree_sitter_available(), reason="optional Tree-sitter experiment is not installed")
def test_tree_sitter_smoke_grammar_rejects_recovery_nodes() -> None:
    source = "SELECT"

    with pytest.raises(QuerySyntaxError) as captured:
        recognise_tree_sitter_query(source)

    assert captured.value.position == len(source)
