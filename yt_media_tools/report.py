"""Acquisition and query reporting for yt-discover."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from .cache import CacheStats, SourceCoverage
from .tools import ToolRegistry
from .ytdlp import AcquisitionStats, EnumerationStats


@dataclass(frozen=True)
class RunReport:
    source_kind: str
    source_url: str
    query: str
    acquisition: AcquisitionStats
    normalised: int
    archive_excluded: int
    query_input: int
    matched_before_limit: int
    emitted: int
    limit: int | None
    where_matched: int | None = None
    distinct_rows: int | None = None
    distinct: bool = False
    offset: int = 0
    output_format: str = "auto"
    output_destination: str = "stdout"
    acquisition_plan: str = "full"
    acquisition_reason: str = ""
    enumeration: EnumerationStats | None = None
    requested_backend: str = "auto"
    selected_backend: str = "ytdlp"
    fallback_reason: str = ""
    tools: ToolRegistry | None = None
    cost_class: str = "unknown"
    cost_reason: str = ""
    lightweight_rejected: int = 0
    detailed_candidates: int | None = None
    source_size_warning_threshold: int = 0
    cache_enabled: bool = False
    cache_path: str = ""
    cache: CacheStats = field(default_factory=CacheStats)
    offline: bool = False
    coverage: SourceCoverage | None = None
    frontier_attempted: bool = False
    frontier_confirmed: bool = False
    frontier_new_entries: int = 0
    limit_termination_eligible: bool = False
    limit_terminated: bool = False
    limit_batches: int = 0
    limit_candidates_examined: int = 0
    append_existing: int | None = None
    append_duplicates: int | None = None
    append_added: int | None = None
    acquisition_seconds: float = 0.0
    query_seconds: float = 0.0
    total_seconds: float = 0.0


def format_report(report: RunReport) -> str:
    """Render a stable human-readable report suitable for console or a text file."""
    a = report.acquisition
    attempted_note = ""
    unidentified_errors = max(0, a.error_lines - a.identified_error_lines)
    if unidentified_errors:
        attempted_note = " (minimum; some errors could not be tied to a video ID)"

    lines = [
        "yt-discover acquisition report",
        "",
        "Source",
        f"  Type: {report.source_kind}",
        f"  URL: {report.source_url}",
    ]
    if report.tools is not None:
        tools = report.tools
        lines.extend(
            [
                "",
                "Tools",
                f"  yt-dlp: {tools.ytdlp.version if tools.ytdlp.available else 'unavailable'}",
                f"  Node.js: {tools.node.version if tools.node.available else 'unavailable'}",
                f"  YouTube.js: {tools.youtubejs.version if tools.youtubejs_available else 'unavailable'}",
            ]
        )
    lines.extend(
        [
            "",
            "Acquisition",
            f"  Plan: {report.acquisition_plan}",
            f"  Cost estimate: {report.cost_class}",
            f"  Requested backend: {report.requested_backend}",
            f"  Selected backend: {report.selected_backend}",
            f"  Fallback used: {'yes' if report.fallback_reason else 'no'}",
        ]
    )
    if report.fallback_reason:
        lines.append(f"  Fallback reason: {report.fallback_reason}")
    if report.acquisition_reason:
        lines.append(f"  Reason: {report.acquisition_reason}")
    if report.cost_reason:
        lines.append(f"  Cost reason: {report.cost_reason}")
    if report.enumeration is not None:
        e = report.enumeration
        lines.extend(
            [
                f"  Lightweight entries enumerated: {e.enumerated}",
                f"  Lightweight entries with approximate dates: {e.dated}",
                f"  Lightweight entries without dates: {e.undated}",
                f"  Pagination stopped early: {'yes' if e.stopped_early else 'no'}",
                f"  Lightweight candidates safely rejected: {report.lightweight_rejected}",
            ]
        )
    if report.detailed_candidates is not None:
        lines.append(f"  Detailed candidates requested: {report.detailed_candidates}")
    if report.source_size_warning_threshold:
        lines.append(f"  Source-size warning threshold: {report.source_size_warning_threshold}")

    lines.extend(["", "Cache"])
    if report.cache_enabled:
        lines.extend(
            [
                "  Enabled: yes",
                f"  Offline mode: {'yes' if report.offline else 'no'}",
                f"  Path: {report.cache_path}",
                f"  Records examined: {report.cache.examined}",
                f"  Fresh hits: {report.cache.hits}",
                f"  Stale entries: {report.cache.stale}",
                f"  Misses: {report.cache.misses}",
                f"  Refreshed records: {report.cache.refreshed}",
                f"  Records written: {report.cache.written}",
            ]
        )
        if report.coverage is None:
            lines.append("  Source coverage: unknown")
        else:
            lines.extend(
                [
                    f"  Source coverage: {'complete at last observation' if report.coverage.complete else 'incomplete'}",
                    f"  Coverage observed at: {report.coverage.observed_at.isoformat()}",
                    f"  Coverage records: {report.coverage.cached_entries}/{report.coverage.observed_entries}",
                    f"  Coverage reason: {report.coverage.reason}",
                ]
            )
    else:
        lines.append("  Enabled: no")

    lines.extend(["", "Optimisation outcome"])
    if report.offline:
        lines.append("  Network acquisition executed: no")
        lines.append(f"  Cached records evaluated: {report.cache.examined}")
        lines.append(f"  Cached records stale for required fields: {report.cache.stale}")
    elif report.acquisition_plan == "bounded-date":
        lines.append("  Planned bounded enumeration: yes")
        if report.enumeration is not None:
            lines.append(f"  Bounded enumeration executed: yes ({report.selected_backend})")
            lines.append(
                f"  Boundary terminated enumeration early: {'yes' if report.enumeration.stopped_early else 'no'}"
            )
        else:
            lines.append("  Bounded enumeration executed: no")
        lines.append(f"  Candidates rejected before detailed extraction: {report.lightweight_rejected}")
        if report.detailed_candidates is not None:
            lines.append(f"  Candidates sent to detailed extraction: {report.detailed_candidates}")
    else:
        lines.append("  Planned bounded enumeration: no")
        if report.frontier_attempted:
            lines.append("  Incremental frontier attempted: yes")
            lines.append(f"  Frontier overlap confirmed: {'yes' if report.frontier_confirmed else 'no'}")
            lines.append(f"  New source entries discovered: {report.frontier_new_entries}")
            lines.append("  Full source enumeration avoided: " + ("yes" if report.frontier_confirmed else "no"))
        else:
            lines.append("  Incremental frontier attempted: no")
            lines.append("  Full source enumeration executed: yes")

    if report.limit is not None:
        lines.append(
            f"  LIMIT-aware detailed acquisition eligible: {'yes' if report.limit_termination_eligible else 'no'}"
        )
        if report.limit_termination_eligible:
            lines.append(f"  LIMIT terminated detailed acquisition early: {'yes' if report.limit_terminated else 'no'}")
            lines.append(f"  LIMIT acquisition batches: {report.limit_batches}")
            lines.append(f"  LIMIT candidates examined: {report.limit_candidates_examined}")

    lines.extend(
        [
            f"  Videos attempted/observed: {a.attempted}{attempted_note}",
            f"  Metadata available: {a.available}",
            f"  Inaccessible/skipped: {a.skipped}",
        ]
    )
    for category, count in sorted(a.skipped_categories.items()):
        lines.append(f"    {category}: {count}")
    if unidentified_errors:
        lines.append(f"  Other yt-dlp error lines: {unidentified_errors}")

    lines.extend(
        [
            "",
            "Query",
            f"  Expression: {report.query}",
            f"  Normalised records: {report.normalised}",
            f"  Archive exclusions: {report.archive_excluded}",
            f"  Records evaluated by WHERE: {report.query_input}",
            f"  WHERE matches before row shaping: {report.where_matched if report.where_matched is not None else report.matched_before_limit}",
            f"  Rows after DISTINCT: {report.distinct_rows if report.distinct_rows is not None else report.matched_before_limit}",
            f"  Rows after OFFSET / before LIMIT: {report.matched_before_limit}"
            + (" (at least; acquisition stopped after LIMIT was satisfied)" if report.limit_terminated else ""),
            f"  Matched before LIMIT: {report.matched_before_limit}"
            + (" (at least; acquisition stopped after LIMIT was satisfied)" if report.limit_terminated else ""),
            f"  DISTINCT: {'yes' if report.distinct else 'no'}",
            f"  OFFSET: {report.offset}",
            f"  Emitted rows: {report.emitted}",
            f"  LIMIT: {report.limit if report.limit is not None else 'None'}",
            "",
            "Timing",
            f"  Acquisition/cache phase: {report.acquisition_seconds:.3f}s",
            f"  Query evaluation: {report.query_seconds:.3f}s",
            f"  Total: {report.total_seconds:.3f}s",
            "",
            "Output",
            f"  Format: {report.output_format}",
            f"  Destination: {report.output_destination}",
        ]
    )
    if report.append_added is not None:
        lines.extend(
            [
                f"  Existing nonblank IDs: {report.append_existing}",
                f"  Query results already present: {report.append_duplicates}",
                f"  Newly appended IDs: {report.append_added}",
            ]
        )
    return "\n".join(lines)


def write_report(report: RunReport, destination: str) -> None:
    """Write a report to stderr, stdout, or a named UTF-8 file.

    The special destination ``stderr`` is used by bare --report. ``-`` explicitly selects stdout.
    """
    text = format_report(report) + "\n"
    stream: TextIO
    close_stream = False
    if destination == "stderr":
        stream = sys.stderr
    elif destination == "-":
        stream = sys.stdout
    else:
        path = Path(destination).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        stream = path.open("w", encoding="utf-8", newline="")
        close_stream = True
    try:
        stream.write(text)
        stream.flush()
    finally:
        if close_stream:
            stream.close()
