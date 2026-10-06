"""Baseline differential inventory for the experimental Lark parser."""

from __future__ import annotations

from dataclasses import replace

import pytest

from yt_discover_tests.conformance.cases import CASES
from yt_discover_tests.parser_fuzzing import seeded_parser_fuzz_inputs, shrink_by_token_deletion
from yt_discover_tests.parser_grammar_generation import generated_valid_queries
from yt_discover_tests.parser_migration_corpus import ACCEPTED_PARSER_CASES, REJECTED_PARSER_CASES
from yt_discover_tests.parser_migration_harness import ParserDifference, canonical_round_trip, compare_parsers
from yt_discover_tests.parser_mutation import malformed_neighbours
from yt_media_tools.discover_cli import bind_query_parameters
from yt_media_tools.experimental_lark_parser import parse_lark_query
from yt_media_tools.query_formatter import format_query
from yt_media_tools.query_model import Query, QuerySyntaxError
from yt_media_tools.query_parser import parse_query


def _bound_conformance_query(query: str, parameters: tuple[str, ...]) -> str:
    values = dict(parameter.split("=", 1) for parameter in parameters)
    return bind_query_parameters(query, values)


def _accepted_inventory() -> tuple[tuple[str, str], ...]:
    cases = [(f"migration:{case.name}", case.query) for case in ACCEPTED_PARSER_CASES]
    cases.extend((f"conformance:{case.name}", _bound_conformance_query(case.query, case.params)) for case in CASES)
    cases.extend(
        (f"generated:{index}:{case.production}", case.query)
        for index, case in enumerate(generated_valid_queries(rounds=3))
    )
    return tuple(cases)


def _malformed_mutation_inventory() -> tuple[tuple[str, str], ...]:
    cases = {
        mutation.source: mutation.name
        for generated in generated_valid_queries(rounds=3)
        for mutation in malformed_neighbours(generated.query)
    }
    return tuple((name, source) for source, name in cases.items())


def test_differential_harness_reports_independent_model_and_origin_differences() -> None:
    source = "SELECT id FROM @fixture"

    def changed_model(text: str) -> Query:
        return replace(parse_query(text), limit=1)

    model_comparison = compare_parsers(parse_query, changed_model, source)
    assert model_comparison.differences == (ParserDifference.MODEL,)
    assert model_comparison.describe() == "model"

    def changed_origin(text: str) -> Query:
        query = parse_query(text)
        return replace(query, select=(replace(query.select[0], position=query.select[0].position + 1),))

    origin_comparison = compare_parsers(parse_query, changed_origin, source)
    assert origin_comparison.differences == (ParserDifference.ORIGINS,)
    assert origin_comparison.describe() == "origins"


def test_differential_harness_contains_and_reports_unexpected_errors() -> None:
    def broken_parser(_source: str) -> Query:
        raise IndexError("model construction escaped")

    comparison = compare_parsers(parse_query, broken_parser, "SELECT id FROM @fixture")

    assert comparison.differences == (ParserDifference.UNEXPECTED_ERROR,)
    assert comparison.candidate.unexpected_error == ("IndexError", "model construction escaped")
    assert comparison.describe() == "unexpected-error"


def test_differential_harness_distinguishes_acceptance_and_diagnostics() -> None:
    def rejecting_parser(source: str) -> Query:
        raise QuerySyntaxError(source, "candidate rejection", len(source))

    acceptance = compare_parsers(parse_query, rejecting_parser, "SELECT id FROM @fixture")
    assert acceptance.differences == (ParserDifference.ACCEPTANCE,)
    assert acceptance.describe() == "acceptance"

    diagnostic = compare_parsers(parse_query, rejecting_parser, "SELECT FROM @fixture")
    assert diagnostic.differences == (ParserDifference.DIAGNOSTIC,)
    assert diagnostic.describe() == "diagnostic"


def test_normalised_model_excludes_non_semantic_literal_source_spelling() -> None:
    single_quoted = compare_parsers(
        parse_query,
        parse_query,
        "SELECT id FROM @fixture WHERE title = 'Case Test'",
    ).reference.model
    double_quoted = compare_parsers(
        parse_query,
        parse_query,
        'SELECT id FROM @fixture WHERE title = "Case Test"',
    ).reference.model

    assert double_quoted == single_quoted


