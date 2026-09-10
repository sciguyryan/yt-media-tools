"""Explain and analyse-plan presentation for yt-discover."""

from __future__ import annotations

from yt_media_tools.cache import CacheStats, SourceCoverage
from yt_media_tools.capabilities import capabilities_for_fields
from yt_media_tools.dates import DateContext
from yt_media_tools.discover_constants import PROGRAM_VERSION
from yt_media_tools.planner import (
    AcquisitionPlan,
    assess_cost,
    plan_acquisition,
    plan_limit_termination,
    required_query_fields,
)
from yt_media_tools.optimizer import optimise_query
from yt_media_tools.query import (
    Query,
    QuerySchema,
    QuerySyntaxError,
    SelectTerm,
    explain_expression,
    format_expression,
    format_query,
    format_scalar_expression,
    parse_query,
    query_physical_source_requests,
    resolve_query,
)
from yt_media_tools.sources import SourceSpec, resolve_source_request, source_capabilities
from yt_media_tools.ytdlp import AcquisitionStats, EnumerationStats

def explain_user_query(query_text: str, *, source_type: str, tab: str, date_format: str, offline: bool = False) -> str:
    """Explain query semantics, field capabilities, and safe acquisition optimisations."""
    query = parse_query(query_text)
    source_requests = query_physical_source_requests(query)
    source_inputs = tuple(item for item, _facet in source_requests)
    if not source_inputs:
        raise ValueError("--explain requires a complete query containing a physical FROM <source>")
    explained_sources = [
        resolve_source_request(item, facet=facet, source_type=source_type, tab=tab) for item, facet in source_requests
    ]
    source_input = source_inputs[0]
    source = explained_sources[0]
    dates = DateContext(date_order=date_format)
    schema = QuerySchema(())

    if len(source_inputs) == 1:
        lines = [
            "Query explanation",
            "",
            "Source",
            f"  Type: {source.kind}",
            f"  Input: {source_input}",
            f"  Resolved URL: {source.canonical_url}",
        ]
        capabilities = source_capabilities(source)
        lines.append(f"  Adapter: {capabilities.adapter}")
        lines.append(f"  Advertised facets: {', '.join(capabilities.facets) if capabilities.facets else 'none'}")
        if source.facet is not None:
            lines.append(f"  Facet: {source.facet}")
        if source_requests[0][1] is None and tab != "all":
            lines.append(f"  Compatibility input: --tab {tab}")
    else:
        lines = ["Query explanation", "", "Sources"]
        for (item, request_facet), source_spec in zip(source_requests, explained_sources, strict=True):
            lines.append(f"  {item}: {source_spec.kind} -> {source_spec.canonical_url}")
            capabilities = source_capabilities(source_spec)
            lines.append(f"    Adapter: {capabilities.adapter}")
            lines.append(f"    Advertised facets: {', '.join(capabilities.facets) if capabilities.facets else 'none'}")
            if source_spec.facet is not None:
                lines.append(f"    Facet: {source_spec.facet}")
            if request_facet is None and tab != "all":
                lines.append(f"    Compatibility input: --tab {tab}")

    lines.extend(["", "Common table expressions"])
    if query.ctes:
        for cte in query.ctes:
            lines.append(f"  {cte.name}: {format_query(cte.query)}")
        lines.append(f"  Physical sources: {len(source_inputs)}.")
    else:
        lines.append("  None.")

    # Resolve using the known schema. Dynamic fields cannot be validated without metadata,
    # so explain their parsed form while making the deferred validation explicit.
    try:
        resolved = resolve_query(query, schema, dates)
        dynamic_deferred = False
    except QuerySyntaxError as exc:
        message = exc.message
        if message.startswith("Unknown field "):
            resolved = None
            dynamic_deferred = True
        else:
            raise

    optimisation = optimise_query(resolved) if resolved is not None else None

    lines.extend(["", "Projection"])
    if resolved is not None:
        for term in resolved.select:
            original = next(
                (
                    item
                    for item in (query.select or (SelectTerm("id"),))
                    if (item.alias or item.field) == term.output_name
                ),
                None,
            )
            detail = f"  {term.output_name}: {term.field} ({term.kind or 'unknown'})"
            if original is not None and original.field.casefold() != term.field.casefold():
                detail += f" [resolved from {original.field}]"
            lines.append(detail)
    else:
        for term in query.select or (SelectTerm("id"),):
            lines.append(f"  {term.output_name}: {term.field}")

    lines.extend(["", "Filter"])
    if query.predicate is None:
        lines.append("  None. All acquired entries qualify.")
    elif resolved is not None:
        lines.append(f"  {explain_expression(resolved.predicate)}")
    else:
        lines.append(f"  {format_query(Query(predicate=query.predicate))}")

    lines.extend(["", "Aggregation"])
    active_aggregate = bool(
        query.group_by
        or query.having is not None
        or any(
            any(name in term.field.upper() for name in ("COUNT(", "SUM(", "AVG(", "MIN(", "MAX("))
            for term in query.select + query.order_by
        )
    )
    if active_aggregate:
        if resolved is not None and resolved.group_by:
            lines.append("  GROUP BY: " + ", ".join(format_scalar_expression(item) for item in resolved.group_by))
        elif query.group_by:
            lines.append("  GROUP BY: " + ", ".join(format_scalar_expression(item) for item in query.group_by))
        else:
            lines.append("  GROUP BY: none; one global aggregate group is used.")
        active_having = resolved.having if resolved is not None else query.having
        lines.append(f"  HAVING: {format_expression(active_having) if active_having is not None else 'None'}")
        lines.append("  Early LIMIT acquisition: disabled; complete groups are required.")
    else:
        lines.append("  None.")

    lines.extend(["", "Predicate optimiser"])
    if optimisation is None:
        lines.append("  Deferred until dynamic metadata fields can be resolved.")
    elif optimisation.changed:
        lines.append(f"  Applied {len(optimisation.decisions)} semantics-preserving rewrite(s):")
        for decision in optimisation.decisions:
            lines.append(f"  [{decision.rule}] {decision.before} -> {decision.after}")
        if optimisation.query.predicate is not None:
            lines.append(f"  Optimised filter: {explain_expression(optimisation.query.predicate)}")
        else:
            lines.append("  Rewrites apply to predicates embedded in scalar expressions.")
    else:
        lines.append("  No semantics-preserving query rewrite was applicable.")

    lines.extend(["", "Ordering"])
    if resolved is not None and resolved.order_by:
        for term in resolved.order_by:
            lines.append(f"  {term.field} {'descending' if term.descending else 'ascending'}; NULL values last")
    elif query.order_by:
        for term in query.order_by:
            lines.append(f"  {term.field} {'descending' if term.descending else 'ascending'}; NULL values last")
    else:
        lines.append("  Source order is preserved.")

    lines.extend(
        [
            "",
            "Row shaping",
            f"  DISTINCT: {'yes' if query.distinct else 'no'}",
            f"  OFFSET: {query.offset}",
            f"  LIMIT: {query.limit if query.limit is not None else 'None'}",
        ]
    )

    required = required_query_fields(query)
    lines.extend(["", "Required fields"])
    for capability in capabilities_for_fields(required):
        lines.append(
            f"  {capability.field}: YouTube.js={capability.youtubejs}; "
            f"yt-dlp-flat={capability.ytdlp_flat}; yt-dlp-detailed={capability.ytdlp_detailed}"
        )

    plan = plan_acquisition(query, source_kind=source.kind, tab=(source.facet or tab), dates=dates)
    if len(source_inputs) > 1:
        plan = AcquisitionPlan(
            "full",
            "UNION composition spans multiple physical source/facet requests; each request is acquired independently before logical reconciliation",
        )
    if offline:
        plan = AcquisitionPlan("offline-cache", "offline mode uses cached detailed metadata only")
        cost_class, cost_reason = "local", "no network acquisition is permitted; only cached records are evaluated"
    else:
        cost_class, cost_reason = assess_cost(query, plan)
    lines.extend(
        [
            "",
            "Acquisition plan",
            f"  Strategy: {plan.mode}",
            f"  Reason: {plan.reason}",
        ]
    )
    if plan.targeted:
        lines.append(f"  Safe lower upload-date boundary: {plan.lower_date_bound.isoformat()}")
        lines.append(f"  Conservative enumeration stop threshold: {plan.stop_before.isoformat()}")
        lines.append(f"  Boundary confirmations required: {plan.confirmation_entries}")

    lines.extend(["", "Optimisation paths"])
    if offline:
        lines.extend(
            [
                "  [active] Cache-only execution",
                "           Source enumeration and detailed metadata refresh are disabled.",
                "  [inactive] Network acquisition optimisations",
                "             Bounded enumeration and backend selection do not run in offline mode.",
            ]
        )
    elif plan.targeted:
        lines.extend(
            [
                "  [active] Bounded channel enumeration",
                "           The newest-first videos feed can stop after the conservative date boundary is confirmed.",
                "  [available] YouTube.js lightweight enumeration",
                "              Used automatically when installed and --backend permits it; yt-dlp flat enumeration is the fallback.",
                "  [active] Conservative lightweight predicate rejection",
                "           Exact ID/title predicates and provable upload-date interval failures may reject candidates before detailed extraction.",
                "  [active] Upper date-bound pruning when provable",
                "           Candidates provably newer than an upper upload-date condition are also rejected before detailed extraction.",
            ]
        )
    else:
        lines.extend(
            [
                "  [unavailable] Bounded channel enumeration",
                f"                {plan.reason}.",
                "  [conditional] Incremental channel frontier",
                "                Eligible channel /videos full-source queries can stop after conservative overlap with a trusted persisted source ordering.",
                "  [unavailable] Conservative lightweight predicate rejection",
                "                Lightweight rejection is available for entries observed during lightweight enumeration; cached historical entries are evaluated authoritatively.",
            ]
        )
    limit_plan = plan_limit_termination(query)
    if len(source_inputs) > 1 and limit_plan.eligible:
        limit_plan = type(limit_plan)(
            False,
            "multi-source UNION requires complete branch acquisition before global LIMIT",
            limit_plan.limit,
        )
    if query.limit is None:
        lines.append("  [not applicable] LIMIT-aware acquisition termination: query has no LIMIT.")
    elif offline:
        lines.append(
            "  [inactive] LIMIT-aware acquisition termination: offline execution performs no metadata acquisition."
        )
    elif limit_plan.eligible:
        lines.extend(
            [
                "  [active] LIMIT-aware acquisition termination",
                f"           {limit_plan.reason}.",
                "           Detailed metadata is acquired in source-order batches and may stop once LIMIT authoritative matches exist.",
            ]
        )
    else:
        lines.extend(
            [
                "  [unavailable] LIMIT-aware acquisition termination",
                f"                {limit_plan.reason}.",
            ]
        )

    lines.extend(
        [
            "",
            "Cache plan",
            *(
                [
                    "  Offline execution: query cached detailed metadata only.",
                    "  Missing records: cannot be acquired.",
                    "  Stale required fields: reported and used without refresh.",
                    "  Source completeness: reported explicitly from persisted coverage state when available.",
                ]
                if offline
                else [
                    "  Normal execution: consult the persistent metadata cache after source enumeration.",
                    "  Fresh required fields: reuse cached yt-dlp metadata.",
                    "  Missing or stale required fields: refresh that video's detailed metadata with yt-dlp.",
                    "  Source completeness: not inferred from cache rows.",
                    "  Incremental frontier: for eligible channel /videos full-source queries, a trusted persisted source ordering may stop enumeration after conservative known-ID overlap.",
                ]
            ),
            "",
            "Detailed metadata",
            f"  Required: {'cached only' if offline else 'yes'}",
            f"  Reason: {'offline mode never refreshes metadata' if offline else 'final WHERE evaluation and selected metadata remain authoritative yt-dlp operations'}.",
            "",
            "Estimated cost",
            f"  {cost_class}",
            f"  {cost_reason}",
        ]
    )

    selected_count = len(query.select) if query.select else 1
    lines.extend(
        [
            "",
            "Output",
            f"  Selected scalar fields: {selected_count}",
            f"  Default serialisation: {'lines' if selected_count == 1 else 'jsonl'}",
        ]
    )
    lines.extend(
        ["", "Temporal context", f"  TODAY() = {dates.today.isoformat()}", f"  NOW() = {dates.local_now.isoformat()}"]
    )
    if dynamic_deferred:
        lines.extend(
            [
                "",
                "Deferred validation",
                "  One or more fields are dynamic yt-dlp metadata fields and can only be type-checked after metadata acquisition.",
            ]
        )
    return "\n".join(lines)

