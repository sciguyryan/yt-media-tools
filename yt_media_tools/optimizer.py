"""Semantics-preserving optimisation for resolved yt-sql queries."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .query import (
    AggregateFunction,
    Between,
    Binary,
    CaseWhen,
    InList,
    IsNull,
    Literal,
    Query,
    ScalarBinary,
    ScalarCase,
    ScalarComparison,
    ScalarFunction,
    ScalarIsNull,
    ScalarUnary,
    TextPredicate,
    Unary,
    evaluate_scalar_expression,
    format_expression,
    format_scalar_expression,
)
from .optimizer_proofs import (
    TRUTH_FALSE,
    TRUTH_TRUE,
    TRUTH_UNKNOWN,
    OptimisationProof,
    prove_expression_constant,
    prove_expression_deterministic,
    prove_predicate_truth,
)
from .query_semantics import same_field as _same_field
from .query_semantics import semantic_key as _semantic_key
from .source_model import SourceSpec

MAX_OPTIMISER_PASSES = 32
_INVERTED_COMPARISON = {
    "=": "!=",
    "!=": "=",
    "<": ">=",
    "<=": ">",
    ">": "<=",
    ">=": "<",
}
_LOWER_BOUND_OPERATORS = {">", ">="}
_UPPER_BOUND_OPERATORS = {"<", "<="}


@dataclass(frozen=True)
class OptimisationDecision:
    """One deterministic, semantics-preserving optimiser rewrite."""

    rule: str
    before: str
    after: str
    proofs: tuple[OptimisationProof, ...] = ()


@dataclass(frozen=True)
class OptimisationResult:
    """The optimised query and an ordered audit trail of rewrites."""

    query: Query
    decisions: tuple[OptimisationDecision, ...]

    @property
    def changed(self) -> bool:
        return bool(self.decisions)


def optimise_query(query: Query, *, source: SourceSpec | None = None) -> OptimisationResult:
    """Optimise a resolved query without changing its observable semantics.

    The optimiser deliberately works after semantic resolution so comparisons operate
    on typed literals rather than parser text. Rewrites must preserve yt-sql's SQL-like
    three-valued logic, including UNKNOWN results caused by NULL values.
    """

    decisions: list[OptimisationDecision] = []
    optimised_ctes = []
    for cte in query.ctes:
        cte_result = optimise_query(cte.query)
        optimised_ctes.append(replace(cte, query=cte_result.query))
        decisions.extend(
            OptimisationDecision(f"cte-{cte.name}-{item.rule}", item.before, item.after, item.proofs)
            for item in cte_result.decisions
        )

    optimised_set_operations = []
    for index, operation in enumerate(query.set_operations, start=1):
        branch_result = optimise_query(operation.query)
        optimised_set_operations.append(replace(operation, query=branch_result.query))
        decisions.extend(
            OptimisationDecision(f"union-{index}-{item.rule}", item.before, item.after, item.proofs)
            for item in branch_result.decisions
        )

    predicate, predicate_decisions = _optimise_predicate_fixed_point(query.predicate, source=source)
    decisions.extend(predicate_decisions)

    select_terms = []
    for term in query.select:
        expression, expression_decisions = _optimise_scalar_expression(term.expression, source=source)
        decisions.extend(expression_decisions)
        select_terms.append(
            replace(term, field=format_scalar_expression(expression), expression=expression)
            if term.expression is not None
            else term
        )

    group_by = []
    for expression in query.group_by:
        optimised, expression_decisions = _optimise_scalar_expression(expression, source=source)
        decisions.extend(expression_decisions)
        group_by.append(optimised)

    having, having_decisions = _optimise_having(query.having, source=source)
    decisions.extend(having_decisions)

    order_terms = []
    for term in query.order_by:
        expression, expression_decisions = _optimise_scalar_expression(term.expression, source=source)
        decisions.extend(expression_decisions)
        order_terms.append(
            replace(term, field=format_scalar_expression(expression), expression=expression)
            if term.expression is not None
            else term
        )

    return OptimisationResult(
        replace(
            query,
            predicate=predicate,
            select=tuple(select_terms),
            order_by=tuple(order_terms),
            group_by=tuple(group_by),
            having=having,
            ctes=tuple(optimised_ctes),
            set_operations=tuple(optimised_set_operations),
        ),
        tuple(decisions),
    )


def _optimise_having(node: Any, *, source: SourceSpec | None = None) -> tuple[Any, list[OptimisationDecision]]:
    """Optimise scalar subexpressions in HAVING without changing its Boolean semantics."""
    if node is None:
        return None, []
    if source is not None:
        truth = prove_predicate_truth(node, source=source)
        if truth.proven and truth.truth is not None:
            value = {TRUTH_TRUE: True, TRUTH_FALSE: False, TRUTH_UNKNOWN: None}[truth.truth]
            literal = Literal(value, "NULL" if value is None else ("TRUE" if value else "FALSE"))
            if literal != node:
                return literal, [
                    _decision(
                        "capability-constant-having",
                        node,
                        literal,
                        proofs=(truth.proof,),
                    )
                ]
    if isinstance(node, Unary):
        operand, decisions = _optimise_having(node.operand, source=source)
        optimised = replace(node, operand=operand)
        if isinstance(operand, Unary):
            decisions.append(_decision("having-double-negation", optimised, operand.operand))
            return operand.operand, decisions
        return optimised, decisions
    if isinstance(node, Binary) and node.operator in {"AND", "OR"}:
        left, left_decisions = _optimise_having(node.left, source=source)
        right, right_decisions = _optimise_having(node.right, source=source)
        decisions = left_decisions + right_decisions
        optimised = replace(node, left=left, right=right)
        if _semantic_key(left) == _semantic_key(right):
            decisions.append(_decision(f"having-duplicate-{node.operator.lower()}", optimised, left))
            return left, decisions
        return optimised, decisions
    if isinstance(node, ScalarComparison):
        left, left_decisions = _optimise_scalar_expression(node.left, source=source)
        right, right_decisions = _optimise_scalar_expression(node.right, source=source)
        return replace(node, left=left, right=right), left_decisions + right_decisions
    if isinstance(node, ScalarIsNull):
        expression, decisions = _optimise_scalar_expression(node.expression, source=source)
        return replace(node, expression=expression), decisions
    return node, []


def _optimise_predicate_fixed_point(
    node: Any, *, source: SourceSpec | None = None
) -> tuple[Any, list[OptimisationDecision]]:
    """Optimise one predicate tree to convergence with the ordinary pass limit."""
    predicate = node
    decisions: list[OptimisationDecision] = []
    for _ in range(MAX_OPTIMISER_PASSES):
        optimised, pass_decisions = _optimise_node(predicate, source=source)
        decisions.extend(pass_decisions)
        if optimised == predicate:
            return predicate, decisions
        predicate = optimised
    raise RuntimeError("yt-sql optimiser did not converge")


def _optimise_scalar_expression(
    expression: Any, *, source: SourceSpec | None = None
) -> tuple[Any, list[OptimisationDecision]]:
    """Optimise a resolved scalar expression without changing observable semantics.

    Constant folding is deliberately limited to subtrees whose inputs are all
    literals. Symbolic algebra such as ``field * 0 -> 0`` is not performed because
    field values can be NULL and future scalar kinds may have additional semantics.
    """
    if expression is None:
        return None, []
    if isinstance(expression, ScalarUnary):
        operand, decisions = _optimise_scalar_expression(expression.operand, source=source)
        optimised = replace(expression, operand=operand)
        if isinstance(operand, Literal):
            folded = _fold_constant_scalar(optimised)
            decisions.append(_scalar_decision("fold-constant-unary", optimised, folded))
            return folded, decisions
        return optimised, decisions
    if isinstance(expression, ScalarBinary):
        left, left_decisions = _optimise_scalar_expression(expression.left, source=source)
        right, right_decisions = _optimise_scalar_expression(expression.right, source=source)
        decisions = left_decisions + right_decisions
        optimised = replace(expression, left=left, right=right)
        if isinstance(left, Literal) and isinstance(right, Literal):
            folded = _fold_constant_scalar(optimised)
            decisions.append(_scalar_decision("fold-constant-arithmetic", optimised, folded))
            return folded, decisions
        return optimised, decisions
    if isinstance(expression, AggregateFunction):
        args = []
        decisions: list[OptimisationDecision] = []
        for arg in expression.args:
            optimised, arg_decisions = _optimise_scalar_expression(arg, source=source)
            args.append(optimised)
            decisions.extend(arg_decisions)
        filter_predicate, filter_decisions = _optimise_predicate_fixed_point(expression.filter_predicate, source=source)
        decisions.extend(
            OptimisationDecision(f"aggregate-filter-{decision.rule}", decision.before, decision.after, decision.proofs)
            for decision in filter_decisions
        )
        return replace(expression, args=tuple(args), filter_predicate=filter_predicate), decisions
    if isinstance(expression, ScalarFunction):
        args = []
        decisions: list[OptimisationDecision] = []
        for arg in expression.args:
            optimised, arg_decisions = _optimise_scalar_expression(arg, source=source)
            args.append(optimised)
            decisions.extend(arg_decisions)
        optimised = replace(expression, args=tuple(args))
        if optimised.name == "RANDOM":
            return optimised, decisions
        if all(isinstance(arg, Literal) for arg in optimised.args):
            folded = _fold_constant_scalar(optimised)
            decisions.append(_scalar_decision("fold-constant-function", optimised, folded))
            return folded, decisions
        return optimised, decisions
    if isinstance(expression, ScalarCase):
        branches = []
        decisions: list[OptimisationDecision] = []
        for branch in expression.whens:
            condition, condition_decisions = _optimise_predicate_fixed_point(branch.condition, source=source)
            for decision in condition_decisions:
                decisions.append(
                    OptimisationDecision(
                        f"case-when-{decision.rule}",
                        decision.before,
                        decision.after,
                        decision.proofs,
                    )
                )
            result, result_decisions = _optimise_scalar_expression(branch.result, source=source)
            decisions.extend(result_decisions)
            branches.append(CaseWhen(condition, result, branch.position))
        else_result, else_decisions = _optimise_scalar_expression(expression.else_result, source=source)
        decisions.extend(else_decisions)
        optimised = replace(expression, whens=tuple(branches), else_result=else_result)
        return optimised, decisions
    return expression, []


def _fold_constant_scalar(expression: Any) -> Literal:
    """Evaluate a fully literal scalar subtree once and retain it as a literal."""
    value = evaluate_scalar_expression(expression, {})
    position = getattr(expression, "position", 0)
    return Literal(value, _literal_raw(value), position, isinstance(value, str))


def _literal_raw(value: Any) -> str:
    """Return canonical yt-sql source text for a folded literal value."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return repr(value)


