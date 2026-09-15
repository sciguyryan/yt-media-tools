"""Tests for the shared yt-sql AST traversal infrastructure."""

from yt_media_tools.query_model import (
    AggregateFunction,
    Binary,
    CaseWhen,
    CollectionPredicate,
    Field,
    Literal,
    Query,
    ScalarCase,
    ScalarFunction,
    SelectTerm,
)
from yt_media_tools.query_traversal import ast_children, walk_ast


def test_ast_children_preserves_structural_order() -> None:
    left = Field("title")
    right = Literal("x", "'x'", quoted=True)
    predicate = Binary("AND", left, right)

    assert ast_children(predicate) == (left, right)


def test_walk_ast_visits_query_expression_tree_in_preorder() -> None:
    argument = Field("title")
    function = ScalarFunction("LOWER", (argument,))
    query = Query(select=(SelectTerm("", expression=function),))

    assert list(walk_ast(query)) == [query, query.select[0], function, argument]


def test_walk_ast_can_preserve_semantic_boundaries() -> None:
    argument = Field("duration")
    aggregate = AggregateFunction("SUM", (argument,))
    outer = ScalarFunction("COALESCE", (aggregate, Literal(0, "0")))

    visited = list(walk_ast(outer, descend=lambda node: not isinstance(node, AggregateFunction)))

    assert aggregate in visited
    assert argument not in visited


def test_ast_children_covers_scoped_and_case_children() -> None:
    collection = Field("tags")
    scoped_predicate = Binary("=", Field("tag"), Literal("x", "'x'", quoted=True))
    collection_predicate = CollectionPredicate("ANY", collection, "tag", scoped_predicate)
    branch = CaseWhen(collection_predicate, Literal(1, "1"))
    expression = ScalarCase((branch,), Literal(0, "0"))

    assert ast_children(collection_predicate) == (collection, scoped_predicate)
    assert ast_children(expression) == (branch, expression.else_result)
