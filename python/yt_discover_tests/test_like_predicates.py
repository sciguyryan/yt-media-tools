"""Tests for yt-sql LIKE and ILIKE predicates."""

from __future__ import annotations

import pytest

from yt_media_tools.optimizer import optimise_query
import yt_media_tools.query_evaluator as evaluator_module
from yt_media_tools.query import (
    apply_query,
    format_query,
    like_matches,
    parse_query,
    resolve_query,
)
from yt_media_tools.schema import QuerySchema


def _resolved(source: str, records: list[dict[str, object]]):
    return resolve_query(parse_query(source), QuerySchema(records))


def test_like_terminal_escaped_backslash_is_supported() -> None:
    """Retained pending a committed fixture value ending with a backslash.

    The escaped-percent, escaped-underscore and escaped-backslash assertions
    are normative in the portable corpus. Only the pattern-terminal escaped
    backslash remains here because no committed dataset value ends with a
    backslash, so the obligation cannot be expressed portably yet.
    """
    records = [{"id": "slash", "title": "abc\\"}]
    query = _resolved(r"WHERE title LIKE 'abc\\'", records)
    assert apply_query(records, query)[0]["id"] == "slash"


def test_optimizer_preserves_like_and_matches_without_unproven_cross_rewrite() -> None:
    records = [{"id": "a", "title": "The "}, {"id": "b", "title": "x The thing"}, {"id": "c", "title": None}]
    for source in ("WHERE title LIKE 'The %'", r"WHERE title MATCHES 'The .+?'"):
        original = _resolved(source, records)
        result = optimise_query(original)
        assert result.query == original
        assert result.decisions == ()
        assert apply_query(records, result.query) == apply_query(records, original)


def test_like_formatting_is_stable() -> None:
    records = [{"id": "a", "title": "Mars"}]
    query = _resolved("WHERE title NOT ILIKE 'mars%'", records)
    assert format_query(query) == "SELECT id WHERE title NOT ILIKE 'mars%'"


def test_exact_case_sensitive_like_bypasses_regex_compilation(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_compile(*_args, **_kwargs):
        raise AssertionError("exact LIKE should not invoke the regex compiler")

    monkeypatch.setattr(evaluator_module, "_compile_like_pattern", fail_compile)
    assert like_matches("Cymru 🏴󠁧󠁢󠁷󠁬󠁳󠁿", "Cymru 🏴󠁧󠁢󠁷󠁬󠁳󠁿")
    assert like_matches("100%", r"100\%")
    assert not like_matches("1000", r"100\%")


def test_ilike_and_wildcard_like_keep_regex_semantics(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    real = evaluator_module._compile_like_pattern

    def recording_compile(pattern: str, case_insensitive: bool):
        calls.append((pattern, case_insensitive))
        return real(pattern, case_insensitive)

    monkeypatch.setattr(evaluator_module, "_compile_like_pattern", recording_compile)
    assert like_matches("Mars mission", "Mars%")
    assert like_matches("MARS", "mars", case_insensitive=True)
    assert calls == [("Mars%", False), ("mars", True)]
