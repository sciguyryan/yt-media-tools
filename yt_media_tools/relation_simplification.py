"""Proof-backed relation and branch simplification for yt-sql planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .optimizer_proofs import (
    PROVEN,
    PROVENANCE_SEMANTIC_PROPERTIES,
    TRUTH_TRUE,
    OptimisationProof,
    PredicateTruthProof,
    prove_predicate_truth,
)
from .query_model import Between, Binary, Field, InList, IsNull, Literal, Query, TextPredicate
from .source_model import SourceSpec


@dataclass(frozen=True)
class RelationSimplificationPlan:
    """Static relational facts proven before physical acquisition."""

    empty: bool
    where_truth: str | None
    having_truth: str | None
    where_redundant: bool
    having_redundant: bool
    reason: str
    proofs: tuple[OptimisationProof, ...]


def _rejection_proven(proof: PredicateTruthProof) -> bool:
    """Return whether SQL filtering is proven to reject every candidate row."""
    return proof.proven and proof.truth != TRUTH_TRUE


def _relation_proof(reason: str) -> OptimisationProof:
    """Build a proof that a predicate cannot evaluate TRUE for any input row."""
    return OptimisationProof(
        claim="relation-predicate-never-true",
        status=PROVEN,
        provenance=(PROVENANCE_SEMANTIC_PROPERTIES,),
        reasons=(reason,),
    )


def _field_name(node: Any) -> str | None:
    """Return a canonical direct field name where one is present."""
    return node.name.casefold() if isinstance(node, Field) else None


def _literal_value(node: Any) -> Any:
    """Return a safely comparable literal value or the sentinel NotImplemented."""
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
    """Flatten only top-level AND terms, preserving OR and NOT subtrees."""
    if isinstance(node, Binary) and node.operator == "AND":
        return _flatten_and(node.left) + _flatten_and(node.right)
    return (node,)


def _comparison_constraint(term: Any) -> tuple[str, str, Any] | None:
    """Return a direct-field literal comparison constraint when safely recognisable."""
    if not isinstance(term, Binary) or term.operator in {"AND", "OR"}:
        return None
    field = _field_name(term.left)
    value = _literal_value(term.right)
    if field is None or value is NotImplemented or value is None:
        return None
    return field, term.operator, value


def _null_constraint(term: Any) -> tuple[str, bool] | None:
    """Return ``(field, requires_null)`` for a direct IS NULL predicate."""
    if not isinstance(term, IsNull):
        return None
    field = _field_name(term.field)
    if field is None:
        return None
    return field, not term.negated


def _null_rejecting_field(term: Any) -> str | None:
    """Return a field when NULL can never make this predicate TRUE."""
    comparison = _comparison_constraint(term)
    if comparison is not None:
        return comparison[0]
    if isinstance(term, (Between, InList, TextPredicate)):
        return _field_name(term.field)
    if isinstance(term, IsNull) and term.negated:
        return _field_name(term.field)
    return None


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


def _and_contradiction(node: Any) -> OptimisationProof | None:
    """Prove common same-field AND contradictions under SQL filtering semantics."""
    terms = _flatten_and(node)
    by_field: dict[str, list[tuple[str, Any]]] = {}
    null_requirements: dict[str, set[bool]] = {}
    null_rejecting: set[str] = set()

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
            return _relation_proof(f"{field} cannot be both NULL and NOT NULL")
        if True in requirements and field in null_rejecting:
            return _relation_proof(f"{field} IS NULL cannot be TRUE together with a predicate that rejects NULL")

    for field, constraints in by_field.items():
        equalities = [value for operator, value in constraints if operator == "="]
        if equalities:
            first = equalities[0]
            if any(value != first for value in equalities[1:]):
                return _relation_proof(f"{field} has incompatible equality requirements")
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
                    return _relation_proof(f"{field} equality is incompatible with its lower bound")
                if upper is not None and (value > upper[0] or (value == upper[0] and not upper[1])):
                    return _relation_proof(f"{field} equality is incompatible with its upper bound")
            except TypeError:
                pass
        if lower is not None and upper is not None:
            try:
                if lower[0] > upper[0] or (lower[0] == upper[0] and not (lower[1] and upper[1])):
                    return _relation_proof(f"{field} lower and upper bounds cannot both be satisfied")
            except TypeError:
                pass
    return None


def prove_predicate_never_true(
    node: Any,
    *,
    source: SourceSpec | None,
) -> OptimisationProof | None:
    """Prove that a filtering predicate cannot evaluate TRUE for any row."""
    if node is None:
        return None
    truth = prove_predicate_truth(node, source=source)
    if _rejection_proven(truth):
        return truth.proof
    if isinstance(node, Binary) and node.operator == "AND":
        left = prove_predicate_never_true(node.left, source=source)
        if left is not None:
            return left
        right = prove_predicate_never_true(node.right, source=source)
        if right is not None:
            return right
        return _and_contradiction(node)
    return None


def plan_relation_simplification(
    query: Query,
    *,
    source: SourceSpec | None,
) -> RelationSimplificationPlan:
    """Prove relation-level simplifications without relying on acquired row values.

    WHERE and HAVING both keep rows only when their predicates evaluate TRUE. A proven
    FALSE or UNKNOWN result therefore proves the relation empty. A proven TRUE result
    is redundant at its filtering stage and may be omitted from physical predicate work.
    """
    where = prove_predicate_truth(query.predicate, source=source)
    having = prove_predicate_truth(query.having, source=source) if query.having is not None else None
    where_never_true = prove_predicate_never_true(query.predicate, source=source)
    having_never_true = prove_predicate_never_true(query.having, source=source)

    where_empty = query.predicate is not None and where_never_true is not None
    having_empty = query.having is not None and having_never_true is not None
    where_redundant = query.predicate is not None and where.proven and where.truth == TRUTH_TRUE
    having_redundant = query.having is not None and having is not None and having.proven and having.truth == TRUTH_TRUE

    proofs: list[OptimisationProof] = []
    reasons: list[str] = []
    if where_empty and where_never_true is not None:
        proofs.append(where_never_true)
        reasons.append("WHERE is proven never TRUE, so the relation is empty")
    if having_empty and having_never_true is not None:
        proofs.append(having_never_true)
        reasons.append("HAVING is proven never TRUE, so no group can survive")
    if where_redundant:
        proofs.append(where.proof)
        reasons.append("WHERE is proven TRUE and is redundant for physical filtering")
    if having_redundant and having is not None:
        proofs.append(having.proof)
        reasons.append("HAVING is proven TRUE and is redundant after grouping")

    return RelationSimplificationPlan(
        empty=where_empty or having_empty,
        where_truth=where.truth if where.proven else None,
        having_truth=having.truth if having is not None and having.proven else None,
        where_redundant=where_redundant,
        having_redundant=having_redundant,
        reason=("; ".join(reasons) if reasons else "no relation-level constant simplification is proven"),
        proofs=tuple(proofs),
    )
