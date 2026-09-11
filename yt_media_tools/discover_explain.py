"""Explain and analyse-plan presentation for yt-discover."""

from __future__ import annotations

from yt_media_tools.cache import CacheStats, SourceCoverage
from yt_media_tools.cte_dependencies import plan_cte_dependencies
from yt_media_tools.capabilities import capabilities_for_fields
from yt_media_tools.dates import DateContext
from yt_media_tools.explain_presentation import (
    EXPLANATION_SCHEMA_VERSION,
    build_explain_graph,
    explain_decisions,
    graph_to_json,
    render_console_overview,
)
from yt_media_tools.discover_constants import PROGRAM_VERSION
from yt_media_tools.planner import (
    AcquisitionPlan,
    assess_cost,
    plan_acquisition,
    plan_limit_termination,
    plan_metadata_requirements,
    plan_source_boundaries,
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
from yt_media_tools.staged_predicates import plan_predicate_stages
from yt_media_tools.temporal_bounds import infer_temporal_bounds
from yt_media_tools.sources import SourceSpec, resolve_source_request, source_capabilities
from yt_media_tools.ytdlp import AcquisitionStats, EnumerationStats, lower_acquisition_plan_to_ytdlp


def _optimiser_explain_payload(
    optimisation: object | None,
    *,
    deferred_reason: str | None = None,
) -> dict[str, object]:
    """Build the stable optimiser subsection used by text and JSON explain."""
    if optimisation is None:
        return {
            "status": "deferred",
            "changed": None,
            "rewrites": [],
            "reason": deferred_reason or "dynamic metadata fields require post-acquisition type resolution",
        }

    decisions = getattr(optimisation, "decisions")
    query = getattr(optimisation, "query")
    return {
        "status": "active",
        "changed": bool(getattr(optimisation, "changed")),
        "rewrites": [
            {
                "rule": item.rule,
                "before": item.before,
                "after": item.after,
            }
            for item in decisions
        ],
        "optimised_query": format_query(query),
    }


def _presentation_input(
    *,
    query: Query,
    optimiser_payload: dict[str, object],
    predicate_stages: object,
    source_boundaries: tuple[object, ...],
    limit_plan: object,
    cte_dependencies: object,
    offline: bool,
) -> dict[str, object]:
    """Project planner state into the renderer-facing explanation subset."""
    return {
        "query": format_query(query),
        "predicate_optimiser": optimiser_payload,
        "predicate_stages": {
            "enumeration_terms": [format_expression(term) for term in getattr(predicate_stages, "enumeration_terms")],
            "residual_terms": [format_expression(term) for term in getattr(predicate_stages, "residual_terms")],
            "reason": getattr(predicate_stages, "reason"),
        },
        "source_boundaries": [
            {
                "source": getattr(boundary, "source_name"),
                "facet": getattr(boundary, "facet"),
                "acquisition_stages": [
                    {
                        "name": stage.name,
                        "required": stage.required,
                        "fields": sorted(stage.fields),
                        "reason": stage.reason,
                    }
                    for stage in getattr(
                        boundary,
                        "physical_acquisition",
                    ).stages
                ],
                "pre_acquisition_predicates": [
                    format_expression(term) for term in getattr(boundary, "pre_acquisition_predicates")
                ],
                "acquisition": getattr(boundary, "acquisition").mode,
                "acquisition_reason": getattr(boundary, "acquisition").reason,
                "cost_class": getattr(boundary, "cost_class"),
                "heuristics": {
                    "cost_tier": getattr(boundary, "heuristics").cost_tier,
                    "selectivity_tier": getattr(
                        boundary,
                        "heuristics",
                    ).selectivity_tier,
                    "information_value_tier": getattr(
                        boundary,
                        "heuristics",
                    ).information_value_tier,
                    "deferred_expensive_stages": list(
                        getattr(
                            boundary,
                            "heuristics",
                        ).deferred_expensive_stages
                    ),
                    "reason": getattr(boundary, "heuristics").reason,
                },
                "branch_empty": getattr(boundary, "branch_empty"),
            }
            for boundary in source_boundaries
        ],
        "limit_aware_termination": {
            "applicable": query.limit is not None,
            "eligible": False if offline else bool(getattr(limit_plan, "eligible")),
            "reason": (
                "offline execution performs no metadata acquisition" if offline else getattr(limit_plan, "reason")
            ),
            "mode": "none" if offline else getattr(limit_plan, "mode"),
        },
        "cte_dependencies": [
            {
                "name": dependency.name,
                "pruned_outputs": sorted(dependency.pruned_outputs),
                "pruning_applied": dependency.pruning_applied,
                "reason": dependency.reason,
            }
            for dependency in getattr(cte_dependencies, "dependencies")
        ],
    }


def explain_user_query(
    query_text: str,
    *,
    source_type: str,
    tab: str,
    date_format: str,
    offline: bool = False,
    unicode: bool = True,
    colour: bool = False,
) -> str:
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
    lines.extend(["", "Logical required fields"])
    for capability in capabilities_for_fields(required):
        lines.append(
            f"  {capability.field}: YouTube.js={capability.youtubejs}; "
            f"yt-dlp-flat={capability.ytdlp_flat}; yt-dlp-detailed={capability.ytdlp_detailed}"
        )
    metadata_requirements = plan_metadata_requirements(query, source=source)
    lines.extend(
        [
            "",
            "Logical metadata requirements",
            "  Enumeration: " + (", ".join(sorted(metadata_requirements.enumeration_fields)) or "none"),
            "  Detailed: " + (", ".join(sorted(metadata_requirements.detailed_fields)) or "none"),
            "  Predicate enumeration: "
            + (", ".join(sorted(metadata_requirements.predicate_enumeration_fields)) or "none"),
            "  Predicate detailed: " + (", ".join(sorted(metadata_requirements.predicate_detailed_fields)) or "none"),
            f"  Reason: {metadata_requirements.reason}",
        ]
    )
    predicate_stages = plan_predicate_stages(query, source=source)
    temporal_bounds = infer_temporal_bounds(query.predicate, dates)
    lines.extend(
        [
            "",
            "Predicate stages",
            "  Enumeration: "
            + (" AND ".join(format_expression(term) for term in predicate_stages.enumeration_terms) or "none"),
            "  Residual: "
            + (" AND ".join(format_expression(term) for term in predicate_stages.residual_terms) or "none"),
            "  Enumeration fields: " + (", ".join(sorted(predicate_stages.enumeration_fields)) or "none"),
            "  Residual fields: " + (", ".join(sorted(predicate_stages.residual_fields)) or "none"),
            f"  Reason: {predicate_stages.reason}",
        ]
    )
    if predicate_stages.enumeration_heuristics:
        lines.extend(["", "Predicate cost/selectivity heuristics"])
        for index, (term, heuristic) in enumerate(
            zip(
                predicate_stages.enumeration_terms,
                predicate_stages.enumeration_heuristics,
                strict=True,
            ),
            1,
        ):
            lines.append(
                f"  {index}. {format_expression(term)}: "
                f"selectivity={heuristic.selectivity}; "
                f"local-cost={heuristic.evaluation_cost}; "
                f"information-value={heuristic.information_value}"
            )
            lines.append(f"     Reason: {heuristic.reason}")
        lines.append("  Evaluation order changed: " + ("yes" if predicate_stages.heuristic_order_changed else "no"))

    lines.extend(["", "Temporal bounds"])
    if temporal_bounds.fields:
        for item in temporal_bounds.fields:
            lower = (
                "none"
                if item.lower is None
                else ((">=" if item.lower.inclusive else ">") + " " + item.lower.value.isoformat())
            )
            upper = (
                "none"
                if item.upper is None
                else (("<=" if item.upper.inclusive else "<") + " " + item.upper.value.isoformat())
            )
            lines.append(f"  {item.field}: lower {lower}; upper {upper}")
    else:
        lines.append("  none")
    lines.append(f"  Reason: {temporal_bounds.reason}")

    plan = plan_acquisition(
        query,
        source_kind=source.kind,
        tab=(source.facet or tab),
        dates=dates,
        temporal_bounds=temporal_bounds,
    )
    if len(source_inputs) > 1:
        plan = AcquisitionPlan(
            "full",
            "UNION composition spans multiple physical source/facet requests; each request is acquired independently before logical reconciliation",
        )
    if offline:
        plan = AcquisitionPlan("offline-cache", "offline mode uses cached detailed metadata only")
        cost_class, cost_reason = "local", "no network acquisition is permitted; only cached records are evaluated"
    else:
        cost_class, cost_reason = assess_cost(query, plan, source=source)
    source_boundaries = plan_source_boundaries(
        query, requests=source_requests, sources=tuple(explained_sources), dates=dates
    )
    cte_dependencies = plan_cte_dependencies(query)
    if len(source_boundaries) == 1:
        physical = source_boundaries[0]
        lines.extend(["", "Physical metadata requirements"])
        lines.append("  Required fields: " + (", ".join(sorted(physical.required_fields)) or "none"))
        lines.append(
            "  Enumeration: " + (", ".join(sorted(physical.metadata_requirements.enumeration_fields)) or "none")
        )
        lines.append("  Detailed: " + (", ".join(sorted(physical.metadata_requirements.detailed_fields)) or "none"))
        lines.append(f"  Reason: {physical.metadata_requirements.reason}")
    if source_boundaries:
        lines.extend(["", "Metadata acquisition stages"])
        for boundary in source_boundaries:
            facet_text = f" OF {boundary.facet}" if boundary.facet is not None else ""
            lowering = lower_acquisition_plan_to_ytdlp(boundary.physical_acquisition)
            lines.append(f"  {boundary.source_name}{facet_text}")
            for stage in boundary.physical_acquisition.stages:
                status = "required" if stage.required else "not required"
                fields = ", ".join(sorted(stage.fields)) or "none"
                lines.append(f"    {stage.name}: {status}; fields={fields}; {stage.reason}")
            lines.append(f"    yt-dlp lowering: {lowering.reason}")
            if lowering.collapsed_detailed_stages:
                lines.append(
                    "    Collapsed into detailed JSON extraction: " + ", ".join(lowering.collapsed_detailed_stages)
                )

    if source_boundaries:
        lines.extend(["", "Cost and selectivity heuristics"])
        for boundary in source_boundaries:
            facet_text = f" OF {boundary.facet}" if boundary.facet is not None else ""
            lines.append(
                f"  {boundary.source_name}{facet_text}: "
                f"cost={boundary.heuristics.cost_tier}; "
                f"selectivity={boundary.heuristics.selectivity_tier}; "
                f"information-value={boundary.heuristics.information_value_tier}"
            )
            if boundary.heuristics.deferred_expensive_stages:
                lines.append(
                    "    Deferred until cheap filters survive: "
                    + ", ".join(boundary.heuristics.deferred_expensive_stages)
                )
            lines.append(f"    Reason: {boundary.heuristics.reason}")

    if source_boundaries:
        simplified = [
            boundary for boundary in source_boundaries if boundary.eliminated_uses or boundary.redundant_where_uses
        ]
        if simplified:
            lines.extend(["", "Static relation simplification"])
            for boundary in simplified:
                facet_text = f" OF {boundary.facet}" if boundary.facet is not None else ""
                lines.append(
                    f"  {boundary.source_name}{facet_text}: "
                    f"eliminated uses={boundary.eliminated_uses}; "
                    f"redundant WHERE filters={boundary.redundant_where_uses}; "
                    f"source acquisition={boundary.acquisition.mode}"
                )
                for relation in boundary.relation_simplifications:
                    if relation.empty or relation.where_redundant or relation.having_redundant:
                        lines.append(f"    Reason: {relation.reason}")
    if cte_dependencies.dependencies:
        lines.extend(["", "CTE dependency propagation"])
        for dependency in cte_dependencies.dependencies:
            lines.append(
                f"  {dependency.name}: required outputs={', '.join(sorted(dependency.required_outputs)) or 'none'}; "
                f"input fields={', '.join(sorted(dependency.input_fields)) or 'none'}; "
                f"pruned outputs={', '.join(sorted(dependency.pruned_outputs)) or 'none'}"
            )
            lines.append(f"    Reason: {dependency.reason}")
    if len(source_boundaries) == 1 and not offline:
        physical = source_boundaries[0]
        plan = physical.acquisition
        cost_class, cost_reason = physical.cost_class, physical.cost_reason
    if len(source_boundaries) > 1:
        lines.extend(["", "Source-boundary plans"])
        for index, branch in enumerate(source_boundaries, 1):
            facet_text = f" OF {branch.facet}" if branch.facet is not None else ""
            lines.append(
                f"  {index}. {branch.source_name}{facet_text}: uses={branch.use_count}; "
                f"acquisition={branch.acquisition.mode}; metadata={branch.metadata_requirements.reason}; "
                f"fields={', '.join(sorted(branch.required_fields)) or 'none'}"
            )
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
    limit_plan = plan_limit_termination(query, source=source, predicate_stages=predicate_stages)
    if len(source_inputs) > 1 and limit_plan.eligible:
        limit_plan = type(limit_plan)(
            False,
            "multi-source UNION requires complete branch acquisition before global LIMIT",
            limit_plan.limit,
            limit_plan.required_matches,
        )
    if not offline and plan.mode != "skip":
        cost_class, cost_reason = assess_cost(query, plan, source=source, limit_termination=limit_plan)
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
                f"           Mode: {limit_plan.mode}",
                f"           Required authoritative matches: {limit_plan.required_matches}",
                f"           {limit_plan.reason}.",
            ]
        )
        if limit_plan.stops_enumeration:
            lines.append(
                "           Lightweight source enumeration itself may stop once the final source-order slice is proven."
            )
        else:
            lines.append(
                "           Detailed metadata is acquired in source-order batches and may stop once the authoritative match target is satisfied."
            )
            lines.append("           Source enumeration remains exhaustive.")
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
            f"  Required: {'cached only' if offline else ('yes' if (source_boundaries and source_boundaries[0].metadata_requirements.requires_detailed_metadata) else 'no')}",
            f"  Reason: {'offline mode never refreshes metadata' if offline else (source_boundaries[0].metadata_requirements.reason if source_boundaries else metadata_requirements.reason)}.",
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
    optimiser_payload = _optimiser_explain_payload(
        optimisation,
        deferred_reason=(
            "dynamic metadata fields require post-acquisition type resolution" if dynamic_deferred else None
        ),
    )
    presentation = _presentation_input(
        query=query,
        optimiser_payload=optimiser_payload,
        predicate_stages=predicate_stages,
        source_boundaries=tuple(source_boundaries),
        limit_plan=limit_plan,
        cte_dependencies=cte_dependencies,
        offline=offline,
    )
    overview = render_console_overview(
        presentation,
        unicode=unicode,
        colour=colour,
    )
    return overview + "\n\n" + "\n".join(lines)


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
    metadata_requirements = plan_metadata_requirements(query, source=source)
    predicate_stages = plan_predicate_stages(query, source=source)
    temporal_bounds = infer_temporal_bounds(query.predicate, dates)
    plan = plan_acquisition(
        query,
        source_kind=source.kind,
        tab=(source.facet or tab),
        dates=dates,
        temporal_bounds=temporal_bounds,
    )
    if offline:
        plan = AcquisitionPlan("offline-cache", "offline mode uses cached detailed metadata only")
        cost_class, cost_reason = "local", "no network acquisition is permitted; only cached records are evaluated"
    else:
        cost_class, cost_reason = assess_cost(query, plan, source=source)
    source_boundaries = plan_source_boundaries(
        query, requests=source_requests, sources=tuple(explained_sources), dates=dates
    )
    cte_dependencies = plan_cte_dependencies(query)
    if len(source_boundaries) == 1 and not offline:
        physical = source_boundaries[0]
        plan = physical.acquisition
        cost_class, cost_reason = physical.cost_class, physical.cost_reason
    limit_plan = plan_limit_termination(query, source=source, predicate_stages=predicate_stages)
    if len(source_inputs) > 1 and limit_plan.eligible:
        limit_plan = type(limit_plan)(
            False,
            "multi-source UNION requires complete branch acquisition before global LIMIT",
            limit_plan.limit,
            limit_plan.required_matches,
        )
    if not offline and plan.mode != "skip":
        cost_class, cost_reason = assess_cost(query, plan, source=source, limit_termination=limit_plan)

    try:
        resolved_for_optimiser = resolve_query(query, QuerySchema(()), dates)
        optimiser_result = optimise_query(resolved_for_optimiser)
        optimiser_payload = _optimiser_explain_payload(optimiser_result)
    except QuerySyntaxError as exc:
        if not exc.message.startswith("Unknown field "):
            raise
        optimiser_payload = _optimiser_explain_payload(
            None,
            deferred_reason=("dynamic metadata fields require post-acquisition type resolution"),
        )

    payload = {
        "kind": "yt-discover-explain",
        "schema_version": EXPLANATION_SCHEMA_VERSION,
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
        "metadata_requirements": {
            "enumeration_fields": sorted(metadata_requirements.enumeration_fields),
            "detailed_fields": sorted(metadata_requirements.detailed_fields),
            "predicate_enumeration_fields": sorted(metadata_requirements.predicate_enumeration_fields),
            "predicate_detailed_fields": sorted(metadata_requirements.predicate_detailed_fields),
            "requires_detailed_metadata": metadata_requirements.requires_detailed_metadata,
            "reason": metadata_requirements.reason,
        },
        "logical_metadata_requirements": {
            "enumeration_fields": sorted(metadata_requirements.enumeration_fields),
            "detailed_fields": sorted(metadata_requirements.detailed_fields),
            "predicate_enumeration_fields": sorted(metadata_requirements.predicate_enumeration_fields),
            "predicate_detailed_fields": sorted(metadata_requirements.predicate_detailed_fields),
            "requires_detailed_metadata": metadata_requirements.requires_detailed_metadata,
            "reason": metadata_requirements.reason,
        },
        "predicate_stages": {
            "enumeration_terms": [format_expression(term) for term in predicate_stages.enumeration_terms],
            "residual_terms": [format_expression(term) for term in predicate_stages.residual_terms],
            "enumeration_fields": sorted(predicate_stages.enumeration_fields),
            "residual_fields": sorted(predicate_stages.residual_fields),
            "reason": predicate_stages.reason,
            "heuristic_order_changed": predicate_stages.heuristic_order_changed,
            "enumeration_heuristics": [
                {
                    "term": format_expression(term),
                    "selectivity": heuristic.selectivity,
                    "evaluation_cost": heuristic.evaluation_cost,
                    "information_value": heuristic.information_value,
                    "reason": heuristic.reason,
                }
                for term, heuristic in zip(
                    predicate_stages.enumeration_terms,
                    predicate_stages.enumeration_heuristics,
                    strict=True,
                )
            ],
        },
        "temporal_bounds": {
            "fields": [
                {
                    "field": item.field,
                    "kind": item.kind,
                    "lower": None
                    if item.lower is None
                    else {"value": item.lower.value.isoformat(), "inclusive": item.lower.inclusive},
                    "upper": None
                    if item.upper is None
                    else {"value": item.upper.value.isoformat(), "inclusive": item.upper.inclusive},
                    "contradictory": item.contradictory,
                }
                for item in temporal_bounds.fields
            ],
            "reason": temporal_bounds.reason,
        },
        "physical_metadata_requirements": [
            {
                "source": boundary.source_name,
                "facet": boundary.facet,
                "required_fields": sorted(boundary.required_fields),
                "enumeration_fields": sorted(boundary.metadata_requirements.enumeration_fields),
                "detailed_fields": sorted(boundary.metadata_requirements.detailed_fields),
                "requires_detailed_metadata": boundary.metadata_requirements.requires_detailed_metadata,
                "reason": boundary.metadata_requirements.reason,
            }
            for boundary in source_boundaries
        ],
        "cte_dependencies": [
            {
                "name": dependency.name,
                "required_outputs": sorted(dependency.required_outputs),
                "retained_outputs": sorted(dependency.retained_outputs),
                "pruned_outputs": sorted(dependency.pruned_outputs),
                "input_fields": sorted(dependency.input_fields),
                "pruning_applied": dependency.pruning_applied,
                "reason": dependency.reason,
            }
            for dependency in cte_dependencies.dependencies
        ],
        "source_boundaries": [
            {
                "source": branch.source_name,
                "facet": branch.facet,
                "url": branch.source.canonical_url,
                "uses": branch.use_count,
                "required_fields": sorted(branch.required_fields),
                "acquisition_stages": [
                    {
                        "name": stage.name,
                        "required": stage.required,
                        "fields": sorted(stage.fields),
                        "reason": stage.reason,
                    }
                    for stage in branch.physical_acquisition.stages
                ],
                "required_acquisition_stages": list(branch.physical_acquisition.required_stage_names),
                "ytdlp_lowering": {
                    "flat_stages": list(lower_acquisition_plan_to_ytdlp(branch.physical_acquisition).flat_stages),
                    "detailed_stages": list(
                        lower_acquisition_plan_to_ytdlp(branch.physical_acquisition).detailed_stages
                    ),
                    "collapsed_detailed_stages": list(
                        lower_acquisition_plan_to_ytdlp(branch.physical_acquisition).collapsed_detailed_stages
                    ),
                    "reason": lower_acquisition_plan_to_ytdlp(branch.physical_acquisition).reason,
                },
                "enumeration_fields": sorted(branch.metadata_requirements.enumeration_fields),
                "detailed_fields": sorted(branch.metadata_requirements.detailed_fields),
                "pre_acquisition_predicate": format_expression(branch.combined_predicate)
                if branch.combined_predicate is not None
                else None,
                "temporal_bounds": [
                    {
                        "field": item.field,
                        "kind": item.kind,
                        "lower": None
                        if item.lower is None
                        else {"value": item.lower.value.isoformat(), "inclusive": item.lower.inclusive},
                        "upper": None
                        if item.upper is None
                        else {"value": item.upper.value.isoformat(), "inclusive": item.upper.inclusive},
                    }
                    for item in branch.temporal_bounds.fields
                ],
                "pre_acquisition_predicates": [format_expression(term) for term in branch.pre_acquisition_predicates],
                "metadata_depth": branch.metadata_depth,
                "stable_collection": branch.stable_collection,
                "stable_order_field": branch.stable_order_field,
                "early_termination": branch.early_termination,
                "acquisition": branch.acquisition.mode,
                "acquisition_reason": branch.acquisition.reason,
                "cost_class": branch.cost_class,
                "heuristics": {
                    "cost_tier": branch.heuristics.cost_tier,
                    "selectivity_tier": branch.heuristics.selectivity_tier,
                    "information_value_tier": branch.heuristics.information_value_tier,
                    "deferred_expensive_stages": list(branch.heuristics.deferred_expensive_stages),
                    "reason": branch.heuristics.reason,
                },
                "branch_empty": branch.branch_empty,
                "eliminated_uses": branch.eliminated_uses,
                "redundant_where_uses": branch.redundant_where_uses,
                "relation_simplifications": [
                    {
                        "empty": relation.empty,
                        "where_truth": relation.where_truth,
                        "having_truth": relation.having_truth,
                        "where_redundant": relation.where_redundant,
                        "having_redundant": relation.having_redundant,
                        "reason": relation.reason,
                    }
                    for relation in branch.relation_simplifications
                ],
                "collection_requirements": sorted(branch.collection_requirements),
            }
            for branch in source_boundaries
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
            "eligible": (False if offline else limit_plan.eligible),
            "reason": ("offline execution performs no metadata acquisition" if offline else limit_plan.reason),
            "mode": ("none" if offline else limit_plan.mode),
            "required_matches": limit_plan.required_matches,
            "stops_source_enumeration": (False if offline else limit_plan.stops_enumeration),
            "stops_detailed_acquisition": (False if offline else limit_plan.stops_detailed_acquisition),
            "backend_range_lowered": False,
            "backend_range_reason": (
                "yt-dlp positional item ranges are not equivalent to final rows when source entries may be skipped or unavailable"
                if limit_plan.eligible
                else "no eligible LIMIT termination proof is available"
            ),
            "scope": "source-order acquisition",
        },
        "cost": {"class": cost_class, "reason": cost_reason},
        "temporal_context": {
            "today": dates.today.isoformat(),
            "now": dates.local_now.isoformat(),
        },
    }
    graph = build_explain_graph(payload)
    payload["explanation"] = {
        "schema_version": EXPLANATION_SCHEMA_VERSION,
        "decisions": explain_decisions(payload),
        "graph": graph_to_json(graph),
    }
    return payload


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
    limit_termination_mode: str = "none",
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
                "mode": limit_termination_mode,
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


