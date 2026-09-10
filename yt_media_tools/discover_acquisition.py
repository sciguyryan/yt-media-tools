"""Acquisition and cache orchestration for yt-discover.

The functions in this module preserve the accepted 0.26.6 behaviour while
keeping remote acquisition concerns out of the executable entry point.
"""

from __future__ import annotations

import sys
from pathlib import Path

from yt_media_tools.cache import CacheStats, MetadataCache
from yt_media_tools.dates import DateContext
from yt_media_tools.discover_constants import (
    DEFAULT_ENUMERATION_PROGRESS_INTERVAL,
    VERBOSE_ENUMERATION_PROGRESS_INTERVAL,
)
from yt_media_tools.metadata import normalise_record
from yt_media_tools.query import Query, QuerySchema, QuerySyntaxError, apply_query, resolve_query
from yt_media_tools.ytdlp import (
    AcquisitionStats,
    build_video_metadata_command,
    load_metadata,
    shell_join,
)


def _verbose(level: int, message: str, *, minimum: int = 1) -> None:
    """Write operational progress to stderr without contaminating pipeline output."""
    if level >= minimum:
        print(f"[yt-discover] {message}", file=sys.stderr, flush=True)


def _acquisition_progress(level: int):
    """Create a yt-dlp progress callback for concise (-v) or detailed (-vv) telemetry."""

    def callback(event: str, stats: AcquisitionStats, detail: str | None) -> None:
        if event == "available":
            if level >= 2:
                _verbose(level, f"Available entry {stats.available}: {detail}", minimum=2)
            elif level >= 1 and (stats.available == 1 or stats.available % 10 == 0):
                _verbose(level, f"Acquired {stats.available} available entries; {stats.skipped} skipped so far.")
        elif event == "skipped":
            _verbose(level, f"Skipped inaccessible entry: {detail}.")

    return callback


def _enumeration_progress(
    level: int,
    *,
    context: str,
    warn_threshold: int = 0,
    acquisition_observability: bool = False,
):
    """Create pipe-safe progress reporting for potentially lengthy source enumeration."""
    interval = (
        1
        if level >= 2
        else VERBOSE_ENUMERATION_PROGRESS_INTERVAL
        if level >= 1
        else DEFAULT_ENUMERATION_PROGRESS_INTERVAL
    )
    large_warning_emitted = False

    def callback(event: str, stats: AcquisitionStats, detail: str | None) -> None:
        nonlocal large_warning_emitted
        if event == "skipped":
            if acquisition_observability:
                _verbose(level, f"Skipped inaccessible entry: {detail}.")
            return
        if event != "enumerated":
            return
        count = stats.available
        if acquisition_observability and level >= 2:
            _verbose(level, f"Available entry {count}: {detail}", minimum=2)
        if warn_threshold and not large_warning_emitted and count >= warn_threshold:
            print(
                f"yt-discover: large-source warning: {context} has already observed {count} items and is still enumerating "
                f"(configured warning threshold: {warn_threshold}).",
                file=sys.stderr,
                flush=True,
            )
            large_warning_emitted = True
        if count == 1 and level >= 1:
            _verbose(level, f"{context}: observed first source item.")
        elif count and count % interval == 0:
            if level >= 1:
                _verbose(level, f"{context}: enumerated {count} source items so far.")
            else:
                print(
                    f"yt-discover: {context}: enumerated {count} source items so far.",
                    file=sys.stderr,
                    flush=True,
                )

    return callback


