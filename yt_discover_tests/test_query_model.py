"""Regression tests for the extracted yt-sql query model boundary."""

from __future__ import annotations

from dataclasses import replace

from yt_media_tools import query as query_module
from yt_media_tools.query_model import (
    AggregateFunction,
    Binary,
    CaseWhen,
    Field,
    Literal,
    Query,
    ScalarCase,
    ScalarFunction,
    SelectTerm,
    SetOperation,
)
from yt_media_tools.query_semantics import same_field, semantic_key


def test_query_module_preserves_established_model_exports() -> None:
    assert query_module.Query is Query
    assert query_module.Field is Field
    assert query_module.Literal is Literal
    assert query_module.AggregateFunction is AggregateFunction
    assert query_module.ScalarCase is ScalarCase


def test_dataclass_equality_remains_exact_about_source_positions() -> None:
    left = Field("view_count", position=4, kind="count")
    right = Field("view_count", position=99, kind="count")
    assert left != right


def test_semantic_field_identity_ignores_source_positions() -> None:
    left = Field("View_Count", position=4, kind="count")
    right = Field("view_count", position=99, kind="count")
    assert same_field(left, right)
    assert semantic_key(left) == semantic_key(right)


def test_semantic_identity_covers_scalar_case_and_aggregate_nodes() -> None:
    field_a = Field("view_count", position=2, kind="count")
    field_b = replace(field_a, position=202)
    literal_a = Literal(10, "10", position=15)
    literal_b = replace(literal_a, position=215)
    condition_a = Binary(">=", field_a, literal_a)
    condition_b = Binary(">=", field_b, literal_b)
    case_a = ScalarCase(
        whens=(
            CaseWhen(
                condition_a,
                ScalarFunction(
                    "LOWER",
                    (Literal("A", "'A'", position=25, quoted=True),),
                    position=20,
                    kind="string",
                ),
                position=18,
            ),
        ),
        else_result=Literal("b", "'b'", position=30, quoted=True),
        position=12,
        kind="string",
    )
    case_b = ScalarCase(
        whens=(
            CaseWhen(
                condition_b,
                ScalarFunction(
                    "LOWER",
                    (Literal("A", "'A'", position=225, quoted=True),),
                    position=220,
                    kind="string",
                ),
                position=218,
            ),
        ),
        else_result=Literal("b", "'b'", position=230, quoted=True),
        position=212,
        kind="string",
    )
    aggregate_a = AggregateFunction("MAX", (case_a,), position=5, kind="string")
    aggregate_b = AggregateFunction("MAX", (case_b,), position=205, kind="string")
    assert aggregate_a != aggregate_b
    assert semantic_key(aggregate_a) == semantic_key(aggregate_b)


def test_semantic_identity_covers_composed_queries_without_source_text_or_positions() -> None:
    branch_a = Query(
        select=(SelectTerm("id", position=7, kind="string", expression=Field("id", position=7, kind="string")),),
        from_source="@alpha",
        source="SELECT id FROM @alpha",
    )
    branch_b = Query(
        select=(SelectTerm("id", position=77, kind="string", expression=Field("id", position=77, kind="string")),),
        from_source="@alpha",
        source="  SELECT id\nFROM @alpha  ",
    )
    query_a = Query(
        select=branch_a.select,
        from_source="@alpha",
        set_operations=(SetOperation(branch_a, all=True, position=30),),
        source="SELECT id FROM @alpha UNION ALL SELECT id FROM @alpha",
    )
    query_b = Query(
        select=branch_b.select,
        from_source="@alpha",
        set_operations=(SetOperation(branch_b, all=True, position=300),),
        source="SELECT id FROM @alpha\nUNION ALL\nSELECT id FROM @alpha",
    )
    assert query_a != query_b
    assert semantic_key(query_a) == semantic_key(query_b)
