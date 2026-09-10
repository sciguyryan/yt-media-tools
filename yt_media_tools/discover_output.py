"""Discover output-shaping, schema display and provenance helpers."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from yt_media_tools.cache import SourceCoverage
from yt_media_tools.schema import QuerySchema


def print_schema(schema: QuerySchema, *, include_raw: bool) -> None:
    print("Field\tType\tNullable\tNotes")
    for info in schema.available_fields():
        notes = []
        if info.alias_of:
            notes.append(f"alias for {info.alias_of}")
        elif info.dynamic:
            notes.append("dynamic yt-dlp scalar")
        print(f"{info.name}\t{info.kind}\t{'yes' if info.nullable else 'no'}\t{'; '.join(notes)}")
    if include_raw:
        for info in schema.raw_scalar_paths():
            print(f"{info.name}\t{info.kind}\t{'yes' if info.nullable else 'no'}\traw nested scalar")


def _effective_output_format(output_format: str, selected_count: int, *, explicit_select: bool) -> str:
    if output_format == "auto":
        return "lines" if selected_count == 1 else "jsonl"
    if output_format == "ids":
        return "lines (legacy ids shortcut)"
    if output_format == "urls":
        return "lines (legacy urls shortcut)"
    return output_format


def _format_coverage_warning(coverage: SourceCoverage | None, cached_count: int) -> str:
    """Describe offline source coverage without overstating completeness."""
    if coverage is None:
        return f"source completeness is unknown; querying {cached_count} cached detailed record(s) only"
    if coverage.complete:
        return (
            f"last recorded source coverage was complete at {coverage.observed_at.isoformat()} "
            f"({coverage.cached_entries}/{coverage.observed_entries} detailed records cached)"
        )
    return (
        f"source coverage is incomplete: {coverage.reason}; querying {cached_count} cached detailed record(s) only "
        f"(last observation {coverage.observed_at.isoformat()})"
    )


def _write_provenance(destination: str, payload: dict[str, object]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if destination == "-":
        sys.stdout.write(text)
        return
    path = Path(destination).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