def explain_user_query_json(
    query_text: str, *, source_type: str, tab: str, date_format: str, offline: bool = False
) -> dict[str, object]:
    """Return a machine-readable offline query plan for D16."""
    query = parse_query(query_text)
    source_requests = query_physical_source_requests(query)
    source_inputs = tuple(item for item, _facet in source_requests)
    if not source_inputs:
        raise ValueError("--explain requires a complete query containing a physical FROM <source>")
    explained_sources = [
        resolve_source_request(item, facet=facet, source_type=source_type, tab=tab) for item, facet in source_requests
    ]
    source_input = source_inputs[0]
    source = explained_sources[0]
    dates = DateContext(date_order=date_format)
    required = sorted(required_query_fields(query))
    plan = plan_acquisition(query, source_kind=source.kind, tab=(source.facet or tab), dates=dates)
    if offline:
        plan = AcquisitionPlan("offline-cache", "offline mode uses cached detailed metadata only")
        cost_class, cost_reason = "local", "no network acquisition is permitted; only cached records are evaluated"
    else:
        cost_class, cost_reason = assess_cost(query, plan)

    try:
        resolved_for_optimiser = resolve_query(query, QuerySchema(()), dates)
        optimiser_result = optimise_query(resolved_for_optimiser)
        optimiser_payload: dict[str, object] = {
            "status": "active",
            "changed": optimiser_result.changed,
            "rewrites": [
                {"rule": item.rule, "before": item.before, "after": item.after} for item in optimiser_result.decisions
            ],
            "optimised_query": format_query(optimiser_result.query),
        }
    except QuerySyntaxError as exc:
        if not exc.message.startswith("Unknown field "):
            raise
        optimiser_payload = {
            "status": "deferred",
            "changed": None,
            "rewrites": [],
            "reason": "dynamic metadata fields require post-acquisition type resolution",
        }

    return {
        "kind": "yt-discover-explain",
        "version": PROGRAM_VERSION,
        "query": format_query(query),
        "ctes": [
            {
                "name": cte.name,
                "query": format_query(cte.query),
                "from": cte.query.from_source,
                "facet": cte.query.from_facet,
            }
            for cte in query.ctes
        ],
        "row_shaping": {"distinct": query.distinct, "offset": query.offset, "limit": query.limit},
        "aggregation": {
            "group_by": [format_scalar_expression(item) for item in query.group_by],
            "having": format_expression(query.having) if query.having is not None else None,
            "complete_groups_required": bool(
                query.group_by
                or query.having is not None
                or any(
                    any(name in term.field.upper() for name in ("COUNT(", "SUM(", "AVG(", "MIN(", "MAX("))
                    for term in query.select + query.order_by
                )
            ),
        },
        "predicate_optimiser": optimiser_payload,
        "source": {
            "type": source.kind,
            "input": source_input,
            "url": source.canonical_url,
            "tab": tab if source_requests[0][1] is None and tab != "all" else None,
            "facet": source.facet,
            "adapter": source_capabilities(source).adapter,
            "advertised_facets": list(source_capabilities(source).facets),
        },
        "sources": [
            {
                "type": source_spec.kind,
                "input": item,
                "url": source_spec.canonical_url,
                "tab": tab if request_facet is None and tab != "all" else None,
                "facet": source_spec.facet,
                "adapter": source_capabilities(source_spec).adapter,
                "advertised_facets": list(source_capabilities(source_spec).facets),
            }
            for (item, request_facet), source_spec in zip(source_requests, explained_sources, strict=True)
        ],
        "required_fields": [
            {
                "field": capability.field,
                "youtubejs": capability.youtubejs,
                "ytdlp_flat": capability.ytdlp_flat,
                "ytdlp_detailed": capability.ytdlp_detailed,
            }
            for capability in capabilities_for_fields(required)
        ],
        "acquisition": {
            "strategy": plan.mode,
            "reason": plan.reason,
            "lower_upload_date": plan.lower_date_bound.isoformat() if plan.lower_date_bound else None,
            "stop_before": plan.stop_before.isoformat() if plan.stop_before else None,
            "boundary_confirmations": plan.confirmation_entries if plan.targeted else None,
        },
        "cache": {
            "mode": "offline-cache-only" if offline else "cache-first-after-source-enumeration",
            "offline_supported": True,
            "source_completeness_inferred_from_rows": False,
        },
        "limit_aware_termination": {
            "applicable": query.limit is not None,
            "implemented": True,
            "eligible": (False if offline else plan_limit_termination(query).eligible),
            "reason": (
                "offline execution performs no metadata acquisition"
                if offline
                else plan_limit_termination(query).reason
            ),
            "scope": "source-order detailed metadata acquisition",
        },
        "cost": {"class": cost_class, "reason": cost_reason},
        "temporal_context": {
            "today": dates.today.isoformat(),
            "now": dates.local_now.isoformat(),
        },
    }