def _scalar_decision(rule: str, before: Any, after: Any) -> OptimisationDecision:
    proof = prove_expression_constant(before)
    if not proof.proven:
        raise AssertionError(f"Constant-fold rule {rule} lacks a constant-expression proof")
    return OptimisationDecision(
        rule,
        format_scalar_expression(before),
        format_scalar_expression(after),
        (proof,),
    )


def _optimise_node(node: Any, *, source: SourceSpec | None = None) -> tuple[Any, list[OptimisationDecision]]:
    decisions: list[OptimisationDecision] = []
    if node is None:
        return None, decisions

    if source is not None:
        truth = prove_predicate_truth(node, source=source)
        if truth.proven and truth.truth is not None:
            value = {TRUTH_TRUE: True, TRUTH_FALSE: False, TRUTH_UNKNOWN: None}[truth.truth]
            literal = Literal(value, "NULL" if value is None else ("TRUE" if value else "FALSE"))
            if literal != node:
                decisions.append(
                    _decision(
                        "capability-constant-predicate",
                        node,
                        literal,
                        proofs=(truth.proof,),
                    )
                )
                return literal, decisions

    if isinstance(node, Unary) and node.operator == "NOT":
        operand, child_decisions = _optimise_node(node.operand, source=source)
        decisions.extend(child_decisions)
        rewritten = _normalise_not(operand)
        if rewritten != Unary("NOT", operand):
            decisions.append(_decision("normalise-not", Unary("NOT", operand), rewritten))
            return rewritten, decisions
        return Unary("NOT", operand), decisions

    if isinstance(node, Binary) and node.operator in {"AND", "OR"}:
        left, left_decisions = _optimise_node(node.left, source=source)
        right, right_decisions = _optimise_node(node.right, source=source)
        decisions.extend(left_decisions)
        decisions.extend(right_decisions)
        operator = node.operator
        if isinstance(left, Literal) and (left.value is None or isinstance(left.value, bool)):
            if operator == "AND" and left.value is False:
                decisions.append(_decision("constant-and-false", Binary(operator, left, right), left))
                return left, decisions
            if operator == "OR" and left.value is True:
                decisions.append(_decision("constant-or-true", Binary(operator, left, right), left))
                return left, decisions
            if left.value is True and operator == "AND":
                decisions.append(_decision("constant-and-true", Binary(operator, left, right), right))
                return right, decisions
            if left.value is False and operator == "OR":
                decisions.append(_decision("constant-or-false", Binary(operator, left, right), right))
                return right, decisions
        if isinstance(right, Literal) and (right.value is None or isinstance(right.value, bool)):
            if operator == "AND" and right.value is False:
                decisions.append(_decision("constant-and-false", Binary(operator, left, right), right))
                return right, decisions
            if operator == "OR" and right.value is True:
                decisions.append(_decision("constant-or-true", Binary(operator, left, right), right))
                return right, decisions
            if right.value is True and operator == "AND":
                decisions.append(_decision("constant-and-true", Binary(operator, left, right), left))
                return left, decisions
            if right.value is False and operator == "OR":
                decisions.append(_decision("constant-or-false", Binary(operator, left, right), left))
                return left, decisions
        operator = node.operator
        terms = _flatten(operator, Binary(operator, left, right))
        terms, dedupe_decisions = _deduplicate_terms(operator, terms)
        decisions.extend(dedupe_decisions)
        terms, membership_decisions = _simplify_memberships(operator, terms)
        decisions.extend(membership_decisions)
        terms, bound_decisions = _simplify_bounds(operator, terms)
        decisions.extend(bound_decisions)
        rebuilt = _rebuild(operator, terms)
        return rebuilt, decisions

    if isinstance(node, Between) and node.lower.value == node.upper.value:
        rewritten = Binary("!=" if node.negated else "=", node.field, node.lower)
        decisions.append(_decision("collapse-degenerate-between", node, rewritten))
        return rewritten, decisions

    if isinstance(node, InList):
        values: list[Any] = []
        seen: set[Any] = set()
        for value in node.values:
            key = _semantic_key(value)
            if key in seen:
                continue
            seen.add(key)
            values.append(value)
        normalised = replace(node, values=tuple(values))
        if normalised != node:
            decisions.append(_decision("deduplicate-in-values", node, normalised))
        if len(normalised.values) == 1:
            rewritten = Binary("!=" if normalised.negated else "=", normalised.field, normalised.values[0])
            decisions.append(_decision("collapse-singleton-in", normalised, rewritten))
            return rewritten, decisions
        return normalised, decisions

    return node, decisions


