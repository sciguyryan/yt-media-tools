"""Adversarial Unicode identifier conformance and cross-pipeline torture coverage."""

from __future__ import annotations

import pytest

from yt_discover_tests.unicode_identifier_corpus import FIXTURES_BY_NAME, IDENTIFIER_FIXTURES
from yt_media_tools.optimizer import optimise_query
from yt_media_tools.query import QuerySyntaxError, apply_query, parse_query, resolve_query
from yt_media_tools.query_formatter import format_query
from yt_media_tools.query_parser import tokenise
from yt_media_tools.schema import QuerySchema


def _quoted(spelling: str) -> str:
    return "`" + spelling.replace("`", "``") + "`"


def _codepoints(spelling: str) -> tuple[int, ...]:
    return tuple(ord(character) for character in spelling)


@pytest.mark.parametrize(
    "fixture", [fixture for fixture in IDENTIFIER_FIXTURES if fixture.valid_unquoted], ids=lambda item: item.name
)
def test_valid_unicode_corpus_matches_declared_codepoints_and_round_trips(fixture) -> None:
    # The explicit code-point assertion makes invisible and visually ambiguous fixtures reviewable.
    assert fixture.codepoints == _codepoints(fixture.spelling)
    source = f"SELECT {fixture.spelling} FROM @fixture"
    tokens = tokenise(source)
    assert tokens[1].kind == "IDENT"
    assert tokens[1].value == fixture.spelling

    rows = [{fixture.spelling: fixture.name}]
    resolved = resolve_query(parse_query(source), QuerySchema(rows))
    canonical = format_query(resolved)
    reparsed = resolve_query(parse_query(canonical), QuerySchema(rows))
    assert reparsed.select[0].expression.name == fixture.spelling
    assert format_query(reparsed) == canonical
    assert apply_query(rows, reparsed) == [{fixture.spelling: fixture.name}]


@pytest.mark.parametrize(
    "fixture", [fixture for fixture in IDENTIFIER_FIXTURES if not fixture.valid_unquoted], ids=lambda item: item.name
)
def test_invalid_unquoted_unicode_corpus_has_deterministic_boundary_and_quoted_escape_hatch(fixture) -> None:
    assert fixture.codepoints == _codepoints(fixture.spelling)
    source = f"SELECT {fixture.spelling} FROM @fixture"
    with pytest.raises(QuerySyntaxError) as first:
        parse_query(source)
    with pytest.raises(QuerySyntaxError) as second:
        parse_query(source)
    assert (first.value.message, first.value.position) == (second.value.message, second.value.position)

    quoted = _quoted(fixture.spelling)
    rows = [{fixture.spelling: fixture.name}]
    resolved = resolve_query(parse_query(f"SELECT {quoted} FROM @fixture"), QuerySchema(rows))
    assert resolved.select[0].expression.name == fixture.spelling
    assert apply_query(rows, resolved) == [{fixture.spelling: fixture.name}]
    assert format_query(parse_query(format_query(resolved))) == format_query(resolved)


def test_canonically_equivalent_identifiers_coexist_without_normalisation() -> None:
    composed = FIXTURES_BY_NAME["precomposed_acute"].spelling
    decomposed = FIXTURES_BY_NAME["decomposed_acute"].spelling
    assert composed != decomposed
    rows = [{composed: "composed", decomposed: "decomposed"}]
    resolved = resolve_query(parse_query(f"SELECT {composed}, {decomposed} FROM @fixture"), QuerySchema(rows))
    assert [term.expression.name for term in resolved.select] == [composed, decomposed]
    assert apply_query(rows, resolved) == [{composed: "composed", decomposed: "decomposed"}]


def test_zwj_and_zwnj_chains_are_distinct_exact_identifiers() -> None:
    zwj = FIXTURES_BY_NAME["zwj_combining"].spelling
    zwnj = FIXTURES_BY_NAME["zwnj_combining"].spelling
    plain = FIXTURES_BY_NAME["decomposed_acute"].spelling
    assert len({zwj, zwnj, plain}) == 3
    rows = [{zwj: "zwj", zwnj: "zwnj", plain: "plain"}]
    query = resolve_query(parse_query(f"SELECT {zwj}, {zwnj}, {plain} FROM @fixture"), QuerySchema(rows))
    assert [term.expression.name for term in query.select] == [zwj, zwnj, plain]
    assert list(apply_query(rows, query)[0].values()) == ["zwj", "zwnj", "plain"]


def test_visually_confusable_mixed_script_identifiers_remain_distinct() -> None:
    latin = FIXTURES_BY_NAME["latin_confusable"].spelling
    cyrillic = FIXTURES_BY_NAME["cyrillic_confusable"].spelling
    assert latin != cyrillic
    rows = [{latin: 1, cyrillic: 2}]
    query = resolve_query(parse_query(f"SELECT {latin}, {cyrillic} FROM @fixture"), QuerySchema(rows))
    assert apply_query(rows, query) == [{latin: 1, cyrillic: 2}]


def test_pathological_unicode_identifier_query_is_formatter_and_optimizer_stable() -> None:
    names = [
        FIXTURES_BY_NAME[name].spelling
        for name in (
            "precomposed_acute",
            "decomposed_acute",
            "combining_chain",
            "zwj_combining",
            "zwnj_combining",
            "variation_selector",
            "devanagari_joined",
            "deseret_supplementary",
            "latin_confusable",
            "cyrillic_confusable",
            "middle_dot_continue",
        )
    ]
    row = {name: index for index, name in enumerate(names, start=1)}
    schema = QuerySchema([row])
    source = "SELECT " + ", ".join(names) + " FROM @fixture"
    query = resolve_query(parse_query(source), schema)
    canonical = format_query(query)
    reparsed = resolve_query(parse_query(canonical), schema)
    assert format_query(reparsed) == canonical
    assert [term.expression.name for term in reparsed.select] == names

    expected = apply_query([row], query)
    optimised = optimise_query(query)
    assert apply_query([row], optimised.query) == expected
    assert optimise_query(optimised.query).query == optimised.query
