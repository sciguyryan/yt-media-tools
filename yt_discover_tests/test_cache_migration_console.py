"""Tests for the ASCII cache-migration presentation layer."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

from yt_media_tools.cache_migration import MigrationContext
from yt_media_tools.cache_migration_console import AsciiMigrationConsole
from yt_media_tools.cache_migration_support import MigrationEvent


def _event(
    *,
    stage: str,
    kind: str,
    message: str,
    completed: int | None = None,
    total: int | None = None,
) -> MigrationEvent:
    context = MigrationContext(Path("v3.sqlite3"), Path("v4.sqlite3"), 3, 4)
    return MigrationEvent.create(
        context,
        stage=stage,
        kind=kind,
        message=message,
        completed=completed,
        total=total,
    )


def test_ascii_console_renders_stable_stage_progress_and_cutover_summary() -> None:
    output = StringIO()
    console = AsciiMigrationConsole(output, interactive=True)
    console.begin(Path("/cache/metadata.sqlite3"), Path("/cache/metadata-v4.sqlite3"))
    console.event_sink(_event(stage="source validation", kind="start", message="Starting source validation"))
    console.event_sink(
        _event(
            stage="phase preflight destination space",
            kind="progress",
            message="Disk space is sufficient",
            completed=2048,
            total=1024,
        )
    )
    console.event_sink(_event(stage="phase populate v4 representation", kind="start", message="Starting population"))
    console.event_sink(
        _event(
            stage="phase populate v4 representation",
            kind="progress",
            message="Migrated 500 detailed metadata records",
            completed=500,
            total=1000,
        )
    )
    console.event_sink(_event(stage="phase build bulk indexes", kind="start", message="Starting indexes"))
    console.event_sink(_event(stage="target validation", kind="start", message="Starting verification"))
    console.event_sink(_event(stage="destination finalisation", kind="start", message="Starting finalisation"))
    console.finish(
        active_path=Path("/cache/metadata-v4.sqlite3"),
        source_retained=False,
        log_path=Path("/cache/migration.jsonl"),
    )

    assert output.getvalue().splitlines() == [
        "yt-discover cache migration",
        "  Source: /cache/metadata.sqlite3",
        "  Destination: /cache/metadata-v4.sqlite3",
        "[>] Preflight",
        "    Disk space is sufficient (2048/1024)",
        "[>] Migration",
        "    Migrated 500 detailed metadata records (500/1000)",
        "[>] Indexing",
        "[>] Verification",
        "[>] Cut-over",
        "[OK] Cut-over complete",
        "  Active cache: /cache/metadata-v4.sqlite3",
        "  Legacy v3 cache: removed",
        "  Migration log: /cache/migration.jsonl",
    ]


def test_ascii_console_bounds_repeated_batch_progress() -> None:
    output = StringIO()
    console = AsciiMigrationConsole(output, interactive=False, progress_step_percent=10)
    for completed in range(1, 101):
        console.event_sink(
            _event(
                stage="phase populate v4 representation",
                kind="progress",
                message=f"Migrated {completed} records",
                completed=completed,
                total=100,
            )
        )

    progress = output.getvalue().splitlines()
    assert len(progress) <= 12
    assert progress[-1].endswith("(100/100)")


def test_ascii_console_failure_explains_safe_restart() -> None:
    output = StringIO()
    console = AsciiMigrationConsole(output, interactive=False)
    console.fail(
        error=RuntimeError("certification mismatch"),
        source_path=Path("/cache/metadata.sqlite3"),
        destination_retained=False,
        log_path=Path("/cache/migration.jsonl"),
    )

    rendered = output.getvalue()
    assert "[FAIL] Migration did not complete: certification mismatch" in rendered
    assert "Legacy v3 cache remains unchanged: /cache/metadata.sqlite3" in rendered
    assert "Incomplete v4 destination discarded." in rendered
    assert "Restart yt-discover to retry" in rendered
