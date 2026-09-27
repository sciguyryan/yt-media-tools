"""Tests for yt-sql LIKE and ILIKE predicates."""

from __future__ import annotations

import pytest

from yt_media_tools.optimizer import optimise_query
import yt_media_tools.query_evaluator as evaluator_module
from yt_media_tools.query import (
    QuerySyntaxError,
    apply_query,
    evaluate,
    format_query,
    like_matches,
    parse_query,
    resolve_query,
)
from yt_media_tools.schema import QuerySchema


def _resolved(source: str, records: list[dict[str, object]]):
    return resolve_query(parse_query(source), QuerySchema(records))


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("WHERE title LIKE 'Mars%'", [True, False, False, None]),
        ("WHERE title ILIKE 'mars%'", [True, True, False, None]),
        ("WHERE title NOT LIKE 'Mars%'", [False, True, True, None]),
        ("WHERE title NOT ILIKE 'mars%'", [False, False, True, None]),
        ("WHERE title LIKE '%mission%'", [True, False, True, None]),
        ("WHERE title LIKE 'Mars_mission'", [True, False, False, None]),
        (r"WHERE title LIKE 'Mars\_mission'", [True, False, False, None]),
    ],
)
def test_like_semantics(source: str, expected: list[bool | None]) -> None:
    records = [
        {"id": "a", "title": "Mars_mission"},
        {"id": "b", "title": "mars Mission"},
        {"id": "c", "title": "Venus mission"},
        {"id": "d", "title": None},
    ]
    query = _resolved(source, records)
    assert [evaluate(query.predicate, record) for record in records] == expected


def test_like_wildcards_cover_newlines_and_unicode_code_points() -> None:
    records = [
        {"id": "newline", "title": "a\nb"},
        {"id": "unicode", "title": "a😀b"},
        {"id": "two", "title": "a😀😀b"},
    ]
    one = _resolved("WHERE title LIKE 'a_b'", records)
    many = _resolved("WHERE title LIKE 'a%b'", records)
    assert [evaluate(one.predicate, record) for record in records] == [True, True, False]
    assert [evaluate(many.predicate, record) for record in records] == [True, True, True]


def test_like_backslash_quotes_percent_underscore_and_backslash() -> None:
    records = [
        {"id": "percent", "title": "100%"},
        {"id": "underscore", "title": "a_b"},
        {"id": "slash", "title": r"a\b"},
    ]
    assert apply_query(records, _resolved(r"WHERE title LIKE '100\%'", records))[0]["id"] == "percent"
    assert apply_query(records, _resolved(r"WHERE title LIKE 'a\_b'", records))[0]["id"] == "underscore"
    assert apply_query(records, _resolved(r"WHERE title LIKE 'a\\b'", records))[0]["id"] == "slash"


def test_like_requires_quoted_pattern() -> None:
    with pytest.raises(QuerySyntaxError, match="quoted text"):
        parse_query("WHERE title LIKE Mars%")


def test_like_terminal_escaped_backslash_is_supported() -> None:
    records = [{"id": "slash", "title": "abc\\"}]
    query = _resolved(r"WHERE title LIKE 'abc\\'", records)
    assert apply_query(records, query)[0]["id"] == "slash"


@pytest.mark.parametrize("operator", ["LIKE", "ILIKE"])
def test_like_requires_text_field(operator: str) -> None:
    records = [{"id": "a", "view_count": 10}]
    with pytest.raises(QuerySyntaxError, match=f"{operator} requires a text field"):
        _resolved(f"WHERE view_count {operator} '10'", records)


def test_does_not_like_alias_is_supported() -> None:
    records = [{"id": "a", "title": "Mars"}, {"id": "b", "title": "Venus"}]
    query = _resolved("WHERE title DOES NOT LIKE 'Mars%'", records)
    assert [row["id"] for row in apply_query(records, query)] == ["b"]


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
