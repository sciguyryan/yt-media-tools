"""Conservative acquisition planning for query-driven YouTube discovery."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from .cte_dependencies import plan_cte_dependencies
from .dates import DateContext
from .query_model import Binary, Query
from .optimizer_proofs import TRUTH_TRUE, OptimisationProof, prove_predicate_truth
from .query_semantics import query_physical_source_requests
from .query_properties import (
    METADATA_DETAILED,
    METADATA_ENUMERATION,
    METADATA_NONE,
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


@dataclass(frozen=True)
class SourceBoundaryPlan:
    """Physical planning state for one unique source/facet acquisition boundary."""

    source_name: str
    facet: str | None
    source: SourceSpec
    use_count: int
    required_fields: frozenset[str]
    combined_predicate: object | None
    pre_acquisition_predicates: tuple[object, ...]
    metadata_requirements: MetadataRequirementPlan
    predicate_stages: PredicateStagePlan
    temporal_bounds: TemporalBoundPlan
    acquisition: AcquisitionPlan
    cost_class: str
    cost_reason: str
    metadata_depth: str
    stable_collection: bool
    stable_order_field: str | None
    early_termination: bool
    branch_empty: bool
    elimination_proof: OptimisationProof | None
    collection_requirements: frozenset[str]


def _physical_query_uses(query: Query) -> tuple[tuple[str, str | None, Query, str | None], ...]:
    """Return logical physical-source uses with their owning CTE, where applicable."""
    cte_names = {cte.name.casefold() for cte in query.ctes}
    uses: list[tuple[str, str | None, Query, str | None]] = []

    def visit(candidate: Query, owner_cte: str | None = None) -> None:
        if candidate.from_source is not None and candidate.from_source.casefold() not in cte_names:
            local = replace(candidate, ctes=(), set_operations=(), order_by=(), limit=None, offset=0)
            uses.append((candidate.from_source, candidate.from_facet, local, owner_cte))
        for operation in candidate.set_operations:
            visit(operation.query, owner_cte)

    for cte in query.ctes:
        visit(cte.query, cte.name)
    visit(query)
    return tuple(uses)


def _or_predicates(predicates: tuple[object | None, ...]) -> object | None:
    """Return a predicate that retains every row needed by any physical-source use."""
    if not predicates or any(item is None for item in predicates):
        return None
    result = predicates[0]
    for predicate in predicates[1:]:
        result = Binary("OR", result, predicate)
    return result


def _collection_requirements(fields: frozenset[str]) -> frozenset[str]:
    """Identify nested collection families required by dynamic metadata references."""
    families = {
        field.split(".", 1)[0].casefold()
        for field in fields
        if "." in field
        and field.split(".", 1)[0].casefold()
        in {"formats", "chapters", "subtitles", "automatic_captions", "thumbnails", "tags"}
    }
    return frozenset(families)


def _assess_source_boundary_cost(
    metadata: MetadataRequirementPlan, acquisition: AcquisitionPlan, *, source: SourceSpec
) -> tuple[str, str]:
    """Classify one physical boundary from its complete unioned metadata requirements."""
    detailed = sorted(metadata.detailed_fields)
    if acquisition.targeted:
        if detailed:
            return (
                "moderate",
                "a safe source boundary limits enumeration; detailed metadata is required for "
                + ", ".join(detailed)
                + " unless a fresh cache entry can satisfy it",
            )
        return "moderate", "a safe source boundary limits enumeration and no authoritative detailed fields are required"
    if not detailed and selected_facet_capabilities(source).cheaply_enumerates_identities:
        return (
            "high",
            "the complete source boundary must be enumerated, but its required fields are authoritative in lightweight metadata",
        )
    return (
        "very-high",
        "no safe source boundary exists; the boundary must be fully enumerated and stale or missing detailed metadata refreshed as required",
    )


def plan_source_boundaries(
    query: Query,
    *,
    requests: tuple[tuple[str, str | None], ...],
    sources: tuple[SourceSpec, ...],
    dates: DateContext,
) -> tuple[SourceBoundaryPlan, ...]:
    """Build an independent conservative physical plan for every unique source/facet request."""
    source_map = {request: source for request, source in zip(requests, sources, strict=True)}
    cte_dependencies = plan_cte_dependencies(query)
    grouped: dict[tuple[str, str | None], list[tuple[Query, str | None]]] = {request: [] for request in requests}
    for source_name, facet, branch, owner_cte in _physical_query_uses(query):
        grouped.setdefault((source_name, facet), []).append((branch, owner_cte))

    result: list[SourceBoundaryPlan] = []
    for request in requests:
        source = source_map[request]
        uses = grouped.get(request, [])
        if not uses:
            continue
        predicate = _or_predicates(tuple(use.predicate for use, _owner in uses))
        use_fields: list[frozenset[str]] = []
        for use, owner in uses:
            dependency = cte_dependencies.for_cte(owner) if owner is not None else None
            if dependency is not None and dependency.pruning_applied and not use.set_operations:
                use_fields.append(dependency.input_fields)
            else:
                use_fields.append(frozenset(required_query_fields(use)))
        fields = frozenset().union(*use_fields)
        synthetic = replace(uses[0][0], predicate=predicate)
        # Ensure repeated uses contribute all physical field needs without pushing one use's
        # projection or grouping requirements into another use's predicate semantics.
        properties = analyse_query(synthetic, source=source)
        metadata = plan_metadata_requirements(synthetic, source=source)
        if fields != properties.required_fields:
            enum = frozenset(
                field for field in fields if selected_facet_capabilities(source).field(field).ytdlp_flat == EXACT
            )
            detailed = fields - enum
            metadata = MetadataRequirementPlan(
                enum,
                detailed,
                metadata.predicate_enumeration_fields,
                metadata.predicate_detailed_fields,
                "source-boundary requirements union every field needed by all logical uses of this source/facet",
            )
        stages = plan_predicate_stages(synthetic, source=source)
        temporal = infer_temporal_bounds(predicate, dates)
        acquisition = plan_acquisition(
            synthetic, source_kind=source.kind, tab=source.facet or "videos", dates=dates, temporal_bounds=temporal
        )
        facet_caps = selected_facet_capabilities(source)
        if acquisition.targeted and (not facet_caps.stable_collection or facet_caps.trustworthy_order_field is None):
            acquisition = AcquisitionPlan(
                "full", "the selected source/facet does not declare stable trustworthy ordering for bounded acquisition"
            )
        truth = prove_predicate_truth(predicate, source=source)
        empty = predicate is not None and truth.proven and truth.truth != TRUTH_TRUE
        if empty:
            acquisition = AcquisitionPlan(
                "skip", "source/facet capabilities prove every logical use of this physical request is empty"
            )
            cost_class, cost_reason = "none", "the physical source/facet request is proven empty before acquisition"
        else:
            cost_class, cost_reason = _assess_source_boundary_cost(metadata, acquisition, source=source)
        result.append(
            SourceBoundaryPlan(
                request[0],
                request[1],
                source,
                len(uses),
                fields,
                predicate,
                stages.enumeration_terms,
                metadata,
                stages,
                temporal,
                acquisition,
                cost_class,
                cost_reason,
                (
                    METADATA_DETAILED
                    if metadata.requires_detailed_metadata
                    else METADATA_ENUMERATION
                    if fields
                    else METADATA_NONE
                ),
                facet_caps.stable_collection,
                facet_caps.trustworthy_order_field,
                acquisition.targeted,
                empty,
                truth.proof if empty else None,
                _collection_requirements(fields),
            )
        )
    return tuple(result)


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

    physical_required_fields = properties.required_fields
    boundary_override: SourceBoundaryPlan | None = None
    physical_requests = query_physical_source_requests(query)
    if query.ctes and len(physical_requests) == 1:
        boundaries = plan_source_boundaries(
            query,
            requests=physical_requests,
            sources=(source,),
            dates=dates,
        )
        if len(boundaries) == 1:
            boundary_override = boundaries[0]
            physical_required_fields = boundary_override.required_fields
            metadata_requirements = boundary_override.metadata_requirements
            predicate_stages = boundary_override.predicate_stages
            temporal_bounds = boundary_override.temporal_bounds
            acquisition = boundary_override.acquisition
    # A bounded newest-first scan is valid only when the selected adapter explicitly
    # declares a stable collection and trustworthy source order.
    if acquisition.targeted and (not facet.stable_collection or facet.trustworthy_order_field is None):
        acquisition = AcquisitionPlan(
            "full",
            "the selected source/facet does not declare stable trustworthy ordering for bounded acquisition",
        )
    truth = prove_predicate_truth(query.predicate, source=source)
    eliminated = truth.proven and truth.truth != TRUTH_TRUE
    elimination_proof = truth.proof if eliminated else None
    if boundary_override is not None:
        eliminated = boundary_override.branch_empty
        elimination_proof = boundary_override.elimination_proof if eliminated else None
    if eliminated:
        acquisition = AcquisitionPlan(
            "skip",
            "source/facet capabilities prove the WHERE predicate cannot evaluate TRUE",
        )
    limit = plan_limit_termination(query)
    if boundary_override is not None:
        cost_class, cost_reason = boundary_override.cost_class, boundary_override.cost_reason
    elif eliminated:
        cost_class, cost_reason = "none", "the source branch is proven empty before acquisition"
    else:
        cost_class, cost_reason = assess_cost(query, acquisition, source=source)
    request = PhysicalAcquisitionRequest(
        source=source,
        required_fields=physical_required_fields,
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
        elimination_proof,
    )
