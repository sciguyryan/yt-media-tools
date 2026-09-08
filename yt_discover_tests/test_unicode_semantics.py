"""Unicode semantics and regression coverage for the yt-sql text surface."""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from datetime import datetime

import pytest

from yt_discover_tests.conformance.generate_dataset import GENERATED_AT, PROFILE_SIZES, build_records
from yt_media_tools.dates import DateContext
from yt_media_tools.metadata import normalise_record
from yt_media_tools.optimizer import optimise_query
from yt_media_tools.output import write_records
from yt_media_tools.query import apply_query, evaluate_scalar_expression, parse_query, resolve_query
from yt_media_tools.schema import QuerySchema


def _records() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for source_index, raw in enumerate(build_records(PROFILE_SIZES["small"]), start=1):
        record = normalise_record(dict(raw))
        record["source_index"] = source_index
        records.append(record)
    return records


def _resolve(query: str):
    records = _records()
    context = DateContext(date_order="dmy", now=datetime.fromisoformat(GENERATED_AT))
    parsed = parse_query(query)
    resolved = resolve_query(parsed, QuerySchema(records), context)
    return records, parsed, resolved


def _ids(query: str) -> list[str]:
    records, _, resolved = _resolve(query)
    return [str(record["id"]) for record in apply_query(records, resolved)]


def test_exact_text_comparison_does_not_normalise_unicode() -> None:
    assert _ids("SELECT id FROM @yt_sql_fixture WHERE title = 'Café composed é'") == ["vid037"]
    assert _ids("SELECT id FROM @yt_sql_fixture WHERE title = 'Café decomposed é'") == ["vid038"]


def test_contains_uses_unicode_casefold_without_normalising() -> None:
    assert "vid046" in _ids("SELECT id FROM @yt_sql_fixture WHERE title CONTAINS 'strasse'")
    assert _ids("SELECT id FROM @yt_sql_fixture WHERE title CONTAINS 'CAFÉ COMPOSED'") == ["vid037"]
    assert _ids("SELECT id FROM @yt_sql_fixture WHERE title CONTAINS 'CAFÉ DECOMPOSED'") == []


@pytest.mark.parametrize(
    ("pattern", "expected"),
    (
        ("Emoji _", ["vid040"]),
        ("Flag __", ["vid042"]),
        ("Variation __", ["vid043"]),
        ("Astral _ _", ["vid056"]),
        ("Zero width joiner A_B", ["vid059"]),
        ("Zero width non-joiner A_B", ["vid060"]),
    ),
)
def test_like_underscore_counts_unicode_codepoints(pattern: str, expected: list[str]) -> None:
    assert _ids(f"SELECT id FROM @yt_sql_fixture WHERE title LIKE '{pattern}' ORDER BY source_index") == expected


def test_like_does_not_treat_fullwidth_wildcards_as_ascii_wildcards() -> None:
    assert _ids("SELECT id FROM @yt_sql_fixture WHERE title LIKE '%fullwidth ％＿'") == ["vid055"]


def test_ilike_unicode_special_case_contract_is_locked_down() -> None:
    assert _ids("SELECT id FROM @yt_sql_fixture WHERE id = 'vid045' AND title ILIKE '%i%'") == ["vid045"]
    assert _ids("SELECT id FROM @yt_sql_fixture WHERE id = 'vid047' AND title ILIKE '%k%'") == ["vid047"]
    assert _ids("SELECT id FROM @yt_sql_fixture WHERE id = 'vid048' AND title ILIKE '%s%'") == ["vid048"]
    # Unicode-aware regex case-insensitivity does not expand sharp-s to ``ss``.
    assert _ids("SELECT id FROM @yt_sql_fixture WHERE id = 'vid046' AND title ILIKE '%straße%'") == ["vid046"]


def test_matches_handles_non_latin_scripts_and_supplementary_characters() -> None:
    assert _ids("SELECT id FROM @yt_sql_fixture WHERE title MATCHES '東京|مرحبا|שלום|𐐷' ORDER BY source_index") == [
        "vid049",
        "vid050",
        "vid051",
        "vid056",
    ]


