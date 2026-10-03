"""Tests for cache startup migration authorisation policy."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

from yt_media_tools.cache_discovery import (
    CacheCandidate,
    CacheCandidateKind,
    CacheCandidateState,
    CacheResolution,
    CacheResolutionKind,
)
from yt_media_tools.cache_startup_policy import (
    CacheStartupAction,
    MigrationAuthorisation,
    decide_cache_startup,
    terminal_startup_is_interactive,
)


class _TTY(StringIO):
    def __init__(self, value: str = "", *, tty: bool) -> None:
        super().__init__(value)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


class _ExplodingInput(StringIO):
    def readline(self, *args: object, **kwargs: object) -> str:
        raise AssertionError("non-interactive startup attempted to read input")


def _candidate(kind: CacheCandidateKind = CacheCandidateKind.HISTORICAL) -> CacheCandidate:
    version = 3 if kind is CacheCandidateKind.HISTORICAL else 4
    name = "metadata.sqlite3" if version == 3 else "metadata-v4.sqlite3"
    return CacheCandidate(Path("/cache") / name, kind, version, CacheCandidateState.VALID, version, "complete")


def test_active_current_cache_is_immediately_usable() -> None:
    candidate = _candidate(CacheCandidateKind.CURRENT)
    decision = decide_cache_startup(CacheResolution(CacheResolutionKind.ACTIVE, candidate=candidate), interactive=False)
    assert decision.action is CacheStartupAction.USE_ACTIVE
    assert decision.path == candidate.path
    assert decision.may_begin_normal_work


def test_missing_cache_requests_fresh_current_cache_without_authorisation() -> None:
    decision = decide_cache_startup(CacheResolution(CacheResolutionKind.FRESH_REQUIRED), interactive=False)
    assert decision.action is CacheStartupAction.CREATE_FRESH
    assert decision.authorisation is MigrationAuthorisation.NOT_REQUIRED
    assert not decision.may_begin_normal_work


def test_blocked_candidate_remains_blocked_without_prompting() -> None:
    candidate = CacheCandidate(
        Path("/cache/metadata-v4.sqlite3"),
        CacheCandidateKind.CURRENT,
        4,
        CacheCandidateState.INCOMPLETE,
        4,
        "incomplete",
        "current-schema cache is not marked complete",
    )
    decision = decide_cache_startup(
        CacheResolution(CacheResolutionKind.BLOCKED, blocking_candidate=candidate),
        interactive=True,
        input_stream=_ExplodingInput(),
        output_stream=StringIO(),
    )
    assert decision.action is CacheStartupAction.BLOCKED
    assert decision.path == candidate.path
    assert "not marked complete" in (decision.detail or "")


def test_non_interactive_mandatory_migration_uses_documented_default_without_reading_input() -> None:
    candidate = _candidate()
    decision = decide_cache_startup(
        CacheResolution(CacheResolutionKind.MIGRATION_REQUIRED, candidate=candidate),
        interactive=False,
        input_stream=_ExplodingInput(),
        output_stream=StringIO(),
    )
    assert decision.action is CacheStartupAction.MIGRATE
    assert decision.path == candidate.path
    assert decision.authorisation is MigrationAuthorisation.NON_INTERACTIVE_DEFAULT
    assert not decision.may_begin_normal_work


@pytest.mark.parametrize("answer", ["y\n", "Y\n", "yes\n", " YES \n"])
def test_interactive_migration_accepts_explicit_affirmative_answer(answer: str) -> None:
    candidate = _candidate()
    output = StringIO()
    decision = decide_cache_startup(
        CacheResolution(CacheResolutionKind.MIGRATION_REQUIRED, candidate=candidate),
        interactive=True,
        input_stream=StringIO(answer),
        output_stream=output,
    )
    assert decision.action is CacheStartupAction.MIGRATE
    assert decision.authorisation is MigrationAuthorisation.INTERACTIVE
    assert "schema v3" in output.getvalue()
    assert "[y/N]" in output.getvalue()


@pytest.mark.parametrize("answer", ["\n", "n\n", "no\n", "anything else\n", ""])
def test_interactive_migration_declines_by_default(answer: str) -> None:
    candidate = _candidate()
    decision = decide_cache_startup(
        CacheResolution(CacheResolutionKind.MIGRATION_REQUIRED, candidate=candidate),
        interactive=True,
        input_stream=StringIO(answer),
        output_stream=StringIO(),
    )
    assert decision.action is CacheStartupAction.CANCELLED
    assert decision.authorisation is MigrationAuthorisation.DECLINED
    assert not decision.may_begin_normal_work


def test_interactive_policy_requires_explicit_streams() -> None:
    with pytest.raises(ValueError, match="requires input and output streams"):
        decide_cache_startup(
            CacheResolution(CacheResolutionKind.MIGRATION_REQUIRED, candidate=_candidate()),
            interactive=True,
        )


@pytest.mark.parametrize(
    ("input_tty", "output_tty", "expected"),
    [(True, True, True), (True, False, False), (False, True, False), (False, False, False)],
)
def test_terminal_interactivity_requires_both_input_and_output_ttys(
    input_tty: bool, output_tty: bool, expected: bool
) -> None:
    assert terminal_startup_is_interactive(_TTY(tty=input_tty), _TTY(tty=output_tty)) is expected
