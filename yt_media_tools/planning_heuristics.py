"""Conservative coarse cost and selectivity heuristics for yt-discover planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .acquisition_plan import (
    PhysicalAcquisitionPlan,
    STAGE_BASIC_METADATA,
    STAGE_CHAPTERS,
    STAGE_COMPLETE_METADATA,
    STAGE_DYNAMIC_RAW,
    STAGE_ENUMERATE_IDENTITIES,
    STAGE_FORMATS,
    STAGE_SUBTITLES,
    STAGE_TAGS,
    STAGE_THUMBNAILS,
)
from .query_model import Between, Binary, InList, IsNull, Literal, TextPredicate
from .source_capabilities import selected_facet_capabilities

COST_NONE = "none"
COST_LOW = "low"
COST_MODERATE = "moderate"
COST_HIGH = "high"
COST_VERY_HIGH = "very-high"

SELECTIVITY_NONE = "none"
SELECTIVITY_LOW = "low"
SELECTIVITY_MODERATE = "moderate"
SELECTIVITY_HIGH = "high"

INFORMATION_NONE = "none"
INFORMATION_LOW = "low"
INFORMATION_MODERATE = "moderate"
INFORMATION_HIGH = "high"

_COST_RANK = {
    COST_NONE: 0,
    COST_LOW: 1,
    COST_MODERATE: 2,
    COST_HIGH: 3,
    COST_VERY_HIGH: 4,
}
_SELECTIVITY_RANK = {
    SELECTIVITY_NONE: 0,
    SELECTIVITY_LOW: 1,
    SELECTIVITY_MODERATE: 2,
    SELECTIVITY_HIGH: 3,
}
_INFORMATION_RANK = {
    INFORMATION_NONE: 0,
    INFORMATION_LOW: 1,
    INFORMATION_MODERATE: 2,
    INFORMATION_HIGH: 3,
}

_EXPENSIVE_STAGES = {
    STAGE_COMPLETE_METADATA,
    STAGE_FORMATS,
    STAGE_SUBTITLES,
    STAGE_CHAPTERS,
    STAGE_THUMBNAILS,
    STAGE_TAGS,
    STAGE_DYNAMIC_RAW,
}
_VERY_EXPENSIVE_STAGES = {
    STAGE_FORMATS,
    STAGE_SUBTITLES,
    STAGE_CHAPTERS,
    STAGE_THUMBNAILS,
    STAGE_TAGS,
    STAGE_DYNAMIC_RAW,
}


@dataclass(frozen=True)
class PredicateHeuristic:
    """Coarse local-evaluation heuristic for one deterministic predicate term."""

    selectivity: str
    evaluation_cost: str
    information_value: str
    reason: str

    @property
    def sort_key(self) -> tuple[int, int]:
        """Prefer greater information value and then cheaper local evaluation."""
        return (-_INFORMATION_RANK[self.information_value], _COST_RANK[self.evaluation_cost])


@dataclass(frozen=True)
class AcquisitionHeuristicPlan:
    """Coarse physical cost and filtering-value guidance for one source boundary."""

    cost_tier: str
    selectivity_tier: str
    information_value_tier: str
    deferred_expensive_stages: tuple[str, ...]
    reason: str


def _predicate_selectivity(node: Any) -> tuple[str, str]:
    """Estimate only broad filtering power from syntactic predicate shape."""
    if isinstance(node, Literal):
        return SELECTIVITY_HIGH, "constant predicates have maximal decision value"

    if isinstance(node, IsNull):
        return SELECTIVITY_MODERATE, "NULL tests often partition rows without expensive local work"

    if isinstance(node, Binary) and node.operator not in {"AND", "OR"}:
        if node.operator == "=":
            return SELECTIVITY_HIGH, "exact equality is treated as a high-selectivity local filter"
        if node.operator == "!=":
            return SELECTIVITY_LOW, "inequality commonly retains a broad portion of rows"
        if node.operator in {"<", "<=", ">", ">="}:
            return SELECTIVITY_MODERATE, "range comparisons have moderate expected filtering value"

    if isinstance(node, Between):
        return (
            SELECTIVITY_LOW if node.negated else SELECTIVITY_MODERATE,
            "bounded ranges have moderate expected filtering value"
            if not node.negated
            else "negated ranges are treated conservatively",
        )

    if isinstance(node, InList):
        if node.negated:
            return SELECTIVITY_LOW, "negated membership is treated conservatively"
        if len(node.values) <= 3:
            return SELECTIVITY_HIGH, "small exact membership sets are treated as high-selectivity filters"
        return SELECTIVITY_MODERATE, "larger exact membership sets have moderate expected filtering value"

    if isinstance(node, TextPredicate):
        if node.negated:
            return SELECTIVITY_LOW, "negated text predicates are treated conservatively"
        return SELECTIVITY_MODERATE, "positive text predicates have moderate expected filtering value"

    return SELECTIVITY_LOW, "predicate shape does not justify a stronger selectivity assumption"


def predicate_heuristic(node: Any, *, field_count: int = 1) -> PredicateHeuristic:
    """Return a deterministic coarse heuristic without claiming numeric selectivity."""
    selectivity, reason = _predicate_selectivity(node)
    evaluation_cost = (
        COST_MODERATE
        if isinstance(node, TextPredicate) and node.operator == "MATCHES"
        else COST_MODERATE
        if field_count > 1
        else COST_LOW
    )

    if selectivity == SELECTIVITY_HIGH and evaluation_cost == COST_LOW:
        information = INFORMATION_HIGH
    elif (
        _SELECTIVITY_RANK[selectivity] >= _SELECTIVITY_RANK[SELECTIVITY_MODERATE]
        and _COST_RANK[evaluation_cost] <= _COST_RANK[COST_MODERATE]
    ):
        information = INFORMATION_MODERATE
    else:
        information = INFORMATION_LOW

    return PredicateHeuristic(selectivity, evaluation_cost, information, reason)


def order_predicate_terms(
    terms: tuple[Any, ...],
    term_fields: tuple[frozenset[str], ...],
) -> tuple[tuple[Any, ...], tuple[frozenset[str], ...], tuple[PredicateHeuristic, ...], bool]:
    """Order independent deterministic AND terms by information value per local cost."""
    annotated = [
        (
            index,
            term,
            fields,
            predicate_heuristic(term, field_count=len(fields)),
        )
        for index, (term, fields) in enumerate(zip(terms, term_fields, strict=True))
    ]
    ordered = sorted(
        annotated,
        key=lambda item: (item[3].sort_key, item[0]),
    )
    changed = [item[0] for item in ordered] != list(range(len(annotated)))
    return (
        tuple(item[1] for item in ordered),
        tuple(item[2] for item in ordered),
        tuple(item[3] for item in ordered),
        changed,
    )


def _acquisition_cost_tier(
    plan: PhysicalAcquisitionPlan,
    *,
    bounded: bool,
) -> str:
    """Match the planner's existing coarse whole-boundary acquisition classes."""
    required = set(plan.required_stage_names)
    if not required:
        return COST_NONE
    if bounded:
        return COST_MODERATE
    facet = selected_facet_capabilities(plan.source)
    if required <= {STAGE_ENUMERATE_IDENTITIES, STAGE_BASIC_METADATA} and facet.cheaply_enumerates_identities:
        return COST_HIGH
    return COST_VERY_HIGH