def _normalise_not(node: Any) -> Any:
    if isinstance(node, Unary) and node.operator == "NOT":
        return node.operand
    if isinstance(node, Binary) and node.operator in _INVERTED_COMPARISON:
        return Binary(_INVERTED_COMPARISON[node.operator], node.left, node.right)
    if isinstance(node, Between):
        return replace(node, negated=not node.negated)
    if isinstance(node, InList):
        return replace(node, negated=not node.negated)
    if isinstance(node, IsNull):
        return replace(node, negated=not node.negated)
    if isinstance(node, TextPredicate):
        return replace(node, negated=not node.negated)
    return Unary("NOT", node)


def _flatten(operator: str, node: Any) -> list[Any]:
    if isinstance(node, Binary) and node.operator == operator:
        return _flatten(operator, node.left) + _flatten(operator, node.right)
    return [node]


def _rebuild(operator: str, terms: list[Any]) -> Any:
    if not terms:
        raise AssertionError("Boolean optimiser cannot rebuild an empty term list")
    node = terms[0]
    for term in terms[1:]:
        node = Binary(operator, node, term)
    return node


def _deduplicate_terms(operator: str, terms: list[Any]) -> tuple[list[Any], list[OptimisationDecision]]:
    unique: list[Any] = []
    decisions: list[OptimisationDecision] = []
    for term in terms:
        duplicate = next(
            (existing for existing in unique if _semantic_key(term) == _semantic_key(existing)),
            None,
        )
        if duplicate is not None:
            proof = prove_expression_deterministic(term)
            if proof.proven:
                decisions.append(
                    _decision(
                        f"deduplicate-{operator.casefold()}",
                        Binary(operator, term, duplicate),
                        term,
                        proofs=(proof,),
                    )
                )
                continue
        unique.append(term)
    return unique, decisions