def _explain_analyze_payload(
    *,
    query: Query,
    source: SourceSpec,
    plan: AcquisitionPlan,
    requested_backend: str,
    selected_backend: str,
    fallback_reason: str,
    enumeration: EnumerationStats | None,
    acquisition: AcquisitionStats,
    cache: CacheStats,
    cache_enabled: bool,
    offline: bool,
    coverage: SourceCoverage | None,
    lightweight_rejected: int,
    detailed_candidates: int | None,
    query_input: int,
    matched_before_limit: int,
    emitted: int,
    acquisition_seconds: float,
    query_seconds: float,
    total_seconds: float,
    frontier_attempted: bool = False,
    frontier_confirmed: bool = False,
    frontier_new_entries: int = 0,
    limit_termination_eligible: bool = False,
    limit_terminated: bool = False,
    limit_batches: int = 0,
    limit_candidates_examined: int = 0,
) -> dict[str, object]:
    """Build machine-readable actual execution telemetry for B1/D16."""
    return {
        "kind": "yt-discover-explain-analyze",
        "version": PROGRAM_VERSION,
        "query": format_query(query),
        "row_shaping": {"distinct": query.distinct, "offset": query.offset, "limit": query.limit},
        "source": {"type": source.kind, "url": source.canonical_url},
        "plan": {"strategy": plan.mode, "reason": plan.reason},
        "actual": {
            "offline": offline,
            "requested_backend": requested_backend,
            "selected_backend": selected_backend,
            "fallback_reason": fallback_reason or None,
            "enumerated": enumeration.enumerated if enumeration is not None else 0,
            "enumeration_stopped_early": enumeration.stopped_early if enumeration is not None else False,
            "frontier": {
                "attempted": frontier_attempted,
                "confirmed": frontier_confirmed,
                "new_source_entries": frontier_new_entries,
                "full_enumeration_avoided": frontier_confirmed,
            },
            "limit_termination": {
                "eligible": limit_termination_eligible,
                "terminated_early": limit_terminated,
                "batches": limit_batches,
                "candidates_examined": limit_candidates_examined,
            },
            "lightweight_rejected": lightweight_rejected,
            "detailed_candidates": detailed_candidates,
            "metadata_available": acquisition.available,
            "metadata_skipped": acquisition.skipped,
            "cache": {
                "enabled": cache_enabled,
                "examined": cache.examined,
                "fresh_hits": cache.hits,
                "stale": cache.stale,
                "misses": cache.misses,
                "refreshed": cache.refreshed,
                "written": cache.written,
            },
            "coverage": None
            if coverage is None
            else {
                "complete": coverage.complete,
                "observed_at": coverage.observed_at.isoformat(),
                "observed_entries": coverage.observed_entries,
                "cached_entries": coverage.cached_entries,
                "reason": coverage.reason,
            },
            "query_input": query_input,
            "matched_before_limit": matched_before_limit,
            "emitted": emitted,
        },
        "timing_seconds": {
            "acquisition_or_cache": acquisition_seconds,
            "query": query_seconds,
            "total": total_seconds,
        },
    }

