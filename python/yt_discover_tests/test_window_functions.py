"""Language and execution contract for the first yt-sql window function.

The portable conformance corpus owns normative expected values. These tests pin
the parser, resolver, evaluator, optimiser and planner contracts of
``ROW_NUMBER() OVER (...)`` as established by ``docs/WINDOW-DESIGN.md``.
"""

import pytest

from yt_media_tools.query_formatter import format_query
from yt_media_tools.query_model import (
    Field,
    OrderTerm,
    QuerySemanticError,
    QuerySyntaxError,
    WindowFunction,
    WindowSpecification,
)
from yt_media_tools.query_parser import parse_query
from yt_media_tools.query_resolver import resolve_query
from yt_media_tools.schema import QuerySchema
from yt_media_tools.query_semantics import semantic_key

BASE = "SELECT ROW_NUMBER() OVER (ORDER BY upload_date ASC) AS n, id FROM @example"


def _schema(*records: dict) -> QuerySchema:
    return QuerySchema(list(records))


def _apply(sql: str, records: tuple[dict, ...], *, relational_optimisation: bool = True):
    from yt_media_tools.query_evaluator import apply_query

    resolved = resolve_query(parse_query(sql), _schema(*records))
    return apply_query(records, resolved, relational_optimisation=relational_optimisation)


def _resolve(sql: str, records: tuple[dict, ...] = ({"id": "a"},)):
    return resolve_query(parse_query(sql), _schema(*records))


_EVAL_RECORDS = (
    {"id": "c", "title": "zebra", "upload_date": "2026-01-03", "view_count": 5},
    {"id": "a", "title": "apple", "upload_date": "2026-01-01", "view_count": 9},
    {"id": "b", "title": "mango", "upload_date": "2026-01-02", "view_count": 7},
    {"id": "d", "title": None, "upload_date": None, "view_count": None},
)


# ---------------------------------------------------------------------------
# Parsing and canonical formatting


def test_window_projection_parses_into_window_nodes() -> None:
    query = parse_query(BASE)
    expression = query.select[0].expression
    assert isinstance(expression, WindowFunction)
    assert expression.name == "ROW_NUMBER"
    specification = expression.specification
    assert isinstance(specification, WindowSpecification)
    assert specification.partition_by == ()
    assert len(specification.order_by) == 1
    term = specification.order_by[0]
    assert isinstance(term, OrderTerm)
    assert term.field == "upload_date"
    assert term.descending is False
    assert query.select[0].field == "ROW_NUMBER() OVER (ORDER BY upload_date ASC)"


def test_window_specification_parses_partition_and_order_terms() -> None:
    query = parse_query("SELECT row_number() over (partition by a, b.c order by x desc, y) as n FROM @example")
    expression = query.select[0].expression
    assert isinstance(expression, WindowFunction)
    assert expression.name == "ROW_NUMBER"
    assert [item.name for item in expression.specification.partition_by if isinstance(item, Field)] == ["a", "b.c"]
    assert len(expression.specification.order_by) == 2
    assert expression.specification.order_by[0].descending is True
    assert expression.specification.order_by[1].descending is False


def test_window_projection_canonicalises_deterministically() -> None:
    canonical = format_query(parse_query("SELECT row_number() over(order by upload_date asc) as n FROM @example"))
    assert canonical == "SELECT ROW_NUMBER() OVER (ORDER BY upload_date ASC) AS n FROM @example"
    assert format_query(parse_query(canonical)) == canonical


def test_window_canonical_round_trip_preserves_semantics() -> None:
    sources = (
        BASE,
        "SELECT ROW_NUMBER() OVER (PARTITION BY id, title ORDER BY view_count DESC, id ASC) AS n FROM @example",
        "SELECT id, ROW_NUMBER() OVER (ORDER BY LENGTH(id) + 1, CASE WHEN id = 'a' THEN 2 ELSE 1 END) AS n FROM @example",
    )
    for source in sources:
        query = parse_query(source)
        canonical = format_query(query)
        reparsed = parse_query(canonical)
        assert semantic_key(reparsed) == semantic_key(query)
        assert format_query(reparsed) == canonical


