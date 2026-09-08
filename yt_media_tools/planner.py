"""Conservative acquisition planning for query-driven YouTube discovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from .dates import DateContext, parse_date_literal
from .query import (
    AggregateFunction,
    Between,
    Binary,
    Field,
    InList,
    Literal,
    Query,
    ScalarBinary,
    ScalarCase,
    ScalarComparison,
    ScalarFunction,
    ScalarIsNull,
    ScalarUnary,
    Unary,
)
from .schema import ALIASES, KNOWN_FIELD_TYPES


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

    This first implementation is intentionally narrow. With no explicit ORDER BY,
    yt-discover preserves source order, so once N authoritative matches have been
    observed no later row can enter the first N results. Dynamic fields are deferred
    because their types cannot be proven before detailed metadata is observed.
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
    if (
        query.group_by
        or query.having is not None
        or any(_contains_aggregate_expression(term.expression) for term in query.select + query.order_by)
    ):
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
    if query.offset:
        return LimitTerminationPlan(
            False,
            "OFFSET requires skipping matching rows before LIMIT and is not yet part of the early-termination proof",
            query.limit,
        )
    fields = required_query_fields(query)
    dynamic = sorted(
        field for field in fields if field.casefold() not in KNOWN_FIELD_TYPES and field.casefold() not in ALIASES
    )
    if dynamic:
        return LimitTerminationPlan(
            False,
            "dynamic fields require post-acquisition schema resolution: " + ", ".join(dynamic),
            query.limit,
        )
    return LimitTerminationPlan(
        True,
        "source order is the final result order, so acquisition may stop after the requested number of authoritative matches",
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


def _fields_in_node(node: Any) -> set[str]:
    """Return field names referenced by a predicate node."""
    if node is None:
        return set()
    if isinstance(node, Unary):
        return _fields_in_node(node.operand)
    if isinstance(node, Binary) and node.operator in {"AND", "OR"}:
        return _fields_in_node(node.left) | _fields_in_node(node.right)
    field = getattr(node, "field", None)
    if isinstance(field, Field):
        return {field.name.casefold()}
    if isinstance(node, Binary) and isinstance(node.left, Field):
        return {node.left.name.casefold()}
    return set()


def _fields_in_scalar_expression(expression: Any) -> set[str]:
    """Return field names referenced by a scalar expression."""
    if expression is None:
        return set()
    if isinstance(expression, Field):
        return {expression.name.casefold()}
    if isinstance(expression, ScalarUnary):
        return _fields_in_scalar_expression(expression.operand)
    if isinstance(expression, ScalarBinary):
        return _fields_in_scalar_expression(expression.left) | _fields_in_scalar_expression(expression.right)
    if isinstance(expression, AggregateFunction):
        fields: set[str] = set()
        for arg in expression.args:
            fields.update(_fields_in_scalar_expression(arg))
        fields.update(_fields_in_node(expression.filter_predicate))
        return fields
    if isinstance(expression, ScalarFunction):
        fields: set[str] = set()
        for arg in expression.args:
            fields.update(_fields_in_scalar_expression(arg))
        return fields
    if isinstance(expression, ScalarCase):
        fields: set[str] = set()
        for branch in expression.whens:
            fields.update(_fields_in_node(branch.condition))
            fields.update(_fields_in_scalar_expression(branch.result))
        fields.update(_fields_in_scalar_expression(expression.else_result))
        return fields
    return set()


def _contains_aggregate_expression(expression: Any) -> bool:
    if isinstance(expression, AggregateFunction):
        return True
    if isinstance(expression, ScalarUnary):
        return _contains_aggregate_expression(expression.operand)
    if isinstance(expression, ScalarBinary):
        return _contains_aggregate_expression(expression.left) or _contains_aggregate_expression(expression.right)
    if isinstance(expression, ScalarFunction):
        return any(_contains_aggregate_expression(arg) for arg in expression.args)
    if isinstance(expression, ScalarCase):
        return any(_contains_aggregate_expression(branch.result) for branch in expression.whens) or (
            expression.else_result is not None and _contains_aggregate_expression(expression.else_result)
        )
    return False


def _fields_in_having(node: Any) -> set[str]:
    if node is None:
        return set()
    if isinstance(node, Unary):
        return _fields_in_having(node.operand)
    if isinstance(node, Binary) and node.operator in {"AND", "OR"}:
        return _fields_in_having(node.left) | _fields_in_having(node.right)
    if isinstance(node, ScalarComparison):
        return _fields_in_scalar_expression(node.left) | _fields_in_scalar_expression(node.right)
    if isinstance(node, ScalarIsNull):
        return _fields_in_scalar_expression(node.expression)
    return set()


def _required_body_fields(query: Query) -> set[str]:
    """Return fields referenced by one query body, excluding nested CTE relations."""
    fields = _fields_in_node(query.predicate)
    for term in query.order_by:
        if term.expression is not None:
            fields.update(_fields_in_scalar_expression(term.expression))
        else:
            fields.add(term.field.casefold())
    for term in query.select or ():
        if term.expression is not None:
            fields.update(_fields_in_scalar_expression(term.expression))
        else:
            fields.add(term.field.casefold())
    for expression in query.group_by:
        fields.update(_fields_in_scalar_expression(expression))
    fields.update(_fields_in_having(query.having))
    if not query.select:
        fields.add("id")
    return fields


def required_query_fields(query: Query) -> set[str]:
    """Return physical-source fields needed by a query, CTEs, and UNION branches."""
    cte_names = {cte.name.casefold() for cte in query.ctes}
    fields: set[str] = set()

    def visit(candidate: Query) -> None:
        if (candidate.from_source or "").casefold() not in cte_names:
            fields.update(_required_body_fields(candidate))
        for operation in candidate.set_operations:
            visit(operation.query)

    for cte in query.ctes:
        visit(cte.query)
    visit(query)
    return fields


def assess_cost(query: Query, plan: AcquisitionPlan) -> tuple[str, str]:
    """Classify the actual acquisition plan using the explicit capability model."""
    from .capabilities import EXACT, field_capability

    fields = required_query_fields(query)
    detailed_only = sorted(field for field in fields if field_capability(field).ytdlp_flat != EXACT)
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