def test_lark_accepted_syntax_inventory_is_structurally_equivalent() -> None:
    cases = _accepted_inventory()
    assert cases

    for name, source in cases:
        comparison = compare_parsers(parse_query, parse_lark_query, source)
        assert comparison.reference.kind == "accepted", name
        assert comparison.equivalent, f"{name}: {comparison.describe()}"


def test_lark_accepted_syntax_inventory_has_canonical_cross_parser_convergence() -> None:
    for name, source in _accepted_inventory():
        reference_model, reference_canonical = canonical_round_trip(parse_query, source)
        candidate_model, candidate_canonical = canonical_round_trip(parse_lark_query, source)

        assert candidate_model == reference_model, name
        assert candidate_canonical == reference_canonical, name
        canonical_comparison = compare_parsers(parse_query, parse_lark_query, reference_canonical)
        assert canonical_comparison.equivalent, f"{name}: {canonical_comparison.describe()}"


def test_lark_malformed_syntax_inventory_is_diagnostically_equivalent() -> None:
    for case in REJECTED_PARSER_CASES:
        comparison = compare_parsers(parse_query, parse_lark_query, case.query)
        assert comparison.reference.kind == "rejected", case.name
        assert comparison.candidate.kind == "rejected", case.name
        assert comparison.equivalent, f"{case.name}: {comparison.describe()}"


def test_lark_controlled_malformed_neighbours_are_diagnostically_equivalent() -> None:
    cases = _malformed_mutation_inventory()
    assert cases

    for name, source in cases:
        comparison = compare_parsers(parse_query, parse_lark_query, source)
        assert comparison.reference.kind == "rejected", name
        assert comparison.candidate.kind == "rejected", name
        assert comparison.equivalent, f"{name}: {comparison.describe()} for {source!r}"


@pytest.mark.parametrize("seed", (0, 1, 2, 3, 31415926, 27182818, 16180339, 14142135))
def test_lark_seeded_fuzz_inputs_are_differentially_equivalent(seed: int) -> None:
    inputs = seeded_parser_fuzz_inputs(seed=seed, limit=128)
    assert inputs

    for index, source in enumerate(inputs):
        comparison = compare_parsers(parse_query, parse_lark_query, source)
        smaller = shrink_by_token_deletion(source)[:3]
        context = f"seed={seed}, case={index}, source={source!r}, smaller={smaller!r}"
        assert comparison.equivalent, f"{context}: {comparison.describe()}"

        if comparison.reference.kind != "accepted":
            continue
        reference_model, reference_canonical = canonical_round_trip(parse_query, source)
        candidate_model, candidate_canonical = canonical_round_trip(parse_lark_query, source)
        assert candidate_model == reference_model, context
        assert candidate_canonical == reference_canonical, context


