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
    prove_field_non_null,
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
    Query,
    ScalarComparison,
    ScalarIsNull,
    TextPredicate,
)
from .source_capabilities import selected_facet_capabilities
from .source_model import SourceSpec


@dataclass(frozen=True)
class FieldFacts:
    """Authoritative facts available for one stable logical source field."""

    known_logical_field: bool
    logical_kind: str | None
    nullable: bool | None
    proof: OptimisationProof | None
    boundaries: tuple[str, ...] = ()


def prove_source_field_facts(source: SourceSpec, field: str) -> FieldFacts:
    """Expose only field facts promised by the selected source/facet contract.

    ``nullable`` is ``None`` for dynamic fields because detailed metadata may
    expose them without any stable logical-schema promise. This deliberately
    distinguishes unavailable knowledge from a nullable declaration.
    """
    capability = selected_facet_capabilities(source).field(field)
    if capability.logical_kind is None:
        return FieldFacts(
            False,
            None,
            None,
            None,
            ("dynamic field has no stable logical-schema type or nullability contract",),
        )
    non_null = prove_field_non_null(field, source=source)
    proof = (
        non_null
        if non_null.proven
        else OptimisationProof(
            claim="field-capability-facts",
            status=PROVEN,
            provenance=("source-capability",),
            reasons=(f"{field.casefold()} has a stable logical field declaration",),
        )
    )
    return FieldFacts(True, capability.logical_kind, capability.nullable, proof)


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
    operator = term.operator
    if field is None:
        field = _field_key(term.right)
        value = _literal_value(term.left)
        operator = {"<": ">", "<=": ">=", ">": "<", ">=": "<=", "=": "=", "!=": "!="}.get(operator)
    if field is None or operator is None or value is NotImplemented or value is None:
        return None
    return field, operator, value


def _positive_in_constraint(term: Any) -> tuple[tuple[str | None, str], frozenset[Any]] | None:
    """Return a finite positive IN domain when every non-NULL value is safely hashable."""
    if not isinstance(term, InList) or term.negated:
        return None
    field = _field_key(term.field)
    if field is None:
        return None
    values: set[Any] = set()
    try:
        for item in term.values:
            value = _literal_value(item)
            if value is NotImplemented:
                return None
            if value is not None:
                values.add(value)
    except TypeError:
        return None
    return field, frozenset(values)


def _between_constraints(term: Any) -> tuple[tuple[str | None, str], tuple[Any, bool], tuple[Any, bool]] | None:
    """Return inclusive bounds for an ordinary positive BETWEEN predicate."""
    if not isinstance(term, Between) or term.negated:
        return None
    field = _field_key(term.field)
    lower = _literal_value(term.lower)
    upper = _literal_value(term.upper)
    if field is None or lower is NotImplemented or lower is None or upper is NotImplemented or upper is None:
        return None
    return field, (lower, True), (upper, True)


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
    finite_domains: dict[tuple[str | None, str], list[frozenset[Any]]] = {}
    null_requirements: dict[tuple[str | None, str], set[bool]] = {}
    null_rejecting: set[tuple[str | None, str]] = set()

    for term in terms:
        comparison = _comparison_constraint(term)
        if comparison is not None:
            field, operator, value = comparison
            by_field.setdefault(field, []).append((operator, value))
        finite = _positive_in_constraint(term)
        if finite is not None:
            field, values = finite
            finite_domains.setdefault(field, []).append(values)
        between = _between_constraints(term)
        if between is not None:
            field, lower, upper = between
            by_field.setdefault(field, []).extend(((">=", lower[0]), ("<=", upper[0])))
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

    for field in by_field.keys() | finite_domains.keys():
        constraints = by_field.get(field, [])
        equalities = [value for operator, value in constraints if operator == "="]
        exclusions = [value for operator, value in constraints if operator == "!="]
        if equalities and any(value != equalities[0] for value in equalities[1:]):
            return _proof(f"{_label(field)} has incompatible equality requirements")
        if equalities and any(value == equalities[0] for value in exclusions):
            return _proof(f"{_label(field)} cannot equal and differ from the same value")
        domains = finite_domains.get(field, [])
        if domains:
            allowed = set(domains[0])
            for domain in domains[1:]:
                allowed.intersection_update(domain)
            if not allowed:
                return _proof(f"{_label(field)} has disjoint finite IN requirements")
            if equalities and equalities[0] not in allowed:
                return _proof(f"{_label(field)} equality is outside its finite IN requirements")
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
    if isinstance(node, Binary) and node.operator == "OR":
        left = prove_predicate_never_true(node.left, source=source)
        right = prove_predicate_never_true(node.right, source=source)
        if left is not None and right is not None:
            return OptimisationProof(
                claim="predicate-never-true",
                status=PROVEN,
                provenance=tuple(dict.fromkeys(left.provenance + right.provenance)),
                reasons=("both OR branches are independently proven never TRUE",),
                premises=(left, right),
            )
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


