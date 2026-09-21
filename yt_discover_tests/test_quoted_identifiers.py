"""Conformance tests for backtick-quoted yt-sql identifiers."""

from __future__ import annotations

import pytest

from yt_media_tools.query import parse_query
from yt_media_tools.query_formatter import format_query, format_scalar_expression
from yt_media_tools.query_model import Field, QuerySyntaxError, ScalarMember
from yt_media_tools.query_parser import tokenise


def test_backtick_identifier_token_preserves_exact_value() -> None:
    token = tokenise("SELECT `release title` FROM @fixture")[1]
    assert (token.kind, token.text, token.value) == ("QIDENT", "`release title`", "release title")


def test_doubled_backtick_escapes_embedded_backtick() -> None:
    query = parse_query("SELECT title AS `odd``name` FROM @fixture")
    assert query.select[0].alias == "odd`name"
    assert format_query(query) == "SELECT title AS `odd``name` FROM @fixture"


def test_quoted_reserved_literal_word_is_an_identifier() -> None:
    query = parse_query("SELECT `true` FROM @fixture")
    assert query.select[0].expression == Field("true", 7)
    assert format_query(query) == "SELECT `true` FROM @fixture"


def test_contextual_keyword_does_not_need_quotes_in_canonical_output() -> None:
    query = parse_query("SELECT title AS `format` FROM @fixture")
    assert query.select[0].alias == "format"
    assert format_query(query) == "SELECT title AS format FROM @fixture"


def test_quoted_alias_and_cte_name_round_trip() -> None:
    source = "WITH `source name` AS (SELECT id FROM @fixture) SELECT id AS `output name` FROM `source name`"
    query = parse_query(source)
    assert query.ctes[0].name == "source name"
    assert query.from_source == "source name"
    assert query.select[0].alias == "output name"
    assert format_query(query) == source


def test_quoted_relation_alias_and_wildcard_round_trip() -> None:
    source = "SELECT `left side`.* FROM @fixture AS `left side`"
    assert format_query(parse_query(source)) == source


def test_quoted_raw_backend_key_segment_round_trip() -> None:
    query = parse_query("SELECT raw.`provider key` FROM @fixture")
    assert query.select[0].expression == Field("raw.provider key", 7)
    assert format_query(query) == "SELECT raw.`provider key` FROM @fixture"


def test_quoted_structured_member_round_trip() -> None:
    query = parse_query("SELECT formats[0].`video height` FROM @fixture")
    expression = query.select[0].expression
    assert isinstance(expression, ScalarMember)
    assert expression.member == "video height"
    assert format_scalar_expression(expression) == "formats[0].`video height`"
    assert format_query(parse_query(format_query(query))) == format_query(query)


def test_quoted_and_unquoted_same_spelling_have_same_semantic_name() -> None:
    plain = parse_query("SELECT title FROM @fixture").select[0].expression
    quoted = parse_query("SELECT `title` FROM @fixture").select[0].expression
    assert plain.name == quoted.name == "title"


def test_empty_quoted_identifier_is_rejected() -> None:
    with pytest.raises(QuerySyntaxError, match="Quoted identifier cannot be empty"):
        parse_query("SELECT `` FROM @fixture")


def test_unterminated_quoted_identifier_has_dedicated_diagnostic() -> None:
    with pytest.raises(QuerySyntaxError) as exc_info:
        parse_query("SELECT `broken FROM @fixture")
    assert exc_info.value.message == "Unterminated quoted identifier."
    assert exc_info.value.position == 7


def test_cte_names_differing_only_by_case_can_coexist() -> None:
    query = parse_query("WITH Base AS (SELECT id FROM @fixture), base AS (SELECT id FROM @fixture) SELECT id FROM Base")
    assert [cte.name for cte in query.ctes] == ["Base", "base"]


def test_quoted_raw_backend_key_resolves_exact_spelling() -> None:
    from yt_media_tools.query import resolve_query
    from yt_media_tools.schema import QuerySchema

    parsed = parse_query("SELECT raw.`provider key` FROM @fixture")
    resolved = resolve_query(parsed, QuerySchema([{"id": "a", "_raw": {"provider key": 3}}]))
    assert resolved.select[0].expression == Field("raw.provider key", 7, "integer")


def test_quoted_relation_alias_can_qualify_fields() -> None:
    from yt_media_tools.query import RelationField, resolve_join_references
    from yt_media_tools.schema import QuerySchema

    left = QuerySchema([{"id": "left"}])
    right = QuerySchema([{"id": "right", "title": "Right"}])
    query = parse_query(
        "SELECT `right side`.title FROM @left AS `left side` "
        "JOIN @right AS `right side` ON `left side`.id = `right side`.id"
    )
    resolved = resolve_join_references(
        query,
        left,
        source_schemas={("@left", None): left, ("@right", None): right},
    )
    expression = resolved.select[0].expression
    assert isinstance(expression, RelationField)
    assert expression.qualifier == "right side"
    assert expression.name == "title"
    assert format_query(query).startswith("SELECT `right side`.title")


def test_quoted_cte_reference_stays_quoted_across_set_branch() -> None:
    source = "WITH `true` AS (SELECT id FROM @fixture) SELECT id FROM `true` UNION SELECT id FROM `true`"
    canonical = format_query(parse_query(source))
    assert canonical == source
    assert format_query(parse_query(canonical)) == canonical


def test_resolved_quoted_nonordinary_field_preserves_output_name_and_formatting() -> None:
    from yt_media_tools.query import apply_query, resolve_query
    from yt_media_tools.schema import QuerySchema

    name = "a\U0001f600"
    rows = [{name: "value"}]
    resolved = resolve_query(parse_query(f"SELECT `{name}` FROM @fixture"), QuerySchema(rows))
    assert resolved.select[0].output_name == name
    assert apply_query(rows, resolved) == [{name: "value"}]
    assert format_query(resolved) == f"SELECT `{name}` FROM @fixture"
