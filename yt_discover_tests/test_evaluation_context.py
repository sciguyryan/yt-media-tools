"""Tests for explicit yt-sql expression evaluation context."""

from yt_media_tools.query_evaluation_context import EvaluationContext
from yt_media_tools.query_evaluator import evaluate, evaluate_scalar_expression
from yt_media_tools.query_model import CollectionElementReference, Literal, ScalarComparison


def test_context_preserves_metadata_record_identity() -> None:
    record = {"id": "example"}
    context = EvaluationContext(record)
    assert context.record is record
    assert context.collection_bindings == ()


def test_nested_collection_bindings_resolve_by_lexical_distance() -> None:
    context = EvaluationContext({}).bind_collection_element("outer").bind_collection_element("inner")
    assert context.collection_element(0) == "inner"
    assert context.collection_element(1) == "outer"
    assert context.collection_element(2) is None


def test_binding_collection_element_returns_new_context() -> None:
    context = EvaluationContext({"id": "example"})
    child = context.bind_collection_element("value")
    assert context.collection_bindings == ()
    assert child.record is context.record
    assert child.collection_bindings == ("value",)


def test_scalar_evaluator_accepts_explicit_context() -> None:
    context = EvaluationContext({}).bind_collection_element("value")
    expression = CollectionElementReference(binding="item", scope_distance=0, position=0, kind="string")
    assert evaluate_scalar_expression(expression, context) == "value"


def test_boolean_evaluator_accepts_explicit_context() -> None:
    context = EvaluationContext({}).bind_collection_element("value")
    expression = ScalarComparison(
        operator="=",
        left=CollectionElementReference(binding="item", scope_distance=0, position=0, kind="string"),
        right=Literal("value", "'value'", position=0),
    )
    assert evaluate(expression, context) is True


def test_context_public_state_is_read_only() -> None:
    context = EvaluationContext({"id": "example"})
    try:
        context.record = {"id": "replacement"}  # type: ignore[misc]
    except AttributeError:
        pass
    else:
        raise AssertionError("EvaluationContext.record must be read-only")

    try:
        context.collection_bindings = ("replacement",)  # type: ignore[misc]
    except AttributeError:
        pass
    else:
        raise AssertionError("EvaluationContext.collection_bindings must be read-only")


def test_plain_record_scalar_fast_path_matches_explicit_context() -> None:
    """Plain scalar evaluation must remain equivalent to explicit context evaluation."""
    from yt_media_tools.query import evaluate_scalar_expression, parse_query, resolve_query
    from yt_media_tools.schema import QuerySchema

    record = {"view_count": 7}
    resolved = resolve_query(parse_query("SELECT COALESCE(view_count, 0) + 10 AS adjusted"), QuerySchema([record]))
    expression = resolved.select[0].expression
    assert expression is not None
    assert evaluate_scalar_expression(expression, record) == evaluate_scalar_expression(
        expression, EvaluationContext(record)
    )


def test_plain_record_collection_fast_path_matches_explicit_context() -> None:
    """Collection binding must create context lazily without changing semantics."""
    from yt_media_tools.query import evaluate_scalar_expression, parse_query, resolve_query
    from yt_media_tools.schema import QuerySchema

    record = {"tags": ["one", None, "two"]}
    source = "SELECT MAP(FILTER(tags AS tag WHERE tag IS NOT NULL) AS tag SELECT UPPER(tag)) AS tags"
    resolved = resolve_query(parse_query(source), QuerySchema([record]))
    expression = resolved.select[0].expression
    assert expression is not None
    assert evaluate_scalar_expression(expression, record) == evaluate_scalar_expression(
        expression, EvaluationContext(record)
    )