MAXIMAL_DERIVED_RELATION_TORTURE_QUERY = r"""WITH `Ω seed` AS (
SELECT DISTINCT id, title, tags, formats, duration, view_count, upload_date, is_live,
       LOWER(title) AS `é!`, UPPER(title) AS `é!`, LENGTH(title) AS `👩‍💻`,
       CARDINALITY(tags) AS tag_count,
       COUNT(tags AS tag WHERE tag IS NOT NULL AND tag != 'skip') AS kept_count,
       FILTER(tags AS tag WHERE tag IS NOT NULL AND tag != 'skip') AS kept,
       MAP(tags AS tag SELECT UPPER(tag)) AS mapped,
       COALESCE(title, '∅') AS fallback,
       CONCAT(COALESCE(title, ''), CHAR(0x20, 0x1F642)) AS `🏴󠁧󠁢󠁷󠁬󠁳󠁿`,
       NULLIF(title, '') AS nonempty,
       GREATEST(COALESCE(view_count, 0), 0x10, 0o17, 0b1110) AS hi,
       LEAST(COALESCE(view_count, 0), 0xFF, 0o755, 0b1010_0101) AS lo_num,
       CASE WHEN is_live IS TRUE THEN 0x1 WHEN is_live IS FALSE THEN 0o2 ELSE 0b11 END AS live_rank,
       RANDOM(31415926) AS seeded,
       (+0x10 + 0o7 * 0b10 - 3) / 2 % 5 AS arithmetic
FROM @yt_sql_fixture OF videos, shorts
WHERE ((ANY(tags AS tag WHERE tag = 'mars' OR tag = 'unicode')
        OR ALL(tags AS tag WHERE tag IS NOT NULL))
       AND title IS DISTINCT FROM NULL
       AND title IS NOT DISTINCT FROM title
       AND title NOT LIKE 'never%'
       AND title NOT ILIKE 'NEVER%'
       AND title MATCHES '.*'
       AND title NOT MATCHES '^$'
       AND title DOES NOT CONTAIN 'definitely absent'
       AND duration NOT BETWEEN 0s AND 1.5m
       AND upload_date BETWEEN -INFINITY() AND TODAY()+1baktun
       AND release_timestamp < NOW()+2hour
       AND view_count IN (0, 0x10, 0o20, 0b1_0000, 1k, 2m)
       AND view_count NOT IN (-1, -0x2)
       AND (is_live IS NOT TRUE OR is_live IS UNKNOWN OR is_live IS NOT UNKNOWN))
ORDER BY seeded DESC, `🏴󠁧󠁢󠁷󠁬󠁳󠁿` ASC LIMIT 32 OFFSET 1
), `left pain` AS (
SELECT id, title, duration, view_count, tags, formats, `🏴󠁧󠁢󠁷󠁬󠁳󠁿`, `é!`, `é!`, `👩‍💻`, seeded
FROM (SELECT id, title, duration, view_count, tags, formats, `🏴󠁧󠁢󠁷󠁬󠁳󠁿`, `é!`, `é!`, `👩‍💻`, seeded FROM `Ω seed` ORDER BY seeded LIMIT 16) AS d
WHERE formats[0].height IS NULL OR formats[0].height >= 0x2D0
), `right pain` AS (
SELECT id, title, duration, view_count, tags, formats
FROM (SELECT id, title, duration, view_count, tags, formats FROM @yt_sql_fixture WHERE upload_date >= 2026-08-01 UNION SELECT id, title, duration, view_count, tags, formats FROM @yt_sql_fixture WHERE upload_date < 2026-08-01) AS r
WHERE NOT (title = 'impossible' AND view_count <> 0)
), `joined agony` AS (
SELECT l.id AS id, l.title AS title, r.title AS right_title,
       l.duration AS duration, l.view_count AS view_count,
       `🏴󠁧󠁢󠁷󠁬󠁳󠁿`, `é!`, `é!`, `👩‍💻`, l.seeded AS seeded,
       COUNT(*) FILTER (WHERE r.title IS NOT NULL) AS matches,
       SUM(COALESCE(r.duration, 0)) AS total_duration,
       MIN(COALESCE(r.view_count, 0)) AS min_views,
       MAX(COALESCE(r.view_count, 0)) AS max_views,
       AVG(COALESCE(r.view_count, 0)) AS avg_views
FROM `left pain` AS l INNER JOIN `right pain` AS r
ON l.id = r.id AND (l.title = r.title OR l.title IS DISTINCT FROM r.title)
WHERE l.duration >= 0s OR l.duration IS NULL
GROUP BY l.id, l.title, r.title, l.duration, l.view_count, `🏴󠁧󠁢󠁷󠁬󠁳󠁿`, `é!`, `é!`, `👩‍💻`, l.seeded
HAVING COUNT(*) >= 0b1 AND SUM(COALESCE(r.duration, 0)) IS NOT NULL
)
SELECT id, `🏴󠁧󠁢󠁷󠁬󠁳󠁿`, `é!`, `é!`, `👩‍💻`, matches, total_duration, min_views, max_views, avg_views,
       CASE WHEN right_title IS NULL THEN '∅' ELSE right_title END AS branch
FROM (SELECT * FROM `joined agony` WHERE matches > 0) AS final
UNION ALL
SELECT l.id, `🏴󠁧󠁢󠁷󠁬󠁳󠁿`, `é!`, `é!`, `👩‍💻`, 0 AS matches, 0 AS total_duration, 0 AS min_views, 0 AS max_views, 0 AS avg_views, 'left' AS branch
FROM `left pain` AS l LEFT OUTER JOIN `right pain` AS r ON l.id = r.id
WHERE r.id IS NULL
UNION ALL
SELECT l.id, `🏴󠁧󠁢󠁷󠁬󠁳󠁿`, `é!`, `é!`, `👩‍💻`, 1 AS matches, 0, 0, 0, 0, 'semi'
FROM `left pain` AS l SEMI JOIN `right pain` AS r ON l.id = r.id
UNION ALL
SELECT l.id, `🏴󠁧󠁢󠁷󠁬󠁳󠁿`, `é!`, `é!`, `👩‍💻`, 0 AS matches, 0, 0, 0, 0, 'anti'
FROM `left pain` AS l ANTI JOIN `right pain` AS r ON l.id = r.id
ORDER BY branch ASC, id DESC LIMIT 1_000 OFFSET 0"""