def test_window_ordering_accepts_only_scalar_expressions() -> None:
    with pytest.raises(QuerySyntaxError):
        parse_query("SELECT ROW_NUMBER() OVER (ORDER BY id IS NOT DISTINCT FROM NULL) AS n FROM @example")


def test_row_number_without_call_remains_an_ordinary_field() -> None:
    query = parse_query("SELECT row_number, Row_Number FROM @example")
    assert query.select[0].field == "row_number"
    assert query.select[1].field == "Row_Number"


def test_row_number_requires_an_over_specification() -> None:
    with pytest.raises(QuerySyntaxError) as excinfo:
        parse_query("SELECT ROW_NUMBER() AS n FROM @example")
    assert excinfo.value.reason == "missing-window-specification"
    assert "OVER" in excinfo.value.message


def test_row_number_rejects_arguments() -> None:
    with pytest.raises(QuerySyntaxError) as excinfo:
        parse_query("SELECT ROW_NUMBER(id) OVER (ORDER BY id) AS n FROM @example")
    assert "requires no arguments" in excinfo.value.message


@pytest.mark.parametrize(
    "source",
    (
        "SELECT ROW_NUMBER() OVER ORDER BY id AS n FROM @example",
        "SELECT ROW_NUMBER() OVER (PARTITION id) AS n FROM @example",
        "SELECT ROW_NUMBER() OVER (ORDER id) AS n FROM @example",
        "SELECT ROW_NUMBER() OVER (ORDER BY id AS n FROM @example",
        "SELECT ROW_NUMBER() OVER (PARTITION BY ) AS n FROM @example",
        "SELECT ROW_NUMBER() OVER (ORDER BY ) AS n FROM @example",
    ),
)
def test_malformed_window_specifications_are_rejected_deterministically(source: str) -> None:
    with pytest.raises(QuerySyntaxError):
        parse_query(source)


def test_over_natural_comparison_still_applies_to_fields() -> None:
    query = parse_query("SELECT id FROM @example WHERE duration OVER 5m")
    canonical = format_query(query)
    assert "duration > 5m" in canonical


def test_over_after_a_non_window_function_is_not_a_window_specification() -> None:
    with pytest.raises(QuerySyntaxError):
        parse_query("SELECT LENGTH(title) OVER (ORDER BY id) AS n FROM @example")


def test_window_function_in_where_parses_then_fails_at_resolution() -> None:
    query = parse_query("SELECT id FROM @example WHERE ROW_NUMBER() OVER (ORDER BY id) = 1")
    with pytest.raises(QuerySemanticError) as excinfo:
        resolve_query(query, _schema({"id": "a", "upload_date": None}))
    assert excinfo.value.reason == "invalid-window-placement"


# ---------------------------------------------------------------------------
# Resolution and placement


def test_window_projection_resolves_to_non_nullable_integer() -> None:
    resolved = _resolve(BASE)
    assert resolved.select[0].kind == "integer"
    assert resolved.select[0].expression.resolved_type is not None
    assert resolved.select[0].expression.resolved_type.nullable is False


def test_window_alias_may_order_the_final_result() -> None:
    from yt_media_tools.query_model import ScalarBinary

    resolved = _resolve(BASE + " ORDER BY n ASC")
    assert isinstance(resolved.order_by[0].expression, WindowFunction)
    resolved = _resolve(BASE + " ORDER BY n + 1 DESC")
    assert isinstance(resolved.order_by[0].expression, ScalarBinary)
    assert isinstance(resolved.order_by[0].expression.left, WindowFunction)


