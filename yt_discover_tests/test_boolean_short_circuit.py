"""Observable left-to-right Boolean evaluation semantics."""

from __future__ import annotations

import pytest

from yt_media_tools.optimizer import _optimise_node
from yt_media_tools.query_evaluator import EvaluationContext, _evaluate_boolean_expression, _evaluate_having
from yt_media_tools.query_model import (
    Binary,
    CollectionElementReference,
    CollectionPredicate,
    Literal,
    RelationField,
    ScalarComparison,
    ScalarFunction,
)


class _MustNotEvaluate:
    """Sentinel expression whose evaluation reaches the unsupported-node assertion."""


def _literal(value: bool | None) -> Literal:
    """Build a Boolean/UNKNOWN literal for direct evaluator contract tests."""
    if value is None:
        return Literal(None, "NULL")
    return Literal(value, "TRUE" if value else "FALSE")


@pytest.mark.parametrize(
    ("operator", "left", "right", "expected"),
    [
        ("AND", True, True, True),
        ("AND", True, False, False),
        ("AND", True, None, None),
        ("AND", False, True, False),
        ("AND", False, False, False),
        ("AND", False, None, False),
        ("AND", None, True, None),
        ("AND", None, False, False),
        ("AND", None, None, None),
        ("OR", True, True, True),
        ("OR", True, False, True),
        ("OR", True, None, True),
        ("OR", False, True, True),
        ("OR", False, False, False),
        ("OR", False, None, None),
        ("OR", None, True, True),
        ("OR", None, False, None),
        ("OR", None, None, None),
    ],
)
def test_boolean_truth_table(operator: str, left: bool | None, right: bool | None, expected: bool | None) -> None:
    node = Binary(operator, _literal(left), _literal(right))
    assert _evaluate_boolean_expression(node, {}) is expected
    assert _evaluate_boolean_expression(node, EvaluationContext({})) is expected


def test_and_false_does_not_evaluate_right_operand() -> None:
    node = Binary("AND", Literal(False, "FALSE"), _MustNotEvaluate())
    assert _evaluate_boolean_expression(node, EvaluationContext({})) is False


def test_or_true_does_not_evaluate_right_operand() -> None:
    node = Binary("OR", Literal(True, "TRUE"), _MustNotEvaluate())
    assert _evaluate_boolean_expression(node, EvaluationContext({})) is True


@pytest.mark.parametrize("left", [True, None])
def test_and_non_dominating_left_operand_still_evaluates_right(left: bool | None) -> None:
    node = Binary("AND", _literal(left), _MustNotEvaluate())
    with pytest.raises(AssertionError):
        _evaluate_boolean_expression(node, EvaluationContext({}))


@pytest.mark.parametrize("left", [False, None])
def test_or_non_dominating_left_operand_still_evaluates_right(left: bool | None) -> None:
    node = Binary("OR", _literal(left), _MustNotEvaluate())
    with pytest.raises(AssertionError):
        _evaluate_boolean_expression(node, EvaluationContext({}))


def test_having_uses_the_same_short_circuit_contract() -> None:
    assert _evaluate_having(Binary("AND", Literal(False, "FALSE"), _MustNotEvaluate()), ({},)) is False
    assert _evaluate_having(Binary("OR", Literal(True, "TRUE"), _MustNotEvaluate()), ({},)) is True


@pytest.mark.parametrize(
    ("operator", "left", "right", "expected"),
    [
        ("AND", True, True, True),
        ("AND", True, False, False),
        ("AND", True, None, None),
        ("AND", False, True, False),
        ("AND", False, False, False),
        ("AND", False, None, False),
        ("AND", None, True, None),
        ("AND", None, False, False),
        ("AND", None, None, None),
        ("OR", True, True, True),
        ("OR", True, False, True),
        ("OR", True, None, True),
        ("OR", False, True, True),
        ("OR", False, False, False),
        ("OR", False, None, None),
        ("OR", None, True, True),
        ("OR", None, False, None),
        ("OR", None, None, None),
    ],
)
def test_having_boolean_truth_table(
    operator: str, left: bool | None, right: bool | None, expected: bool | None
) -> None:
    node = Binary(operator, _literal(left), _literal(right))
    assert _evaluate_having(node, ({},)) is expected


def test_join_relation_context_uses_the_same_short_circuit_contract() -> None:
    predicate = Binary(
        "OR",
        ScalarComparison("=", RelationField("right", "id"), Literal("match", "'match'")),
        _MustNotEvaluate(),
    )
    context = EvaluationContext(
        {"id": "left"},
        relation_records={"left": {"id": "left"}, "right": {"id": "match"}},
    )
    assert _evaluate_boolean_expression(predicate, context) is True


def test_any_stops_after_first_true_element_without_evaluating_later_elements() -> None:
    element = CollectionElementReference("item")
    predicate = CollectionPredicate(
        "ANY",
        Literal([1, 2], "[1, 2]"),
        "item",
        Binary(
            "OR",
            ScalarComparison("=", element, Literal(1, "1")),
            _MustNotEvaluate(),
        ),
    )
    assert _evaluate_boolean_expression(predicate, {}) is True


