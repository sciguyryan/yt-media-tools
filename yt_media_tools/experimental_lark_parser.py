"""Experimental Lark parser boundary for yt-sql grammar revision 1.

This module is intentionally not wired into the production parser path. The
formal EBNF remains authoritative; this Lark grammar is an implementation
artefact used to investigate issue #143.
"""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files

from lark import Lark
from lark.exceptions import LarkError

from .query_model import QuerySyntaxError


@lru_cache(maxsize=1)
def _parser() -> Lark:
    """Build the experimental parser once per process."""
    grammar = files("yt_media_tools").joinpath("yt_sql_lark.lark").read_text(encoding="utf-8")
    return Lark(grammar, parser="earley", propagate_positions=True, maybe_placeholders=False)


def recognise_lark_query(source: str) -> None:
    """Recognise *source* without exposing parser-library objects to callers."""
    try:
        _parser().parse(source)
        return None
    except LarkError as error:
        position = getattr(error, "pos_in_stream", None)
        if not isinstance(position, int):
            position = len(source)
        raise QuerySyntaxError(source, "Experimental declarative parser rejected the query.", position) from error


def parse_lark_query(source: str):
    """Parse a supported prototype slice into the existing yt-sql Query model.

    This is deliberately independent of ``query_parser.parse_query``. The
    prototype currently covers the core SELECT/FROM/WHERE, scalar-expression,
    ordering and pagination model surface; later #143 increments extend the
    same boundary across composition and aggregate families.
    """
    try:
        tree = _parser().parse(source)
    except LarkError as error:
        position = getattr(error, "pos_in_stream", None)
        if not isinstance(position, int):
            position = len(source)
        raise QuerySyntaxError(source, "Experimental declarative parser rejected the query.", position) from error
    return _LarkModelBuilder(source).query(tree)