def test_alias_reference_inside_a_window_specification_is_an_unknown_field() -> None:
    with pytest.raises(QuerySemanticError) as excinfo:
        _resolve("SELECT ROW_NUMBER() OVER (ORDER BY n) AS n, id FROM @example")
    assert excinfo.value.reason == "unknown-field"


def test_direct_window_call_in_order_by_is_rejected() -> None:
    with pytest.raises(QuerySemanticError) as excinfo:
        _resolve("SELECT id FROM @example ORDER BY ROW_NUMBER() OVER (ORDER BY id)")
    assert excinfo.value.reason == "invalid-window-placement"


def test_window_inside_a_larger_projection_expression_is_rejected() -> None:
    with pytest.raises(QuerySemanticError) as excinfo:
        _resolve("SELECT ROW_NUMBER() OVER (ORDER BY id) + 0 AS n FROM @example")
    assert excinfo.value.reason == "invalid-window-placement"
    assert "standalone" in excinfo.value.message


@pytest.mark.parametrize(
    "source,reason",
    (
        ("SELECT id FROM @example WHERE ROW_NUMBER() OVER (ORDER BY id) = 1", "invalid-window-placement"),
        ("SELECT id FROM @example GROUP BY ROW_NUMBER() OVER (ORDER BY id)", "unsupported-window-aggregate-query"),
        (
            "SELECT COUNT(*) FROM @example HAVING ROW_NUMBER() OVER (ORDER BY id) > 0",
            "unsupported-window-aggregate-query",
        ),
        (
            "SELECT a.id FROM @example AS a JOIN @example AS b ON a.id = b.id AND ROW_NUMBER() OVER (ORDER BY a.id) = 1",
            "invalid-window-placement",
        ),
        (
            "SELECT id FROM @example WHERE ANY(x AS item WHERE ROW_NUMBER() OVER (ORDER BY id) = 1)",
            "invalid-window-placement",
        ),
        (
            "SELECT MAP(x AS item SELECT ROW_NUMBER() OVER (ORDER BY id)) AS m FROM @example",
            "invalid-window-placement",
        ),
        (
            "SELECT ROW_NUMBER() OVER (ORDER BY ROW_NUMBER() OVER (ORDER BY id)) AS n FROM @example",
            "unsupported-window-nesting",
        ),
        (
            "SELECT ROW_NUMBER() OVER (ORDER BY RANDOM()) AS n FROM @example",
            "invalid-window-volatile",
        ),
        ("SELECT ROW_NUMBER() OVER (PARTITION BY RANDOM()) AS n FROM @example", "invalid-window-volatile"),
        ("SELECT id, ROW_NUMBER() OVER () AS n FROM @example", "window-order-required"),
        ("SELECT id, ROW_NUMBER() OVER (PARTITION BY id) AS n FROM @example", "window-order-required"),
    ),
)
def test_window_placement_rejections(source: str, reason: str) -> None:
    schema_records = ({"id": "a", "x": [1], "upload_date": None, "duration": 1},)
    with pytest.raises(QuerySemanticError) as excinfo:
        resolve_query(parse_query(source), _schema(*schema_records))
    assert excinfo.value.reason == reason


def test_aggregate_queries_reject_window_functions() -> None:
    with pytest.raises(QuerySemanticError) as excinfo:
        _resolve("SELECT COUNT(*), ROW_NUMBER() OVER (ORDER BY id) AS n FROM @example")
    assert excinfo.value.reason == "unsupported-window-aggregate-query"
    with pytest.raises(QuerySemanticError) as excinfo:
        _resolve("SELECT id, ROW_NUMBER() OVER (ORDER BY id) AS n FROM @example GROUP BY id")
    assert excinfo.value.reason == "unsupported-window-aggregate-query"
    with pytest.raises(QuerySemanticError) as excinfo:
        _resolve("SELECT ROW_NUMBER() OVER (ORDER BY SUM(view_count)) AS n FROM @example")
    assert excinfo.value.reason == "unsupported-window-aggregate-query"


