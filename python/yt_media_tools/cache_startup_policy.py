"""Startup policy for versioned Discover cache resolution.

This module decides whether a required supported migration is authorised. It deliberately
contains no migration execution, cut-over, cleanup or terminal rendering policy so those
later startup stages can consume the same deterministic decision model.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TextIO

from .cache_discovery import CacheResolution, CacheResolutionKind


class CacheStartupAction(Enum):
    """Action permitted by cache discovery and startup authorisation."""

    USE_ACTIVE = "use_active"
    CREATE_FRESH = "create_fresh"
    MIGRATE = "migrate"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class MigrationAuthorisation(Enum):
    """Origin of a migration authorisation decision."""

    NOT_REQUIRED = "not_required"
    INTERACTIVE = "interactive"
    NON_INTERACTIVE_DEFAULT = "non_interactive_default"
    DECLINED = "declined"


@dataclass(frozen=True)
class CacheStartupDecision:
    """Policy decision made before migration or ordinary cache-backed work begins."""

    action: CacheStartupAction
    path: Path | None = None
    authorisation: MigrationAuthorisation = MigrationAuthorisation.NOT_REQUIRED
    detail: str | None = None

    @property
    def may_begin_normal_work(self) -> bool:
        """Whether a complete current cache is already available for ordinary work."""
        return self.action is CacheStartupAction.USE_ACTIVE


def _migration_summary(resolution: CacheResolution) -> str:
    candidate = resolution.candidate
    if candidate is None:
        raise ValueError("migration resolution has no historical candidate")
    return (
        f"Discover found a supported historical cache at {candidate.path}.\n"
        f"It must be migrated from schema v{candidate.expected_schema_version} "
        "to the current schema before cache-backed Discover work can begin.\n"
        "Migration creates a separate current-version database and verifies it before cut-over."
    )


def _confirm_migration(resolution: CacheResolution, *, input_stream: TextIO, output_stream: TextIO) -> bool:
    print(_migration_summary(resolution), file=output_stream)
    print("Proceed with cache migration? [y/N] ", end="", file=output_stream, flush=True)
    answer = input_stream.readline()
    if answer == "":
        return False
    return answer.strip().casefold() in {"y", "yes"}


def decide_cache_startup(
    resolution: CacheResolution,
    *,
    interactive: bool,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
) -> CacheStartupDecision:
    """Apply startup authorisation policy to a read-only cache resolution.

    Supported mandatory migration is automatically authorised when startup is
    non-interactive. Interactive startup requires an affirmative confirmation. This
    function never reads input in non-interactive mode.
    """
    if resolution.kind is CacheResolutionKind.ACTIVE:
        if resolution.candidate is None:
            raise ValueError("active cache resolution has no candidate")
        return CacheStartupDecision(CacheStartupAction.USE_ACTIVE, path=resolution.candidate.path)
    if resolution.kind is CacheResolutionKind.FRESH_REQUIRED:
        return CacheStartupDecision(CacheStartupAction.CREATE_FRESH)
    if resolution.kind is CacheResolutionKind.BLOCKED:
        candidate = resolution.blocking_candidate
        detail = candidate.detail if candidate is not None else "cache discovery is blocked"
        return CacheStartupDecision(
            CacheStartupAction.BLOCKED,
            path=candidate.path if candidate is not None else None,
            detail=detail,
        )
    if resolution.kind is not CacheResolutionKind.MIGRATION_REQUIRED:
        raise ValueError(f"unsupported cache resolution: {resolution.kind.value}")
    if resolution.candidate is None:
        raise ValueError("migration resolution has no historical candidate")

    if not interactive:
        return CacheStartupDecision(
            CacheStartupAction.MIGRATE,
            path=resolution.candidate.path,
            authorisation=MigrationAuthorisation.NON_INTERACTIVE_DEFAULT,
        )

    if input_stream is None or output_stream is None:
        raise ValueError("interactive migration authorisation requires input and output streams")
    if _confirm_migration(resolution, input_stream=input_stream, output_stream=output_stream):
        return CacheStartupDecision(
            CacheStartupAction.MIGRATE,
            path=resolution.candidate.path,
            authorisation=MigrationAuthorisation.INTERACTIVE,
        )
    return CacheStartupDecision(
        CacheStartupAction.CANCELLED,
        path=resolution.candidate.path,
        authorisation=MigrationAuthorisation.DECLINED,
        detail="cache migration was not authorised",
    )


def terminal_startup_is_interactive(input_stream: TextIO, output_stream: TextIO) -> bool:
    """Return whether startup may safely ask an interactive migration question."""
    return bool(input_stream.isatty() and output_stream.isatty())
