"""Experimental Lark parser boundary for yt-sql grammar revision 1.

This module is intentionally not wired into the production parser path. The
formal EBNF remains authoritative; this Lark grammar is an implementation
artefact used for the differential conformance work in issue #144.
"""

from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
from importlib.resources import files
import re

from lark import Lark, Token, Tree
from lark.exceptions import LarkError
from lark.lexer import PatternRE, PatternStr

from .query_formatter import format_scalar_expression
from .query_model import (
    AggregateFunction,
    Between,
    Binary,
    CaseWhen,
    CollectionCount,
    CollectionElementReference,
    CollectionFilter,
    CollectionPredicate,
    CollectionProjection,
    CommonTableExpression,
    Field,
    InList,
    IsNull,
    JoinClause,
    JoinKind,
    Literal,
    OrderTerm,
    Query,
    QueryLexicalError,
    QuerySyntaxError,
    RelationReference,
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
    TruthTest,
    Unary,
)


def _bound_keyword_terminal(terminal) -> None:
    """Keep case-insensitive grammar words from consuming identifier prefixes."""
    pattern = terminal.pattern
    if isinstance(pattern, PatternStr) and "i" in pattern.flags and pattern.value.isalpha():
        terminal.pattern = PatternRE(f"{pattern.to_regexp()}(?![\\w-])")
        terminal.priority = 2


@lru_cache(maxsize=1)
def _parser() -> Lark:
    """Build the experimental parser once per process."""
    grammar = files("yt_media_tools").joinpath("yt_sql_lark.lark").read_text(encoding="utf-8")
    return Lark(
        grammar,
        parser="lalr",
        lexer="contextual",
        propagate_positions=True,
        maybe_placeholders=False,
        edit_terminals=_bound_keyword_terminal,
    )


def recognise_lark_query(source: str) -> None:
    """Recognise *source* without exposing parser-library objects to callers."""
    _parse_lark_tree(source)
    return None


def parse_lark_query(source: str):
    """Parse grammar revision 1 into the existing yt-sql Query model.

    This remains deliberately independent of ``query_parser.parse_query`` and
    is not wired into the production parser path.
    """
    tree = _parse_lark_tree(source, validate_field_calls=False)
    return _LarkModelBuilder(source).query(tree)


def _parse_lark_tree(source: str, *, validate_field_calls: bool = True):
    """Parse and validate candidate-only lexical boundaries."""
    try:
        tree = _parser().parse(source)
    except LarkError as error:
        raise _translated_lark_error(source, error) from None
    _validate_lark_tree(source, tree, validate_field_calls=validate_field_calls)
    return tree


def _validate_lark_tree(source: str, tree, *, validate_field_calls: bool = True) -> None:
    """Validate reference boundaries shared grammar productions cannot express."""
    contains_order = re.search(r"\bORDER\s+(?!BY(?:\s|$))[^\s,()]+", source, re.IGNORECASE) is not None
    contains_call = validate_field_calls and "(" in source
    if not contains_order and not contains_call:
        return

    nodes = tuple(tree.iter_subtrees())
    if contains_order and not any(node.data == "order_by_clause" for node in nodes):
        for node in nodes:
            if node.data not in {"where_clause", "predicate_only_query"}:
                continue
            start = node.meta.start_pos
            segment = source[start : node.meta.end_pos]
            malformed_order = re.search(r"\bORDER\s+(?!BY(?:\s|$))(?P<term>[^\s,()]+)", segment, re.IGNORECASE)
            if malformed_order:
                term_start = start + malformed_order.start("term")
                term_end = start + malformed_order.end("term")
                raise QuerySyntaxError(
                    source,
                    "Expected BY after ORDER.",
                    term_start,
                    end_position=term_end,
                    expected=("BY",),
                )

    if not contains_call:
        return

    for node in nodes:
        if node.data != "predicate" or not node.children:
            continue
        left = node.children[0]
        if hasattr(left, "data") and left.data != "identifier":
            continue
        comparison = next((child for child in node.iter_subtrees() if child.data == "comparison_value"), None)
        if comparison is None:
            continue
        right_text = source[comparison.meta.start_pos : comparison.meta.end_pos]
        if "(" in right_text and not re.fullmatch(
            r"(?i)(?:-?INFINITY\(\)|(?:TODAY|NOW)\(\)(?:\s*[+-].*)?)",
            right_text,
        ):
            raise QuerySyntaxError(
                source,
                "A field comparison requires a literal value.",
                comparison.meta.start_pos + right_text.index("("),
            )


