"""Proof-backed relation and branch simplification for yt-sql planning."""

from __future__ import annotations

from dataclasses import dataclass

from .optimizer_proofs import TRUTH_TRUE, OptimisationProof, prove_predicate_truth
from .semantic_provability import prove_predicate_never_true
from .query_model import Query
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
