"""Shared projection and output formatting for query results."""

from __future__ import annotations

import csv
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, TextIO

from .query import Query, SelectTerm, canonical_record_value


YOUTUBE_WATCH_PREFIX = "https://www.youtube.com/watch?v="


def _serialisable(value: Any) -> Any:
    """Convert typed query values into stable output-friendly scalar values."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def project_record(record: dict[str, Any], terms: tuple[SelectTerm, ...]) -> dict[str, Any]:
    """Project one record onto the resolved SELECT list."""
    return {term.output_name: _serialisable(canonical_record_value(record, term)) for term in terms}


def _line_value(record: dict[str, Any], term: SelectTerm) -> str:
    value = _serialisable(canonical_record_value(record, term))
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _open_output(output_path: Path | None) -> tuple[TextIO, bool]:
    if output_path is None:
        return sys.stdout, False
    path = output_path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("w", encoding="utf-8", newline=""), True


def write_records(
    records: list[dict[str, Any]],
    query: Query,
    output_format: str,
    output_path: Path | None,
    *,
    explicit_select: bool,
) -> None:
    """Write selected records using automatic or explicitly requested serialisation."""
    terms = query.select
    if not terms:
        raise ValueError("resolved query has no SELECT projection")

    if output_format == "ids":
        if explicit_select:
            raise ValueError("--format ids cannot be combined with SELECT; use SELECT id with --format lines")
        terms = (SelectTerm("id", "id", kind="string"),)
        output_format = "lines"
    elif output_format == "urls":
        if explicit_select:
            raise ValueError("--format urls cannot be combined with SELECT; use SELECT url with --format lines")
        stream, close_stream = _open_output(output_path)
        try:
            for record in records:
                video_id = record.get("id")
                if video_id is not None:
                    stream.write(f"{YOUTUBE_WATCH_PREFIX}{video_id}\n")
        finally:
            if close_stream:
                stream.close()
        return
    elif output_format == "auto":
        output_format = "lines" if len(terms) == 1 else "jsonl"

    if output_format == "lines" and len(terms) != 1:
        raise ValueError("--format lines requires exactly one selected field")

    stream, close_stream = _open_output(output_path)
    try:
        if output_format == "lines":
            term = terms[0]
            for record in records:
                stream.write(_line_value(record, term))
                stream.write("\n")
            return

        if output_format == "jsonl":
            for record in records:
                stream.write(json.dumps(project_record(record, terms), ensure_ascii=False, sort_keys=False))
                stream.write("\n")
            return

        if output_format in {"csv", "tsv"}:
            delimiter = "," if output_format == "csv" else "\t"
            writer = csv.DictWriter(
                stream,
                fieldnames=[term.output_name for term in terms],
                delimiter=delimiter,
                lineterminator="\n",
                extrasaction="ignore",
            )
            writer.writeheader()
            for record in records:
                writer.writerow(project_record(record, terms))
            return

        raise ValueError(f"unsupported output format: {output_format}")
    finally:
        if close_stream:
            stream.close()


def append_unique_ids(
    records: list[dict[str, Any]],
    query: Query,
    output_path: Path,
) -> tuple[int, int, int]:
    """Atomically append projected video IDs that are not already present.

    Returns ``(existing_nonblank_lines, already_present, appended)``. Existing file
    content is preserved byte-for-byte apart from adding one separating newline when
    a non-empty file does not already end with one.
    """
    terms = query.select
    if len(terms) != 1 or terms[0].field.casefold() != "id":
        raise ValueError("--append requires a single ID projection such as SELECT id")

    path = output_path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing_text = path.read_text(encoding="utf-8") if path.exists() else ""
    except UnicodeDecodeError as exc:
        raise ValueError(f"--append target is not valid UTF-8: {path}") from exc

    existing_lines = [line.strip() for line in existing_text.splitlines() if line.strip()]
    seen = set(existing_lines)
    new_ids: list[str] = []
    duplicate_results = 0
    for record in records:
        value = canonical_record_value(record, terms[0])
        if value is None:
            continue
        video_id = str(value)
        if video_id in seen:
            duplicate_results += 1
            continue
        seen.add(video_id)
        new_ids.append(video_id)

    if not new_ids:
        return len(existing_lines), duplicate_results, 0

    import os
    import tempfile

    mode = path.stat().st_mode & 0o7777 if path.exists() else None
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(existing_text)
            if existing_text and not existing_text.endswith(("\n", "\r")):
                stream.write("\n")
            for video_id in new_ids:
                stream.write(video_id)
                stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            os.chmod(temp_path, mode)
        os.replace(temp_path, path)
        try:
            dir_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            dir_fd = None
        if dir_fd is not None:
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return len(existing_lines), duplicate_results, len(new_ids)