def _translated_lark_error(source: str, error: LarkError) -> QuerySyntaxError:
    """Translate one implementation-native failure into yt-sql vocabulary."""
    native_position = getattr(error, "pos_in_stream", None)
    native_token = getattr(error, "token", None)
    at_end = getattr(native_token, "type", None) in {"$END", "<EOF>"}
    if at_end or not isinstance(native_position, int) or native_position < 0:
        position = len(source)
    else:
        position = native_position
    stripped = source.rstrip()
    expected = set(getattr(error, "expected", ()) or ())

    if expected == {"BY"} and native_token is not None:
        return QuerySyntaxError(
            source,
            "Expected BY after ORDER.",
            position,
            end_position=getattr(native_token, "end_pos", position),
            expected=("BY",),
        )

    if re.match(r"(?i)^SELECT(?:COALESCE|COUNT)\b", source):
        return QuerySyntaxError(source, "A function name cannot include SELECT.", 0)

    missing_distinct_from = re.search(
        r"(?i)\bIS\s+(?:NOT\s+)?DISTINCT\s+(?P<term>FROM[\w-]+)",
        source,
    )
    if missing_distinct_from and position == missing_distinct_from.start("term"):
        return QuerySyntaxError(
            source,
            "Expected FROM after IS DISTINCT.",
            position,
            end_position=missing_distinct_from.end("term"),
            expected=("FROM",),
        )

    if position < len(source) and source[position] in {"'", '"'}:
        return QueryLexicalError(
            source,
            "Unterminated string literal.",
            position,
            end_position=len(source),
            reason="unterminated-string",
        )

    if "[]" in source and position == source.index("[]") + 1:
        return QuerySyntaxError(
            source,
            "Collection indexing requires an index expression.",
            position - 1,
            reason="missing-index-expression",
        )

    if re.match(r"(?i)(?:WHERE|UNION)[\w-]", source[position:]):
        return QuerySyntaxError(
            source,
            "A separator is required after the clause keyword.",
            position,
            reason="missing-clause-separator",
        )

    if (
        position < len(source)
        and source[position] == ","
        and re.search(r"\bOF\b[^,]*,\s*$", source[:position], re.IGNORECASE)
    ):
        return QuerySyntaxError(source, "A facet name is required.", position, reason="missing-facet")

    if re.search(r"\bAS\s*\(\s*\)$", source[: position + 1], re.IGNORECASE):
        return QuerySyntaxError(source, "Query body cannot be empty.", position, reason="empty-query")

    if position == len(source):
        if re.search(r"\b(?:FROM|JOIN)\s*$", stripped, re.IGNORECASE):
            return QuerySyntaxError(source, "A relation source is required.", position, reason="missing-source")
        if re.search(r"\bOF\s*$", stripped, re.IGNORECASE):
            return QuerySyntaxError(source, "A facet name is required after OF.", position, reason="missing-facet")
        union = re.search(r"\bUNION\s*$", stripped, re.IGNORECASE)
        if union:
            return QuerySyntaxError(
                source,
                "UNION requires a query on both sides.",
                union.start(),
                reason="incomplete-union",
            )
        if re.search(r"\bJOIN\b", stripped, re.IGNORECASE) and not re.search(r"\bON\b[^)]*$", stripped, re.IGNORECASE):
            return QuerySyntaxError(
                source,
                "JOIN requires an ON predicate.",
                position,
                expected=("ON",),
                reason="missing-join-on",
            )
        if "RPAR" in expected:
            return QuerySyntaxError(
                source,
                "A closing ')' delimiter is required.",
                position,
                expected=(")",),
                reason="invalid",
            )

    word = re.match(r"[A-Za-z]+", source[position:])
    if word and word.group(0).upper() in {"WHERE", "GROUP", "HAVING", "ORDER", "LIMIT", "OFFSET"}:
        return QuerySyntaxError(
            source,
            "A clause is repeated or out of canonical order.",
            position,
            reason="clause-order",
        )

    if position < len(source) and source[position] == "@" and re.match(r"(?is)^\s*SELECT\s+FROM\s+", source):
        return QuerySyntaxError(
            source,
            "A clause separator is required.",
            position,
            reason="missing-clause-separator",
        )

    return QuerySyntaxError(source, "The query is not valid yt-sql syntax.", position)


