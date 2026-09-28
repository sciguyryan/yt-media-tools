"""Migration-gate coverage for a future replacement yt-sql parser."""

from __future__ import annotations

from yt_discover_tests.parser_fuzzing import seeded_parser_fuzz_inputs, shrink_by_token_deletion
from yt_discover_tests.parser_grammar_generation import generated_valid_queries, grammar_productions
from yt_discover_tests.parser_migration_corpus import ACCEPTED_PARSER_CASES, REJECTED_PARSER_CASES
from yt_discover_tests.parser_migration_harness import benchmark_parser, canonical_round_trip, capture_outcome
from yt_discover_tests.parser_mutation import malformed_neighbours
from yt_media_tools.query_model import QuerySyntaxError
from yt_media_tools.query_parser import parse_query


def test_deterministic_accepted_corpus_parses_and_round_trips() -> None:
    for case in ACCEPTED_PARSER_CASES:
        model, canonical = canonical_round_trip(parse_query, case.query)
        assert model
        assert canonical


def test_deterministic_rejected_corpus_matches_expected_categories() -> None:
    for case in REJECTED_PARSER_CASES:
        outcome = capture_outcome(parse_query, case.query)
        assert outcome.model is None, case.name
        assert outcome.diagnostic is not None, case.name
        assert outcome.diagnostic[0] == case.category, case.name


def test_grammar_generated_cases_reference_real_productions_and_parse() -> None:
    productions = grammar_productions()
    for case in generated_valid_queries(rounds=3):
        assert case.production in productions
        assert capture_outcome(parse_query, case.query).diagnostic is None


def test_controlled_mutations_are_rejected_neighbours() -> None:
    mutations = tuple(
        mutation for case in generated_valid_queries(rounds=2) for mutation in malformed_neighbours(case.query)
    )
    assert mutations
    for mutation in mutations:
        outcome = capture_outcome(parse_query, mutation.source)
        assert outcome.model is None, mutation.name
        assert outcome.diagnostic is not None, mutation.name
        assert outcome.diagnostic[0] == mutation.expected_category, mutation.name


def test_seeded_fuzz_inputs_never_escape_the_query_error_boundary() -> None:
    first = seeded_parser_fuzz_inputs(seed=31415926)
    assert first == seeded_parser_fuzz_inputs(seed=31415926)
    for source in first:
        try:
            parse_query(source)
        except QuerySyntaxError:
            pass


def test_fuzz_shrinking_is_deterministic_and_strictly_smaller() -> None:
    source = "SELECT id FROM @fixture WHERE duration > 60"
    shrunk = shrink_by_token_deletion(source)
    assert shrunk == shrink_by_token_deletion(source)
    assert shrunk
    assert all(len(item) < len(source) for item in shrunk)


def test_reference_parser_outcome_is_self_equivalent() -> None:
    for case in ACCEPTED_PARSER_CASES:
        assert capture_outcome(parse_query, case.query) == capture_outcome(parse_query, case.query)


def test_performance_harness_records_baseline_without_enforcing_policy() -> None:
    queries = tuple(case.query for case in ACCEPTED_PARSER_CASES[:4])
    timing = benchmark_parser(parse_query, queries, label="reference", iterations=2)
    assert timing.queries == len(queries)
    assert timing.iterations == 2
    assert timing.elapsed_seconds >= 0
    assert timing.parses_per_second > 0
