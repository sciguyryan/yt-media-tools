"""Structural traversal helpers for the yt-sql abstract syntax tree.

This module owns knowledge of child relationships between query-model nodes. It
intentionally does not attach semantic meaning to those relationships: callers
remain responsible for deciding whether a child should be analysed, transformed
or treated as a scope boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

from .query_model import (
    AggregateFunction,
    Between,
    Binary,
    CaseWhen,
    CommonTableExpression,
    CollectionCount,
    CollectionFilter,
    CollectionProjection,
    CollectionPredicate,
    InList,
    JoinClause,
    IsNull,
    OrderTerm,
    Query,
    ScalarBinary,
    ScalarCase,
    ScalarComparison,
    ScalarFunction,
    ScalarIndex,
    ScalarIsNull,
    ScalarMember,
    ScalarUnary,
    SelectTerm,
    SetOperation,
    TextPredicate,
    Unary,
)

# Leaf nodes deliberately have no entries here. Keeping the structural node set
# explicit makes additions to the query model visible to traversal tests rather
# than relying on reflective dataclass walking that could accidentally traverse
# non-AST metadata in the future.


def ast_children(node: Any) -> tuple[Any, ...]:
    """Return direct AST children in stable source/semantic order."""
    if isinstance(node, (Unary, ScalarUnary)):
        return (node.operand,)
    if isinstance(node, (Binary, ScalarBinary, ScalarComparison)):
        return (node.left, node.right)
    if isinstance(node, Between):
        return (node.field, node.lower, node.upper)
    if isinstance(node, InList):
        return (node.field, *node.values)
    if isinstance(node, IsNull):
        return (node.field,)
    if isinstance(node, TextPredicate):
        return (node.field, node.value)
    if isinstance(node, CollectionPredicate):
        return (node.collection, node.predicate)
    if isinstance(node, (CollectionCount, CollectionFilter)):
        return (node.collection, node.predicate)
    if isinstance(node, CollectionProjection):
        return (node.collection, node.projection)
    if isinstance(node, ScalarIndex):
        return (node.collection, node.index)
    if isinstance(node, ScalarMember):
        return (node.value,)
    if isinstance(node, ScalarFunction):
        return node.args
    if isinstance(node, AggregateFunction):
        return (*node.args, *((node.filter_predicate,) if node.filter_predicate is not None else ()))
    if isinstance(node, CaseWhen):
        return (node.condition, node.result)
    if isinstance(node, ScalarCase):
        return (*node.whens, *((node.else_result,) if node.else_result is not None else ()))
    if isinstance(node, ScalarIsNull):
        return (node.expression,)
    if isinstance(node, (SelectTerm, OrderTerm)):
        return (node.expression,) if node.expression is not None else ()
    if isinstance(node, CommonTableExpression):
        return (node.query,)
    if isinstance(node, SetOperation):
        return (node.query,)
    if isinstance(node, JoinClause):
        return (node.predicate,)
    if isinstance(node, Query):
        children: list[Any] = []
        if node.predicate is not None:
            children.append(node.predicate)
        children.extend(node.order_by)
        children.extend(node.select)
        children.extend(node.group_by)
        if node.having is not None:
            children.append(node.having)
        children.extend(node.joins)
        children.extend(node.ctes)
        children.extend(node.set_operations)
        return tuple(children)
    return ()


def walk_ast(
    root: Any,
    *,
    descend: Callable[[Any], bool] | None = None,
) -> Iterator[Any]:
    """Yield ``root`` and descendants depth-first in stable pre-order.

    ``descend`` controls whether the children of an already yielded node are
    visited. This lets semantic callers retain boundaries such as aggregate or
    lexical-scope nodes without reimplementing structural child discovery.
    """
    stack = [root]
    while stack:
        node = stack.pop()
        if node is None:
            continue
        yield node
        if descend is not None and not descend(node):
            continue
        stack.extend(reversed(ast_children(node)))