def _format_explain_analyze_text(payload: dict[str, object]) -> str:
    actual = payload["actual"]
    timing = payload["timing_seconds"]
    assert isinstance(actual, dict)
    assert isinstance(timing, dict)
    cache = actual["cache"]
    assert isinstance(cache, dict)
    lines = [
        "EXPLAIN ANALYZE",
        "",
        "Plan",
        f"  Strategy: {payload['plan']['strategy']}",
        f"  Reason: {payload['plan']['reason']}",
        "",
        "Actual execution",
        f"  Offline: {'yes' if actual['offline'] else 'no'}",
        f"  Backend: {actual['selected_backend']} (requested: {actual['requested_backend']})",
        f"  Entries enumerated: {actual['enumerated']}",
        f"  Enumeration stopped early: {'yes' if actual['enumeration_stopped_early'] else 'no'}",
        f"  Lightweight candidates rejected: {actual['lightweight_rejected']}",
        f"  Detailed candidates: {actual['detailed_candidates'] if actual['detailed_candidates'] is not None else 'n/a'}",
        f"  Metadata available from refresh: {actual['metadata_available']}",
        f"  Inaccessible/skipped during refresh: {actual['metadata_skipped']}",
        "",
        "Incremental frontier",
        f"  Attempted: {'yes' if actual['frontier']['attempted'] else 'no'}",
        f"  Overlap confirmed: {'yes' if actual['frontier']['confirmed'] else 'no'}",
        f"  New source entries: {actual['frontier']['new_source_entries']}",
        f"  Full enumeration avoided: {'yes' if actual['frontier']['full_enumeration_avoided'] else 'no'}",
        "",
        "LIMIT-aware acquisition",
        f"  Eligible: {'yes' if actual['limit_termination']['eligible'] else 'no'}",
        f"  Detailed acquisition stopped early: {'yes' if actual['limit_termination']['terminated_early'] else 'no'}",
        f"  Batches: {actual['limit_termination']['batches']}",
        f"  Candidates examined: {actual['limit_termination']['candidates_examined']}",
        "",
        "Cache outcome",
        f"  Records examined: {cache['examined']}",
        f"  Fresh hits: {cache['fresh_hits']}",
        f"  Stale entries: {cache['stale']}",
        f"  Misses: {cache['misses']}",
        f"  Refreshed: {cache['refreshed']}",
        f"  Written: {cache['written']}",
        "",
        "Result statistics",
        f"  DISTINCT: {'yes' if payload['row_shaping']['distinct'] else 'no'}",
        f"  OFFSET: {payload['row_shaping']['offset']}",
        f"  LIMIT: {payload['row_shaping']['limit'] if payload['row_shaping']['limit'] is not None else 'None'}",
        f"  Records evaluated by WHERE: {actual['query_input']}",
        f"  Matched before LIMIT: {actual['matched_before_limit']}"
        + (
            " (at least; acquisition stopped after LIMIT was satisfied)"
            if actual["limit_termination"]["terminated_early"]
            else ""
        ),
        f"  Rows that would be emitted: {actual['emitted']}",
        "",
        "Timing",
        f"  Acquisition/cache phase: {timing['acquisition_or_cache']:.3f}s",
        f"  Query evaluation: {timing['query']:.3f}s",
        f"  Total: {timing['total']:.3f}s",
    ]
    if actual.get("fallback_reason"):
        lines.insert(8, f"  Fallback: {actual['fallback_reason']}")
    coverage = actual.get("coverage")
    if isinstance(coverage, dict):
        lines.extend(
            [
                "",
                "Source coverage",
                f"  Complete at last observation: {'yes' if coverage['complete'] else 'no'}",
                f"  Observed at: {coverage['observed_at']}",
                f"  Cached/observed records: {coverage['cached_entries']}/{coverage['observed_entries']}",
                f"  Reason: {coverage['reason']}",
            ]
        )
    else:
        lines.extend(["", "Source coverage", "  Unknown"])
    return "\n".join(lines)

