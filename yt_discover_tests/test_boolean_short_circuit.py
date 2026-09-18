"""Observable left-to-right Boolean evaluation semantics."""

from __future__ import annotations

import pytest

from yt_media_tools.optimizer import _optimise_node
from yt_media_tools.query_evaluator import EvaluationContext, _evaluate_boolean_expression, _evaluate_having
from yt_media_tools.query_model import Binary, Literal, ScalarComparison, ScalarFunction


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
