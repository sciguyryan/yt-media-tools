"""Language-only contract for the deferred final-result POSITION expression."""

import pytest

from yt_media_tools.query_formatter import format_query
from yt_media_tools.query_model import ScalarFunction
from yt_media_tools.query_parser import parse_query
from yt_media_tools.query_resolver import resolve_query
from yt_media_tools.schema import QuerySchema


def test_position_projection_parses_and_canonicalises():
    query = parse_query("SELECT POSITION() AS position, id FROM @fixture ORDER BY id LIMIT 3 OFFSET 2")
    assert isinstance(query.select[0].expression, ScalarFunction)
    assert query.select[0].expression.name == "POSITION"
    canonical = format_query(query)
    assert "POSITION()" in canonical
    assert format_query(parse_query(canonical)) == canonical
    resolved = resolve_query(query, QuerySchema([{"id": "a"}]))
    assert resolved.select[0].kind == "integer"


def test_position_projection_does_not_mutate_source_records():
    """Keep implementation-specific source immutability outside portable fixtures."""
    from yt_media_tools.query_evaluator import apply_query

    records = [{"id": "c"}, {"id": "a"}, {"id": "d"}, {"id": "b"}]
    resolved = resolve_query(
        parse_query("SELECT POSITION() AS position, id FROM @fixture ORDER BY id ASC LIMIT 2 OFFSET 1"),
        QuerySchema(records),
    )
    apply_query(records, resolved)
    assert all("position" not in row for row in records)


def test_position_properties_are_final_stage_without_metadata_requirements():
    from yt_media_tools.query_properties import (
        METADATA_NONE,
        STAGE_FINAL_RESULT,
        analyse_expression,
        required_query_fields,
    )

    query = resolve_query(
        parse_query("SELECT POSITION() AS position FROM @fixture ORDER BY id LIMIT 2 OFFSET 1"),
        QuerySchema([{"id": "a"}]),
    )
    properties = analyse_expression(query.select[0].expression)
    assert properties.earliest_stage == STAGE_FINAL_RESULT
    assert properties.metadata_depth == METADATA_NONE
    assert properties.required_fields == frozenset()
    assert not properties.constant
    assert not properties.decidable_from_enumeration
    assert required_query_fields(query) == {"id"}


def test_position_disables_unproven_source_prefix_termination():
    from yt_media_tools.planner import plan_limit_termination

    query = resolve_query(
        parse_query("SELECT POSITION() AS position, id FROM @fixture LIMIT 2 OFFSET 3"),
        QuerySchema([{"id": "a"}]),
    )
    plan = plan_limit_termination(query)
    assert not plan.eligible
    assert plan.required_matches == 5
    assert "POSITION()" in plan.reason


def test_position_optimiser_preserves_final_sequence():
    from yt_media_tools.optimizer import optimise_query
    from yt_media_tools.query_evaluator import apply_query

    records = [{"id": "c"}, {"id": "a"}, {"id": "d"}, {"id": "b"}]
    query = resolve_query(
        parse_query("SELECT POSITION() AS position, id FROM @fixture ORDER BY id ASC LIMIT 2 OFFSET 1"),
        QuerySchema(records),
    )
    # The portable corpus owns the expected values; this checks execution-path equivalence.
    baseline = apply_query(records, query, relational_optimisation=False)
    for candidate in (query, optimise_query(query).query):
        for relational_optimisation in (False, True):
            assert apply_query(records, candidate, relational_optimisation=relational_optimisation) == baseline


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT POSITION() AS position, id FROM @fixture ORDER BY id ASC",
        "SELECT POSITION() AS position, id FROM @fixture ORDER BY id DESC LIMIT 2 OFFSET 1",
        "SELECT POSITION() AS position, id FROM @fixture ORDER BY id ASC OFFSET 10",
        "SELECT POSITION() AS position, id FROM @fixture WHERE id = 'z' ORDER BY id",
    ],
)
def test_position_order_and_slice_differential(sql):
    from yt_media_tools.optimizer import optimise_query
    from yt_media_tools.query_evaluator import apply_query

    records = [{"id": "c"}, {"id": "a"}, {"id": "b"}]
    resolved = resolve_query(parse_query(sql), QuerySchema(records))
    baseline = apply_query(records, resolved, relational_optimisation=False)
    for query in (resolved, optimise_query(resolved).query):
        for relational_optimisation in (False, True):
            assert apply_query(records, query, relational_optimisation=relational_optimisation) == baseline


def test_position_canonical_round_trip_in_nested_cte():
    sql = (
        "WITH ranked AS (SELECT POSITION() AS position, id FROM @fixture ORDER BY id ASC) "
        "SELECT id FROM ranked ORDER BY id DESC"
    )
    parsed = parse_query(sql)
    canonical = format_query(parsed)
    assert format_query(parse_query(canonical)) == canonical


@pytest.mark.parametrize(
    "sql",
    [
        (
            "WITH ranked AS (SELECT POSITION() AS position, id FROM @fixture ORDER BY id ASC) "
            "SELECT position, id FROM ranked ORDER BY id DESC"
        ),
        (
            "WITH ranked AS (SELECT POSITION() AS position, id FROM @fixture ORDER BY id ASC LIMIT 2 OFFSET 1) "
            "SELECT position, id FROM ranked ORDER BY id DESC"
        ),
        (
            "SELECT position, id FROM (SELECT POSITION() AS position, id FROM @fixture ORDER BY id ASC) "
            "AS ranked ORDER BY id DESC"
        ),
        (
            "SELECT POSITION() AS position, id FROM "
            "(SELECT id FROM @fixture ORDER BY id ASC LIMIT 2 OFFSET 1) AS ranked ORDER BY id DESC"
        ),
    ],
)
def test_position_is_scoped_to_its_own_query_block(sql):
    """An enclosing query's ordering must not renumber an inner query's POSITION()."""
    # The portable corpus owns the expected values; this checks execution-path equivalence.
    from yt_media_tools.optimizer import optimise_query
    from yt_media_tools.query_evaluator import apply_query

    records = [{"id": value} for value in "dcba"]
    query = resolve_query(parse_query(sql), QuerySchema(records))
    baseline = apply_query(records, query, relational_optimisation=False)
    for candidate in (query, optimise_query(query).query):
        for relational_optimisation in (False, True):
            assert apply_query(records, candidate, relational_optimisation=relational_optimisation) == baseline