def test_lower_upper_and_length_follow_python_unicode_string_semantics() -> None:
    records, _, resolved = _resolve(
        "SELECT id, LOWER(title) AS lo, UPPER(title) AS hi, LENGTH(title) AS n "
        "FROM @yt_sql_fixture WHERE id IN ('vid038','vid041','vid044','vid045','vid046') ORDER BY source_index"
    )
    selected = apply_query(records, resolved)
    projected = [
        {
            "id": row["id"],
            "lo": evaluate_scalar_expression(
                next(term for term in resolved.select if term.output_name == "lo").expression, row
            ),
            "hi": evaluate_scalar_expression(
                next(term for term in resolved.select if term.output_name == "hi").expression, row
            ),
            "n": evaluate_scalar_expression(
                next(term for term in resolved.select if term.output_name == "n").expression, row
            ),
        }
        for row in selected
    ]
    by_id = {row["id"]: row for row in projected}
    assert by_id["vid038"]["n"] == len("Café decomposed é")
    assert by_id["vid041"]["n"] == len("Emoji family 👩‍👩‍👧‍👦")
    assert by_id["vid044"]["lo"] == "Greek Σ σ ς".lower()
    assert by_id["vid045"]["lo"] == "Turkish İ I ı i".lower()
    assert by_id["vid046"]["hi"] == "German Straße STRASSE".upper()


def test_ordering_uses_unmodified_unicode_string_values() -> None:
    wanted = {"vid044", "vid045", "vid046", "vid047", "vid048", "vid049", "vid050", "vid051"}
    rows = [row for row in _records() if row["id"] in wanted]
    expected = [str(row["id"]) for row in sorted(rows, key=lambda row: str(row["title"]))]
    actual = _ids(
        "SELECT id FROM @yt_sql_fixture WHERE id IN "
        "('vid044','vid045','vid046','vid047','vid048','vid049','vid050','vid051') ORDER BY title"
    )
    assert actual == expected


def test_unicode_scalar_constant_folding_is_observationally_equivalent() -> None:
    records, parsed, original = _resolve(
        "SELECT LOWER('İ') AS lo, UPPER('straße') AS hi, LENGTH('👩‍👩‍👧‍👦') AS n FROM @yt_sql_fixture LIMIT 1"
    )
    optimised = optimise_query(original).query
    assert apply_query(records, original) == apply_query(records, optimised)

    original_stream = io.StringIO()
    with redirect_stdout(original_stream):
        write_records(apply_query(records, original), original, "jsonl", None, explicit_select=bool(parsed.select))
    optimised_stream = io.StringIO()
    with redirect_stdout(optimised_stream):
        write_records(apply_query(records, optimised), optimised, "jsonl", None, explicit_select=bool(parsed.select))
    assert optimised_stream.getvalue() == original_stream.getvalue()
    assert "İ".lower() in original_stream.getvalue()


def test_unicode_jsonl_output_preserves_text_without_ascii_escaping() -> None:
    records, parsed, resolved = _resolve(
        "SELECT id, title FROM @yt_sql_fixture WHERE id IN ('vid040','vid049','vid050','vid051') ORDER BY source_index"
    )
    stream = io.StringIO()
    with redirect_stdout(stream):
        write_records(apply_query(records, resolved), resolved, "jsonl", None, explicit_select=bool(parsed.select))
    text = stream.getvalue()
    assert "😀" in text
    assert "東京" in text
    assert "مرحبا" in text
    assert "שלום" in text


def test_all_unicode_anchor_titles_survive_projection_unchanged() -> None:
    records, _, resolved = _resolve(
        "SELECT id, title FROM @yt_sql_fixture WHERE source_index BETWEEN 37 AND 60 ORDER BY source_index"
    )
    selected = apply_query(records, resolved)
    actual = [(str(row["id"]), str(row["title"])) for row in selected]
    expected = [(str(row["id"]), str(row["title"])) for row in records if 37 <= int(row["source_index"]) <= 60]
    assert actual == expected


def test_like_percent_spans_ascii_newline_and_unicode_line_separator() -> None:
    assert _ids("SELECT id FROM @yt_sql_fixture WHERE title LIKE 'Line%break'") == ["vid057"]
    assert _ids("SELECT id FROM @yt_sql_fixture WHERE title LIKE 'Line separator %'") == ["vid058"]


def test_ilike_does_not_normalise_composed_and_decomposed_forms() -> None:
    assert _ids("SELECT id FROM @yt_sql_fixture WHERE title ILIKE '%café composed%'") == ["vid037"]
    assert _ids("SELECT id FROM @yt_sql_fixture WHERE title ILIKE '%café decomposed%'") == []