def test_predicate_only_query_rejects_window_functions() -> None:
    with pytest.raises(QuerySemanticError) as excinfo:
        _resolve("ROW_NUMBER() OVER (ORDER BY id) = 1")
    assert excinfo.value.reason == "invalid-window-placement"


def test_duplicate_window_output_names_are_rejected() -> None:
    with pytest.raises(QuerySemanticError) as excinfo:
        _resolve("SELECT ROW_NUMBER() OVER (ORDER BY id), ROW_NUMBER() OVER (ORDER BY id) FROM @example")
    assert "Duplicate SELECT output name" in excinfo.value.message


def test_position_and_window_projections_coexist() -> None:
    resolved = _resolve(
        "SELECT POSITION() AS position, ROW_NUMBER() OVER (ORDER BY id ASC) AS n, id FROM @example ORDER BY id ASC"
    )
    assert resolved.select[0].kind == "integer"
    assert resolved.select[1].kind == "integer"


# ---------------------------------------------------------------------------
# Evaluation


def test_window_numbering_survives_a_reordering_final_order_by() -> None:
    rows = _apply(BASE + " ORDER BY title ASC", _EVAL_RECORDS)
    assert [(row["n"], row["id"]) for row in rows] == [(1, "a"), (2, "b"), (3, "c"), (4, "d")]


def test_window_numbering_without_a_final_order_by() -> None:
    rows = _apply(BASE, _EVAL_RECORDS)
    numbers = {row["id"]: row["n"] for row in rows}
    assert numbers == {"a": 1, "b": 2, "c": 3, "d": 4}


def test_where_filtering_precedes_window_numbering() -> None:
    rows = _apply("SELECT ROW_NUMBER() OVER (ORDER BY id ASC) AS n, id FROM @example WHERE id != 'c'", _EVAL_RECORDS)
    numbers = {row["id"]: row["n"] for row in rows}
    assert numbers == {"a": 1, "b": 2, "d": 3}


def test_partition_keys_group_by_exact_equality_including_nulls() -> None:
    records = (
        {"id": "a", "upload_date": "2026-01-01", "view_count": 7},
        {"id": "b", "upload_date": "2026-01-01", "view_count": 7},
        {"id": "c", "upload_date": "2026-01-02", "view_count": 7},
        {"id": "d", "upload_date": None, "view_count": 7},
        {"id": "e", "upload_date": None, "view_count": 7},
    )
    sql = "SELECT ROW_NUMBER() OVER (PARTITION BY upload_date ORDER BY id ASC) AS n, id, upload_date FROM @example"
    rows = _apply(sql, records)
    by_id = {row["id"]: row["n"] for row in rows}
    assert by_id == {"a": 1, "b": 2, "c": 1, "d": 1, "e": 2}


def test_window_ordering_places_nulls_last_in_both_directions() -> None:
    records = (
        {"id": "a", "upload_date": None},
        {"id": "b", "upload_date": "2026-01-02"},
        {"id": "c", "upload_date": "2026-01-01"},
    )
    asc = _apply("SELECT ROW_NUMBER() OVER (ORDER BY upload_date ASC, id ASC) AS n, id FROM @example", records)
    desc = _apply("SELECT ROW_NUMBER() OVER (ORDER BY upload_date DESC, id ASC) AS n, id FROM @example", records)
    assert {row["id"]: row["n"] for row in asc} == {"c": 1, "b": 2, "a": 3}
    assert {row["id"]: row["n"] for row in desc} == {"b": 1, "c": 2, "a": 3}


def test_tied_window_ordering_keys_receive_distinct_consecutive_numbers() -> None:
    """Tied numbering is unspecified language behaviour; only the 1..n contract is normative."""
    records = tuple({"id": chr(ord("a") + index), "upload_date": "2026-01-01"} for index in range(5))
    rows = _apply("SELECT ROW_NUMBER() OVER (ORDER BY upload_date ASC) AS n, id FROM @example", records)
    assert sorted(row["n"] for row in rows) == [1, 2, 3, 4, 5]