def _simplify_memberships(operator: str, terms: list[Any]) -> tuple[list[Any], list[OptimisationDecision]]:
    """Remove same-field membership predicates that are provably subsumed.

    The rule is deliberately limited to non-negated IN predicates and exact resolved
    literal identities. It therefore preserves NULL/UNKNOWN behaviour and avoids
    assuming any field-specific case-folding semantics.
    """
    terms = list(terms)
    decisions: list[OptimisationDecision] = []
    changed = True
    while changed:
        changed = False
        for left_index in range(len(terms)):
            for right_index in range(left_index + 1, len(terms)):
                left = terms[left_index]
                right = terms[right_index]
                keep: int | None = None

                if isinstance(left, InList) and isinstance(right, InList):
                    if left.negated or right.negated or not _same_field(left.field, right.field):
                        continue
                    left_values = {_semantic_key(value) for value in left.values}
                    right_values = {_semantic_key(value) for value in right.values}
                    if left_values <= right_values:
                        keep = left_index if operator == "AND" else right_index
                    elif right_values <= left_values:
                        keep = right_index if operator == "AND" else left_index

                elif isinstance(left, InList) or isinstance(right, InList):
                    membership_index = left_index if isinstance(left, InList) else right_index
                    comparison_index = right_index if membership_index == left_index else left_index
                    membership = terms[membership_index]
                    comparison = terms[comparison_index]
                    if (
                        membership.negated
                        or not isinstance(comparison, Binary)
                        or comparison.operator != "="
                        or not _same_field(membership.field, comparison.left)
                    ):
                        continue
                    values = {_semantic_key(value) for value in membership.values}
                    if _semantic_key(comparison.right) in values:
                        keep = comparison_index if operator == "AND" else membership_index

                if keep is None:
                    continue
                drop = right_index if keep == left_index else left_index
                before = Binary(operator, left, right)
                kept = terms[keep]
                decisions.append(_decision(f"subsumed-{operator.casefold()}-membership", before, kept))
                del terms[drop]
                changed = True
                break
            if changed:
                break
    return terms, decisions


