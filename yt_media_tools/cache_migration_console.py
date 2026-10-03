"""ASCII presentation for metadata-cache migration progress."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from .cache_migration_support import MigrationEvent

_STAGE_LABELS = {
    "source validation": "Preflight",
    "phase preflight destination space": "Preflight",
    "phase copy v3 database": "Migration",
    "phase reset transitional v4 state": "Migration",
    "phase defer bulk indexes": "Migration",
    "phase populate v4 representation": "Migration",
    "phase build bulk indexes": "Indexing",
    "phase remove legacy v3 tables": "Migration",
    "target validation": "Verification",
    "destination finalisation": "Cut-over",
}


@dataclass
class AsciiMigrationConsole:
    """Render structured migration events as deterministic, bounded ASCII output."""

    stream: TextIO
    interactive: bool
    progress_step_percent: int = 10

    def __post_init__(self) -> None:
        self._active_stage: str | None = None
        self._last_progress_bucket: dict[str, int] = {}

    def begin(self, source: Path, destination: Path) -> None:
        self._write("yt-discover cache migration")
        self._write(f"  Source: {source}")
        self._write(f"  Destination: {destination}")

    def event_sink(self, event: MigrationEvent) -> None:
        label = _STAGE_LABELS.get(event.stage, "Migration")
        if event.kind == "start":
            if label != self._active_stage:
                self._write(f"[>] {label}")
                self._active_stage = label
            return
        if event.kind == "complete":
            # A user-facing stage can contain several implementation phases. Its
            # completion is announced when the next stage begins or by finish().
            return
        if event.kind == "skipped":
            self._write(f"    {event.message}")
            return
        if event.kind in {"failed", "interrupted"}:
            marker = "[FAIL]" if event.kind == "failed" else "[STOP]"
            self._write(f"{marker} {label}: {event.message}")
            return
        if event.kind != "progress":
            return
        if not self._should_render_progress(event):
            return
        detail = event.message
        if event.completed is not None and event.total is not None and event.total > 0:
            detail = f"{detail} ({event.completed}/{event.total})"
        self._write(f"    {detail}")

    def finish(
        self,
        *,
        active_path: Path,
        source_retained: bool,
        log_path: Path | None,
    ) -> None:
        self._write("[OK] Cut-over complete")
        self._write(f"  Active cache: {active_path}")
        self._write(f"  Legacy v3 cache: {'retained' if source_retained else 'removed'}")
        if log_path is not None:
            self._write(f"  Migration log: {log_path}")

    def fail(
        self,
        *,
        error: BaseException,
        source_path: Path,
        destination_retained: bool,
        log_path: Path,
    ) -> None:
        self._write(f"[FAIL] Migration did not complete: {error}")
        self._write(f"  Legacy v3 cache remains unchanged: {source_path}")
        if destination_retained:
            self._write("  Incomplete v4 destination retained for diagnostics.")
        else:
            self._write("  Incomplete v4 destination discarded.")
        self._write(f"  Migration log: {log_path}")
        self._write("  Restart yt-discover to retry the migration from the protected v3 cache.")

    def _should_render_progress(self, event: MigrationEvent) -> bool:
        if event.completed is None or event.total is None or event.total <= 0:
            return True
        if event.completed >= event.total:
            return True
        percent = max(0, min(100, int(event.completed * 100 / event.total)))
        bucket = percent // self.progress_step_percent
        previous = self._last_progress_bucket.get(event.stage)
        if previous == bucket:
            return False
        self._last_progress_bucket[event.stage] = bucket
        return True

    def _write(self, line: str) -> None:
        print(line, file=self.stream, flush=self.interactive)
