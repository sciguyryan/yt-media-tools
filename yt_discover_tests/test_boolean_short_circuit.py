"""Left-to-right Boolean short-circuit semantics."""

from __future__ import annotations

import pytest

from yt_media_tools.optimizer import _optimise_node
from yt_media_tools.query_evaluator import EvaluationContext, _evaluate_boolean_expression, _evaluate_having
from yt_media_tools.query_model import Binary, Literal, ScalarComparison, ScalarFunction


class _MustNotEvaluate:
    """Sentinel expression whose evaluation would hit the evaluator's unsupported-node assertion."""


def test_and_false_does_not_evaluate_right_operand() -> None:
    node = Binary("AND", Literal(False, "FALSE"), _MustNotEvaluate())
    assert _evaluate_boolean_expression(node, EvaluationContext({})) is False


def test_or_true_does_not_evaluate_right_operand() -> None:
    node = Binary("OR", Literal(True, "TRUE"), _MustNotEvaluate())
    assert _evaluate_boolean_expression(node, EvaluationContext({})) is True


@pytest.mark.parametrize("left", [True, None])
def test_and_non_dominating_left_operand_still_evaluates_right(left: bool | None) -> None:
    node = Binary("AND", Literal(left, "NULL" if left is None else "TRUE"), _MustNotEvaluate())
    with pytest.raises(AssertionError):
        _evaluate_boolean_expression(node, EvaluationContext({}))


@pytest.mark.parametrize("left", [False, None])
def test_or_non_dominating_left_operand_still_evaluates_right(left: bool | None) -> None:
    node = Binary("OR", Literal(left, "NULL" if left is None else "FALSE"), _MustNotEvaluate())
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