def _simplify_bounds(operator: str, terms: list[Any]) -> tuple[list[Any], list[OptimisationDecision]]:
    terms = list(terms)
    decisions: list[OptimisationDecision] = []
    changed = True
    while changed:
        changed = False
        for left_index in range(len(terms)):
            for right_index in range(left_index + 1, len(terms)):
                dominant = _dominant_comparison(operator, terms[left_index], terms[right_index])
                if dominant is None:
                    continue
                keep_index, drop_index = dominant
                before = Binary(operator, terms[left_index], terms[right_index])
                kept = terms[left_index] if keep_index == 0 else terms[right_index]
                decisions.append(_decision(f"subsumed-{operator.casefold()}-predicate", before, kept))
                actual_drop = left_index if drop_index == 0 else right_index
                del terms[actual_drop]
                changed = True
                break
            if changed:
                break
    return terms, decisions


def _dominant_comparison(operator: str, left: Any, right: Any) -> tuple[int, int] | None:
    if not isinstance(left, Binary) or not isinstance(right, Binary):
        return None
    if left.operator in {"AND", "OR"} or right.operator in {"AND", "OR"}:
        return None
    if not _same_field(left.left, right.left):
        return None

    left_value = getattr(left.right, "value", None)
    right_value = getattr(right.right, "value", None)
    if left_value is None or right_value is None:
        return None

    if left.operator in _LOWER_BOUND_OPERATORS and right.operator in _LOWER_BOUND_OPERATORS:
        comparison = _safe_compare(left_value, right_value)
        if comparison is None:
            return None
        if operator == "AND":
            return _select_lower_bound(left, right, comparison, stronger=True)
        return _select_lower_bound(left, right, comparison, stronger=False)

    if left.operator in _UPPER_BOUND_OPERATORS and right.operator in _UPPER_BOUND_OPERATORS:
        comparison = _safe_compare(left_value, right_value)
        if comparison is None:
            return None
        if operator == "AND":
            return _select_upper_bound(left, right, comparison, stronger=True)
        return _select_upper_bound(left, right, comparison, stronger=False)

    if left.operator == "=" or right.operator == "=":
        equality_index = 0 if left.operator == "=" else 1
        equality = left if equality_index == 0 else right
        bound = right if equality_index == 0 else left
        if bound.operator not in _LOWER_BOUND_OPERATORS | _UPPER_BOUND_OPERATORS:
            return None
        if not _comparison_is_true(equality.right.value, bound.operator, bound.right.value):
            return None
        if operator == "AND":
            return equality_index, 1 - equality_index
        return 1 - equality_index, equality_index

    return None


