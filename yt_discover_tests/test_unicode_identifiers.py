"""Conformance tests for the ordinary Unicode yt-sql identifier grammar."""

from __future__ import annotations

import pytest

from yt_media_tools.query import QuerySemanticError, QuerySyntaxError, parse_query, resolve_query
from yt_media_tools.query_formatter import format_query
from yt_media_tools.query_parser import tokenise
from yt_media_tools.schema import QuerySchema


def _resolve(source: str, rows: list[dict]):
    return resolve_query(parse_query(source), QuerySchema(rows))


def test_xid_unicode_identifiers_are_accepted_and_preserved() -> None:
    rows = [{"café": "composed", "東京": "tokyo", "Δelta": "delta", "snake_name": "snake"}]
    query = _resolve("SELECT café, 東京, Δelta, snake_name FROM @fixture", rows)
    assert [term.output_name for term in query.select] == ["café", "東京", "Δelta", "snake_name"]
    assert format_query(query).startswith("SELECT café, 東京, Δelta, snake_name")


def test_xid_continue_accepts_combining_marks() -> None:
    decomposed = "cafe\u0301"
    query = _resolve(f"SELECT {decomposed} FROM @fixture", [{decomposed: "value"}])
    assert query.select[0].output_name == decomposed


def test_no_unicode_normalisation_is_performed() -> None:
    composed = "café"
    decomposed = "cafe\u0301"
    query = _resolve(
        f"SELECT {composed}, {decomposed} FROM @fixture",
        [{composed: "composed", decomposed: "decomposed"}],
    )
    assert [term.output_name for term in query.select] == [composed, decomposed]
    assert composed != decomposed


def test_identifier_must_begin_with_xid_start_or_underscore() -> None:
    with pytest.raises(QuerySyntaxError, match="Unexpected character"):
        parse_query("SELECT \u0301mark FROM @fixture")


def test_non_xid_unicode_word_character_is_rejected_as_identifier_start() -> None:
    with pytest.raises(QuerySyntaxError, match="Unexpected character"):
        parse_query("SELECT ²value FROM @fixture")


def test_identifier_components_may_not_begin_with_digits() -> None:
    tokens = tokenise("alpha.2beta")
    assert [(token.kind, token.text) for token in tokens[:2]] == [("IDENT", "alpha"), ("DOT", ".")]
    assert tokens[0].text != "alpha.2beta"


def test_established_unquoted_hyphen_extension_is_retained() -> None:
    query = _resolve("SELECT release-title FROM @fixture", [{"release-title": "value"}])
    assert query.select[0].output_name == "release-title"


def test_spaced_hyphen_remains_subtraction() -> None:
    query = _resolve("SELECT alpha - beta FROM @fixture", [{"alpha": 7, "beta": 2}])
    assert format_query(query).startswith("SELECT (alpha - beta)")


def test_unicode_identifier_resolution_remains_case_sensitive() -> None:
    rows = [{"Δelta": "upper", "δelta": "lower"}]
    query = _resolve("SELECT Δelta, δelta FROM @fixture", rows)
    assert [term.output_name for term in query.select] == ["Δelta", "δelta"]
    with pytest.raises(QuerySemanticError, match="Unknown field"):
        _resolve("SELECT ΔELTA FROM @fixture", rows)