def plan_acquisition_heuristics(
    *,
    physical_acquisition: PhysicalAcquisitionPlan,
    predicate_heuristics: tuple[PredicateHeuristic, ...],
    bounded: bool,
) -> AcquisitionHeuristicPlan:
    """Combine coarse remote cost with cheap filtering information.

    The result never changes semantics by itself. It is consumed only where the
    planner already has a proof that evaluation stages are independent and safe.
    """
    cost = _acquisition_cost_tier(
        physical_acquisition,
        bounded=bounded,
    )

    if predicate_heuristics:
        selectivity = max(
            (item.selectivity for item in predicate_heuristics),
            key=lambda item: _SELECTIVITY_RANK[item],
        )
        information = max(
            (item.information_value for item in predicate_heuristics),
            key=lambda item: _INFORMATION_RANK[item],
        )
    else:
        selectivity = SELECTIVITY_NONE
        information = INFORMATION_NONE

    deferred = (
        tuple(stage for stage in physical_acquisition.required_stage_names if stage in _EXPENSIVE_STAGES)
        if predicate_heuristics
        else ()
    )

    if cost == COST_NONE:
        reason = "the physical source boundary requires no acquisition"
    elif predicate_heuristics and deferred:
        reason = (
            "cheap deterministic enumeration predicates are evaluated before "
            "higher-cost metadata stages; deeper work is reserved for surviving rows"
        )
    elif predicate_heuristics:
        reason = "cheap deterministic predicates are ordered by coarse information value per local evaluation cost"
    else:
        reason = "no safe cheap predicate term is available to gate later acquisition work"

    return AcquisitionHeuristicPlan(
        cost,
        selectivity,
        information,
        deferred,
        reason,
    )