@dataclass(frozen=True)
class RelationFacts:
    """Conservative facts proven about one complete logical query result.

    ``max_rows`` is present only when an explicit language construct proves an
    upper bound. Output nullability is intentionally absent here: stable
    source/facet contracts do carry field nullability, but the complete query
    result model does not yet preserve enough projection and LEFT-extension
    information to lift those declarations safely to arbitrary result columns.
    """

    empty: bool
    max_rows: int | None
    proof: OptimisationProof | None
    boundaries: tuple[str, ...] = ()


def _relation_fact_proof(claim: str, reason: str, *premises: OptimisationProof) -> OptimisationProof:
    provenance: tuple[str, ...] = tuple(dict.fromkeys(item for premise in premises for item in premise.provenance))
    return OptimisationProof(
        claim=claim,
        status=PROVEN,
        provenance=provenance or (PROVENANCE_SEMANTIC_PROPERTIES,),
        reasons=(reason,),
        premises=tuple(premises),
    )


def prove_query_relation_facts(query: Query) -> RelationFacts:
    """Prove bounded relation-level facts from the validated query structure.

    The proof deliberately uses only facts represented authoritatively by the
    current query model. In particular, direct physical sources have unknown
    cardinality. Stable source contracts may prove input-field nullability, but
    arbitrary result-column nullability is not inferred here. CTE emptiness is
    propagated by name, JOIN consequences are applied by JOIN kind, UNION is
    empty only when every branch is proven empty, and an explicit LIMIT is an
    unconditional result-cardinality upper bound.
    """
    # Local import avoids making the semantic proof module part of the query
    # model's import cycle.
    from .query_model import Query

    if not isinstance(query, Query):
        raise TypeError("query must be a resolved Query")

    cte_facts: dict[str, RelationFacts] = {}
    for cte in query.ctes:
        cte_facts[cte.name.casefold()] = prove_query_relation_facts(cte.query)

    premises: list[OptimisationProof] = []
    reasons: list[str] = []
    body_empty = False

    source_name = (query.from_source or "").casefold()
    source_fact = cte_facts.get(source_name)
    if source_fact is not None and source_fact.empty:
        body_empty = True
        if source_fact.proof is not None:
            premises.append(source_fact.proof)
        reasons.append(f"CTE {query.from_source} is proven empty")

    where_proof = prove_predicate_never_true(query.predicate, source=None)
    if query.predicate is not None and where_proof is not None:
        body_empty = True
        premises.append(where_proof)
        reasons.append("WHERE is proven never TRUE")

    having_proof = prove_predicate_never_true(query.having, source=None)
    if query.having is not None and having_proof is not None:
        body_empty = True
        premises.append(having_proof)
        reasons.append("HAVING is proven never TRUE")

    # Apply only the currently executable single-JOIN semantics. Multi-way JOIN
    # remains a guarded execution boundary and is therefore not used as a proof
    # source here.
    if len(query.joins) == 1 and not body_empty:
        join = query.joins[0]
        right_fact = cte_facts.get(join.relation.source.casefold())
        kind = join.kind.value.upper()
        join_consequence = prove_join_consequences(kind, join.predicate)
        if join_consequence.result_empty:
            body_empty = True
            if join_consequence.proof is not None:
                premises.append(join_consequence.proof)
            reasons.append(f"{kind} JOIN predicate is proven unable to match")
        elif right_fact is not None and right_fact.empty and kind in {"INNER", "SEMI"}:
            body_empty = True
            if right_fact.proof is not None:
                premises.append(right_fact.proof)
            reasons.append(f"{kind} JOIN right CTE is proven empty")

    body_proof = _relation_fact_proof("relation-empty", "; ".join(reasons), *premises) if body_empty else None

    # A UNION result is empty iff its left body and every branch are empty.
    # The branches are complete logical relations; UNION versus UNION ALL does
    # not change this emptiness law.
    final_empty = body_empty
    final_proof = body_proof
    if query.set_operations:
        branch_facts = [prove_query_relation_facts(operation.query) for operation in query.set_operations]
        if body_empty and all(fact.empty for fact in branch_facts):
            union_premises = [proof for proof in [body_proof, *(fact.proof for fact in branch_facts)] if proof]
            final_empty = True
            final_proof = _relation_fact_proof(
                "relation-empty",
                "every UNION branch is independently proven empty",
                *union_premises,
            )
        else:
            final_empty = False
            final_proof = None

    max_rows = 0 if final_empty else query.limit
    boundaries = (
        "output-field nullability is not authoritative in the current resolved query model",
        "direct physical-source cardinality is unknown unless constrained by explicit query semantics",
        "multi-way JOIN execution remains a guarded boundary and is not used for relation proofs",
    )
    return RelationFacts(final_empty, max_rows, final_proof, boundaries)