def test_incompatible_window_ordering_values_raise_a_comparison_error() -> None:
    records = (
        {"id": "a", "upload_date": "2026-01-01"},
        {"id": "b", "upload_date": 5},
    )
    with pytest.raises(TypeError) as excinfo:
        _apply("SELECT ROW_NUMBER() OVER (ORDER BY upload_date ASC) AS n FROM @example", records)
    assert "cannot be compared" in str(excinfo.value)


def test_window_alias_orders_inside_larger_expressions() -> None:
    rows = _apply(BASE + " ORDER BY n + 0 DESC", _EVAL_RECORDS)
    assert [row["n"] for row in rows] == [4, 3, 2, 1]


def test_distinct_operates_on_numbered_rows() -> None:
    rows = _apply("SELECT DISTINCT ROW_NUMBER() OVER (ORDER BY id ASC) AS n FROM @example", _EVAL_RECORDS)
    assert sorted(row["n"] for row in rows) == [1, 2, 3, 4]


def test_slicing_applies_after_numbering() -> None:
    rows = _apply(BASE + " ORDER BY n ASC LIMIT 2 OFFSET 1", _EVAL_RECORDS)
    assert [(row["n"], row["id"]) for row in rows] == [(2, "b"), (3, "c")]


def test_empty_input_produces_no_rows() -> None:
    rows = _apply(BASE, ())
    assert rows == []


def test_position_and_window_numbering_are_independent() -> None:
    rows = _apply(
        "SELECT POSITION() AS position, ROW_NUMBER() OVER (ORDER BY id ASC) AS n, id FROM @example ORDER BY id DESC",
        _EVAL_RECORDS[:3],
    )
    assert [(row["position"], row["n"], row["id"]) for row in rows] == [(1, 3, "c"), (2, 2, "b"), (3, 1, "a")]


def test_cte_window_numbering_survives_outer_reordering() -> None:
    sql = (
        "WITH ranked AS ("
        "SELECT ROW_NUMBER() OVER (ORDER BY upload_date ASC) AS n, id, title FROM @example"
        ") "
        "SELECT n, id FROM ranked ORDER BY title ASC"
    )
    rows = _apply(sql, _EVAL_RECORDS)
    assert [(row["n"], row["id"]) for row in rows] == [(1, "a"), (2, "b"), (3, "c"), (4, "d")]


def test_derived_relation_window_numbering_is_scoped_to_the_nested_query() -> None:
    sql = "SELECT n, id FROM (SELECT ROW_NUMBER() OVER (ORDER BY id ASC) AS n, id FROM @example) AS d ORDER BY id DESC"
    rows = _apply(sql, ({"id": "b"}, {"id": "a"}, {"id": "c"}))
    assert [(row["n"], row["id"]) for row in rows] == [(3, "c"), (2, "b"), (1, "a")]


def test_union_branches_number_their_own_rows() -> None:
    sql = (
        "SELECT ROW_NUMBER() OVER (ORDER BY id ASC) AS n, id FROM @example "
        "UNION ALL "
        "SELECT ROW_NUMBER() OVER (ORDER BY id ASC) AS n, id FROM @example"
    )
    rows = _apply(sql, ({"id": "a"}, {"id": "b"}))
    assert sorted(row["n"] for row in rows) == [1, 1, 2, 2]
    assert len(rows) == 4


def test_plain_union_deduplicates_numbered_rows_independently() -> None:
    sql = (
        "SELECT ROW_NUMBER() OVER (ORDER BY id ASC) AS n, id FROM @example "
        "UNION "
        "SELECT ROW_NUMBER() OVER (ORDER BY id ASC) AS n, id FROM @example"
    )
    rows = _apply(sql, ({"id": "a"}, {"id": "b"}))
    # Each branch produces rows (1, a) and (2, b); the identical projected pairs collapse.
    assert sorted((row["n"], row["id"]) for row in rows) == [(1, "a"), (2, "b")]


