"""Reusable optimiser safety proofs for resolved yt-sql expressions.

The optimiser must not infer safety from incidental execution behaviour.  This
module turns semantic properties and source/facet capabilities into explicit,
inspectable proof results that optimisation passes can consume conservatively.
A failed or unavailable proof is represented explicitly rather than guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .query_model import Field, Query
from .query_properties import analyse_expression, analyse_query
from .source_capabilities import STRUCTURALLY_UNSUPPORTED, selected_facet_capabilities
from .source_model import SourceSpec

PROVEN = "proven"
NOT_PROVEN = "not-proven"

PROVENANCE_SEMANTIC_PROPERTIES = "semantic-properties"
PROVENANCE_SOURCE_CAPABILITY = "source-capability"
PROVENANCE_QUERY_REQUIREMENTS = "query-requirements"


@dataclass(frozen=True)
class OptimisationProof:
    """One deterministic proof or explicit refusal used by optimiser logic."""

    claim: str
    status: str
    provenance: tuple[str, ...]
    reasons: tuple[str, ...]

    @property
    def proven(self) -> bool:
        """Return whether the claim has been established safely."""
        return self.status == PROVEN


def _proof(
    claim: str,
    proven: bool,
    *,
    provenance: tuple[str, ...],
    reasons: tuple[str, ...],
) -> OptimisationProof:
    return OptimisationProof(
        claim=claim,
        status=PROVEN if proven else NOT_PROVEN,
        provenance=provenance,
        reasons=reasons,
    )


def prove_expression_deterministic(
    expression: Any,
    *,
    source: SourceSpec | None = None,
) -> OptimisationProof:
    """Prove that repeated evaluation cannot observe volatile behaviour."""
    properties = analyse_expression(expression, source=source)
    if properties.deterministic:
        return _proof(
            "expression-deterministic",
            True,
            provenance=(PROVENANCE_SEMANTIC_PROPERTIES,),
            reasons=("semantic property analysis contains no volatile descendants",),
        )
    return _proof(
        "expression-deterministic",
        False,
        provenance=(PROVENANCE_SEMANTIC_PROPERTIES,),
        reasons=("semantic property analysis reports volatile or unknown behaviour",),
    )


def prove_expression_constant(
    expression: Any,
    *,
    source: SourceSpec | None = None,
) -> OptimisationProof:
    """Prove that an expression does not depend on a row or group."""
    properties = analyse_expression(expression, source=source)
    if properties.constant and properties.deterministic:
        return _proof(
            "expression-constant",
            True,
            provenance=(PROVENANCE_SEMANTIC_PROPERTIES,),
            reasons=("expression is deterministic and row-independent",),
        )
    reasons: list[str] = []
    if not properties.constant:
        reasons.append("expression depends on row, group, or relation state")
    if not properties.deterministic:
        reasons.append("expression is volatile or contains a volatile descendant")
    return _proof(
        "expression-constant",
        False,
        provenance=(PROVENANCE_SEMANTIC_PROPERTIES,),
        reasons=tuple(reasons) or ("constantness is not proven",),
    )


def prove_field_structurally_unavailable(
    field: Field | str,
    *,
    source: SourceSpec | None,
) -> OptimisationProof:
    """Prove that a field is necessarily SQL NULL for one source/facet.

    Absence of a source contract is not evidence of structural unavailability.
    Likewise, supported-but-unacquired metadata must never satisfy this proof.
    """
    name = field.name if isinstance(field, Field) else field
    if source is None:
        return _proof(
            "field-structurally-unavailable",
            False,
            provenance=(PROVENANCE_SOURCE_CAPABILITY,),
            reasons=("no source/facet capability contract is available",),
        )
    capability = selected_facet_capabilities(source).field(name)
    if capability.structural_support == STRUCTURALLY_UNSUPPORTED:
        return _proof(
            "field-structurally-unavailable",
            True,
            provenance=(PROVENANCE_SOURCE_CAPABILITY,),
            reasons=(f"{name.casefold()} is declared structurally unsupported for the selected source/facet",),
        )
    return _proof(
        "field-structurally-unavailable",
        False,
        provenance=(PROVENANCE_SOURCE_CAPABILITY,),
        reasons=("the capability contract does not prove structural unavailability",),
    )


def prove_query_independent_of_fields(
    query: Query,
    discarded_fields: set[str] | frozenset[str],
    *,
    source: SourceSpec | None = None,
) -> OptimisationProof:
    """Prove that discarding the named physical fields cannot affect the query."""
    properties = analyse_query(query, source=source)
    discarded = frozenset(field.casefold() for field in discarded_fields)
    overlap = properties.required_fields & discarded
    if not overlap:
        return _proof(
            "query-independent-of-discarded-fields",
            True,
            provenance=(PROVENANCE_QUERY_REQUIREMENTS,),
            reasons=("none of the discarded fields are semantic query requirements",),
        )
    return _proof(
        "query-independent-of-discarded-fields",
        False,
        provenance=(PROVENANCE_QUERY_REQUIREMENTS,),
        reasons=("required fields would be discarded: " + ", ".join(sorted(overlap)),),
    )


def compose_proofs(claim: str, *proofs: OptimisationProof) -> OptimisationProof:
    """Combine prerequisite proofs without turning uncertainty into permission."""
    if not proofs:
        return _proof(
            claim,
            False,
            provenance=(PROVENANCE_SEMANTIC_PROPERTIES,),
            reasons=("no prerequisite proofs were supplied",),
        )
    proven = all(proof.proven for proof in proofs)
    provenance = tuple(dict.fromkeys(item for proof in proofs for item in proof.provenance))
    reasons = tuple(reason for proof in proofs for reason in proof.reasons)
    return _proof(claim, proven, provenance=provenance, reasons=reasons)
