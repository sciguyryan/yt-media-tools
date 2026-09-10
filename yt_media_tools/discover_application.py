"""Top-level application orchestration for yt-discover."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from yt_media_tools.archive import exclude_archive, read_archive_ids
from yt_media_tools.cache import CacheStats, MetadataCache, SourceCoverage
from yt_media_tools.capabilities import safely_reject_lightweight
from yt_media_tools.dates import DateContext
from yt_media_tools.discover_acquisition import (
    _acquisition_progress,
    _cached_or_refresh_metadata,
    _enumeration_progress,
    _limit_aware_cached_acquire,
    _verbose,
)
from yt_media_tools.discover_cli import (
    EXAMPLES,
    _parse_parameters,
    bind_query_parameters,
    build_parser,
    looks_like_complete_query,
    parse_user_query,
)
from yt_media_tools.discover_constants import (
    DEFAULT_ARCHIVE_FILE,
    FRONTIER_OVERLAP_CONFIRMATIONS,
    PROGRAM_VERSION,
)
from yt_media_tools.discover_explain import (
    _explain_analyze_payload,
    _format_explain_analyze_text,
    explain_user_query,
    explain_user_query_json,
)
from yt_media_tools.discover_output import (
    _effective_output_format,
    _format_coverage_warning,
    _write_provenance,
    print_schema,
)
from yt_media_tools.metadata import normalise_record
from yt_media_tools.optimizer import optimise_query
from yt_media_tools.output import append_unique_ids, write_records
from yt_media_tools.planner import (
    AcquisitionPlan,
    assess_cost,
    plan_query,
    required_query_fields,
)
from yt_media_tools.query import (
    Query,
    QuerySchema,
    QuerySyntaxError,
    SelectTerm,
    apply_query,
    format_query,
    parse_query,
    query_physical_sources,
    query_physical_source_requests,
    resolve_query,
)
from yt_media_tools.report import RunReport, write_report
from yt_media_tools.sources import SourceSpec, resolve_source_request, source_capabilities
from yt_media_tools.tools import ToolRegistry, ToolStatus, check_tools, format_tool_check
from yt_media_tools.ytdlp_runtime import resolve_cookie_file
from yt_media_tools.youtubejs import (
    YouTubeJsError,
    enumerate_until_date_boundary as enumerate_youtubejs_until_date_boundary,
)
from yt_media_tools.ytdlp import (
    DEFAULT_COOKIES_FILE,
    AcquisitionStats,
    EnumerationStats,
    YtDlpError,
    build_lazy_flat_command,
    build_metadata_command,
    enumerate_all_flat,
    enumerate_until_date_boundary,
    enumerate_until_known_overlap,
    load_metadata,
    shell_join,
)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        cookies_file = resolve_cookie_file(args.cookies, default_file=DEFAULT_COOKIES_FILE)
    except ValueError as exc:
        parser.error(str(exc))

    if args.examples:
        print(EXAMPLES)
        return 0

    if args.check_query is not None:
        try:
            checked = parse_query(bind_query_parameters(args.check_query, _parse_parameters(args.param)))
        except QuerySyntaxError as exc:
            parser.error(exc.format())
        except ValueError as exc:
            parser.error(str(exc))
        print(format_query(checked))
        print("Syntax is valid. Dynamic field and type validation occurs after metadata acquisition.")
        return 0

    if args.explain is not None:
        try:
            if args.explain_format == "json":
                print(
                    json.dumps(
                        explain_user_query_json(
                            bind_query_parameters(args.explain, _parse_parameters(args.param)),
                            source_type=args.source_type,
                            tab=args.tab,
                            date_format=args.date_format,
                            offline=args.offline,
                        ),
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                )
            else:
                print(
                    explain_user_query(
                        bind_query_parameters(args.explain, _parse_parameters(args.param)),
                        source_type=args.source_type,
                        tab=args.tab,
                        date_format=args.date_format,
                        offline=args.offline,
                    )
                )
        except QuerySyntaxError as exc:
            parser.error(exc.format())
        except ValueError as exc:
            parser.error(str(exc))
        return 0

    explain_analyze = args.explain_analyze is not None
    if explain_analyze:
        if args.source is not None or args.query or args.where:
            parser.error("--explain-analyze cannot be combined with SOURCE_OR_QUERY, --query, or --where")
        args.source = args.explain_analyze

    if args.offline and args.no_cache:
        parser.error("--offline requires the metadata cache and cannot be combined with --no-cache")
    if args.offline and (
        args.date or args.after or args.before or args.items or any(item.strip() for item in args.match_filter)
    ):
        parser.error(
            "--offline cannot use yt-dlp acquisition prefilters such as --date/--after/--before/--items/--match-filter"
        )
    if args.append is not None and explain_analyze:
        parser.error("--append cannot be combined with --explain-analyze")
    if args.append is not None and args.format not in {"auto", "lines", "ids"}:
        parser.error("--append supports ID line output only; omit --format or use --format lines/ids")
    if args.provenance == "-" and not explain_analyze and args.output is None and args.append is None:
        parser.error(
            "--provenance - would mix JSON provenance with query rows on stdout; use a file or redirect query output with -o/--append"
        )

    effective_argv = sys.argv[1:] if argv is None else argv
    if not effective_argv:
        print("El Psy Kongroo.", file=sys.stderr)
        parser.error(
            "SOURCE_OR_QUERY is required unless --examples, --check-query, --explain, --explain-analyze, --check-tools, or --version is used"
        )

    total_started = perf_counter()
    # The executable moved into the package, so retain the original project-root semantics.
    project_root = Path(__file__).resolve().parents[1]
    if args.offline and not args.check_tools:
        tools = ToolRegistry(
            ytdlp=ToolStatus("yt-dlp", True, False, detail="not checked in offline mode"),
            node=ToolStatus("Node.js", False, False, detail="not checked in offline mode"),
            youtubejs=ToolStatus("YouTube.js", False, False, detail="not checked in offline mode"),
        )
    else:
        tools = check_tools(project_root)

    if args.check_tools:
        print(format_tool_check(tools))
        return 0 if tools.ytdlp.available else 1

    if args.source is None and not args.query:
        parser.error(
            "SOURCE_OR_QUERY is required unless --examples, --check-query, --explain, --explain-analyze, --check-tools, or --version is used"
        )

    if args.archive != DEFAULT_ARCHIVE_FILE and not args.exclude_archive:
        parser.error("--archive is only meaningful together with --exclude-archive")
    if args.date and (args.after or args.before):
        parser.error("--date cannot be combined with --after or --before")

    inline_query = args.source if looks_like_complete_query(args.source) else None
    positional_source = None if inline_query is not None else args.source

    try:
        query = parse_user_query(args, inline_query)
        physical_requests = query_physical_source_requests(query)
        physical_sources = query_physical_sources(query)
        if physical_sources and positional_source is not None:
            raise ValueError("source is specified both positionally and by FROM")
        source_requests = physical_requests or (((positional_source, None),) if positional_source is not None else ())
        if not source_requests:
            raise ValueError(
                "query has no physical source; add FROM <source> in the main query or a CTE, or provide SOURCE_OR_QUERY positionally"
            )
        source_values = tuple(value for value, _facet in source_requests)
        sources: list[SourceSpec] = [
            resolve_source_request(value, facet=facet, source_type=args.source_type, tab=args.tab)
            for value, facet in source_requests
        ]
        source: SourceSpec = sources[0]
        multi_source = len(sources) > 1
    except QuerySyntaxError as exc:
        parser.error(exc.format())
    except ValueError as exc:
        parser.error(str(exc))

    if not tools.ytdlp.available and not args.dry_run and not args.offline:
        parser.error(f"required tool yt-dlp is unavailable: {tools.ytdlp.detail}. Run --check-tools for details")
    if args.backend == "youtubejs" and not tools.youtubejs_available and not args.offline:
        parser.error(
            f"requested backend 'youtubejs' is unavailable: {tools.youtubejs.detail}. Run --check-tools for details"
        )

    if args.verbose and not args.offline:
        _verbose(True, "Checked acquisition tools before contacting YouTube.")
        _verbose(True, f"yt-dlp: {tools.ytdlp.version if tools.ytdlp.available else 'unavailable'}.")
        _verbose(True, f"Node.js: {tools.node.version if tools.node.available else 'unavailable'}.")
        _verbose(True, f"YouTube.js: {tools.youtubejs.version if tools.youtubejs_available else 'unavailable'}.")

    if multi_source:
        _verbose(args.verbose, f"Resolved {len(sources)} physical source/facet requests for UNION composition.")
        for source_value, source_spec in zip(source_values, sources, strict=True):
            facet_text = f" OF {source_spec.facet}" if source_spec.facet is not None else ""
            _verbose(
                args.verbose, f"Source {source_value}{facet_text}: {source_spec.kind} -> {source_spec.canonical_url}"
            )
    else:
        facet_text = f" OF {source.facet}" if source.facet is not None else ""
        _verbose(args.verbose, f"Resolved source{facet_text} as {source.kind}: {source.canonical_url}")

    date_context = DateContext(date_order=args.date_format)
    query_plan = plan_query(query, source=source, dates=date_context)
    plan: AcquisitionPlan = query_plan.acquisition
    if multi_source:
        plan = AcquisitionPlan(
            "full",
            "UNION composition spans multiple physical source/facet requests; each request is acquired independently before logical reconciliation",
        )
    explicit_prefilters = bool(
        args.items or args.date or args.after or args.before or any(item.strip() for item in args.match_filter)
    )
    if args.offline:
        plan = AcquisitionPlan("offline-cache", "offline mode uses cached detailed metadata only")
    elif args.acquisition == "full":
        plan = AcquisitionPlan("full", "exhaustive acquisition was requested with --acquisition full")
    elif explicit_prefilters and plan.targeted:
        plan = AcquisitionPlan(
            "full",
            "explicit yt-dlp acquisition prefilters are present; automatic bounded planning is disabled",
        )

    limit_plan = query_plan.limit_termination
    if multi_source and limit_plan.eligible:
        limit_plan = type(limit_plan)(
            False,
            "multi-source UNION requires complete branch acquisition before global LIMIT",
            limit_plan.limit,
        )
    if args.exclude_archive and limit_plan.eligible:
        limit_plan = type(limit_plan)(
            False,
            "archive exclusion is applied after acquisition, so early LIMIT termination cannot prove the first N surviving rows",
            limit_plan.limit,
        )
    if args.offline and limit_plan.eligible:
        limit_plan = type(limit_plan)(
            False,
            "offline execution already has a finite cached record set and performs no metadata acquisition",
            limit_plan.limit,
        )

    if args.offline:
        cost_class, cost_reason = "local", "no network acquisition is permitted; only cached records are evaluated"
    else:
        cost_class, cost_reason = assess_cost(query, plan)
    if not args.offline and not args.dry_run and args.acquisition != "full" and cost_class == "very-high":
        if query.set_operations or any(cte.query.set_operations for cte in query.ctes):
            warning = (
                "yt-discover: warning: UNION composition currently acquires each contributing physical source/facet request "
                "conservatively before logical reconciliation; this may require substantial metadata acquisition."
            )
        else:
            warning = (
                "yt-discover: warning: this query may require complete source enumeration and substantial metadata acquisition; "
                "no safe source boundary is available. Add a lower upload_date bound when that matches the intended query."
            )
        print(warning, file=sys.stderr, flush=True)
    if args.verbose:
        _verbose(True, f"Acquisition cost estimate: {cost_class} ({cost_reason}).")

    requested_backend = args.backend
    selected_backend = "cache" if args.offline else "ytdlp"
    fallback_reason = ""
    if plan.targeted:
        if args.backend == "youtubejs":
            selected_backend = "youtubejs"
        elif args.backend == "auto" and tools.youtubejs_available:
            selected_backend = "youtubejs"
        else:
            selected_backend = "ytdlp"
            if args.backend == "auto" and not tools.youtubejs_available:
                fallback_reason = tools.youtubejs.detail or "YouTube.js is unavailable"
                print(
                    f"yt-discover: optional YouTube.js backend unavailable; using yt-dlp bounded enumeration ({fallback_reason}).",
                    file=sys.stderr,
                )

    command = build_metadata_command(
        source.canonical_url,
        cookies_file=cookies_file,
        playlist_items=args.items,
        date=args.date,
        date_after=args.after,
        date_before=args.before,
        match_filters=tuple(item for item in args.match_filter if item.strip()),
    )

    if args.verbose:
        _verbose(True, f"Acquisition plan: {plan.mode} ({plan.reason}).")
        if args.offline:
            _verbose(True, "Execution source: persistent metadata cache only; network acquisition is disabled.")
        elif plan.targeted:
            _verbose(True, f"Enumeration backend: {selected_backend} (requested: {requested_backend}).")
            if fallback_reason:
                _verbose(True, f"Fallback reason: {fallback_reason}.")
            _verbose(True, f"Query lower upload-date bound: {plan.lower_date_bound.isoformat()}.")
            _verbose(
                True,
                f"Conservative flat-scan stop threshold: {plan.stop_before.isoformat()} after {plan.confirmation_entries} consecutive older entries.",
            )
        else:
            _verbose(True, f"yt-dlp command: {shell_join(command)}")
        _verbose(True, f"Parsed query: {format_query(query)}")

    if args.dry_run:
        if multi_source:
            for source_value, source_spec in zip(source_values, sources, strict=True):
                facet_text = f" OF {source_spec.facet}" if source_spec.facet is not None else ""
                print(f"source: {source_value}{facet_text} -> {source_spec.kind} -> {source_spec.canonical_url}")
        else:
            facet_text = f" OF {source.facet}" if source.facet is not None else ""
            print(f"source: {source.kind}{facet_text} -> {source.canonical_url}")
        print(f"acquisition: {plan.mode} -> {plan.reason}")
        if args.offline:
            print(f"cache: {args.cache.expanduser()}")
            print("network: disabled")
        elif plan.targeted:
            print(f"backend: requested={requested_backend} selected={selected_backend}")
            if fallback_reason:
                print(f"fallback: {fallback_reason}")
            flat_command = build_lazy_flat_command(source.canonical_url, cookies_file=cookies_file)
            if selected_backend == "youtubejs":
                print("enumeration: YouTube.js continuation-driven channel videos feed")
            else:
                print(f"enumeration: {shell_join(flat_command)}")
            print(
                f"boundary: lower={plan.lower_date_bound.isoformat()} stop-before={plan.stop_before.isoformat()} confirmations={plan.confirmation_entries}"
            )
            print("detail extraction: candidate video IDs from the bounded enumeration pass")
        elif not args.offline:
            if multi_source:
                for source_value, source_spec in zip(source_values, sources, strict=True):
                    source_command = build_metadata_command(
                        source_spec.canonical_url,
                        cookies_file=cookies_file,
                        playlist_items=args.items,
                        date=args.date,
                        date_after=args.after,
                        date_before=args.before,
                        match_filters=tuple(item for item in args.match_filter if item.strip()),
                    )
                    facet_label = f" OF {source_spec.facet}" if source_spec.facet is not None else ""
                    print(f"yt-dlp [{source_value}{facet_label}]: {shell_join(source_command)}")
            else:
                print(f"yt-dlp: {shell_join(command)}")
        print(f"query:  {format_query(query)}")
        print("note: dynamic fields and typed literals are resolved after metadata acquisition")
        return 0

    if args.exclude_archive and not args.archive.expanduser().is_file():
        parser.error(f"archive file not found: {args.archive.expanduser()}")

    metadata_cache: MetadataCache | None = None
    if not args.no_cache:
        metadata_cache = MetadataCache(args.cache)
        try:
            metadata_cache.open()
        except (OSError, RuntimeError) as exc:
            print(f"Error: could not open metadata cache {args.cache.expanduser()}: {exc}", file=sys.stderr)
            return 1
        _verbose(args.verbose, f"Metadata cache: {args.cache.expanduser()}.")
    else:
        _verbose(args.verbose, "Metadata cache disabled for this run.")

    enumeration_stats: EnumerationStats | None = None
    cache_stats = CacheStats()
    lightweight_rejected = 0
    detailed_candidates: int | None = None
    offline_coverage: SourceCoverage | None = None
    observed_ids_for_cache: list[str] = []
    frontier_attempted = False
    frontier_confirmed = False
    frontier_new_entries = 0
    limit_terminated = False
    limit_batches = 0
    limit_candidates_examined = 0
    acquisition_started = perf_counter()
    source_record_counts: dict[tuple[str, str | None], int] = {}
    if multi_source:
        raw_records = []
        acquisition_stats = AcquisitionStats()
        for (source_value, request_facet), source_spec in zip(source_requests, sources, strict=True):
            if args.offline:
                assert metadata_cache is not None
                cached_items = metadata_cache.source_records(source_spec.canonical_url)
                if not cached_items:
                    print(
                        f"Error: offline cache has no detailed metadata for {source_spec.canonical_url}.",
                        file=sys.stderr,
                    )
                    metadata_cache.close()
                    return 1
                source_records = [dict(item.record) for item in cached_items]
                source_stats = AcquisitionStats()
            else:
                source_command = build_metadata_command(
                    source_spec.canonical_url,
                    cookies_file=cookies_file,
                    playlist_items=args.items,
                    date=args.date,
                    date_after=args.after,
                    date_before=args.before,
                    match_filters=tuple(item for item in args.match_filter if item.strip()),
                )
                _verbose(args.verbose, f"Acquiring UNION source {source_value} with yt-dlp...")
                try:
                    source_records, source_stats = load_metadata(
                        source_command,
                        progress=_acquisition_progress(args.verbose) if args.verbose else None,
                    )
                except YtDlpError as exc:
                    print(f"Error: {exc}.", file=sys.stderr)
                    return 1
                if metadata_cache is not None:
                    metadata_cache.put_many(source_spec.canonical_url, source_records)
            source_record_counts[(source_value, request_facet)] = len(source_records)
            for item in source_records:
                tagged = dict(item)
                tagged["_yt_sql_source"] = source_value
                tagged["_yt_sql_source_facet"] = request_facet
                tagged["_yt_sql_source_url"] = source_spec.canonical_url
                raw_records.append(tagged)
        acquisition_stats = AcquisitionStats(available=len(raw_records))
        detailed_candidates = len(raw_records)
    else:
        if args.offline:
            assert metadata_cache is not None
            cached_items = metadata_cache.source_records(source.canonical_url)
            if not cached_items:
                print(
                    f"Error: offline cache has no detailed metadata for {source.canonical_url}.",
                    file=sys.stderr,
                )
                metadata_cache.close()
                return 1
            required_fields = {field for field in required_query_fields(query) if field.casefold() != "source_index"}
            fresh = sum(1 for item in cached_items if metadata_cache.is_fresh(item, required_fields))
            stale = len(cached_items) - fresh
            raw_records = [item.record for item in cached_items]
            cache_stats = CacheStats(examined=len(cached_items), hits=fresh, stale=stale)
            acquisition_stats = AcquisitionStats()
            detailed_candidates = len(cached_items)
            offline_coverage = metadata_cache.source_coverage(source.canonical_url)
            coverage_message = _format_coverage_warning(offline_coverage, len(cached_items))
            if offline_coverage is None or not offline_coverage.complete:
                print(f"yt-discover: offline warning: {coverage_message}.", file=sys.stderr)
            else:
                _verbose(args.verbose, f"Offline coverage: {coverage_message}.")
            if stale:
                print(
                    f"yt-discover: offline warning: {stale} cached record(s) are stale for one or more fields required by this query; stale values will be used without refresh.",
                    file=sys.stderr,
                )
            _verbose(
                args.verbose,
                f"Offline query loaded {len(cached_items)} cached detailed records and made no YouTube requests.",
            )
        elif plan.targeted:
            flat_command = build_lazy_flat_command(source.canonical_url, cookies_file=cookies_file)
            _verbose(args.verbose, f"Enumerating lightweight channel metadata lazily with {selected_backend}...")
            try:
                if selected_backend == "youtubejs":
                    flat_entries, enumeration_stats = enumerate_youtubejs_until_date_boundary(
                        project_root,
                        source.canonical_url,
                        stop_before=plan.stop_before,
                        confirmation_entries=plan.confirmation_entries,
                        dates=date_context,
                        progress=_enumeration_progress(
                            args.verbose, context="Bounded YouTube.js enumeration", warn_threshold=args.warn_source_size
                        ),
                    )
                else:
                    if args.verbose >= 2:
                        _verbose(args.verbose, f"Flat yt-dlp command: {shell_join(flat_command)}")
                    flat_entries, enumeration_stats = enumerate_until_date_boundary(
                        flat_command,
                        stop_before=plan.stop_before,
                        confirmation_entries=plan.confirmation_entries,
                        progress=_enumeration_progress(
                            args.verbose, context="Bounded yt-dlp enumeration", warn_threshold=args.warn_source_size
                        ),
                    )
            except YouTubeJsError as exc:
                if args.backend == "youtubejs":
                    print(f"Error: YouTube.js enumeration failed: {exc}.", file=sys.stderr)
                    return 1
                fallback_reason = f"YouTube.js enumeration failed: {exc}"
                selected_backend = "ytdlp"
                print(
                    f"yt-discover: YouTube.js enumeration failed; falling back to yt-dlp bounded enumeration ({exc}).",
                    file=sys.stderr,
                )
                try:
                    flat_entries, enumeration_stats = enumerate_until_date_boundary(
                        flat_command,
                        stop_before=plan.stop_before,
                        confirmation_entries=plan.confirmation_entries,
                        progress=_enumeration_progress(
                            args.verbose, context="Bounded yt-dlp enumeration", warn_threshold=args.warn_source_size
                        ),
                    )
                except YtDlpError as fallback_exc:
                    print(f"Error: {fallback_exc}.", file=sys.stderr)
                    return 1
            except YtDlpError as exc:
                print(f"Error: {exc}.", file=sys.stderr)
                return 1
            candidate_ids = []
            seen_ids = set()
            lightweight_rejected = 0
            for entry in flat_entries:
                video_id = entry.get("id")
                if not (isinstance(video_id, str) and video_id and video_id not in seen_ids):
                    continue
                seen_ids.add(video_id)
                observed_ids_for_cache.append(video_id)
                # Lightweight evaluation is deliberately one-sided: a candidate is discarded
                # only when exact values or conservative uncertainty intervals prove that the
                # complete WHERE predicate is false. Unknown or approximate cases are retained.
                if safely_reject_lightweight(query.predicate, entry, date_context):
                    lightweight_rejected += 1
                    continue
                candidate_ids.append(video_id)
            detailed_candidates = len(candidate_ids)
            _verbose(
                args.verbose,
                f"Lightweight enumeration observed {enumeration_stats.enumerated} entries "
                f"({enumeration_stats.dated} dated, {enumeration_stats.undated} undated); "
                f"{len(candidate_ids)} detailed candidates; {lightweight_rejected} safely rejected before full extraction.",
            )
            if enumeration_stats.stopped_early:
                _verbose(args.verbose, "Stopped channel pagination after the conservative date boundary was confirmed.")
            else:
                _verbose(
                    args.verbose,
                    "Channel enumeration reached its natural end before the conservative date boundary was confirmed.",
                )
            if candidate_ids:
                try:
                    if limit_plan.eligible:
                        (
                            raw_records,
                            acquisition_stats,
                            cache_stats,
                            limit_terminated,
                            limit_batches,
                            limit_candidates_examined,
                        ) = _limit_aware_cached_acquire(
                            cache=metadata_cache,
                            source_url=source.canonical_url,
                            video_ids=candidate_ids,
                            query=query,
                            dates=date_context,
                            required_fields=required_query_fields(query),
                            verbose=args.verbose,
                            cookies_file=cookies_file,
                        )
                    else:
                        raw_records, acquisition_stats, cache_stats = _cached_or_refresh_metadata(
                            cache=metadata_cache,
                            source_url=source.canonical_url,
                            video_ids=candidate_ids,
                            required_fields=required_query_fields(query),
                            verbose=args.verbose,
                            cookies_file=cookies_file,
                        )
                except YtDlpError as exc:
                    print(f"Error: {exc}.", file=sys.stderr)
                    return 1
            else:
                raw_records, acquisition_stats = [], AcquisitionStats()
        else:
            cache_first_full = (
                metadata_cache is not None
                and source.kind == "channel"
                and args.tab == "videos"
                and args.items is None
                and not (args.date or args.after or args.before or any(item.strip() for item in args.match_filter))
            )
            if cache_first_full:
                flat_command = build_lazy_flat_command(source.canonical_url, cookies_file=cookies_file)
                if args.verbose >= 2:
                    _verbose(args.verbose, f"Flat yt-dlp command: {shell_join(flat_command)}")
                prior_order = metadata_cache.source_entry_ids(source.canonical_url)
                frontier = metadata_cache.source_frontier(source.canonical_url) if args.acquisition != "full" else None
                if frontier is not None and prior_order:
                    frontier_attempted = True
                    _verbose(
                        args.verbose,
                        f"Using incremental source frontier with {len(prior_order)} known entries; "
                        f"requiring {FRONTIER_OVERLAP_CONFIRMATIONS} consecutive known IDs before stopping.",
                    )
                    try:
                        flat_entries, enumeration_stats = enumerate_until_known_overlap(
                            flat_command,
                            known_ids=set(prior_order),
                            confirmation_entries=FRONTIER_OVERLAP_CONFIRMATIONS,
                            progress=_enumeration_progress(
                                args.verbose,
                                context="Incremental frontier enumeration",
                                warn_threshold=args.warn_source_size,
                            ),
                        )
                    except YtDlpError as exc:
                        print(f"Error: {exc}.", file=sys.stderr)
                        return 1
                else:
                    _verbose(
                        args.verbose,
                        "No trusted incremental frontier is available; enumerating the complete channel videos source.",
                    )
                    try:
                        flat_entries, enumeration_stats = enumerate_all_flat(
                            flat_command,
                            progress=_enumeration_progress(
                                args.verbose,
                                context="Full channel enumeration",
                                warn_threshold=args.warn_source_size,
                            ),
                        )
                    except YtDlpError as exc:
                        print(f"Error: {exc}.", file=sys.stderr)
                        return 1

                current_ids: list[str] = []
                entry_by_id: dict[str, dict] = {}
                seen_ids: set[str] = set()
                for entry in flat_entries:
                    video_id = entry.get("id")
                    if not (isinstance(video_id, str) and video_id and video_id not in seen_ids):
                        continue
                    seen_ids.add(video_id)
                    current_ids.append(video_id)
                    entry_by_id[video_id] = entry

                if frontier_attempted and enumeration_stats.stopped_on_frontier:
                    frontier_confirmed = True
                    current_set = set(current_ids)
                    frontier_new_entries = sum(1 for video_id in current_ids if video_id not in set(prior_order))
                    observed_ids_for_cache = current_ids + [
                        video_id for video_id in prior_order if video_id not in current_set
                    ]
                    _verbose(
                        args.verbose,
                        f"Incremental frontier confirmed after {enumeration_stats.enumerated} observed entries; "
                        f"{frontier_new_entries} new source entr{'y' if frontier_new_entries == 1 else 'ies'} discovered.",
                    )
                else:
                    observed_ids_for_cache = current_ids
                    if frontier_attempted:
                        _verbose(
                            args.verbose,
                            "Stored frontier overlap was not confirmed before source end; rebuilt the source ordering from a complete enumeration.",
                        )

                candidate_ids = []
                for video_id in observed_ids_for_cache:
                    entry = entry_by_id.get(video_id)
                    if entry is not None and safely_reject_lightweight(query.predicate, entry, date_context):
                        lightweight_rejected += 1
                        continue
                    candidate_ids.append(video_id)
                detailed_candidates = len(candidate_ids)
                try:
                    if limit_plan.eligible:
                        (
                            raw_records,
                            acquisition_stats,
                            cache_stats,
                            limit_terminated,
                            limit_batches,
                            limit_candidates_examined,
                        ) = _limit_aware_cached_acquire(
                            cache=metadata_cache,
                            source_url=source.canonical_url,
                            video_ids=candidate_ids,
                            query=query,
                            dates=date_context,
                            required_fields=required_query_fields(query),
                            verbose=args.verbose,
                            cookies_file=cookies_file,
                        )
                    else:
                        raw_records, acquisition_stats, cache_stats = _cached_or_refresh_metadata(
                            cache=metadata_cache,
                            source_url=source.canonical_url,
                            video_ids=candidate_ids,
                            required_fields=required_query_fields(query),
                            verbose=args.verbose,
                            cookies_file=cookies_file,
                        )
                except YtDlpError as exc:
                    print(f"Error: {exc}.", file=sys.stderr)
                    return 1
            else:
                if cost_class == "very-high" and args.acquisition != "full":
                    print(
                        "yt-discover: warning: no safe acquisition optimisation was identified for this query; detailed metadata may be required for most or all source entries.",
                        file=sys.stderr,
                    )
                _verbose(args.verbose, "Acquiring full video metadata with yt-dlp...")
                if args.verbose:
                    _verbose(
                        args.verbose,
                        "Queries requiring ORDER BY/LIMIT are evaluated after acquisition; result output may remain quiet until this phase completes.",
                    )
                try:
                    raw_records, acquisition_stats = load_metadata(
                        command,
                        progress=_acquisition_progress(args.verbose) if args.verbose else None,
                    )
                except YtDlpError as exc:
                    print(f"Error: {exc}.", file=sys.stderr)
                    return 1
                observed_ids_for_cache = [
                    record.get("id") for record in raw_records if isinstance(record.get("id"), str) and record.get("id")
                ]
                if metadata_cache is not None:
                    cache_stats = CacheStats(written=metadata_cache.put_many(source.canonical_url, raw_records))
    acquisition_elapsed = perf_counter() - acquisition_started

    if args.offline:
        _verbose(
            args.verbose,
            f"Cache-only acquisition complete: {len(raw_records)} cached detailed records available; 0 YouTube requests.",
        )
    else:
        _verbose(
            args.verbose,
            f"Acquisition complete: {acquisition_stats.available} available, "
            f"{acquisition_stats.skipped} inaccessible/skipped, "
            f"{acquisition_stats.attempted} attempted/observed.",
        )
    if limit_plan.eligible and not args.offline:
        if limit_terminated:
            _verbose(
                args.verbose,
                f"LIMIT-aware detailed acquisition stopped after {limit_candidates_examined} candidate(s) in {limit_batches} batch(es); {query.offset + query.limit} authoritative match(es) were sufficient for OFFSET + LIMIT in source order.",
            )
        elif limit_batches:
            _verbose(
                args.verbose,
                f"LIMIT-aware detailed acquisition examined all {limit_candidates_examined} candidate(s); fewer than {query.offset + query.limit} authoritative matches were available for OFFSET + LIMIT.",
            )
    if metadata_cache is not None and not multi_source:
        _verbose(
            args.verbose,
            f"Cache outcome: {cache_stats.hits} fresh hits, {cache_stats.stale} stale, "
            f"{cache_stats.misses} misses, {cache_stats.written} records written.",
        )
        source_order_complete = (
            not args.offline
            and plan.mode == "full"
            and not explicit_prefilters
            and (frontier_confirmed or enumeration_stats is None or not enumeration_stats.stopped_early)
        )
        if source_order_complete and observed_ids_for_cache:
            metadata_cache.record_source_entries(source.canonical_url, observed_ids_for_cache)
            metadata_cache.record_source_frontier(
                source.canonical_url,
                source.kind,
                observed_ids_for_cache,
                overlap_confirmations=(FRONTIER_OVERLAP_CONFIRMATIONS if frontier_confirmed else 0),
            )
        if not args.offline and enumeration_stats is not None:
            metadata_cache.record_source_observation(
                source.canonical_url,
                source.kind,
                len(observed_ids_for_cache) if frontier_confirmed else enumeration_stats.enumerated,
            )
            complete_coverage = (
                plan.mode == "full"
                and (frontier_confirmed or not enumeration_stats.stopped_early)
                and args.items is None
                and lightweight_rejected == 0
                and len(raw_records) == len(observed_ids_for_cache)
            )
            coverage_reason = (
                "complete full-source observation with detailed metadata for every observed entry"
                if complete_coverage
                else (
                    "bounded or filtered observation does not establish complete detailed source coverage"
                    if plan.mode != "full" or lightweight_rejected
                    else "one or more observed source entries lack cached detailed metadata"
                )
            )
            metadata_cache.record_source_coverage(
                source.canonical_url,
                source.kind,
                len(observed_ids_for_cache) if frontier_confirmed else enumeration_stats.enumerated,
                complete=complete_coverage,
                reason=coverage_reason,
            )
        elif not args.offline and observed_ids_for_cache:
            complete_coverage = (
                plan.mode == "full"
                and not explicit_prefilters
                and acquisition_stats.skipped == 0
                and acquisition_stats.attempted == len(raw_records)
            )
            metadata_cache.record_source_coverage(
                source.canonical_url,
                source.kind,
                acquisition_stats.attempted,
                complete=complete_coverage,
                reason=(
                    "complete full-source detailed acquisition"
                    if complete_coverage
                    else "detailed acquisition did not establish complete source coverage"
                ),
            )

    if not multi_source:
        source_record_counts[source_requests[0]] = len(raw_records)

    observed_source_work = (
        enumeration_stats.enumerated if enumeration_stats is not None else acquisition_stats.attempted
    )
    if enumeration_stats is None and args.warn_source_size and observed_source_work >= args.warn_source_size:
        print(
            f"yt-discover: warning: observed source work reached {observed_source_work} entries "
            f"(configured warning threshold: {args.warn_source_size}).",
            file=sys.stderr,
        )

    query_started = perf_counter()
    records = []
    for source_index, raw in enumerate(raw_records, start=1):
        record = normalise_record(raw)
        record["source_index"] = source_index
        if "_yt_sql_source" in raw:
            record["_yt_sql_source"] = raw["_yt_sql_source"]
            record["_yt_sql_source_facet"] = raw.get("_yt_sql_source_facet")
            record["_yt_sql_source_url"] = raw.get("_yt_sql_source_url")
        records.append(record)

    schema = QuerySchema(records)
    source_schemas = (
        {
            (source_value, request_facet): QuerySchema(
                [
                    record
                    for record in records
                    if record.get("_yt_sql_source") == source_value
                    and record.get("_yt_sql_source_facet") == request_facet
                ]
            )
            for source_value, request_facet in source_requests
        }
        if multi_source
        else {source_requests[0]: schema}
    )
    _verbose(args.verbose, f"Built query schema from {len(records)} normalised records.")
    if args.fields or args.schema:
        print_schema(schema, include_raw=args.schema)
        return 0

    try:
        resolved_query = resolve_query(
            query,
            schema,
            date_context,
            source_schemas=source_schemas,
        )
    except QuerySyntaxError as exc:
        parser.error(exc.format())

    optimisation = optimise_query(resolved_query)
    resolved_query = optimisation.query
    if optimisation.changed:
        _verbose(args.verbose, f"Optimiser applied {len(optimisation.decisions)} semantics-preserving rewrite(s).")
        for decision in optimisation.decisions:
            _verbose(args.verbose, f"Optimiser [{decision.rule}]: {decision.before} -> {decision.after}")

    archive_excluded = 0
    if args.exclude_archive:
        try:
            archive_ids = read_archive_ids(args.archive.expanduser())
        except OSError as exc:
            print(f"Error: could not read archive file: {exc}", file=sys.stderr)
            return 1
        before_archive = len(records)
        records = exclude_archive(records, archive_ids)
        archive_excluded = before_archive - len(records)
        _verbose(args.verbose, f"Archive exclusion removed {archive_excluded} entries; {len(records)} remain.")

    before_query = len(records)
    if resolved_query.ctes or resolved_query.set_operations:
        unlimited_query = replace(resolved_query, limit=None)
        matched_before_limit = apply_query(records, unlimited_query)
        selected = apply_query(records, resolved_query)
        where_matches = matched_before_limit
        distinct_rows = matched_before_limit
    else:
        where_only_query = Query(
            predicate=resolved_query.predicate,
            source=resolved_query.source,
            select=(SelectTerm("id", "id", kind="string"),),
            from_source=resolved_query.from_source,
        )
        where_matches = apply_query(records, where_only_query)
        distinct_query = Query(
            predicate=resolved_query.predicate,
            order_by=resolved_query.order_by,
            source=resolved_query.source,
            select=resolved_query.select,
            from_source=resolved_query.from_source,
            distinct=resolved_query.distinct,
            group_by=resolved_query.group_by,
            having=resolved_query.having,
        )
        distinct_rows = apply_query(records, distinct_query)
        unlimited_query = Query(
            predicate=resolved_query.predicate,
            order_by=resolved_query.order_by,
            source=resolved_query.source,
            select=resolved_query.select,
            from_source=resolved_query.from_source,
            distinct=resolved_query.distinct,
            offset=resolved_query.offset,
            group_by=resolved_query.group_by,
            having=resolved_query.having,
        )
        matched_before_limit = apply_query(records, unlimited_query)
        selected = (
            matched_before_limit if resolved_query.limit is None else matched_before_limit[: resolved_query.limit]
        )
    query_elapsed = perf_counter() - query_started
    _verbose(args.verbose, f"WHERE matched {len(where_matches)} of {before_query} entries.")
    if resolved_query.distinct:
        _verbose(
            args.verbose,
            f"DISTINCT reduced {len(where_matches)} matching row(s) to {len(distinct_rows)} projected row(s).",
        )
    if resolved_query.offset:
        _verbose(
            args.verbose,
            f"OFFSET skipped up to the first {resolved_query.offset} matching distinct row(s); {len(matched_before_limit)} remain before LIMIT.",
        )
    if resolved_query.limit is not None:
        _verbose(args.verbose, f"LIMIT reduced output to {len(selected)} entries.")
    if resolved_query.order_by:
        order_desc = ", ".join(
            f"{term.field} {'DESC' if term.descending else 'ASC'}" for term in resolved_query.order_by
        )
        _verbose(args.verbose, f"Applied ordering: {order_desc}.")
    _verbose(
        args.verbose,
        f"Output format: {_effective_output_format(args.format, len(resolved_query.select), explicit_select=bool(query.select))}.",
    )
    if args.append is not None:
        _verbose(args.verbose, f"Appending only new IDs atomically to {args.append.expanduser()}.")
    elif args.output is not None:
        _verbose(args.verbose, f"Writing output to {args.output.expanduser()}.")
    else:
        _verbose(args.verbose, "Writing output to stdout.")

    existing_count: int | None = None
    duplicate_count: int | None = None
    appended_count: int | None = None
    if not explain_analyze:
        try:
            if args.append is not None:
                existing_count, duplicate_count, appended_count = append_unique_ids(
                    selected, resolved_query, args.append
                )
                _verbose(
                    args.verbose,
                    f"Append outcome: {existing_count} existing nonblank IDs, "
                    f"{duplicate_count} query result(s) already present, {appended_count} new ID(s) appended.",
                )
            else:
                write_records(
                    selected,
                    resolved_query,
                    args.format,
                    args.output,
                    explicit_select=bool(query.select),
                )
        except ValueError as exc:
            parser.error(str(exc))
        except OSError as exc:
            print(f"Error: could not write output: {exc}", file=sys.stderr)
            return 1
        if args.append is None:
            _verbose(args.verbose, f"Emitted {len(selected)} row{'s' if len(selected) != 1 else ''}.")
    else:
        _verbose(
            args.verbose,
            f"EXPLAIN ANALYZE suppressed {len(selected)} query row{'s' if len(selected) != 1 else ''} from normal output.",
        )

    total_elapsed = perf_counter() - total_started
    current_coverage = offline_coverage
    if metadata_cache is not None and current_coverage is None and not multi_source:
        current_coverage = metadata_cache.source_coverage(source.canonical_url)

    if args.provenance is not None:
        provenance_payload: dict[str, object] = {
            "kind": "yt-discover-query-provenance",
            "version": PROGRAM_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "query": {
                "canonical_bound": format_query(query),
                "resolved": format_query(resolved_query),
                "parameters": {name: value for name, value in sorted(_parse_parameters(args.param).items())},
                "distinct": resolved_query.distinct,
                "offset": resolved_query.offset,
                "limit": resolved_query.limit,
            },
            "source": {
                "type": "union" if multi_source else source.kind,
                "url": source.canonical_url if not multi_source else None,
                "tab": args.tab if not multi_source and source_requests[0][1] is None and args.tab != "all" else None,
                "facet": source.facet if not multi_source else None,
                "adapter": source_capabilities(source).adapter if not multi_source else None,
            },
            "sources": [
                {
                    "input": source_value,
                    "type": source_spec.kind,
                    "url": source_spec.canonical_url,
                    "tab": args.tab if request_facet is None and args.tab != "all" else None,
                    "facet": source_spec.facet,
                    "adapter": source_capabilities(source_spec).adapter,
                    "acquired_records": source_record_counts.get((source_value, request_facet), 0),
                }
                for (source_value, request_facet), source_spec in zip(source_requests, sources, strict=True)
            ],
            "execution": {
                "offline": args.offline,
                "acquisition_plan": plan.mode,
                "backend": selected_backend,
                "frontier_attempted": frontier_attempted,
                "frontier_confirmed": frontier_confirmed,
                "limit_terminated_early": limit_terminated,
                "normalised_records": len(raw_records),
                "records_evaluated": before_query,
                "where_matched": len(where_matches),
                "distinct_rows": len(distinct_rows),
                "matched_before_limit": len(matched_before_limit),
                "emitted_rows": len(selected),
            },
            "cache": {
                "enabled": metadata_cache is not None,
                "path": str(args.cache.expanduser()) if metadata_cache is not None else None,
                "fresh_hits": cache_stats.hits,
                "stale": cache_stats.stale,
                "misses": cache_stats.misses,
                "refreshed": cache_stats.refreshed,
            },
            "temporal_context": {
                "today": date_context.today.isoformat(),
                "now": date_context.local_now.isoformat(),
            },
        }
        try:
            _write_provenance(args.provenance, provenance_payload)
        except OSError as exc:
            print(f"Error: could not write provenance: {exc}", file=sys.stderr)
            return 1
        if args.provenance != "-":
            _verbose(args.verbose, f"Wrote query provenance to {Path(args.provenance).expanduser()}.")

    if args.report is not None:
        output_format = _effective_output_format(
            args.format, len(resolved_query.select), explicit_select=bool(query.select)
        )
        output_destination = (
            f"append:{args.append.expanduser()}"
            if args.append is not None
            else str(args.output.expanduser())
            if args.output is not None
            else "stdout"
        )
        report = RunReport(
            source_kind="union" if multi_source else source.kind,
            source_url=" | ".join(spec.canonical_url for spec in sources) if multi_source else source.canonical_url,
            query=format_query(query),
            acquisition=acquisition_stats,
            normalised=len(raw_records),
            archive_excluded=archive_excluded,
            query_input=before_query,
            matched_before_limit=len(matched_before_limit),
            where_matched=len(where_matches),
            distinct_rows=len(distinct_rows),
            emitted=len(selected),
            limit=resolved_query.limit,
            distinct=resolved_query.distinct,
            offset=resolved_query.offset,
            output_format=output_format,
            output_destination=output_destination,
            acquisition_plan=plan.mode,
            acquisition_reason=plan.reason,
            enumeration=enumeration_stats,
            requested_backend=requested_backend,
            selected_backend=selected_backend,
            fallback_reason=fallback_reason,
            tools=tools,
            cost_class=cost_class,
            cost_reason=cost_reason,
            lightweight_rejected=lightweight_rejected,
            detailed_candidates=detailed_candidates,
            source_size_warning_threshold=args.warn_source_size,
            cache_enabled=metadata_cache is not None,
            cache_path=str(args.cache.expanduser()) if metadata_cache is not None else "",
            cache=cache_stats,
            offline=args.offline,
            coverage=current_coverage,
            frontier_attempted=frontier_attempted,
            frontier_confirmed=frontier_confirmed,
            frontier_new_entries=frontier_new_entries,
            limit_termination_eligible=limit_plan.eligible,
            limit_terminated=limit_terminated,
            limit_batches=limit_batches,
            limit_candidates_examined=limit_candidates_examined,
            append_existing=existing_count,
            append_duplicates=duplicate_count,
            append_added=appended_count,
            acquisition_seconds=acquisition_elapsed,
            query_seconds=query_elapsed,
            total_seconds=total_elapsed,
        )
        try:
            write_report(report, args.report)
        except OSError as exc:
            print(f"Error: could not write report: {exc}", file=sys.stderr)
            return 1
        if args.report not in {"stderr", "-"}:
            _verbose(args.verbose, f"Wrote acquisition report to {Path(args.report).expanduser()}.")
    if explain_analyze:
        analysis_payload = _explain_analyze_payload(
            query=query,
            source=source,
            plan=plan,
            requested_backend=requested_backend,
            selected_backend=selected_backend,
            fallback_reason=fallback_reason,
            enumeration=enumeration_stats,
            acquisition=acquisition_stats,
            cache=cache_stats,
            cache_enabled=metadata_cache is not None,
            offline=args.offline,
            coverage=current_coverage,
            lightweight_rejected=lightweight_rejected,
            detailed_candidates=detailed_candidates,
            query_input=before_query,
            matched_before_limit=len(matched_before_limit),
            emitted=len(selected),
            acquisition_seconds=acquisition_elapsed,
            query_seconds=query_elapsed,
            total_seconds=total_elapsed,
            frontier_attempted=frontier_attempted,
            frontier_confirmed=frontier_confirmed,
            frontier_new_entries=frontier_new_entries,
            limit_termination_eligible=limit_plan.eligible,
            limit_terminated=limit_terminated,
            limit_batches=limit_batches,
            limit_candidates_examined=limit_candidates_examined,
        )
        if args.explain_format == "json":
            print(json.dumps(analysis_payload, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(_format_explain_analyze_text(analysis_payload))

    if metadata_cache is not None:
        metadata_cache.close()
    return 0