def test_of_facet_projection_timing_is_not_regressed_by_windows() -> None:
    """Single-facet OF expansion keeps the documented projection-over-composed-rows behaviour."""
    records = ({"id": "a", "upload_date": "2026-01-01"}, {"id": "b", "upload_date": "2026-01-02"})
    rows = _apply("SELECT ROW_NUMBER() OVER (ORDER BY id ASC) AS n, id FROM @example OF videos", records)
    assert [(row["n"], row["id"]) for row in rows] == [(1, "a"), (2, "b")]


# ---------------------------------------------------------------------------
# Optimiser, properties and planning


def test_window_queries_are_differentially_stable() -> None:
    from yt_media_tools.optimizer import optimise_query

    sqls = (
        BASE + " ORDER BY title ASC",
        "SELECT ROW_NUMBER() OVER (PARTITION BY view_count ORDER BY id ASC) AS n, id FROM @example ORDER BY id",
        BASE + " ORDER BY n DESC LIMIT 2 OFFSET 1",
    )
    for sql in sqls:
        resolved = _resolve(sql, _EVAL_RECORDS)
        baseline = _apply(sql, _EVAL_RECORDS, relational_optimisation=False)
        for candidate in (resolved, optimise_query(resolved).query):
            for relational_optimisation in (False, True):
                assert _apply(sql, _EVAL_RECORDS, relational_optimisation=relational_optimisation) == baseline


def test_optimiser_leaves_window_specifications_untouched() -> None:
    from yt_media_tools.optimizer import optimise_query
    from yt_media_tools.query_model import ScalarBinary

    resolved = _resolve("SELECT ROW_NUMBER() OVER (ORDER BY 1_000 + 1 ASC) AS n, id FROM @example")
    optimised = optimise_query(resolved).query
    specification = optimised.select[0].expression.specification
    # Canonical formatting normalises separator underscores, but the specification
    # expression itself must not be constant-folded into a literal.
    assert specification.order_by[0].field == "1000 + 1"
    assert isinstance(specification.order_by[0].expression, ScalarBinary)


def test_window_properties_are_window_stage_with_specification_requirements() -> None:
    from yt_media_tools.query_properties import METADATA_NONE, STAGE_WINDOW, analyse_expression

    resolved = _resolve(BASE)
    properties = analyse_expression(resolved.select[0].expression)
    assert properties.earliest_stage == STAGE_WINDOW
    assert properties.metadata_depth == METADATA_NONE
    assert not properties.constant
    assert not properties.deterministic
    assert properties.required_fields == frozenset({"upload_date"})


def test_required_query_fields_include_window_specification_fields() -> None:
    from yt_media_tools.query_properties import required_query_fields

    resolved = _resolve(
        "SELECT ROW_NUMBER() OVER (PARTITION BY view_count ORDER BY upload_date DESC) AS n, id FROM @example"
    )
    assert required_query_fields(resolved) == {"id", "upload_date", "view_count"}


def test_window_functions_disable_source_prefix_early_limit() -> None:
    from yt_media_tools.planner import plan_limit_termination

    resolved = _resolve(BASE + " LIMIT 2 OFFSET 3")
    plan = plan_limit_termination(resolved)
    assert not plan.eligible
    assert plan.required_matches == 5
    assert "window functions" in plan.reason


def test_human_explain_reports_window_evaluation() -> None:
    from yt_media_tools.discover_explain import explain_user_query

    output = explain_user_query(
        BASE + " LIMIT 5",
        source_type="auto",
        tab="all",
        date_format="ymd",
    )
    assert "Window evaluation: ROW_NUMBER() OVER (ORDER BY upload_date ASC)" in output
    assert "window functions require complete input numbering" in output
