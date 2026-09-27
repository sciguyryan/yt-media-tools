"""Conformance coverage for the frozen identifier and keyword classification."""

from yt_media_tools.query_parser import _CONTEXTUAL_KEYWORDS, _RESERVED_LITERAL_WORDS, parse_query


def test_reserved_and_contextual_keyword_inventories_are_explicit_and_disjoint() -> None:
    assert _RESERVED_LITERAL_WORDS == {"TRUE", "FALSE", "NULL"}
    assert _RESERVED_LITERAL_WORDS.isdisjoint(_CONTEXTUAL_KEYWORDS)
    assert {"SELECT", "JOIN", "SEMI", "ANTI", "ANY", "ALL", "UNKNOWN"} <= _CONTEXTUAL_KEYWORDS | {"ANY"}


def test_contextual_keyword_spellings_remain_identifiers_in_unambiguous_positions() -> None:
    query = parse_query("SELECT select, Select, SELECT, join, semi, anti, unknown FROM @example")
    assert [term.expression.name for term in query.select] == [
        "select",
        "Select",
        "SELECT",
        "join",
        "semi",
        "anti",
        "unknown",
    ]


def test_reserved_literal_spelling_requires_quoting_when_used_as_identifier() -> None:
    query = parse_query("SELECT `true`, `FALSE`, `null` FROM @example")
    assert [term.expression.name for term in query.select] == ["true", "FALSE", "null"]
