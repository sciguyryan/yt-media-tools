"""Acquisition and cache orchestration for yt-discover.

The functions in this module preserve the accepted 0.26.6 behaviour while
keeping remote acquisition concerns out of the executable entry point.
"""

from __future__ import annotations

import sys
from pathlib import Path

from yt_media_tools.acquisition_progress import (
    AcquisitionProgressEvent,
    AcquisitionProgressKind,
    AcquisitionProgressStage,
    render_acquisition_progress,
)
from yt_media_tools.cache import CacheStats, MetadataCache
from yt_media_tools.dates import DateContext
from yt_media_tools.discover_constants import (
    DEFAULT_ENUMERATION_PROGRESS_INTERVAL,
    VERBOSE_ENUMERATION_PROGRESS_INTERVAL,
)
from yt_media_tools.metadata import normalise_record
from yt_media_tools.query import Query, QuerySchema, QuerySyntaxError, apply_query, resolve_query
from yt_media_tools.youtubejs import YouTubeJsError, acquire_basic_info as acquire_youtubejs_basic_info
from yt_media_tools.ytmusic import YtMusicApiError, acquire_song_metadata as acquire_ytmusic_song_metadata
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


class _DetailedMetadataProgress:
    """Adapt backend extraction telemetry to semantic detailed-metadata progress."""

    def __init__(self, *, level: int, total: int | None, offset: int = 0) -> None:
        self.level = level
        self.total = total
        self.offset = offset
        self.completed = offset
        self._last_reported = offset

    def start(self) -> None:
        render_acquisition_progress(
            AcquisitionProgressEvent(
                AcquisitionProgressKind.STAGE_STARTED,
                AcquisitionProgressStage.DETAILED_METADATA,
                completed=self.offset,
                total=self.total,
            )
        )

    def backend(self, event: str, stats: AcquisitionStats, detail: str | None) -> None:
        if event not in {"available", "skipped"}:
            return
        completed = self.offset + stats.available + stats.skipped
        self.completed = min(completed, self.total) if self.total is not None else completed
        if event == "available":
            if self.level >= 2:
                _verbose(self.level, f"Available entry {stats.available}: {detail}", minimum=2)
            elif self.level >= 1 and (stats.available == 1 or stats.available % 10 == 0):
                _verbose(
                    self.level,
                    f"Acquired {stats.available} available entries; {stats.skipped} skipped so far.",
                )
        if event == "skipped" and self.level >= 1:
            render_acquisition_progress(
                AcquisitionProgressEvent(
                    AcquisitionProgressKind.ENTRY_SKIPPED,
                    AcquisitionProgressStage.DETAILED_METADATA,
                    completed=self.completed,
                    total=self.total,
                    detail=detail,
                )
            )
        if self.level >= 2:
            interval = 1
        elif self.level >= 1:
            interval = 10
        else:
            interval = 25
        if self.completed and (self.completed == self.total or self.completed - self._last_reported >= interval):
            render_acquisition_progress(
                AcquisitionProgressEvent(
                    AcquisitionProgressKind.STAGE_PROGRESS,
                    AcquisitionProgressStage.DETAILED_METADATA,
                    completed=self.completed,
                    total=self.total,
                )
            )
            self._last_reported = self.completed

    def complete(self, completed: int | None = None) -> None:
        final = self.completed if completed is None else completed
        # Backend telemetry can observe more entries than the bounded candidate set
        # represented by this semantic stage. Keep presentation counters within the
        # stage contract without changing the backend acquisition statistics.
        if self.total is not None:
            final = min(final, self.total)
        render_acquisition_progress(
            AcquisitionProgressEvent(
                AcquisitionProgressKind.STAGE_COMPLETED,
                AcquisitionProgressStage.DETAILED_METADATA,
                completed=final,
                total=self.total,
            )
        )


