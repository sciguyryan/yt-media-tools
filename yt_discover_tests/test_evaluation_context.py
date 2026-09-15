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
