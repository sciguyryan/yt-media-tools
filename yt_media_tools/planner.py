"""Conservative acquisition planning for query-driven YouTube discovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from .dates import DateContext
from .query_model import Query
from .optimizer_proofs import TRUTH_TRUE, OptimisationProof, prove_predicate_truth
from .query_properties import (
    QueryProperties,
    analyse_expression,
    analyse_query,
    required_query_fields as required_query_fields,
)
from .source_capabilities import EXACT, selected_facet_capabilities
from .source_model import SourceSpec
from .staged_predicates import PredicateStagePlan, plan_predicate_stages
from .temporal_bounds import TemporalBoundPlan, infer_temporal_bounds, upload_date_frontier


# yt-dlp documents flat-playlist dates as approximate. Keep a generous boundary margin and
# require several consecutive old entries before terminating pagination. These values favour
# correctness over maximal request reduction while still bounding large recent-date scans.
APPROXIMATE_DATE_MARGIN_DAYS = 45
BOUNDARY_CONFIRMATION_ENTRIES = 3


@dataclass(frozen=True)
class AcquisitionPlan:
    """A safe pre-acquisition plan derived from source semantics and the query AST."""

    mode: str
    reason: str
    lower_date_bound: date | None = None
    stop_before: date | None = None
    confirmation_entries: int = BOUNDARY_CONFIRMATION_ENTRIES

    @property
    def targeted(self) -> bool:
        return self.mode == "bounded-date"


@dataclass(frozen=True)
class LimitTerminationPlan:
    """Proof that LIMIT may stop detailed acquisition without changing results."""

    eligible: bool
    reason: str
    limit: int | None = None


def plan_limit_termination(query: Query) -> LimitTerminationPlan:
    """Return whether source-order streaming may stop after LIMIT matching rows.

    This implementation is intentionally narrow. With no explicit ORDER BY,
    yt-discover preserves source order, so once OFFSET + LIMIT authoritative matches
    have been observed no later row can enter the requested result slice. Dynamic
    fields are deferred because their types cannot be proven before detailed metadata
    is observed.
    """
    if query.limit is None:
        return LimitTerminationPlan(False, "the query has no LIMIT")
    if query.ctes:
        return LimitTerminationPlan(
            False,
            "CTE materialisation may filter, reorder or reshape source rows before LIMIT; early termination is not yet proven safe",
            query.limit,
        )
    if query.set_operations:
        return LimitTerminationPlan(
            False,
            "UNION composition requires complete branch results before global LIMIT can be applied",
            query.limit,
        )
    properties = analyse_query(query)
    if properties.requires_aggregation:
        return LimitTerminationPlan(
            False,
            "aggregation requires complete input groups before LIMIT can be applied",
            query.limit,
        )
    if query.order_by:
        return LimitTerminationPlan(
            False, "explicit ORDER BY requires complete result ordering before LIMIT can be applied", query.limit
        )
    if query.distinct:
        return LimitTerminationPlan(
            False,
            "DISTINCT may discard earlier duplicate projections, so complete duplicate resolution is required",
            query.limit,
        )
    dynamic = properties.dynamic_fields
    if dynamic:
        return LimitTerminationPlan(
            False,
            "dynamic fields require post-acquisition schema resolution: " + ", ".join(dynamic),
            query.limit,
        )
    required_matches = query.offset + query.limit
    return LimitTerminationPlan(
        True,
        (
            "source order is the final result order, so acquisition may stop after "
            f"{required_matches} authoritative match(es) satisfy OFFSET + LIMIT"
        ),
        query.limit,
    )


def plan_acquisition(
    query: Query,
    *,
    source_kind: str,
    tab: str,
    dates: DateContext,
    temporal_bounds: TemporalBoundPlan | None = None,
) -> AcquisitionPlan:
    """Choose an ordered temporal frontier only where source semantics prove it safe."""
    if query.set_operations or any(cte.query.set_operations for cte in query.ctes):
        return AcquisitionPlan("full", "UNION composition is acquired conservatively per physical source")
    if source_kind != "channel":
        return AcquisitionPlan("full", "playlists are not assumed to be ordered by upload date")
    if tab != "videos":
        return AcquisitionPlan("full", f"the {tab!r} channel tab is not assumed to have safe upload-date ordering")

    bounds = temporal_bounds or infer_temporal_bounds(query.predicate, dates)
    lower = upload_date_frontier(bounds)
    if lower is None:
        return AcquisitionPlan("full", "the WHERE expression does not imply a safe lower upload-date bound")

    return AcquisitionPlan(
        "bounded-date",
        "the query implies a proven lower upload-date frontier on a newest-first channel feed",
        lower_date_bound=lower,
        stop_before=lower - timedelta(days=APPROXIMATE_DATE_MARGIN_DAYS),
    )


def assess_cost(query: Query, plan: AcquisitionPlan, *, source: SourceSpec | None = None) -> tuple[str, str]:
    """Classify the actual acquisition plan using the explicit capability model."""
    fields = required_query_fields(query)
    properties = analyse_query(query, source=source)
    detailed_only = sorted(field for field in fields if properties.field_capability(field).ytdlp_flat != EXACT)
    if plan.targeted:
        if detailed_only:
            return (
                "moderate",
                (
                    "a safe source boundary limits enumeration; detailed metadata is required "
                    f"for {', '.join(detailed_only)} unless a fresh cache entry can satisfy it"
                ),
            )
        return (
            "moderate",
            "a safe source boundary limits enumeration and no authoritative detailed fields are required",
        )
    if source is not None and not detailed_only and selected_facet_capabilities(source).cheaply_enumerates_identities:
        return (
            "high",
            "the complete source must be enumerated, but all named query fields are authoritative in lightweight metadata",
        )
    return (
        "very-high",
        (
            "no safe source boundary exists; the source must be fully enumerated and stale or missing "
            "detailed metadata refreshed as required"
        ),
    )


@dataclass(frozen=True)
class MetadataRequirementPlan:
    """Authoritative metadata requirements separated by acquisition stage."""

    enumeration_fields: frozenset[str]
    detailed_fields: frozenset[str]
    predicate_enumeration_fields: frozenset[str]
    predicate_detailed_fields: frozenset[str]
    reason: str

    @property
    def requires_detailed_metadata(self) -> bool:
        """Return whether any query field needs more than exact flat metadata."""
        return bool(self.detailed_fields)


def plan_metadata_requirements(query: Query, *, source: SourceSpec) -> MetadataRequirementPlan:
    """Partition physical fields by the earliest authoritative metadata stage.

    Approximate flat metadata is intentionally not classified as authoritative. Such
    fields remain detailed requirements even when a lightweight value happens to be
    available and may still be useful for one-sided conservative rejection.
    """
    properties = analyse_query(query, source=source)
    facet = selected_facet_capabilities(source)

    enumeration_fields = frozenset(
        field for field in properties.required_fields if facet.field(field).ytdlp_flat == EXACT
    )
    detailed_fields = frozenset(properties.required_fields - enumeration_fields)

    predicate_fields = analyse_expression(query.predicate, source=source).required_fields
    predicate_enumeration_fields = frozenset(
        field for field in predicate_fields if facet.field(field).ytdlp_flat == EXACT
    )
    predicate_detailed_fields = frozenset(predicate_fields - predicate_enumeration_fields)

    if detailed_fields:
        reason = (
            "authoritative detailed metadata is required for "
            + ", ".join(sorted(detailed_fields))
            + "; exact flat fields may still be evaluated before detailed extraction"
        )
    elif enumeration_fields:
        reason = "all required query fields are authoritative in lightweight enumeration metadata"
    else:
        reason = "the query requires source enumeration but no named metadata fields"

    return MetadataRequirementPlan(
        enumeration_fields=enumeration_fields,
        detailed_fields=detailed_fields,
        predicate_enumeration_fields=predicate_enumeration_fields,
        predicate_detailed_fields=predicate_detailed_fields,
        reason=reason,
    )


@dataclass(frozen=True)
class PhysicalAcquisitionRequest:
    """Source-adapter input derived from semantic requirements and source policy."""

    source: SourceSpec
    required_fields: frozenset[str]
    enumeration_fields: frozenset[str]
    detailed_fields: frozenset[str]
    mode: str
    lower_date_bound: date | None
    stop_before: date | None


@dataclass(frozen=True)
class QueryPlan:
    """Typed boundary between logical optimisation and physical acquisition."""

    query: Query
    properties: QueryProperties
    acquisition: AcquisitionPlan
    physical_request: PhysicalAcquisitionRequest
    metadata_requirements: MetadataRequirementPlan
    predicate_stages: PredicateStagePlan
    temporal_bounds: TemporalBoundPlan
    limit_termination: LimitTerminationPlan
    cost_class: str
    cost_reason: str
    source_branch_eliminated: bool = False
    elimination_proof: OptimisationProof | None = None


def plan_query(query: Query, *, source: SourceSpec, dates: DateContext) -> QueryPlan:
    """Build the source-aware plan consumed by acquisition orchestration.

    The logical optimiser remains source-independent. This boundary is the first point
    where a resolved query is combined with an adapter/facet capability contract.
    """
    properties = analyse_query(query, source=source)
    facet = selected_facet_capabilities(source)
    metadata_requirements = plan_metadata_requirements(query, source=source)
    predicate_stages = plan_predicate_stages(query, source=source)
    temporal_bounds = infer_temporal_bounds(query.predicate, dates)
    acquisition = plan_acquisition(
        query,
        source_kind=source.kind,
        tab=source.facet or "videos",
        dates=dates,
        temporal_bounds=temporal_bounds,
    )
    # A bounded newest-first scan is valid only when the selected adapter explicitly
    # declares a stable collection and trustworthy source order.
    if acquisition.targeted and (not facet.stable_collection or facet.trustworthy_order_field is None):
        acquisition = AcquisitionPlan(
            "full",
            "the selected source/facet does not declare stable trustworthy ordering for bounded acquisition",
        )
    truth = prove_predicate_truth(query.predicate, source=source)
    eliminated = truth.proven and truth.truth != TRUTH_TRUE
    if eliminated:
        acquisition = AcquisitionPlan(
            "skip",
            "source/facet capabilities prove the WHERE predicate cannot evaluate TRUE",
        )
    limit = plan_limit_termination(query)
    if eliminated:
        cost_class, cost_reason = "none", "the source branch is proven empty before acquisition"
    else:
        cost_class, cost_reason = assess_cost(query, acquisition, source=source)
    request = PhysicalAcquisitionRequest(
        source=source,
        required_fields=properties.required_fields,
        enumeration_fields=metadata_requirements.enumeration_fields,
        detailed_fields=metadata_requirements.detailed_fields,
        mode=acquisition.mode,
        lower_date_bound=acquisition.lower_date_bound,
        stop_before=acquisition.stop_before,
    )
    return QueryPlan(
        query,
        properties,
        acquisition,
        request,
        metadata_requirements,
        predicate_stages,
        temporal_bounds,
        limit,
        cost_class,
        cost_reason,
        eliminated,
        truth.proof if eliminated else None,
    )
