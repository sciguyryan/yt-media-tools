"""Language-only contract for the deferred final-result POSITION expression."""

import pytest

from yt_media_tools.query_formatter import format_query
from yt_media_tools.query_model import QuerySemanticError, QuerySyntaxError, ScalarFunction
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


@pytest.mark.parametrize("expression", ["POSITION(1)", "POSITION(id)", "POSITION(1, 2)"])
def test_position_requires_zero_arguments(expression):
    with pytest.raises(QuerySyntaxError, match="POSITION requires no arguments"):
        parse_query(f"SELECT {expression} FROM @fixture")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id FROM @fixture WHERE POSITION() > 0",
        "SELECT id FROM @fixture ORDER BY POSITION()",
        "SELECT POSITION() + 1 FROM @fixture",
        "SELECT COALESCE(POSITION(), 1) FROM @fixture",
        "SELECT id FROM @fixture GROUP BY POSITION()",
    ],
)
def test_position_is_rejected_outside_standalone_projection(sql):
    query = parse_query(sql)
    with pytest.raises((QuerySemanticError, QuerySyntaxError), match="POSITION"):
        resolve_query(query, QuerySchema([{"id": "a"}]))


def test_position_numbers_after_ordering_before_offset_and_limit():
    from yt_media_tools.query_evaluator import apply_query

    records = [{"id": "c"}, {"id": "a"}, {"id": "d"}, {"id": "b"}]
    sql = "SELECT POSITION() AS position, id FROM @fixture ORDER BY id ASC LIMIT 2 OFFSET 1"
    resolved = resolve_query(parse_query(sql), QuerySchema(records))
    result = apply_query(records, resolved)
    assert [(row["position"], row["id"]) for row in result] == [(2, "b"), (3, "c")]
    assert all("position" not in row for row in records)


def test_position_is_deferred_until_after_distinct():
    from yt_media_tools.query_evaluator import apply_query

    records = [{"title": "a"}, {"title": "a"}, {"title": "b"}]
    sql = "SELECT DISTINCT POSITION() AS position, title FROM @fixture ORDER BY title ASC"
    resolved = resolve_query(parse_query(sql), QuerySchema(records))
    result = apply_query(records, resolved)
    assert [(row["position"], row["title"]) for row in result] == [(1, "a"), (2, "b")]


def test_position_numbers_aggregate_result():
    from yt_media_tools.query_evaluator import apply_query

    records = [{"title": "b"}, {"title": "a"}, {"title": "b"}]
    sql = "SELECT POSITION() AS position, title, COUNT(*) AS total FROM @fixture GROUP BY title ORDER BY title ASC"
    resolved = resolve_query(parse_query(sql), QuerySchema(records))
    result = apply_query(records, resolved)
    assert [(row["position"], row["total"]) for row in result] == [(1, 1), (2, 2)]


def test_position_alias_cannot_order_the_result():
    query = parse_query("SELECT POSITION() AS position, id FROM @fixture ORDER BY position")
    with pytest.raises(QuerySemanticError, match="ORDER BY cannot depend"):
        resolve_query(query, QuerySchema([{"id": "a"}]))


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
    optimised = optimise_query(query).query
    expected = [(2, "b"), (3, "c")]
    for candidate in (query, optimised):
        for relational_optimisation in (False, True):
            rows = apply_query(records, candidate, relational_optimisation=relational_optimisation)
            assert [(row["position"], row["id"]) for row in rows] == expected


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("SELECT POSITION() AS position, id FROM @fixture ORDER BY id ASC", [(1, "a"), (2, "b"), (3, "c")]),
        ("SELECT POSITION() AS position, id FROM @fixture ORDER BY id DESC LIMIT 2 OFFSET 1", [(2, "b"), (3, "a")]),
        ("SELECT POSITION() AS position, id FROM @fixture ORDER BY id ASC OFFSET 10", []),
        ("SELECT POSITION() AS position, id FROM @fixture WHERE id = 'z' ORDER BY id", []),
    ],
)
def test_position_order_and_slice_differential(sql, expected):
    from yt_media_tools.optimizer import optimise_query
    from yt_media_tools.query_evaluator import apply_query

    records = [{"id": "c"}, {"id": "a"}, {"id": "b"}]
    resolved = resolve_query(parse_query(sql), QuerySchema(records))
    for query in (resolved, optimise_query(resolved).query):
        for relational_optimisation in (False, True):
            rows = apply_query(records, query, relational_optimisation=relational_optimisation)
            assert [(row["position"], row["id"]) for row in rows] == expected


def test_position_without_order_reflects_observed_sequence_only():
    from yt_media_tools.query_evaluator import apply_query

    records = [{"id": "c"}, {"id": "a"}, {"id": "b"}]
    query = resolve_query(parse_query("SELECT POSITION() AS position, id FROM @fixture"), QuerySchema(records))
    rows = apply_query(records, query)
    assert [row["position"] for row in rows] == list(range(1, len(rows) + 1))
    assert sorted(row["id"] for row in rows) == ["a", "b", "c"]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT POSITION() AS position, id FROM @fixture UNION ALL SELECT 1 AS position, id FROM @fixture",
        "SELECT 1 AS position, id FROM @fixture UNION ALL SELECT POSITION() AS position, id FROM @fixture",
    ],
)
def test_position_compound_projections_fail_explicitly(sql):
    with pytest.raises((QuerySemanticError, QuerySyntaxError), match="POSITION"):
        resolve_query(parse_query(sql), QuerySchema([{"id": "a"}]))


def test_position_canonical_round_trip_in_nested_cte():
    sql = (
        "WITH ranked AS (SELECT POSITION() AS position, id FROM @fixture ORDER BY id ASC) "
        "SELECT id FROM ranked ORDER BY id DESC"
    )
    parsed = parse_query(sql)
    canonical = format_query(parsed)
    assert format_query(parse_query(canonical)) == canonical


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        (
            "WITH ranked AS (SELECT POSITION() AS position, id FROM @fixture ORDER BY id ASC) "
            "SELECT position, id FROM ranked ORDER BY id DESC",
            [(4, "d"), (3, "c"), (2, "b"), (1, "a")],
        ),
        (
            "WITH ranked AS (SELECT POSITION() AS position, id FROM @fixture ORDER BY id ASC LIMIT 2 OFFSET 1) "
            "SELECT position, id FROM ranked ORDER BY id DESC",
            [(3, "c"), (2, "b")],
        ),
        (
            "SELECT position, id FROM (SELECT POSITION() AS position, id FROM @fixture ORDER BY id ASC) "
            "AS ranked ORDER BY id DESC",
            [(4, "d"), (3, "c"), (2, "b"), (1, "a")],
        ),
        (
            "SELECT POSITION() AS position, id FROM "
            "(SELECT id FROM @fixture ORDER BY id ASC LIMIT 2 OFFSET 1) AS ranked ORDER BY id DESC",
            [(1, "c"), (2, "b")],
        ),
    ],
)
def test_position_is_scoped_to_its_own_query_block(sql, expected):
    """An enclosing query's ordering must not renumber an inner query's POSITION()."""
    from yt_media_tools.optimizer import optimise_query
    from yt_media_tools.query_evaluator import apply_query

    records = [{"id": value} for value in "dcba"]
    query = resolve_query(parse_query(sql), QuerySchema(records))
    for candidate in (query, optimise_query(query).query):
        for relational_optimisation in (False, True):
            rows = apply_query(records, candidate, relational_optimisation=relational_optimisation)
            assert [(row["position"], row["id"]) for row in rows] == expected
