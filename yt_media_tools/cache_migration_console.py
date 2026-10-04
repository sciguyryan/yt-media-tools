"""Terminal presentation for metadata-cache migration progress."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from .cache_migration_support import MigrationEvent

_STAGE_LABELS = {
    "source validation": "Preflight",
    "phase preflight destination space": "Preflight",
    "phase initialise v4 destination": "Migration",
    "phase defer bulk indexes": "Migration",
    "phase populate v4 source state": "Migration",
    "phase populate v4 representation": "Migration",
    "phase build bulk indexes": "Indexing",
    "target validation": "Verification",
    "destination finalisation": "Cut-over",
}

_ANSI = {
    "reset": "\x1b[0m",
    "bold": "\x1b[1m",
    "dim": "\x1b[2m",
    "cyan": "\x1b[36m",
    "green": "\x1b[32m",
    "yellow": "\x1b[33m",
    "red": "\x1b[31m",
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
            return
        if event.kind == "skipped":
            self._write(f"    {event.message}")
            return
        if event.kind in {"failed", "interrupted"}:
            marker = "[FAIL]" if event.kind == "failed" else "[STOP]"
            self._write(f"{marker} {label}: {event.message}")
            return
        if event.kind != "progress" or not self._should_render_progress(event):
            return
        self._write(f"    {self._progress_detail(event)}")

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

    def _progress_detail(self, event: MigrationEvent) -> str:
        detail = event.message
        if event.completed is not None and event.total is not None and event.total > 0:
            detail = f"{detail} ({event.completed}/{event.total})"
        return detail

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


@dataclass
class RichMigrationConsole(AsciiMigrationConsole):
    """Render the migration lifecycle with Unicode structure and optional colour."""

    colour: bool = True
    unicode: bool = True

    def __post_init__(self) -> None:
        super().__post_init__()
        self._completed_labels: list[str] = []

    def begin(self, source: Path, destination: Path) -> None:
        if not self.unicode:
            super().begin(source, destination)
            return
        title = self._paint("yt-discover cache migration", "heading")
        self._write(f"┌─ {title}")
        self._write(f"│  Source      {self._paint(str(source), 'dim')}")
        self._write(f"│  Destination {self._paint(str(destination), 'dim')}")
        self._write("└─")

    def event_sink(self, event: MigrationEvent) -> None:
        if not self.unicode:
            super().event_sink(event)
            return
        label = _STAGE_LABELS.get(event.stage, "Migration")
        if event.kind == "start":
            # Several implementation phases collapse into one user-facing stage.
            # Never move the presentation backwards when a later phase carries an
            # earlier logical label, such as legacy-table cleanup after indexing.
            if label in self._completed_labels:
                return
            if label != self._active_stage:
                if self._active_stage is not None and self._active_stage not in self._completed_labels:
                    self._write(f"├─ {self._paint('[OK]', 'success')} {self._active_stage}")
                    self._completed_labels.append(self._active_stage)
                self._write(f"├─ {self._paint('[RUN]', 'active')} {self._paint(label, 'heading')}")
                self._active_stage = label
            return
        if event.kind == "complete":
            return
        if event.kind == "skipped":
            self._write(f"│    {self._paint('[SKIP]', 'warning')} {event.message}")
            return
        if event.kind in {"failed", "interrupted"}:
            marker = "[FAIL]" if event.kind == "failed" else "[STOP]"
            status = "failure" if event.kind == "failed" else "warning"
            self._write(f"├─ {self._paint(marker, status)} {label}")
            self._write(f"│    {event.message}")
            return
        if event.kind != "progress" or not self._should_render_progress(event):
            return
        detail = self._progress_detail(event)
        progress = self._progress_bar(event)
        suffix = f" {progress}" if progress else ""
        self._write(f"│    {detail}{suffix}")

    def finish(
        self,
        *,
        active_path: Path,
        source_retained: bool,
        log_path: Path | None,
    ) -> None:
        if not self.unicode:
            super().finish(active_path=active_path, source_retained=source_retained, log_path=log_path)
            return
        self._write(f"└─ {self._paint('[OK]', 'success')} {self._paint('Cut-over complete', 'success')}")
        self._write(f"   Active cache  {self._paint(str(active_path), 'heading')}")
        legacy = "retained" if source_retained else "removed"
        self._write(f"   Legacy v3     {legacy}")
        if log_path is not None:
            self._write(f"   Migration log {self._paint(str(log_path), 'dim')}")

    def fail(
        self,
        *,
        error: BaseException,
        source_path: Path,
        destination_retained: bool,
        log_path: Path,
    ) -> None:
        if not self.unicode:
            super().fail(
                error=error,
                source_path=source_path,
                destination_retained=destination_retained,
                log_path=log_path,
            )
            return
        self._write(f"└─ {self._paint('[FAIL]', 'failure')} {self._paint('Migration did not complete', 'failure')}")
        self._write(f"   Reason         {error}")
        self._write(f"   Protected v3   unchanged: {self._paint(str(source_path), 'heading')}")
        disposition = "retained for diagnostics" if destination_retained else "discarded"
        self._write(f"   Incomplete v4  {disposition}")
        self._write(f"   Migration log  {self._paint(str(log_path), 'dim')}")
        self._write("   Next step      Restart yt-discover to retry from the protected v3 cache.")

    def _progress_bar(self, event: MigrationEvent) -> str:
        if event.completed is None or event.total is None or event.total <= 0:
            return ""
        ratio = max(0.0, min(1.0, event.completed / event.total))
        width = 12
        filled = int(ratio * width)
        if event.completed >= event.total:
            filled = width
        bar = "━" * filled + "─" * (width - filled)
        percent = int(ratio * 100)
        return self._paint(f"{bar} {percent:3d}%", "progress")

    def _paint(self, text: str, role: str) -> str:
        if not self.colour:
            return text
        codes = {
            "heading": _ANSI["bold"] + _ANSI["cyan"],
            "active": _ANSI["cyan"],
            "success": _ANSI["green"],
            "warning": _ANSI["yellow"],
            "failure": _ANSI["red"],
            "progress": _ANSI["cyan"],
            "dim": _ANSI["dim"],
        }
        prefix = codes.get(role, "")
        return f"{prefix}{text}{_ANSI['reset']}" if prefix else text


def create_migration_console(
    stream: TextIO,
    *,
    interactive: bool,
    colour: bool,
    unicode: bool,
) -> AsciiMigrationConsole:
    """Select rich terminal presentation or the stable ASCII compatibility renderer."""
    if unicode:
        return RichMigrationConsole(stream, interactive=interactive, colour=colour, unicode=True)
    return AsciiMigrationConsole(stream, interactive=interactive)
