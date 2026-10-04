"""Baseline differential inventory for the experimental Lark parser."""

from __future__ import annotations

from dataclasses import replace

from yt_discover_tests.conformance.cases import CASES
from yt_discover_tests.parser_grammar_generation import generated_valid_queries
from yt_discover_tests.parser_migration_corpus import ACCEPTED_PARSER_CASES, REJECTED_PARSER_CASES
from yt_discover_tests.parser_migration_harness import ParserDifference, canonical_round_trip, compare_parsers
from yt_media_tools.discover_cli import bind_query_parameters
from yt_media_tools.experimental_lark_parser import parse_lark_query
from yt_media_tools.query_model import Query, QuerySyntaxError
from yt_media_tools.query_parser import parse_query


def _bound_conformance_query(query: str, parameters: tuple[str, ...]) -> str:
    values = dict(parameter.split("=", 1) for parameter in parameters)
    return bind_query_parameters(query, values)


def _accepted_inventory() -> tuple[tuple[str, str], ...]:
    cases = [(f"migration:{case.name}", case.query) for case in ACCEPTED_PARSER_CASES]
    cases.extend((f"conformance:{case.name}", _bound_conformance_query(case.query, case.params)) for case in CASES)
    cases.extend(
        (f"generated:{index}:{case.production}", case.query)
        for index, case in enumerate(generated_valid_queries(rounds=3))
    )
    return tuple(cases)


def test_differential_harness_reports_independent_model_and_origin_differences() -> None:
    source = "SELECT id FROM @fixture"

    def changed_model(text: str) -> Query:
        return replace(parse_query(text), limit=1)

    model_comparison = compare_parsers(parse_query, changed_model, source)
    assert model_comparison.differences == (ParserDifference.MODEL,)
    assert model_comparison.describe() == "model"

    def changed_origin(text: str) -> Query:
        query = parse_query(text)
        return replace(query, select=(replace(query.select[0], position=query.select[0].position + 1),))

    origin_comparison = compare_parsers(parse_query, changed_origin, source)
    assert origin_comparison.differences == (ParserDifference.ORIGINS,)
    assert origin_comparison.describe() == "origins"


def test_differential_harness_contains_and_reports_unexpected_errors() -> None:
    def broken_parser(_source: str) -> Query:
        raise IndexError("model construction escaped")

    comparison = compare_parsers(parse_query, broken_parser, "SELECT id FROM @fixture")

    assert comparison.differences == (ParserDifference.UNEXPECTED_ERROR,)
    assert comparison.candidate.unexpected_error == ("IndexError", "model construction escaped")
    assert comparison.describe() == "unexpected-error"


def test_differential_harness_distinguishes_acceptance_and_diagnostics() -> None:
    def rejecting_parser(source: str) -> Query:
        raise QuerySyntaxError(source, "candidate rejection", len(source))

    acceptance = compare_parsers(parse_query, rejecting_parser, "SELECT id FROM @fixture")
    assert acceptance.differences == (ParserDifference.ACCEPTANCE,)
    assert acceptance.describe() == "acceptance"

    diagnostic = compare_parsers(parse_query, rejecting_parser, "SELECT FROM @fixture")
    assert diagnostic.differences == (ParserDifference.DIAGNOSTIC,)
    assert diagnostic.describe() == "diagnostic"


def test_normalised_model_excludes_non_semantic_literal_source_spelling() -> None:
    single_quoted = compare_parsers(
        parse_query,
        parse_query,
        "SELECT id FROM @fixture WHERE title = 'Case Test'",
    ).reference.model
    double_quoted = compare_parsers(
        parse_query,
        parse_query,
        'SELECT id FROM @fixture WHERE title = "Case Test"',
    ).reference.model

    assert double_quoted == single_quoted


def test_lark_accepted_syntax_inventory_is_structurally_equivalent() -> None:
    cases = _accepted_inventory()
    assert cases

    for name, source in cases:
        comparison = compare_parsers(parse_query, parse_lark_query, source)
        assert comparison.reference.kind == "accepted", name
        assert comparison.equivalent, f"{name}: {comparison.describe()}"


def test_lark_accepted_syntax_inventory_has_canonical_cross_parser_convergence() -> None:
    for name, source in _accepted_inventory():
        reference_model, reference_canonical = canonical_round_trip(parse_query, source)
        candidate_model, candidate_canonical = canonical_round_trip(parse_lark_query, source)

        assert candidate_model == reference_model, name
        assert candidate_canonical == reference_canonical, name
        canonical_comparison = compare_parsers(parse_query, parse_lark_query, reference_canonical)
        assert canonical_comparison.equivalent, f"{name}: {canonical_comparison.describe()}"


def test_lark_malformed_syntax_inventory_has_no_unclassified_outcomes() -> None:
    for case in REJECTED_PARSER_CASES:
        comparison = compare_parsers(parse_query, parse_lark_query, case.query)
        assert comparison.reference.kind == "rejected", case.name
        assert comparison.describe(), case.name
        assert comparison.equivalent == (not comparison.differences), case.name