def _cached_or_refresh_metadata(
    *,
    cache: MetadataCache | None,
    source_url: str,
    video_ids: list[str],
    required_fields: set[str],
    verbose: int,
    cookies_file: Path | None,
    specialised_provider: str | None = None,
    specialised_fallback_providers: tuple[str, ...] = (),
    project_root: Path | None = None,
) -> tuple[list[dict], AcquisitionStats, CacheStats]:
    """Reuse fresh source-scoped cache rows and refresh only stale or missing videos."""
    cached_by_id: dict[str, dict] = {}
    refresh_ids: list[str] = []
    hits = stale = misses = 0
    cache_fields = {field for field in required_fields if field.casefold() != "source_index"}

    cached_items = cache.get_many(source_url, video_ids) if cache is not None else {}
    for video_id in video_ids:
        if cache is None:
            refresh_ids.append(video_id)
            continue
        item = cached_items.get(video_id)
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
    used_specialised_provider = False
    if refresh_ids:
        providers = tuple(provider for provider in (specialised_provider, *specialised_fallback_providers) if provider)
        remaining_ids = list(refresh_ids)
        for provider in providers:
            if not remaining_ids:
                break
            try:
                if provider == "youtubejs":
                    if project_root is None:
                        raise ValueError("project_root is required for YouTube.js metadata acquisition")
                    _verbose(
                        verbose, f"Acquiring exact-scalar metadata for {len(remaining_ids)} videos with YouTube.js..."
                    )
                    provider_records, provider_stats = acquire_youtubejs_basic_info(
                        project_root, remaining_ids, cookies_file=cookies_file
                    )
                elif provider == "ytmusicapi":
                    _verbose(
                        verbose,
                        f"Acquiring specialised music metadata for {len(remaining_ids)} videos with ytmusicapi...",
                    )
                    provider_records, provider_stats = acquire_ytmusic_song_metadata(remaining_ids)
                else:
                    continue
            except (YouTubeJsError, YtMusicApiError) as exc:
                _verbose(
                    verbose, f"{provider} specialised acquisition failed; trying the next acquisition path ({exc})."
                )
                continue
            used_specialised_provider = True
            fetched_records.extend(provider_records)
            _merge_acquisition_stats(acquisition_stats, provider_stats)
            fetched_ids = {
                record.get("id")
                for record in provider_records
                if isinstance(record.get("id"), str) and record.get("id")
            }
            remaining_ids = [video_id for video_id in remaining_ids if video_id not in fetched_ids]
            if remaining_ids:
                _verbose(
                    verbose,
                    f"{provider} did not return {len(remaining_ids)} requested videos; trying the next acquisition path.",
                )

        if remaining_ids:
            command = build_video_metadata_command(remaining_ids, cookies_file=cookies_file)
            _verbose(
                verbose, f"Refreshing detailed metadata for {len(remaining_ids)} cache-miss/stale videos with yt-dlp..."
            )
            if verbose >= 2:
                _verbose(verbose, f"Candidate yt-dlp command: {shell_join(command)}")
            semantic_progress = _DetailedMetadataProgress(level=verbose, total=len(remaining_ids))
            semantic_progress.start()
            fallback_records, fallback_stats = load_metadata(command, progress=semantic_progress.backend)
            semantic_progress.complete(fallback_stats.attempted)
            fetched_records.extend(fallback_records)
            _merge_acquisition_stats(acquisition_stats, fallback_stats)

    fetched_by_id = {
        record.get("id"): record for record in fetched_records if isinstance(record.get("id"), str) and record.get("id")
    }
    written = cache.put_many(source_url, fetched_records) if cache is not None and not used_specialised_provider else 0
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
    specialised_provider: str | None = None,
    specialised_fallback_providers: tuple[str, ...] = (),
    project_root: Path | None = None,
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
            specialised_provider=specialised_provider,
            specialised_fallback_providers=specialised_fallback_providers,
            project_root=project_root,
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