class _LarkModelBuilder:
    """Construct yt-sql model objects directly from Lark's parse tree."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.Tree = Tree
        self.collection_bindings: list[str] = []

    def _slice(self, node) -> str:
        return self.source[self._node_start(node) : self._node_end(node)]

    def _trees(self, node, name: str | None = None):
        return [
            child
            for child in getattr(node, "children", ())
            if isinstance(child, self.Tree) and (name is None or child.data == name)
        ]

    def _first(self, node, name: str):
        for child in getattr(node, "children", ()):
            if isinstance(child, self.Tree) and child.data == name:
                return child
        return None

    def _token_text(self, node) -> str:
        if hasattr(node, "value"):
            return str(node)
        return self._slice(node)

    def query(self, root):
        """Build a complete prototype query, including CTE and UNION composition."""
        expression = self._first(root, "query_expression")
        if expression is None:
            raise QuerySyntaxError(self.source, "Unsupported experimental query shape.", 0)
        query = self.query_expression(expression)
        with_clause = self._first(root, "with_clause")
        if with_clause:
            ctes = []
            for cte in self._trees(with_clause, "cte"):
                name_node = cte.children[0]
                nested = self._first(cte, "query_expression")
                ctes.append(
                    CommonTableExpression(
                        self._token_text(name_node).strip("`").replace("``", "`"),
                        self.query_expression(nested),
                        self._node_start(name_node),
                    )
                )
            query = replace(query, ctes=tuple(ctes))
        return replace(query, source=self.source)

    def query_expression(self, expression):
        primaries = [
            child
            for child in expression.children
            if isinstance(child, self.Tree)
            and child.data in {"select_query", "predicate_only_query", "query_expression"}
        ]
        if not primaries:
            raise QuerySyntaxError(self.source, "Unsupported experimental query shape.", expression.meta.start_pos)

        def build_primary(primary):
            if primary.data == "predicate_only_query":
                predicate_tree = next(c for c in primary.children if isinstance(c, self.Tree))
                return Query(predicate=self.boolean(predicate_tree), source=self.source)
            if primary.data == "query_expression":
                return Query(source=self.source, left_query=self.query_expression(primary))
            return self.select_query(primary)

        query = build_primary(primaries[0])
        union_nodes = self._trees(expression, "union_operator")
        operations = []
        for union, primary in zip(union_nodes, primaries[1:]):
            operations.append(
                SetOperation(
                    build_primary(primary),
                    "ALL" in self._slice(union).upper(),
                    union.meta.start_pos,
                    False,
                    primary.data == "query_expression",
                )
            )
        order = self._first(expression, "order_by_clause")
        limit = self._first(expression, "limit_clause")
        offset = self._first(expression, "offset_clause")
        return replace(
            query,
            set_operations=tuple(query.set_operations) + tuple(operations),
            order_by=tuple(self.order_term(term) for term in self._trees(order, "order_term")) if order else (),
            limit=int(str(limit.children[0]).replace("_", "")) if limit else None,
            offset=int(str(offset.children[0]).replace("_", "")) if offset else 0,
            source=self.source,
        )

    def select_query(self, node):
        select_head = self._first(node, "select_head") or node
        select_clause = self._first(select_head, "select_clause")
        from_clause = self._first(select_head, "from_clause")
        where_clause = self._first(node, "where_clause")
        group_clause = self._first(node, "group_by_clause")
        having_clause = self._first(node, "having_clause")
        select = (
            tuple(self.select_term(term) for term in self._trees(select_clause, "select_term")) if select_clause else ()
        )
        distinct = bool(
            select_clause and re.match(r"SELECT\s+DISTINCT\b", self._slice(select_clause).lstrip(), re.IGNORECASE)
        )
        from_source = from_facet = from_alias = None
        joins = ()
        additional_facets = ()
        if from_clause:
            relation = self._first(from_clause, "relation_reference")
            if relation:
                from_source, facets, from_alias = self.relation_reference(relation)
                from_facet = facets[0][0] if facets else None
                additional_facets = tuple(facets[1:])
            joins = tuple(self.join_clause(join) for join in self._trees(from_clause, "join_clause"))
        predicate = None
        if where_clause:
            predicate = self.boolean(next(c for c in where_clause.children if isinstance(c, self.Tree)))
        group_by = tuple(self.scalar(child) for child in (group_clause.children if group_clause else ()))
        having = self.having(self._trees(having_clause)[0]) if having_clause else None
        query = Query(
            predicate=predicate,
            source=self.source,
            select=select,
            from_source=from_source,
            distinct=distinct,
            from_facet=from_facet,
            from_alias=from_alias,
            group_by=group_by,
            having=having,
            joins=joins,
        )
        if additional_facets:
            operations = tuple(
                SetOperation(replace(query, from_facet=facet, set_operations=()), True, position, True)
                for facet, position in additional_facets
            )
            query = replace(query, set_operations=operations)
        return query

    def relation_reference(self, node):
        trees = self._trees(node)
        source_node = trees[0] if trees and trees[0].data not in {"facet_reference"} else node.children[0]
        source = self._token_text(source_node)
        if source.startswith(("'", '"')):
            source = source[1:-1].replace(source[0] * 2, source[0])
        elif source.startswith("`"):
            source = source[1:-1].replace("``", "`")
        facets = []
        for facet_node in self._trees(node, "facet_reference"):
            child = facet_node.children[0] if facet_node.children else facet_node
            facets.append((self._token_text(child).strip("`").replace("``", "`").casefold(), self._node_start(child)))
        alias = None
        text = self._slice(node)
        match = re.search(r"\bAS\s+(`(?:``|[^`])+`|[^\s,]+)\s*$", text, re.IGNORECASE)
        if match:
            alias = match.group(1).replace("``", "`").strip("`")
        return source, facets, alias

    def join_clause(self, node):
        kind_text = self._slice(self._first(node, "join_kind")).upper()
        if kind_text.startswith("LEFT"):
            kind = JoinKind.LEFT
        elif kind_text.startswith("SEMI"):
            kind = JoinKind.SEMI
        elif kind_text.startswith("ANTI"):
            kind = JoinKind.ANTI
        else:
            kind = JoinKind.INNER
        relation_node = self._first(node, "relation_reference_single")
        source, facets, alias = self.relation_reference(relation_node)
        facet = facets[0][0] if facets else None
        relation = RelationReference(source, facet, alias, relation_node.meta.start_pos)
        predicate_node = next(
            child
            for child in node.children
            if isinstance(child, self.Tree) and child.data not in {"join_kind", "relation_reference_single"}
        )
        if predicate_node.data == "boolean_not" and not self._starts_with_keyword(predicate_node, "NOT"):
            predicate_node = self._trees(predicate_node)[0]
        predicate = self.boolean(predicate_node)

        if isinstance(predicate, Binary) and predicate.operator in {"=", "!=", "<>", "<", "<=", ">", ">="}:
            right = predicate.right
            if isinstance(right, Literal) and not right.quoted:
                right = (
                    self.literal_text(right.raw, right.position)
                    if right.raw[:1].isdigit()
                    else Field(right.raw, right.position)
                )
            predicate = ScalarComparison(predicate.operator, predicate.left, right)
        elif isinstance(predicate, IsNull):
            predicate = ScalarIsNull(predicate.field, predicate.negated)
        return JoinClause(kind, relation, predicate, node.meta.start_pos)

    def select_term(self, node):
        wildcard = self._first(node, "projection_wildcard")
        if wildcard is not None:
            return SelectTerm("*", position=self._node_start(wildcard))
        expr_node = next((c for c in node.children if isinstance(c, self.Tree) or hasattr(c, "value")), None)
        expr = self.scalar(expr_node)
        text = self._slice(node)
        match = re.search(r"\s+AS\s+(`(?:``|[^`])+`|[^\s]+)\s*$", text, re.IGNORECASE)
        alias = match.group(1).replace("``", "`").strip("`") if match else None
        return SelectTerm(format_scalar_expression(expr), alias, self._node_start(expr_node), expression=expr)

    def order_term(self, node):
        expr_node = next(c for c in node.children if isinstance(c, self.Tree) or hasattr(c, "value"))
        expr = self.scalar(expr_node)
        return OrderTerm(
            format_scalar_expression(expr),
            self._keyword_text(node).endswith(" DESC"),
            self._node_start(expr_node),
            expression=expr,
        )

    def scalar(self, node):
        if not isinstance(node, self.Tree):
            token_type = getattr(node, "type", "")
            if token_type in {"NUMBER", "UNIT_LITERAL", "STRING", "DATE", "DATETIME", "TIME", "TEMPORAL", "INFINITY"}:
                return self.literal_token(node)
            name = str(node).strip("`").replace("``", "`")
            if name.upper() in {"TRUE", "FALSE", "NULL"}:
                return self.literal_text(name, getattr(node, "start_pos", 0))
            return self.bound_collection_reference(name, getattr(node, "start_pos", 0)) or Field(
                name, getattr(node, "start_pos", 0)
            )
        data = node.data
        if data in {"identifier", "scalar_atom"} and len(node.children) == 1:
            return self.scalar(node.children[0])
        if data in {"scalar_literal", "temporal_literal", "literal_sequence"}:
            return self.literal_text(self._slice(node), self._node_start(node))
        if data == "comparison_value":
            return self.scalar(node.children[0])
        if data in {"additive_expression", "multiplicative_expression"}:
            parts = [c for c in node.children if isinstance(c, self.Tree) or hasattr(c, "value")]
            value = self.scalar(parts[0])
            for right_node in parts[1:]:
                right = self.scalar(right_node)
                gap = self.source[self._end(value) : self._start(right)]
                operator = next(op for op in ("+", "-", "*", "/", "%") if op in gap)
                pos = self.source.index(operator, self._end(value), self._start(right))
                value = ScalarBinary(operator, value, right, pos)
            return value
        if data == "unary_expression":
            operand_node = next(
                c
                for c in node.children
                if (isinstance(c, self.Tree) or hasattr(c, "value")) and getattr(c, "type", "") != "UNARY_OPERATOR"
            )
            operand = self.scalar(operand_node)
            operator = next((str(c) for c in node.children if getattr(c, "type", "") == "UNARY_OPERATOR"), "")
            return ScalarUnary(operator, operand, self._node_start(node)) if operator else operand
        if data == "postfix_expression":
            base = self.scalar(node.children[0])
            value = base
            for suffix in node.children[1:]:
                if suffix.data == "index_suffix":
                    index = self.scalar(suffix.children[0])
                    value = ScalarIndex(value, index, suffix.meta.start_pos)
                elif suffix.data == "member_suffix":
                    member = self._token_text(suffix.children[0])
                    value = ScalarMember(value, member, suffix.meta.start_pos)
            return value
        if data in {"scalar_function", "aggregate_function", "collection_transform"}:
            return self.function(node)
        if data == "case_expression":
            return self.case_expression(node)
        if data in {"NUMBER", "UNIT_LITERAL", "STRING", "DATE", "DATETIME", "TIME", "TEMPORAL", "INFINITY"}:
            return self.literal_token(node)
        if not node.children:
            text = self._slice(node)
            if text[:1].isdigit() or text[:1] in "'\"":
                return self.literal_text(text, node.meta.start_pos)
            name = text.strip("`").replace("``", "`")
            return self.bound_collection_reference(name, self._node_start(node)) or Field(name, self._node_start(node))
        if len(node.children) == 1 and not isinstance(node.children[0], self.Tree):
            token = node.children[0]
            if getattr(token, "type", "") in {
                "NUMBER",
                "UNIT_LITERAL",
                "STRING",
                "DATE",
                "DATETIME",
                "TIME",
                "TEMPORAL",
                "INFINITY",
            }:
                return self.literal_token(token)
            name = str(token).strip("`").replace("``", "`")
            position = getattr(token, "start_pos", self._node_start(node))
            return self.bound_collection_reference(name, position) or Field(name, position)
        raise QuerySyntaxError(
            self.source, f"Experimental model construction does not yet support {data}.", node.meta.start_pos
        )

    def function(self, node):
        text = self._slice(node)
        name = text[: text.index("(")].strip().upper()
        if node.data == "collection_transform":
            values = [child for child in node.children if isinstance(child, self.Tree) or hasattr(child, "value")]
            collection = self.scalar(values[0])
            binding_node = values[1]
            binding = self._token_text(binding_node.children[0] if self._trees(binding_node) else binding_node)
            body = values[-1]
            self.collection_bindings.append(binding)
            try:
                result = self.boolean(body) if name == "FILTER" else self.scalar(body)
            finally:
                self.collection_bindings.pop()
            if name == "FILTER":
                return CollectionFilter(collection, binding, result, self._node_start(node))
            return CollectionProjection(collection, binding, result, self._node_start(node))
        if node.data == "aggregate_function":
            count_star = name == "COUNT" and "*" in text[text.index("(") + 1 : text.rfind(")")]
            values = [
                child
                for child in node.children
                if not (isinstance(child, self.Tree) and child.data in {"aggregate_name", "aggregate_filter"})
            ]
            if name == "COUNT" and " AS " in " ".join(text.upper().split()):
                collection = self.scalar(values[0])
                binding_node = values[1]
                binding = self._token_text(binding_node.children[0] if self._trees(binding_node) else binding_node)
                self.collection_bindings.append(binding)
                try:
                    predicate = self.boolean(values[-1])
                finally:
                    self.collection_bindings.pop()
                return CollectionCount(collection, binding, predicate, self._node_start(node))
            args = tuple(self.scalar(child) for child in values)
            filter_node = self._first(node, "aggregate_filter")
            filter_predicate = self.boolean(self._trees(filter_node)[0]) if filter_node else None
            return AggregateFunction(name, args, count_star, filter_predicate, self._node_start(node))
        args = tuple(
            self.scalar(child)
            for child in node.children
            if not (isinstance(child, self.Tree) and child.data in {"unary_scalar_function", "multi_scalar_function"})
        )
        return ScalarFunction(name, args, self._node_start(node))

    def case_expression(self, node):
        whens = []
        else_result = None
        for child in node.children:
            if not isinstance(child, self.Tree) and not hasattr(child, "value"):
                continue
            if isinstance(child, self.Tree) and child.data == "case_when":
                parts = [part for part in child.children if isinstance(part, self.Tree) or hasattr(part, "value")]
                whens.append(CaseWhen(self.boolean(parts[0]), self.scalar(parts[1]), child.meta.start_pos))
            else:
                else_result = self.scalar(child)
        return ScalarCase(tuple(whens), else_result, self._node_start(node))

    def having(self, node):
        if node.data in {"having_expression", "having_and"}:
            children = self._trees(node)
            value = self.having(children[0])
            operator = "OR" if node.data == "having_expression" else "AND"
            for child in children[1:]:
                value = Binary(operator, value, self.having(child))
            return value
        if node.data == "having_not":
            child = self._trees(node)[0]
            value = self.having(child)
            if self._starts_with_keyword(node, "NOT"):
                return Unary("NOT", value)
            return value
        if node.data == "having_predicate":
            values = [child for child in node.children if isinstance(child, self.Tree) or hasattr(child, "value")]
            left = self.scalar(values[0])
            text = self._keyword_text(node)
            if "IS NOT NULL" in text:
                return ScalarIsNull(left, True)
            if "IS NULL" in text:
                return ScalarIsNull(left, False)
            right = self.scalar(values[-1])
            match = re.search(r"<=|>=|!=|<>|=|<|>", self._slice(node))
            if not match:
                raise QuerySyntaxError(self.source, "Unsupported experimental HAVING predicate.", node.meta.start_pos)
            return ScalarComparison(match.group(0), left, right)
        return self.boolean(node)

    def boolean(self, node):
        if node.data == "boolean_not":
            child = next(c for c in node.children if isinstance(c, self.Tree))
            value = self.boolean(child)
            if self._starts_with_keyword(node, "NOT"):
                return Unary("NOT", value)
            return value
        if node.data in {"boolean_expression", "boolean_and"}:
            children = self._trees(node)
            value = self.boolean(children[0])
            operator = "OR" if node.data == "boolean_expression" else "AND"
            for child in children[1:]:
                value = Binary(operator, value, self.boolean(child))
            return value
        if node.data == "collection_predicate":
            values = [child for child in node.children if isinstance(child, self.Tree) or hasattr(child, "value")]
            collection = self.scalar(values[0])
            binding_node = values[1]
            binding = self._token_text(binding_node.children[0] if self._trees(binding_node) else binding_node)
            self.collection_bindings.append(binding)
            try:
                predicate = self.boolean(values[-1])
            finally:
                self.collection_bindings.pop()
            quantifier = self._slice(node).lstrip().split("(", 1)[0].upper()
            return CollectionPredicate(quantifier, collection, binding, predicate, self._node_start(node))
        if node.data == "predicate":
            left = self.scalar(node.children[0])
            suffix = next(
                (c for c in node.children[1:] if isinstance(c, (self.Tree, Token))),
                None,
            )
            text = self.source[self._end(left) : self._node_end(node)].strip()
            if suffix is None or not text:
                return Binary("=", left, Literal(True, "TRUE", self._start(left)))
            upper = " ".join(text.upper().split())
            if upper.startswith(("IS", "NOT IS")):
                negated = "IS NOT" in upper or upper.startswith("NOT IS")
                if "DISTINCT FROM" in upper:
                    operator = "IS NOT DISTINCT FROM" if negated else "IS DISTINCT FROM"
                    right_node = (
                        next(
                            child
                            for child in reversed(suffix.children)
                            if isinstance(child, self.Tree) or hasattr(child, "value")
                        )
                        if isinstance(suffix, self.Tree)
                        else suffix
                    )
                    return ScalarComparison(operator, left, self.scalar(right_node))
                if upper.endswith("NULL"):
                    return IsNull(left, negated) if isinstance(left, Field) else ScalarIsNull(left, negated)
                for truth in ("TRUE", "FALSE", "UNKNOWN"):
                    if upper.endswith(truth):
                        operand = (
                            Binary("=", left, Literal(True, "TRUE", self._start(left)))
                            if isinstance(left, Field)
                            else left
                        )
                        return TruthTest(operand, truth, negated)
            if "IS NOT NULL" in upper:
                return IsNull(left, True)
            if "IS NULL" in upper:
                return IsNull(left, False)
            values = [c for c in suffix.children if isinstance(c, self.Tree) or hasattr(c, "value")]
            if "BETWEEN" in upper:
                return Between(
                    left, self.predicate_literal(values[-2]), self.predicate_literal(values[-1]), "NOT BETWEEN" in upper
                )
            if re.match(r"^(?:NOT\s+)?IN\s*\(", upper):
                return InList(left, tuple(self.predicate_literal(value) for value in values), "NOT IN" in upper)
            for spelling, canonical in (
                ("CONTAINS", "CONTAINS"),
                ("CONTAIN", "CONTAINS"),
                ("MATCHES", "MATCHES"),
                ("MATCH", "MATCHES"),
                ("ILIKE", "ILIKE"),
                ("LIKE", "LIKE"),
            ):
                if spelling in upper:
                    return TextPredicate(
                        canonical, left, self.predicate_literal(values[-1]), "NOT" in upper or upper.startswith("DOES")
                    )
            right_node = values[-1]
            if isinstance(left, Field) and getattr(right_node, "data", None) == "comparison_value":
                right_text = self._slice(right_node)
                if "(" in right_text and not re.fullmatch(
                    r"(?i)(?:-?INFINITY\(\)|(?:TODAY|NOW)\(\)(?:\s*[+-].*)?)",
                    right_text,
                ):
                    raise QuerySyntaxError(
                        self.source,
                        "A field comparison requires a literal value.",
                        self._node_start(right_node) + right_text.index("("),
                    )
            right = self.predicate_literal(right_node)
            if upper.endswith("-INFINITY()"):
                position = self.source.rfind("-INFINITY()", self._start(left), self._node_end(node))
                right = Literal("-INFINITY()", "-INFINITY()", position)
            natural = (
                (("AT LEAST",), ">="),
                (("AT MOST",), "<="),
                (("GREATER THAN", "MORE THAN", "OVER", "ABOVE"), ">"),
                (("LESS THAN", "UNDER", "BELOW"), "<"),
                (("EQUAL TO", "EQUALS"), "="),
            )
            operator = next((value for spellings, value in natural if any(item in upper for item in spellings)), None)
            match = re.search(r"<=|>=|!=|<>|=|<|>", text)
            if operator is None and match:
                operator = "!=" if match.group(0) == "<>" else match.group(0)
            if operator is None:
                raise QuerySyntaxError(self.source, "Unsupported experimental predicate.", self._node_start(suffix))
            if not isinstance(left, Field):
                return ScalarComparison(operator, left, self.scalar(right_node))
            return Binary(operator, left, right)
        if node.data == "boolean_primary":
            value = self.boolean(next(c for c in node.children if isinstance(c, self.Tree)))
            upper = self._keyword_text(node)
            if " IS " in upper:
                negated = " IS NOT " in upper
                truth = next(item for item in ("TRUE", "FALSE", "UNKNOWN") if upper.rstrip().endswith(item))
                return TruthTest(value, truth, negated)
            return value
        raise QuerySyntaxError(
            self.source, f"Experimental Boolean construction does not yet support {node.data}.", node.meta.start_pos
        )

    def predicate_literal(self, node):
        """Build legacy predicate literals, whose unquoted values remain textual."""
        if isinstance(node, self.Tree) and node.data == "comparison_value":
            value = self.literal_text(self._slice(node), self._node_start(node))
        else:
            value = self.scalar(node)
        if isinstance(value, Field):
            return Literal(value.name, value.name, value.position, False)
        if isinstance(value, Literal) and not value.quoted:
            if value.value is None or isinstance(value.value, bool):
                return value
            raw = value.raw
            unit = re.fullmatch(r"(\d+(?:\.\d+)?)([^\W\d_].*)", raw, re.UNICODE)
            if unit and not raw.lower().startswith(("0x", "0o", "0b")) and not re.fullmatch(r"[kKmMbB]", unit.group(2)):
                raw = f"{unit.group(1)} {unit.group(2)}"
            return Literal(raw, raw, value.position, False)
        return value

    def literal_token(self, token):
        return self.literal_text(str(token), getattr(token, "start_pos", 0))

    def literal_text(self, text: str, position: int):
        raw = text
        if text.startswith(("'", '"')):
            quote = text[0]
            inner = text[1:-1].replace(quote * 2, quote)
            return Literal(inner, raw, position, True)
        if text.upper() == "TRUE":
            return Literal(True, raw, position)
        if text.upper() == "FALSE":
            return Literal(False, raw, position)
        if text.upper() == "NULL":
            return Literal(None, raw, position)
        compact = text.replace("_", "")
        if re.fullmatch(r"0[xX][0-9A-Fa-f]+", compact):
            return Literal(int(compact, 16), raw, position)
        if re.fullmatch(r"0[bB][01]+", compact):
            return Literal(int(compact, 2), raw, position)
        if re.fullmatch(r"0[oO][0-7]+", compact):
            return Literal(int(compact, 8), raw, position)
        if re.fullmatch(r"\d+(?:\.\d+)?", compact):
            value = float(compact) if "." in compact else int(compact)
            return Literal(value, raw, position)
        return Literal(text, raw, position)

    def bound_collection_reference(self, name: str, position: int):
        """Build one scoped collection reference when ``name`` begins with a binding."""
        parts = name.split(".")
        for distance, binding in enumerate(reversed(self.collection_bindings)):
            if parts[0] != binding:
                continue
            value = CollectionElementReference(binding, distance, position)
            offset = len(binding)
            for member in parts[1:]:
                value = ScalarMember(value, member, position + offset)
                offset += len(member) + 1
            return value
        return None

    def _keyword_text(self, node) -> str:
        """Normalise insignificant spacing for keyword-shape inspection."""
        return " ".join(self._slice(node).upper().split())

    def _starts_with_keyword(self, node, keyword: str) -> bool:
        text = self._slice(node).lstrip()
        return re.match(rf"{keyword}(?=$|[^\w-])", text, re.IGNORECASE) is not None

    @staticmethod
    def _node_start(node) -> int:
        return node.start_pos if isinstance(node, Token) else node.meta.start_pos

    @staticmethod
    def _node_end(node) -> int:
        return node.end_pos if isinstance(node, Token) else node.meta.end_pos

    @staticmethod
    def _start(value) -> int:
        if hasattr(value, "position"):
            return value.position
        if hasattr(value, "left"):
            return _LarkModelBuilder._start(value.left)
        return 0

    @staticmethod
    def _end(value) -> int:
        if hasattr(value, "raw") and hasattr(value, "position"):
            return value.position + len(value.raw)
        if hasattr(value, "name") and hasattr(value, "position"):
            return value.position + len(value.name)
        if hasattr(value, "binding") and hasattr(value, "position"):
            return value.position + len(value.binding)
        if hasattr(value, "right"):
            return _LarkModelBuilder._end(value.right)
        if hasattr(value, "member") and hasattr(value, "position"):
            return value.position + 1 + len(value.member)
        return _LarkModelBuilder._start(value)
