"""Shared conservative semantic and relational provability for yt-sql.

This module is intentionally a proof layer, not an execution-policy layer. It
establishes facts from resolved and validated query expressions. Consumers such
as relation simplification and acquisition planning decide what those facts
permit. An unavailable proof is never converted into permission to optimise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .optimizer_proofs import (
    PROVEN,
    PROVENANCE_SEMANTIC_PROPERTIES,
    TRUTH_TRUE,
    OptimisationProof,
    PredicateTruthProof,
    compose_proofs,
    prove_predicate_truth,
)
from .query_model import (
    Between,
    Binary,
    Field,
    InList,
    IsNull,
    Literal,
    RelationField,
    ScalarComparison,
    ScalarIsNull,
    TextPredicate,
)
from .source_model import SourceSpec


@dataclass(frozen=True)
class JoinProvability:
    """Proven relational consequences of one validated JOIN predicate."""

    predicate_never_true: bool
    result_empty: bool
    right_relation_irrelevant: bool
    proof: OptimisationProof | None


def _proof(reason: str) -> OptimisationProof:
    return OptimisationProof(
        claim="predicate-never-true",
        status=PROVEN,
        provenance=(PROVENANCE_SEMANTIC_PROPERTIES,),
        reasons=(reason,),
    )


def _filter_rejection_proven(proof: PredicateTruthProof) -> bool:
    """Return whether SQL filtering is proven to reject every candidate row."""
    return proof.proven and proof.truth != TRUTH_TRUE


def _field_key(node: Any) -> tuple[str | None, str] | None:
    """Return stable relation identity and field name for a direct field reference."""
    if isinstance(node, RelationField):
        return node.relation_key, node.name.casefold()
    if isinstance(node, Field):
        return None, node.name.casefold()
    return None


def _literal_value(node: Any) -> Any:
    """Return a safely comparable literal value or ``NotImplemented``."""
    if not isinstance(node, Literal):
        return NotImplemented
    if node.quoted or not isinstance(node.value, str):
        return node.value
    compact = node.raw.replace("_", "")
    try:
        if compact.lower().startswith(("0x", "0o", "0b")):
            return int(compact, 0)
        if any(marker in compact.lower() for marker in (".", "e")):
            return float(compact)
        return int(compact, 10)
    except ValueError:
        return node.value


def _flatten_and(node: Any) -> tuple[Any, ...]:
    if isinstance(node, Binary) and node.operator == "AND":
        return _flatten_and(node.left) + _flatten_and(node.right)
    return (node,)


def _comparison_constraint(term: Any) -> tuple[tuple[str | None, str], str, Any] | None:
    if not isinstance(term, (Binary, ScalarComparison)) or term.operator in {"AND", "OR"}:
        return None
    field = _field_key(term.left)
    value = _literal_value(term.right)
    if field is None or value is NotImplemented or value is None:
        return None
    return field, term.operator, value


def _null_constraint(term: Any) -> tuple[tuple[str | None, str], bool] | None:
    if not isinstance(term, (IsNull, ScalarIsNull)):
        return None
    field = _field_key(term.field if isinstance(term, IsNull) else term.expression)
    return None if field is None else (field, not term.negated)


def _null_rejecting_field(term: Any) -> tuple[str | None, str] | None:
    comparison = _comparison_constraint(term)
    if comparison is not None:
        return comparison[0]
    if isinstance(term, (Between, InList, TextPredicate)):
        return _field_key(term.field)
    if isinstance(term, IsNull) and term.negated:
        return _field_key(term.field)
    if isinstance(term, ScalarIsNull) and term.negated:
        return _field_key(term.expression)
    return None


def _label(field: tuple[str | None, str]) -> str:
    relation, name = field
    return f"{relation}:{name}" if relation else name


def _stronger_lower(current: tuple[Any, bool] | None, value: Any, inclusive: bool) -> tuple[Any, bool] | None:
    if current is None:
        return value, inclusive
    try:
        if value > current[0]:
            return value, inclusive
        if value == current[0]:
            return value, current[1] and inclusive
    except TypeError:
        return current
    return current


def _stronger_upper(current: tuple[Any, bool] | None, value: Any, inclusive: bool) -> tuple[Any, bool] | None:
    if current is None:
        return value, inclusive
    try:
        if value < current[0]:
            return value, inclusive
        if value == current[0]:
            return value, current[1] and inclusive
    except TypeError:
        return current
    return current


def _prove_and_contradiction(node: Any) -> OptimisationProof | None:
    """Prove a deliberately bounded family of same-field AND contradictions."""
    terms = _flatten_and(node)
    by_field: dict[tuple[str | None, str], list[tuple[str, Any]]] = {}
    null_requirements: dict[tuple[str | None, str], set[bool]] = {}
    null_rejecting: set[tuple[str | None, str]] = set()

    for term in terms:
        comparison = _comparison_constraint(term)
        if comparison is not None:
            field, operator, value = comparison
            by_field.setdefault(field, []).append((operator, value))
        null_constraint = _null_constraint(term)
        if null_constraint is not None:
            field, requires_null = null_constraint
            null_requirements.setdefault(field, set()).add(requires_null)
        rejected = _null_rejecting_field(term)
        if rejected is not None:
            null_rejecting.add(rejected)

    for field, requirements in null_requirements.items():
        if requirements == {True, False}:
            return _proof(f"{_label(field)} cannot be both NULL and NOT NULL")
        if True in requirements and field in null_rejecting:
            return _proof(f"{_label(field)} IS NULL cannot be TRUE with a predicate that rejects NULL")

    for field, constraints in by_field.items():
        equalities = [value for operator, value in constraints if operator == "="]
        if equalities and any(value != equalities[0] for value in equalities[1:]):
            return _proof(f"{_label(field)} has incompatible equality requirements")
        lower: tuple[Any, bool] | None = None
        upper: tuple[Any, bool] | None = None
        for operator, value in constraints:
            if operator == ">":
                lower = _stronger_lower(lower, value, False)
            elif operator == ">=":
                lower = _stronger_lower(lower, value, True)
            elif operator == "<":
                upper = _stronger_upper(upper, value, False)
            elif operator == "<=":
                upper = _stronger_upper(upper, value, True)
        if equalities:
            value = equalities[0]
            try:
                if lower is not None and (value < lower[0] or (value == lower[0] and not lower[1])):
                    return _proof(f"{_label(field)} equality is incompatible with its lower bound")
                if upper is not None and (value > upper[0] or (value == upper[0] and not upper[1])):
                    return _proof(f"{_label(field)} equality is incompatible with its upper bound")
            except TypeError:
                pass
        if lower is not None and upper is not None:
            try:
                if lower[0] > upper[0] or (lower[0] == upper[0] and not (lower[1] and upper[1])):
                    return _proof(f"{_label(field)} lower and upper bounds cannot both be satisfied")
            except TypeError:
                pass
    return None


def prove_predicate_never_true(node: Any, *, source: SourceSpec | None) -> OptimisationProof | None:
    """Prove that a validated predicate cannot evaluate TRUE for any candidate row."""
    if node is None:
        return None
    truth = prove_predicate_truth(node, source=source)
    if _filter_rejection_proven(truth):
        return compose_proofs("predicate-never-true", truth.proof)
    if isinstance(node, Binary) and node.operator == "AND":
        left = prove_predicate_never_true(node.left, source=source)
        if left is not None:
            return compose_proofs("predicate-never-true", left)
        right = prove_predicate_never_true(node.right, source=source)
        if right is not None:
            return compose_proofs("predicate-never-true", right)
        return _prove_and_contradiction(node)
    return None


def prove_join_consequences(kind: str, predicate: Any, *, source: SourceSpec | None = None) -> JoinProvability:
    """Derive JOIN consequences from a shared never-TRUE predicate proof."""
    proof = prove_predicate_never_true(predicate, source=source)
    if proof is None:
        return JoinProvability(False, False, False, None)
    upper_kind = kind.upper()
    result_empty = upper_kind in {"INNER", "SEMI"}
    consequence = OptimisationProof(
        claim="join-consequence",
        status=PROVEN,
        provenance=proof.provenance,
        reasons=(f"{upper_kind} JOIN semantics consume a predicate proven never TRUE",),
        premises=(proof,),
    )
    return JoinProvability(True, result_empty, True, consequence)


def prove_boolean_right_unreachable(node: Any, *, source: SourceSpec | None) -> OptimisationProof | None:
    """Prove that left-to-right Boolean semantics make the right operand unreachable.

    This is deliberately stronger than proving the final truth value. Only a
    dominating left operand establishes reachability: FALSE for AND and TRUE
    for OR. A dominating right operand can prove a final value but cannot make
    earlier left-side evaluation disappear.
    """
    if not isinstance(node, Binary) or node.operator not in {"AND", "OR"}:
        return None
    left = prove_predicate_truth(node.left, source=source)
    if not left.proven:
        return None
    dominating = (node.operator == "AND" and left.truth == "false") or (node.operator == "OR" and left.truth == "true")
    if not dominating:
        return None
    return OptimisationProof(
        claim="boolean-right-unreachable",
        status=PROVEN,
        provenance=left.proof.provenance,
        reasons=(f"left-to-right {node.operator} semantics make the right operand unreachable",),
        premises=(left.proof,),
    )
