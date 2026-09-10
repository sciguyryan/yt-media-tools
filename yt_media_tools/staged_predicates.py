"""Conservative staged evaluation of resolved WHERE predicates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .query_evaluator import evaluate
from .query_model import Binary, Query
from .query_properties import STAGE_CONSTANT, STAGE_ENUMERATION, analyse_expression
from .source_model import SourceSpec


@dataclass(frozen=True)
class PredicateStagePlan:
    """Predicate fragments grouped by the earliest authoritative execution stage."""

    enumeration_terms: tuple[Any, ...]
    enumeration_term_fields: tuple[frozenset[str], ...]
    residual_terms: tuple[Any, ...]
    enumeration_fields: frozenset[str]
    residual_fields: frozenset[str]
    reason: str

    @property
    def has_enumeration_filter(self) -> bool:
        """Return whether any WHERE work can run before detailed acquisition."""
        return bool(self.enumeration_terms)

    @property
    def requires_residual_evaluation(self) -> bool:
        """Return whether part of WHERE still needs a later metadata stage."""
        return bool(self.residual_terms)


def _and_terms(node: Any) -> tuple[Any, ...]:
    if isinstance(node, Binary) and node.operator == "AND":
        return _and_terms(node.left) + _and_terms(node.right)
    return (node,)


def _enumeration_safe(node: Any, *, source: SourceSpec) -> bool:
    properties = analyse_expression(node, source=source)
    return (
        properties.earliest_stage in {STAGE_CONSTANT, STAGE_ENUMERATION}
        and properties.deterministic
        and not properties.requires_group_context
    )


def plan_predicate_stages(query: Query, *, source: SourceSpec) -> PredicateStagePlan:
    """Partition WHERE into safe enumeration terms and residual later-stage terms.

    Top-level AND terms may be separated because any non-TRUE conjunct proves that
    the complete WHERE predicate cannot accept the row. OR and NOT expressions are
    kept intact unless the complete expression is authoritative at enumeration time.
    """
    if query.predicate is None:
        return PredicateStagePlan((), (), (), frozenset(), frozenset(), "the query has no WHERE predicate")

    terms = _and_terms(query.predicate)
    enumeration: list[Any] = []
    residual: list[Any] = []
    for term in terms:
        (enumeration if _enumeration_safe(term, source=source) else residual).append(term)

    enumeration_term_fields = tuple(analyse_expression(term, source=source).required_fields for term in enumeration)
    enumeration_fields = frozenset().union(*enumeration_term_fields) if enumeration_term_fields else frozenset()
    residual_fields = (
        frozenset().union(*(analyse_expression(term, source=source).required_fields for term in residual))
        if residual
        else frozenset()
    )

    if enumeration and residual:
        reason = "authoritative top-level AND terms are evaluated during enumeration; remaining terms stay at their later metadata stage"
    elif enumeration:
        reason = "the complete WHERE predicate is authoritative at enumeration time"
    else:
        reason = "no WHERE fragment can be separated for authoritative enumeration-stage evaluation"
    return PredicateStagePlan(
        tuple(enumeration), enumeration_term_fields, tuple(residual), enumeration_fields, residual_fields, reason
    )


def rejects_at_enumeration(plan: PredicateStagePlan, record: dict[str, Any]) -> bool:
    """Return True only when acquired enumeration values prove WHERE cannot be TRUE.

    A missing dictionary key is treated as not acquired rather than SQL NULL, so the
    corresponding term is deferred. A present key with value ``None`` is an acquired
    SQL NULL and may therefore make a WHERE conjunct reject the row as UNKNOWN.
    """
    for term, fields in zip(plan.enumeration_terms, plan.enumeration_term_fields, strict=True):
        if any(field not in record for field in fields):
            continue
        if evaluate(term, record) is not True:
            return True
    return False


def matches_at_enumeration(plan: PredicateStagePlan, record: dict[str, Any]) -> bool:
    """Return True only when lightweight metadata proves the complete WHERE predicate TRUE."""
    if plan.requires_residual_evaluation:
        return False
    for term, fields in zip(plan.enumeration_terms, plan.enumeration_term_fields, strict=True):
        if any(field not in record for field in fields):
            return False
        if evaluate(term, record) is not True:
            return False
    return True