def _format_explain_analyze_text(
    payload: dict[str, object],
    *,
    unicode: bool = True,
    colour: bool = False,
) -> str:
    actual = payload["actual"]
    timing = payload["timing_seconds"]
    assert isinstance(actual, dict)
    assert isinstance(timing, dict)
    cache = actual["cache"]
    assert isinstance(cache, dict)

    reset = "\x1b[0m"
    heading_colour = "\x1b[1;36m"

    def heading(value: str) -> str:
        return f"{heading_colour}{value}{reset}" if colour else value

    rule = "═" * 15 if unicode else "=" * 15
    lines = [
        heading("EXPLAIN ANALYZE"),
        rule,
        "",
        heading("Plan"),
        f"  Strategy: {payload['plan']['strategy']}",
        f"  Reason: {payload['plan']['reason']}",
        "",
        heading("Actual execution"),
        f"  Offline: {'yes' if actual['offline'] else 'no'}",
        f"  Backend: {actual['selected_backend']} (requested: {actual['requested_backend']})",
        f"  Entries enumerated: {actual['enumerated']}",
        f"  Enumeration stopped early: {'yes' if actual['enumeration_stopped_early'] else 'no'}",
        f"  Lightweight candidates rejected: {actual['lightweight_rejected']}",
        f"  Detailed candidates: {actual['detailed_candidates'] if actual['detailed_candidates'] is not None else 'n/a'}",
        f"  Metadata available from refresh: {actual['metadata_available']}",
        f"  Inaccessible/skipped during refresh: {actual['metadata_skipped']}",
        "",
        heading("Incremental frontier"),
        f"  Attempted: {'yes' if actual['frontier']['attempted'] else 'no'}",
        f"  Overlap confirmed: {'yes' if actual['frontier']['confirmed'] else 'no'}",
        f"  New source entries: {actual['frontier']['new_source_entries']}",
        f"  Full enumeration avoided: {'yes' if actual['frontier']['full_enumeration_avoided'] else 'no'}",
        "",
        heading("LIMIT-aware acquisition"),
        f"  Eligible: {'yes' if actual['limit_termination']['eligible'] else 'no'}",
        f"  Detailed acquisition stopped early: {'yes' if actual['limit_termination']['terminated_early'] else 'no'}",
        f"  Batches: {actual['limit_termination']['batches']}",
        f"  Candidates examined: {actual['limit_termination']['candidates_examined']}",
        "",
        heading("Cache outcome"),
        f"  Records examined: {cache['examined']}",
        f"  Fresh hits: {cache['fresh_hits']}",
        f"  Stale entries: {cache['stale']}",
        f"  Misses: {cache['misses']}",
        f"  Refreshed: {cache['refreshed']}",
        f"  Written: {cache['written']}",
        "",
        heading("Result statistics"),
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
        heading("Timing"),
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
                heading("Source coverage"),
                f"  Complete at last observation: {'yes' if coverage['complete'] else 'no'}",
                f"  Observed at: {coverage['observed_at']}",
                f"  Cached/observed records: {coverage['cached_entries']}/{coverage['observed_entries']}",
                f"  Reason: {coverage['reason']}",
            ]
        )
    else:
        lines.extend(["", "Source coverage", "  Unknown"])
    return "\n".join(lines)