def _cached_or_refresh_metadata(
    *,
    cache: MetadataCache | None,
    source_url: str,
    video_ids: list[str],
    required_fields: set[str],
    verbose: int,
    cookies_file: Path | None,
) -> tuple[list[dict], AcquisitionStats, CacheStats]:
    """Reuse fresh source-scoped cache rows and refresh only stale or missing videos."""
    cached_by_id: dict[str, dict] = {}
    refresh_ids: list[str] = []
    hits = stale = misses = 0
    cache_fields = {field for field in required_fields if field.casefold() != "source_index"}

    for video_id in video_ids:
        if cache is None:
            refresh_ids.append(video_id)
            continue
        item = cache.get(source_url, video_id)
        if item is None:
            misses += 1
            refresh_ids.append(video_id)
        elif cache.is_fresh(item, cache_fields):
            hits += 1
            cached_by_id[video_id] = item.record
        else:
            stale += 1
            refresh_ids.append(video_id)

    fetched_records: list[dict] = []
    acquisition_stats = AcquisitionStats()
    if refresh_ids:
        command = build_video_metadata_command(refresh_ids, cookies_file=cookies_file)
        _verbose(verbose, f"Refreshing detailed metadata for {len(refresh_ids)} cache-miss/stale videos...")
        if verbose >= 2:
            _verbose(verbose, f"Candidate yt-dlp command: {shell_join(command)}")
        fetched_records, acquisition_stats = load_metadata(
            command,
            progress=_acquisition_progress(verbose) if verbose else None,
        )

    fetched_by_id = {
        record.get("id"): record for record in fetched_records if isinstance(record.get("id"), str) and record.get("id")
    }
    written = cache.put_many(source_url, fetched_records) if cache is not None else 0
    records: list[dict] = []
    for video_id in video_ids:
        record = fetched_by_id.get(video_id) or cached_by_id.get(video_id)
        if record is not None:
            records.append(record)
    return (
        records,
        acquisition_stats,
        CacheStats(
            examined=len(video_ids) if cache is not None else 0,
            hits=hits,
            stale=stale,
            misses=misses,
            refreshed=len(fetched_records),
            written=written,
        ),
    )


def _merge_acquisition_stats(total: AcquisitionStats, part: AcquisitionStats) -> None:
    """Merge one detailed-extraction batch into aggregate telemetry."""
    total.available += part.available
    total.error_lines += part.error_lines
    total.identified_error_lines += part.identified_error_lines
    for video_id, category in part.skipped_by_id.items():
        total.record_skip(video_id, category)


def _merge_cache_stats(total: CacheStats, part: CacheStats) -> CacheStats:
    """Return aggregate cache telemetry for repeated LIMIT-aware batches."""
    return CacheStats(
        examined=total.examined + part.examined,
        hits=total.hits + part.hits,
        stale=total.stale + part.stale,
        misses=total.misses + part.misses,
        refreshed=total.refreshed + part.refreshed,
        written=total.written + part.written,
    )


def _limit_aware_cached_acquire(
    *,
    cache: MetadataCache | None,
    source_url: str,
    video_ids: list[str],
    query: Query,
    dates: DateContext,
    required_fields: set[str],
    verbose: int,
    cookies_file: Path | None,
    batch_size: int = 25,
) -> tuple[list[dict], AcquisitionStats, CacheStats, bool, int, int]:
    """Acquire source-order candidates in batches until LIMIT authoritative matches exist.

    The planner calls this only when source order is the final result order and all query
    fields have statically known types. Later source rows therefore cannot displace an
    already observed matching row from the first LIMIT results.
    """
    assert query.limit is not None
    raw_records: list[dict] = []
    acquisition = AcquisitionStats()
    cache_stats = CacheStats()
    matched = 0
    required_matches = query.offset + query.limit
    batches = 0
    examined_candidates = 0

    for start in range(0, len(video_ids), batch_size):
        batch_ids = video_ids[start : start + batch_size]
        if not batch_ids:
            break
        batches += 1
        batch_raw, batch_acquisition, batch_cache = _cached_or_refresh_metadata(
            cache=cache,
            source_url=source_url,
            video_ids=batch_ids,
            required_fields=required_fields,
            verbose=verbose,
            cookies_file=cookies_file,
        )
        _merge_acquisition_stats(acquisition, batch_acquisition)
        cache_stats = _merge_cache_stats(cache_stats, batch_cache)
        raw_records.extend(batch_raw)
        examined_candidates += len(batch_ids)

        batch_records = [normalise_record(record) for record in batch_raw]
        try:
            resolved = resolve_query(query, QuerySchema(batch_records), dates)
        except QuerySyntaxError:
            # Eligibility excludes dynamic fields, so a semantic failure here should be
            # reproduced later by the normal authoritative resolution path.
            continue
        predicate_only = Query(predicate=resolved.predicate)
        matched += len(apply_query(batch_records, predicate_only))
        if matched >= required_matches:
            return raw_records, acquisition, cache_stats, True, batches, examined_candidates

    return raw_records, acquisition, cache_stats, False, batches, examined_candidates