def _safe_compare(left: Any, right: Any) -> int | None:
    try:
        if left < right:
            return -1
        if left > right:
            return 1
        if left == right:
            return 0
    except TypeError:
        return None
    return None


def _select_lower_bound(left: Binary, right: Binary, comparison: int, *, stronger: bool) -> tuple[int, int]:
    if comparison == 0:
        if left.operator == right.operator:
            return 0, 1
        strict_index = 0 if left.operator == ">" else 1
        keep = strict_index if stronger else 1 - strict_index
        return keep, 1 - keep
    higher_index = 0 if comparison > 0 else 1
    keep = higher_index if stronger else 1 - higher_index
    return keep, 1 - keep


def _select_upper_bound(left: Binary, right: Binary, comparison: int, *, stronger: bool) -> tuple[int, int]:
    if comparison == 0:
        if left.operator == right.operator:
            return 0, 1
        strict_index = 0 if left.operator == "<" else 1
        keep = strict_index if stronger else 1 - strict_index
        return keep, 1 - keep
    lower_index = 0 if comparison < 0 else 1
    keep = lower_index if stronger else 1 - lower_index
    return keep, 1 - keep


def _comparison_is_true(left: Any, operator: str, right: Any) -> bool:
    try:
        if operator == ">":
            return left > right
        if operator == ">=":
            return left >= right
        if operator == "<":
            return left < right
        if operator == "<=":
            return left <= right
    except TypeError:
        return False
    return False


def _decision(
    rule: str,
    before: Any,
    after: Any,
    *,
    proofs: tuple[OptimisationProof, ...] = (),
) -> OptimisationDecision:
    return OptimisationDecision(rule, format_expression(before), format_expression(after), proofs)