def test_maximal_torture_unicode_alias_spellings_are_exact() -> None:
    flag = "🏴󠁧󠁢󠁷󠁬󠁳󠁿"
    decomposed = "é!"
    precomposed = "é!"
    zwj_alias = "👩‍💻"

    assert [f"U+{ord(char):04X}" for char in flag] == [
        "U+1F3F4",
        "U+E0067",
        "U+E0062",
        "U+E0077",
        "U+E006C",
        "U+E0073",
        "U+E007F",
    ]
    assert [f"U+{ord(char):04X}" for char in zwj_alias] == ["U+1F469", "U+200D", "U+1F4BB"]
    assert [f"U+{ord(char):04X}" for char in decomposed] == ["U+0065", "U+0301", "U+0021"]
    assert [f"U+{ord(char):04X}" for char in precomposed] == ["U+00E9", "U+0021"]
    assert decomposed != precomposed
    for alias in (flag, decomposed, precomposed, zwj_alias):
        assert f"`{alias}`" in MAXIMAL_DERIVED_RELATION_TORTURE_QUERY


def test_lark_maximal_derived_relation_torture_is_structurally_and_canonically_equivalent() -> None:
    comparison = compare_parsers(parse_query, parse_lark_query, MAXIMAL_DERIVED_RELATION_TORTURE_QUERY)
    assert comparison.equivalent, comparison.describe()

    reference_model, reference_canonical = canonical_round_trip(parse_query, MAXIMAL_DERIVED_RELATION_TORTURE_QUERY)
    candidate_model, candidate_canonical = canonical_round_trip(
        parse_lark_query, MAXIMAL_DERIVED_RELATION_TORTURE_QUERY
    )
    assert candidate_model == reference_model
    assert candidate_canonical == reference_canonical
    assert format_query(parse_query(reference_canonical)) == reference_canonical
    assert compare_parsers(parse_query, parse_lark_query, reference_canonical).equivalent


DERIVED_RELATION_DIFFERENTIAL_CASES = (
    "SELECT id FROM (SELECT id FROM @a)",
    "SELECT combined.id FROM (SELECT id FROM @a UNION SELECT id FROM @b) AS combined",
    "SELECT outer_id FROM (SELECT inner_id AS outer_id FROM (SELECT id AS inner_id FROM @a))",
    "SELECT a.id FROM (SELECT id FROM @a) AS a JOIN (SELECT id FROM @b) AS b ON a.id = b.id",
    "WITH x AS (SELECT id FROM @a) SELECT id FROM (SELECT id FROM x)",
)


@pytest.mark.parametrize("source", DERIVED_RELATION_DIFFERENTIAL_CASES)
def test_lark_derived_relations_are_structurally_and_canonically_equivalent(source: str) -> None:
    comparison = compare_parsers(parse_query, parse_lark_query, source)
    assert comparison.equivalent, comparison.describe()

    reference_model, reference_canonical = canonical_round_trip(parse_query, source)
    candidate_model, candidate_canonical = canonical_round_trip(parse_lark_query, source)
    assert candidate_model == reference_model
    assert candidate_canonical == reference_canonical


@pytest.mark.parametrize(
    "source",
    (
        "SELECT id FROM ()",
        "SELECT id FROM (SELECT id FROM @a",
        "SELECT id FROM (SELECT id FROM @a) OF videos",
        "SELECT id FROM (WITH x AS (SELECT id FROM @a) SELECT id FROM x)",
        "SELECT a.id FROM @a AS a JOIN () AS b ON a.id = b.id",
    ),
)
def test_lark_derived_relation_malformed_boundaries_match_reference_acceptance(source: str) -> None:
    comparison = compare_parsers(parse_query, parse_lark_query, source)
    assert comparison.reference.kind == "rejected"
    assert comparison.candidate.kind == "rejected"