def test_all_stops_after_first_false_element_without_evaluating_later_elements() -> None:
    element = CollectionElementReference("item")
    predicate = CollectionPredicate(
        "ALL",
        Literal([1, 2], "[1, 2]"),
        "item",
        Binary(
            "AND",
            ScalarComparison("!=", element, Literal(1, "1")),
            _MustNotEvaluate(),
        ),
    )
    assert _evaluate_boolean_expression(predicate, {}) is False


def test_optimizer_may_eliminate_only_a_dominating_left_branch() -> None:
    observable = ScalarComparison(">", ScalarFunction("RANDOM", ()), Literal(0.5, "0.5"))
    left, _ = _optimise_node(Binary("AND", Literal(False, "FALSE"), observable))
    right, _ = _optimise_node(Binary("AND", observable, Literal(False, "FALSE")))
    assert left == Literal(False, "FALSE")
    assert isinstance(right, Binary) and right.left == observable


def test_optimizer_does_not_use_a_dominating_right_value_to_skip_left() -> None:
    observable_left = ScalarComparison(">", ScalarFunction("RANDOM", ()), Literal(0.5, "0.5"))
    result, _ = _optimise_node(Binary("OR", observable_left, Literal(True, "TRUE")))
    assert isinstance(result, Binary) and result.left == observable_left


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        (Binary("OR", Binary("AND", Literal(False, "FALSE"), _MustNotEvaluate()), Literal(True, "TRUE")), True),
        (Binary("AND", Binary("OR", Literal(True, "TRUE"), _MustNotEvaluate()), Literal(False, "FALSE")), False),
        (Binary("AND", Literal(None, "NULL"), Binary("OR", Literal(True, "TRUE"), _MustNotEvaluate())), None),
        (Binary("OR", Literal(None, "NULL"), Binary("AND", Literal(False, "FALSE"), _MustNotEvaluate())), None),
    ],
)
def test_nested_boolean_reachability_is_compositional(node: Binary, expected: bool | None) -> None:
    assert _evaluate_boolean_expression(node, EvaluationContext({})) is expected


@pytest.mark.parametrize(
    "node",
    [
        Binary("AND", Literal(True, "TRUE"), _MustNotEvaluate()),
        Binary("OR", Literal(False, "FALSE"), _MustNotEvaluate()),
        Binary("AND", Literal(None, "NULL"), _MustNotEvaluate()),
        Binary("OR", Literal(None, "NULL"), _MustNotEvaluate()),
    ],
)
def test_nested_contract_does_not_hide_reachable_failures(node: Binary) -> None:
    wrapped = Binary("AND", Literal(True, "TRUE"), node)
    with pytest.raises(AssertionError):
        _evaluate_boolean_expression(wrapped, EvaluationContext({}))


def test_having_nested_short_circuit_skips_unreachable_failure() -> None:
    node = Binary(
        "OR",
        Binary("AND", Literal(False, "FALSE"), _MustNotEvaluate()),
        Literal(True, "TRUE"),
    )
    assert _evaluate_having(node, ({},)) is True


def test_join_context_nested_short_circuit_skips_unreachable_failure() -> None:
    predicate = Binary(
        "AND",
        ScalarComparison("=", RelationField("left", "id"), Literal("keep", "'keep'")),
        Binary("OR", Literal(True, "TRUE"), _MustNotEvaluate()),
    )
    context = EvaluationContext(
        {"id": "keep"},
        relation_records={"left": {"id": "keep"}, "right": {"id": "other"}},
    )
    assert _evaluate_boolean_expression(predicate, context) is True


def test_collection_predicate_nested_short_circuit_skips_unreachable_failure() -> None:
    element = CollectionElementReference("item")
    predicate = CollectionPredicate(
        "ANY",
        Literal([1, 2], "[1, 2]"),
        "item",
        Binary(
            "AND",
            ScalarComparison("=", element, Literal(1, "1")),
            Binary("OR", Literal(True, "TRUE"), _MustNotEvaluate()),
        ),
    )
    assert _evaluate_boolean_expression(predicate, {}) is True


def test_optimiser_preserves_nested_reachable_volatile_left_operand() -> None:
    volatile = ScalarComparison(">", ScalarFunction("RANDOM", ()), Literal(0.5, "0.5"))
    node = Binary("OR", Binary("AND", volatile, Literal(False, "FALSE")), Literal(True, "TRUE"))
    result, _ = _optimise_node(node)
    assert isinstance(result, Binary)
    assert result.operator == "OR"
    assert isinstance(result.left, Binary)
    assert result.left.left == volatile


def test_optimiser_can_drop_nested_unreachable_volatile_right_operand() -> None:
    volatile = ScalarComparison(">", ScalarFunction("RANDOM", ()), Literal(0.5, "0.5"))
    node = Binary("OR", Binary("AND", Literal(False, "FALSE"), volatile), Literal(True, "TRUE"))
    result, _ = _optimise_node(node)
    assert result == Literal(True, "TRUE")