class _LarkModelBuilder:
    """Construct yt-sql model objects directly from Lark's parse tree."""

    def __init__(self, source: str) -> None:
        from lark import Tree

        self.source = source
        self.Tree = Tree

    def _slice(self, node) -> str:
        return self.source[node.meta.start_pos : node.meta.end_pos]

    def _trees(self, node, name: str | None = None):
        return [
            child for child in node.children if isinstance(child, self.Tree) and (name is None or child.data == name)
        ]

    def _first(self, node, name: str):
        for child in node.children:
            if isinstance(child, self.Tree) and child.data == name:
                return child
        return None

    def _token_text(self, node) -> str:
        if hasattr(node, "value"):
            return str(node)
        return self._slice(node)

    def query(self, root):
        from dataclasses import replace
        from .query_model import Query

        expression = self._first(root, "query_expression")
        if expression is None:
            raise QuerySyntaxError(self.source, "Unsupported experimental query shape.", 0)
        primary = next(
            (
                c
                for c in expression.children
                if isinstance(c, self.Tree) and c.data in {"select_query", "predicate_only_query"}
            ),
            None,
        )
        if primary is None:
            raise QuerySyntaxError(
                self.source, "Grouped and compound queries are not yet modelled by the prototype.", 0
            )
        if primary.data == "predicate_only_query":
            predicate_tree = next(c for c in primary.children if isinstance(c, self.Tree))
            query = Query(predicate=self.boolean(predicate_tree), source=self.source)
        else:
            query = self.select_query(primary)
        order = self._first(expression, "order_by_clause")
        limit = self._first(expression, "limit_clause")
        offset = self._first(expression, "offset_clause")
        return replace(
            query,
            order_by=tuple(self.order_term(term) for term in self._trees(order, "order_term")) if order else (),
            limit=int(str(limit.children[0]).replace("_", "")) if limit else None,
            offset=int(str(offset.children[0]).replace("_", "")) if offset else 0,
            source=self.source,
        )

    def select_query(self, node):
        from .query_model import Query

        select_clause = self._first(node, "select_clause")
        from_clause = self._first(node, "from_clause")
        where_clause = self._first(node, "where_clause")
        select = (
            tuple(self.select_term(term) for term in self._trees(select_clause, "select_term")) if select_clause else ()
        )
        distinct = bool(select_clause and self._slice(select_clause).lstrip().upper().startswith("SELECT DISTINCT"))
        from_source = from_facet = from_alias = None
        if from_clause:
            relation = self._first(from_clause, "relation_reference")
            if relation:
                from_source, facets, from_alias = self.relation_reference(relation)
                from_facet = facets[0] if facets else None
                if len(facets) > 1:
                    raise QuerySyntaxError(
                        self.source, "Facet expansion is not yet modelled by the prototype.", relation.meta.start_pos
                    )
        predicate = None
        if where_clause:
            predicate = self.boolean(next(c for c in where_clause.children if isinstance(c, self.Tree)))
        return Query(
            predicate=predicate,
            source=self.source,
            select=select,
            from_source=from_source,
            distinct=distinct,
            from_facet=from_facet,
            from_alias=from_alias,
        )

    def relation_reference(self, node):
        trees = self._trees(node)
        source_node = trees[0] if trees else node.children[0]
        source = self._token_text(source_node)
        facets = [self._token_text(f.children[0] if f.children else f) for f in self._trees(node, "facet_reference")]
        alias = None
        text = self._slice(node)
        import re

        match = re.search(r"\bAS\s+(`(?:``|[^`])+`|[^\s,]+)\s*$", text, re.IGNORECASE)
        if match:
            alias = match.group(1).replace("``", "`").strip("`")
        return source, facets, alias

    def select_term(self, node):
        from .query_formatter import format_scalar_expression
        from .query_model import SelectTerm

        expr_node = next((c for c in node.children if isinstance(c, self.Tree) or hasattr(c, "value")), None)
        expr = self.scalar(expr_node)
        text = self._slice(node)
        import re

        match = re.search(r"\s+AS\s+(`(?:``|[^`])+`|[^\s]+)\s*$", text, re.IGNORECASE)
        alias = match.group(1).replace("``", "`").strip("`") if match else None
        return SelectTerm(format_scalar_expression(expr), alias, self._node_start(expr_node), expression=expr)

    def order_term(self, node):
        from .query_formatter import format_scalar_expression
        from .query_model import OrderTerm

        expr_node = next(c for c in node.children if isinstance(c, self.Tree) or hasattr(c, "value"))
        expr = self.scalar(expr_node)
        return OrderTerm(
            format_scalar_expression(expr),
            self._slice(node).rstrip().upper().endswith(" DESC"),
            self._node_start(expr_node),
            expression=expr,
        )

    def scalar(self, node):
        from .query_model import Field, ScalarBinary, ScalarIndex, ScalarMember, ScalarUnary

        if not isinstance(node, self.Tree):
            token_type = getattr(node, "type", "")
            if token_type in {"NUMBER", "UNIT_LITERAL", "STRING"}:
                return self.literal_token(node)
            return Field(str(node).strip("`").replace("``", "`"), getattr(node, "start_pos", 0))
        data = node.data
        if data in {"identifier", "scalar_atom"} and len(node.children) == 1:
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
            operand_node = next(c for c in node.children if isinstance(c, self.Tree) or hasattr(c, "value"))
            operand = self.scalar(operand_node)
            prefix = self.source[node.meta.start_pos : self._start(operand)].strip()
            return ScalarUnary(prefix, operand, node.meta.start_pos) if prefix else operand
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
        if data in {"NUMBER", "UNIT_LITERAL", "STRING"}:
            return self.literal_token(node)
        if not node.children:
            text = self._slice(node)
            if text[:1].isdigit() or text[:1] in "'\"":
                return self.literal_text(text, node.meta.start_pos)
            return Field(text.strip("`").replace("``", "`"), node.meta.start_pos)
        if len(node.children) == 1 and not isinstance(node.children[0], self.Tree):
            token = node.children[0]
            if getattr(token, "type", "") in {"NUMBER", "UNIT_LITERAL", "STRING"}:
                return self.literal_token(token)
            return Field(str(token).strip("`").replace("``", "`"), getattr(token, "start_pos", node.meta.start_pos))
        raise QuerySyntaxError(
            self.source, f"Experimental model construction does not yet support {data}.", node.meta.start_pos
        )

    def boolean(self, node):
        from .query_model import Binary, IsNull

        if node.data == "boolean_not":
            child = next(c for c in node.children if isinstance(c, self.Tree))
            value = self.boolean(child)
            if self._slice(node).lstrip().upper().startswith("NOT "):
                from .query_model import Unary

                return Unary("NOT", value)
            return value
        if node.data in {"boolean_expression", "boolean_and"}:
            children = self._trees(node)
            value = self.boolean(children[0])
            operator = "OR" if node.data == "boolean_expression" else "AND"
            for child in children[1:]:
                value = Binary(operator, value, self.boolean(child))
            return value
        if node.data == "predicate":
            left = self.scalar(node.children[0])
            suffix = next(c for c in node.children[1:] if isinstance(c, self.Tree))
            text = self._slice(suffix).strip()
            upper = text.upper()
            if "IS NOT NULL" in upper:
                return IsNull(left, True)
            if "IS NULL" in upper:
                return IsNull(left, False)
            right_node = next(
                (c for c in reversed(suffix.children) if isinstance(c, self.Tree) or hasattr(c, "value")), None
            )
            right = self.scalar(right_node)
            import re

            match = re.search(r"<=|>=|!=|<>|=|<|>", text)
            if not match:
                raise QuerySyntaxError(self.source, "Unsupported experimental predicate.", suffix.meta.start_pos)
            return Binary(match.group(0), left, right)
        if node.data == "boolean_primary":
            return self.boolean(next(c for c in node.children if isinstance(c, self.Tree)))
        raise QuerySyntaxError(
            self.source, f"Experimental Boolean construction does not yet support {node.data}.", node.meta.start_pos
        )

    def literal_token(self, token):
        return self.literal_text(str(token), getattr(token, "start_pos", 0))

    def literal_text(self, text: str, position: int):
        from .query_model import Literal
        import re

        raw = text
        if text.startswith(("'", '"')):
            quote = text[0]
            inner = text[1:-1].replace(quote * 2, quote)
            return Literal(inner, raw, position, True)
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
        match = re.fullmatch(r"(\d+(?:\.\d+)?)([^\W\d_]+(?:-[^\W\d_]+)*)", compact, re.UNICODE)
        if match:
            return Literal(f"{match.group(1)} {match.group(2)}", f"{match.group(1)} {match.group(2)}", position)
        return Literal(text, raw, position)

    @staticmethod
    def _node_start(node) -> int:
        return getattr(node, "start_pos", getattr(getattr(node, "meta", None), "start_pos", 0))

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
        if hasattr(value, "right"):
            return _LarkModelBuilder._end(value.right)
        if hasattr(value, "member") and hasattr(value, "position"):
            return value.position + 1 + len(value.member)
        return _LarkModelBuilder._start(value)
