"""Conservative acquisition planning for query-driven YouTube discovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from .dates import DateContext, parse_date_literal
from .query_model import Binary, Between, Field, InList, Literal, Query, Unary
from .query_properties import analyse_query, required_query_fields as required_query_fields
from .source_capabilities import EXACT, selected_facet_capabilities
from .source_model import SourceSpec


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


def _is_upload_date(field: Field) -> bool:
    return field.name.casefold() in {"upload_date", "date"}


def _literal_date(literal: Literal, context: DateContext) -> date | None:
    if isinstance(literal.value, date):
        return literal.value
    try:
        return parse_date_literal(str(literal.value), context)
    except ValueError:
        return None


def _lower_bound(node: Any, context: DateContext) -> date | None:
    """Return a date that the expression logically implies upload_date cannot precede.

    None means no safe lower bound can be proven. The function is intentionally conservative.
    """
    if node is None or isinstance(node, Unary):
        return None

    if isinstance(node, Between) and _is_upload_date(node.field) and not node.negated:
        return _literal_date(node.lower, context)

    if isinstance(node, InList) and _is_upload_date(node.field) and not node.negated:
        values = [_literal_date(item, context) for item in node.values]
        if not values or any(item is None for item in values):
            return None
        return min(item for item in values if item is not None)

    if isinstance(node, Binary) and node.operator in {"AND", "OR"}:
        left = _lower_bound(node.left, context)
        right = _lower_bound(node.right, context)
        if node.operator == "AND":
            if left is None:
                return right
            if right is None:
                return left
            return max(left, right)
        if left is None or right is None:
            return None
        return min(left, right)

    if isinstance(node, Binary) and isinstance(node.left, Field) and _is_upload_date(node.left):
        value = _literal_date(node.right, context)
        if value is None:
            return None
        if node.operator in {">=", "="}:
            return value
        if node.operator == ">":
            return value + timedelta(days=1)
    return None


def plan_acquisition(query: Query, *, source_kind: str, tab: str, dates: DateContext) -> AcquisitionPlan:
    """Choose a bounded lazy scan only where source order and the predicate make it safe."""
    if query.set_operations or any(cte.query.set_operations for cte in query.ctes):
        return AcquisitionPlan("full", "UNION composition is acquired conservatively per physical source")
    if source_kind != "channel":
        return AcquisitionPlan("full", "playlists are not assumed to be ordered by upload date")
    if tab != "videos":
        return AcquisitionPlan("full", f"the {tab!r} channel tab is not assumed to have safe upload-date ordering")

    lower = _lower_bound(query.predicate, dates)
    if lower is None:
        return AcquisitionPlan("full", "the WHERE expression does not imply a safe lower upload-date bound")

    return AcquisitionPlan(
        "bounded-date",
        "the query implies a lower upload-date bound on a newest-first channel feed",
        lower_date_bound=lower,
        stop_before=lower - timedelta(days=APPROXIMATE_DATE_MARGIN_DAYS),
    )


def assess_cost(query: Query, plan: AcquisitionPlan) -> tuple[str, str]:
    """Classify the actual acquisition plan using the explicit capability model."""
    fields = required_query_fields(query)
    detailed_only = sorted(
        field for field in fields if analyse_query(query).field_capability(field).ytdlp_flat != EXACT
    )
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
            "a safe source boundary limits enumeration and fresh cached metadata may avoid detailed extraction",
        )
    return (
        "very-high",
        (
            "no safe source boundary exists; the source must be fully enumerated and stale or missing "
            "detailed metadata refreshed as required"
        ),
    )


@dataclass(frozen=True)
class PhysicalAcquisitionRequest:
    """Source-adapter input derived from semantic requirements and source policy."""

    source: SourceSpec
    required_fields: frozenset[str]
    mode: str
    lower_date_bound: date | None
    stop_before: date | None


@dataclass(frozen=True)
class QueryPlan:
    """Typed boundary between logical optimisation and physical acquisition."""

    query: Query
    properties: object
    acquisition: AcquisitionPlan
    physical_request: PhysicalAcquisitionRequest
    limit_termination: LimitTerminationPlan
    cost_class: str
    cost_reason: str


def plan_query(query: Query, *, source: SourceSpec, dates: DateContext) -> QueryPlan:
    """Build the source-aware plan consumed by acquisition orchestration.

    The logical optimiser remains source-independent. This boundary is the first point
    where a resolved query is combined with an adapter/facet capability contract.
    """
    properties = analyse_query(query, source=source)
    facet = selected_facet_capabilities(source)
    acquisition = plan_acquisition(
        query,
        source_kind=source.kind,
        tab=source.facet or "videos",
        dates=dates,
    )
    # A bounded newest-first scan is valid only when the selected adapter explicitly
    # declares a stable collection and trustworthy source order.
    if acquisition.targeted and (not facet.stable_collection or facet.trustworthy_order_field is None):
        acquisition = AcquisitionPlan(
            "full",
            "the selected source/facet does not declare stable trustworthy ordering for bounded acquisition",
        )
    limit = plan_limit_termination(query)
    cost_class, cost_reason = assess_cost(query, acquisition)
    request = PhysicalAcquisitionRequest(
        source=source,
        required_fields=properties.required_fields,
        mode=acquisition.mode,
        lower_date_bound=acquisition.lower_date_bound,
        stop_before=acquisition.stop_before,
    )
    return QueryPlan(query, properties, acquisition, request, limit, cost_class, cost_reason)
