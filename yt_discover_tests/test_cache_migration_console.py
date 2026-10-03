"""Tests for the ASCII cache-migration presentation layer."""

from __future__ import annotations

import re
from io import StringIO
from pathlib import Path

from yt_media_tools.cache_migration import MigrationContext
from yt_media_tools.cache_migration_console import (
    AsciiMigrationConsole,
    RichMigrationConsole,
    create_migration_console,
)
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


def test_rich_console_renders_unicode_hierarchy_without_colour() -> None:
    output = StringIO()
    console = RichMigrationConsole(output, interactive=True, colour=False, unicode=True)
    console.begin(Path("/cache/metadata.sqlite3"), Path("/cache/metadata-v4.sqlite3"))
    console.event_sink(_event(stage="source validation", kind="start", message="Starting source validation"))
    console.event_sink(
        _event(
            stage="phase populate v4 representation",
            kind="progress",
            message="Migrated 50 detailed metadata records",
            completed=50,
            total=100,
        )
    )
    console.event_sink(_event(stage="target validation", kind="start", message="Starting verification"))
    console.finish(
        active_path=Path("/cache/metadata-v4.sqlite3"),
        source_retained=True,
        log_path=Path("/cache/migration.jsonl"),
    )

    assert output.getvalue().splitlines() == [
        "┌─ yt-discover cache migration",
        "│  Source      /cache/metadata.sqlite3",
        "│  Destination /cache/metadata-v4.sqlite3",
        "└─",
        "├─ [RUN] Preflight",
        "│    Migrated 50 detailed metadata records (50/100) ━━━━━━──────  50%",
        "├─ [OK] Preflight",
        "├─ [RUN] Verification",
        "└─ [OK] Cut-over complete",
        "   Active cache  /cache/metadata-v4.sqlite3",
        "   Legacy v3     retained",
        "   Migration log /cache/migration.jsonl",
    ]


def test_rich_console_uses_semantic_colour_without_relying_on_it() -> None:
    plain = StringIO()
    coloured = StringIO()
    plain_console = RichMigrationConsole(plain, interactive=True, colour=False, unicode=True)
    colour_console = RichMigrationConsole(coloured, interactive=True, colour=True, unicode=True)
    event = _event(stage="source validation", kind="start", message="Starting source validation")
    plain_console.event_sink(event)
    colour_console.event_sink(event)

    assert plain.getvalue() == "├─ [RUN] Preflight\n"
    assert "\x1b[" in coloured.getvalue()
    stripped = coloured.getvalue()
    stripped = re.sub(r"\x1b\[[0-9;]*m", "", stripped)
    assert stripped == plain.getvalue()


def test_console_factory_preserves_ascii_fallback_when_unicode_is_disabled() -> None:
    output = StringIO()
    console = create_migration_console(
        output,
        interactive=False,
        colour=False,
        unicode=False,
    )
    assert type(console) is AsciiMigrationConsole


def test_rich_failure_keeps_textual_status_and_restart_guidance() -> None:
    output = StringIO()
    console = RichMigrationConsole(output, interactive=True, colour=False, unicode=True)
    console.fail(
        error=RuntimeError("certification mismatch"),
        source_path=Path("/cache/metadata.sqlite3"),
        destination_retained=True,
        log_path=Path("/cache/migration.jsonl"),
    )

    rendered = output.getvalue()
    assert "└─ [FAIL] Migration did not complete" in rendered
    assert "Reason         certification mismatch" in rendered
    assert "Protected v3   unchanged: /cache/metadata.sqlite3" in rendered
    assert "Incomplete v4  retained for diagnostics" in rendered
    assert "Restart yt-discover to retry" in rendered


def test_rich_console_never_moves_backwards_between_user_facing_stages() -> None:
    output = StringIO()
    console = RichMigrationConsole(output, interactive=True, colour=False, unicode=True)
    stages = (
        "source validation",
        "phase copy v3 database",
        "phase build bulk indexes",
        "phase remove legacy v3 tables",
        "target validation",
        "destination finalisation",
    )
    for stage in stages:
        console.event_sink(_event(stage=stage, kind="start", message=f"Starting {stage}"))

    rendered = output.getvalue().splitlines()
    running = [line.removeprefix("├─ [RUN] ") for line in rendered if "[RUN]" in line]
    assert running == ["Preflight", "Migration", "Indexing", "Verification", "Cut-over"]
