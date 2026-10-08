"""Build parser-neutral yt-sql models from private Tree-sitter concrete trees."""

from __future__ import annotations

from dataclasses import replace
import re
from typing import Any

from .query_formatter import _canonical_numeric_raw, format_scalar_expression
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
    DerivedRelation,
    Field,
    InList,
    IsNull,
    JoinClause,
    JoinKind,
    Literal,
    OrderTerm,
    Query,
    QuerySyntaxError,
    RelationReference,
    RelationWildcard,
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

_KEYWORD_SUFFIX = "_keyword"
_COMPARISON_OPERATORS = re.compile(r"<=|>=|!=|<>|=|<|>")


class TreeSitterModelBuilder:
    """Lower one valid Tree-sitter CST without invoking another parser."""

    __slots__ = ("_offsets", "ascii_source", "collection_bindings", "source", "source_bytes")

    def __init__(self, source: str, source_bytes: bytes | None = None) -> None:
        self.source = source
        self.source_bytes = source_bytes if source_bytes is not None else source.encode("utf-8")
        self.ascii_source = source.isascii()
        self.collection_bindings: list[str] = []
        self._offsets: dict[int, int] = {0: 0, len(self.source_bytes): len(source)}

    def build(self, root) -> Query:
        query_node = self._first(root, "query")
        if query_node is None:
            raise QuerySyntaxError(self.source, "Unsupported experimental query shape.", 0)
        expression = self._first(query_node, "query_expression")
        if expression is None:
            raise QuerySyntaxError(self.source, "Unsupported experimental query shape.", 0)
        query = self.query_expression(expression)
        with_clause = self._first(query_node, "with_clause")
        if with_clause is not None:
            ctes = []
            for cte in self._children(with_clause, "cte"):
                name_node = self._first(cte, "identifier")
                nested = self._first(cte, "query_expression")
                ctes.append(
                    CommonTableExpression(
                        self.identifier(name_node),
                        self.query_expression(nested),
                        self.start(name_node),
                    )
                )
            query = replace(query, ctes=tuple(ctes))
        return query

    def query_expression(self, node) -> Query:
        primaries = []
        unions = []
        order = limit = offset = None
        for child in node.named_children:
            if child.type == "query_primary":
                primaries.append(child)
            elif child.type == "union_operator":
                unions.append(child)
            elif child.type == "order_by_clause":
                order = child
            elif child.type == "limit_clause":
                limit = child
            elif child.type == "offset_clause":
                offset = child
        if not primaries:
            raise QuerySyntaxError(self.source, "Unsupported experimental query shape.", self.start(node))

        query = self.query_primary(primaries[0])
        operations = []
        for union, primary in zip(unions, primaries[1:], strict=True):
            operations.append(
                SetOperation(
                    self.query_primary(primary),
                    self._first(union, "all_keyword") is not None,
                    self.start(union),
                    False,
                    self._first(primary, "query_expression") is not None,
                )
            )

        limit_value = limit_literal = None
        if limit is not None:
            literal = self._first(limit, "positive_integer_literal")
            limit_value, limit_literal = self.row_count(literal)
        offset_value = 0
        offset_literal = None
        if offset is not None:
            literal = self._first(offset, "integer_literal")
            offset_value, offset_literal = self.row_count(literal)
        if not operations and order is None and limit is None and offset is None:
            return query
        return replace(
            query,
            set_operations=tuple(query.set_operations) + tuple(operations),
            order_by=tuple(self.order_term(term) for term in self._children(order, "order_term")),
            limit=limit_value,
            offset=offset_value,
            limit_literal=limit_literal,
            offset_literal=offset_literal,
            source=self.source,
        )

    def query_primary(self, node) -> Query:
        primary = self._first_meaningful(node)
        if primary.type == "predicate_only_query":
            return Query(predicate=self.boolean(self._first_meaningful(primary)), source=self.source)
        if primary.type == "query_expression":
            return Query(source=self.source, left_query=self.query_expression(primary))
        return self.select_query(primary)

    def select_query(self, node) -> Query:
        select_clause = from_clause = where_clause = group_clause = having_clause = None
        for child in node.named_children:
            if child.type == "select_clause":
                select_clause = child
            elif child.type == "from_clause":
                from_clause = child
            elif child.type == "where_clause":
                where_clause = child
            elif child.type == "group_by_clause":
                group_clause = child
            elif child.type == "having_clause":
                having_clause = child
        select = tuple(self.select_term(term) for term in self._children(select_clause, "select_term"))
        distinct = select_clause is not None and self._first(select_clause, "distinct_keyword") is not None

        from_source = from_facet = from_alias = None
        from_relation = None
        joins = ()
        additional_facets: tuple[tuple[str, int], ...] = ()
        if from_clause is not None:
            relation_node = self._first(from_clause, "relation_reference")
            relation, facets = self.relation_reference(relation_node)
            from_source = relation.source
            from_facet = facets[0][0] if facets else None
            from_alias = relation.alias
            from_relation = relation if relation.derived is not None else None
            additional_facets = tuple(facets[1:])
            joins = tuple(self.join_clause(join) for join in self._children(from_clause, "join_clause"))

        predicate = None
        if where_clause is not None:
            predicate = self.boolean(self._first(where_clause, "boolean_expression"))
        group_by = tuple(self.scalar(item) for item in self._children(group_clause, "scalar_expression"))
        having = self.having(self._first(having_clause, "having_expression")) if having_clause is not None else None
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
            from_relation=from_relation,
        )
        if additional_facets:
            query = replace(
                query,
                set_operations=tuple(
                    SetOperation(replace(query, from_facet=facet, set_operations=()), True, position, True)
                    for facet, position in additional_facets
                ),
            )
        return query

    def relation_reference(self, node) -> tuple[RelationReference, list[tuple[str, int]]]:
        operand = self._first(node, "relation_operand") or node
        derived_node = self._first(operand, "derived_relation")
        facet_list = self._first(operand, "facet_list") or self._first(operand, "single_facet")
        facet_nodes = self._children(facet_list, "facet_reference")
        facets = [
            (self.identifier(self._first(facet, "identifier")).casefold(), self.start(facet)) for facet in facet_nodes
        ]
        alias_node = node.child_by_field_name("alias")
        alias = self.identifier(alias_node) if alias_node is not None else None

        if derived_node is not None:
            expression = self._first(derived_node, "query_expression")
            derived = DerivedRelation(self.query_expression(expression), self.start(derived_node))
            return RelationReference(None, None, alias, self.start(derived_node), derived), facets

        source_node = self._first(operand, "relation_source")
        value_node = self._first_meaningful(source_node)
        source = self.text(value_node)
        if value_node.type == "string":
            source = self.unquote_string(source)
        elif value_node.type in {"identifier", "quoted_identifier"}:
            source = self.identifier(value_node)
        facet = facets[0][0] if facets else None
        return RelationReference(source, facet, alias, self.start(node)), facets

    def join_clause(self, node) -> JoinClause:
        kind_node = self._first(node, "join_kind")
        kind_text = self.text(kind_node).upper()
        if kind_text.startswith("LEFT"):
            kind = JoinKind.LEFT
        elif kind_text.startswith("SEMI"):
            kind = JoinKind.SEMI
        elif kind_text.startswith("ANTI"):
            kind = JoinKind.ANTI
        else:
            kind = JoinKind.INNER
        relation_node = self._first(node, "relation_reference_single")
        relation, facets = self.relation_reference(relation_node)
        if len(facets) > 1:
            raise AssertionError("JOIN relation unexpectedly contains multiple facets")
        predicate = self.boolean(self._first(node, "boolean_expression"))
        return JoinClause(kind, relation, self.promote_join_predicate(predicate), self.start(node))

    def promote_join_predicate(self, predicate: Any) -> Any:
        if isinstance(predicate, Binary) and predicate.operator in {"AND", "OR"}:
            return Binary(
                predicate.operator,
                self.promote_join_predicate(predicate.left),
                self.promote_join_predicate(predicate.right),
            )
        if isinstance(predicate, Unary) and predicate.operator == "NOT":
            return Unary(predicate.operator, self.promote_join_predicate(predicate.operand))
        if isinstance(predicate, Binary) and predicate.operator in {"=", "!=", "<>", "<", "<=", ">", ">="}:
            right = predicate.right
            if isinstance(right, Literal) and not right.quoted:
                right = (
                    self.literal_text(right.raw, right.position)
                    if right.raw[:1].isdigit()
                    else Field(right.raw, right.position)
                )
            return ScalarComparison(predicate.operator, predicate.left, right)
        if isinstance(predicate, IsNull):
            return ScalarIsNull(predicate.field, predicate.negated)
        return predicate

    def select_term(self, node) -> SelectTerm:
        wildcard = self._first(node, "projection_wildcard")
        if wildcard is not None:
            return SelectTerm("*", position=self.start(wildcard))
        relation_wildcard = self._first(node, "relation_wildcard")
        if relation_wildcard is not None:
            identifier = self._first(relation_wildcard, "identifier")
            qualifier = self.identifier(identifier)
            expression = RelationWildcard(qualifier, self.start(identifier))
            return SelectTerm(self.text(relation_wildcard), position=self.start(identifier), expression=expression)
        expression_node = self._first(node, "scalar_expression")
        expression = self.scalar(expression_node)
        alias_node = node.child_by_field_name("alias")
        alias = self.identifier(alias_node) if alias_node is not None else None
        return SelectTerm(
            format_scalar_expression(expression),
            alias,
            self.start(expression_node),
            expression=expression,
        )

    def order_term(self, node) -> OrderTerm:
        expression_node = self._first(node, "scalar_expression")
        expression = self.scalar(expression_node)
        return OrderTerm(
            format_scalar_expression(expression),
            self._first(node, "desc_keyword") is not None,
            self.start(expression_node),
            expression=expression,
        )

    def scalar(self, node) -> Any:
        if node is None:
            raise QuerySyntaxError(self.source, "Missing scalar expression.", 0)
        while True:
            node_type = node.type
            if node_type == "scalar_expression":
                scalar_children = self._children(node, "scalar_expression")
                if len(scalar_children) == 2:
                    left = self.scalar(scalar_children[0])
                    right = self.scalar(scalar_children[1])
                    gap_start = self.end(scalar_children[0])
                    gap_end = self.start(scalar_children[1])
                    match = re.search(r"[+\-*/%]", self.source[gap_start:gap_end])
                    if match is None:
                        raise QuerySyntaxError(self.source, "Missing scalar operator.", gap_start)
                    position = gap_start + match.start()
                    return ScalarBinary(match.group(0), left, right, position)
                if len(scalar_children) == 1:
                    prefix = self.source[self.start(node) : self.start(scalar_children[0])]
                    match = re.search(r"[+-]", prefix)
                    if match is not None:
                        operand = self.scalar(scalar_children[0])
                        return ScalarUnary(match.group(0), operand, self.start(node) + match.start())
                    node = scalar_children[0]
                    continue
                node = self._first_meaningful(node)
                continue
            if node_type == "scalar_atom":
                node = self._first_meaningful(node)
                continue
            if node_type == "postfix_expression":
                meaningful = self._meaningful(node)
                if len(meaningful) == 1:
                    node = meaningful[0]
                    continue
                value = self.scalar(meaningful[0])
                for suffix in meaningful[1:]:
                    if suffix.type == "index_suffix":
                        value = ScalarIndex(
                            value, self.scalar(self._first(suffix, "scalar_expression")), self.start(suffix)
                        )
                    elif suffix.type == "member_suffix":
                        member_node = self._first(suffix, "identifier")
                        value = ScalarMember(value, self.identifier(member_node), self.start(suffix))
                return value
            if node_type in {"parenthesised_scalar", "comparison_value"}:
                node = self._first(node, "scalar_expression")
                continue
            break
        if node_type == "identifier":
            name = self.identifier(node)
            return self.bound_collection_reference(name, self.start(node)) or Field(name, self.start(node))
        if node_type in {"ordinary_identifier", "quoted_identifier"}:
            name = self.identifier(node)
            return self.bound_collection_reference(name, self.start(node)) or Field(name, self.start(node))
        if node_type in {"scalar_literal", "temporal_literal", "literal_sequence", "literal_piece"}:
            return self.literal_text(self.text(node), self.start(node))
        if node_type in {"scalar_function", "function_call", "aggregate_function", "collection_transform"}:
            return self.function(node)
        if node_type == "case_expression":
            return self.case_expression(node)
        if node_type in {
            "number",
            "unit_literal",
            "string",
            "datetime",
            "date",
            "time",
            "infinity_literal",
            "relative_temporal_literal",
            "true_keyword",
            "false_keyword",
            "null_keyword",
        }:
            return self.literal_text(self.text(node), self.start(node))
        meaningful = self._meaningful(node)
        if len(meaningful) == 1:
            return self.scalar(meaningful[0])
        raise QuerySyntaxError(
            self.source,
            f"Experimental Tree-sitter model construction does not yet support {node_type}.",
            self.start(node),
        )

    def function(self, node) -> Any:
        name = self.text(node).split("(", 1)[0].strip().upper()
        if node.type == "function_call":
            raise QuerySyntaxError(self.source, f"Unsupported scalar function {name!r}.", self.start(node))
        if node.type == "collection_transform":
            values = self._children(node, "scalar_expression")
            collection = self.scalar(values[0])
            binding_node = node.child_by_field_name("binding")
            binding = self.identifier(binding_node)
            self.collection_bindings.append(binding)
            try:
                result = (
                    self.boolean(self._first(node, "boolean_expression"))
                    if name == "FILTER"
                    else self.scalar(values[-1])
                )
            finally:
                self.collection_bindings.pop()
            if name == "FILTER":
                return CollectionFilter(collection, binding, result, self.start(node))
            return CollectionProjection(collection, binding, result, self.start(node))
        if node.type == "aggregate_function":
            scalar_values = self._children(node, "scalar_expression")
            count_star = name == "COUNT" and "*" in self.text(node).split("(", 1)[1].split(")", 1)[0]
            binding_node = node.child_by_field_name("binding")
            if name == "COUNT" and binding_node is not None:
                collection = self.scalar(scalar_values[0])
                binding = self.identifier(binding_node)
                self.collection_bindings.append(binding)
                try:
                    predicate = self.boolean(self._first(node, "boolean_expression"))
                finally:
                    self.collection_bindings.pop()
                return CollectionCount(collection, binding, predicate, self.start(node))
            args = tuple(self.scalar(value) for value in scalar_values)
            filter_node = self._first(node, "aggregate_filter")
            filter_predicate = (
                self.boolean(self._first(filter_node, "boolean_expression")) if filter_node is not None else None
            )
            return AggregateFunction(name, args, count_star, filter_predicate, self.start(node))
        args = tuple(self.scalar(value) for value in self._children(node, "scalar_expression"))
        return ScalarFunction(name, args, self.start(node))

    def case_expression(self, node) -> ScalarCase:
        whens = []
        for when in self._children(node, "case_when"):
            condition = self._first(when, "boolean_expression")
            result = self._first(when, "scalar_expression")
            whens.append(CaseWhen(self.boolean(condition), self.scalar(result), self.start(when)))
        direct_results = self._children(node, "scalar_expression")
        else_result = self.scalar(direct_results[-1]) if direct_results else None
        return ScalarCase(tuple(whens), else_result, self.start(node))

    def having(self, node) -> Any:
        if node.type == "having_expression":
            expressions = self._children(node, "having_expression")
            if len(expressions) == 2:
                operator = "OR" if self._first(node, "or_keyword") is not None else "AND"
                return Binary(operator, self.having(expressions[0]), self.having(expressions[1]))
            primary = self._first(node, "having_primary")
            value = self.having(primary)
            return Unary("NOT", value) if self._first(node, "not_keyword") is not None else value
        if node.type == "having_primary":
            predicate = self._first(node, "having_predicate")
            value = (
                self.having(predicate) if predicate is not None else self.having(self._first(node, "having_expression"))
            )
            truth = self._first(node, "truth_test")
            return self.apply_truth_test(value, truth) if truth is not None else value
        if node.type == "having_predicate":
            values = self._children(node, "scalar_expression")
            left = self.scalar(values[0])
            negated = self._first(node, "not_keyword") is not None
            if self._first(node, "null_keyword") is not None:
                return ScalarIsNull(left, negated)
            truth = self._first(node, "truth_value")
            if truth is not None:
                return TruthTest(left, self.truth_value(truth), negated)
            if self._first(node, "distinct_keyword") is not None:
                operator = "IS NOT DISTINCT FROM" if negated else "IS DISTINCT FROM"
                return ScalarComparison(operator, left, self.scalar(values[-1]))
            match = _COMPARISON_OPERATORS.search(self.text(node))
            if match is None:
                raise QuerySyntaxError(self.source, "Unsupported experimental HAVING predicate.", self.start(node))
            operator = "!=" if match.group(0) == "<>" else match.group(0)
            return ScalarComparison(operator, left, self.scalar(values[-1]))
        return self.boolean(node)

    def boolean(self, node) -> Any:
        if node.type == "boolean_expression":
            expressions = []
            primary = not_keyword = or_keyword = None
            for child in node.named_children:
                if child.type == "boolean_expression":
                    expressions.append(child)
                elif child.type == "boolean_primary":
                    primary = child
                elif child.type == "not_keyword":
                    not_keyword = child
                elif child.type == "or_keyword":
                    or_keyword = child
            if len(expressions) == 2:
                operator = "OR" if or_keyword is not None else "AND"
                return Binary(operator, self.boolean(expressions[0]), self.boolean(expressions[1]))
            child = expressions[0] if expressions else primary
            value = self.boolean(child)
            return Unary("NOT", value) if not_keyword is not None else value
        if node.type == "boolean_primary":
            return self.boolean(self._first_meaningful(node))
        if node.type == "parenthesised_boolean":
            value = self.boolean(self._first(node, "boolean_expression"))
            truth = self._first(node, "truth_test")
            return self.apply_truth_test(value, truth) if truth is not None else value
        if node.type == "collection_predicate":
            collection = self.scalar(self._first(node, "scalar_expression"))
            binding_node = node.child_by_field_name("binding")
            binding = self.identifier(binding_node)
            self.collection_bindings.append(binding)
            try:
                predicate = self.boolean(self._first(node, "boolean_expression"))
            finally:
                self.collection_bindings.pop()
            quantifier = "ALL" if self._first(node, "all_keyword") is not None else "ANY"
            return CollectionPredicate(quantifier, collection, binding, predicate, self.start(node))
        if node.type == "predicate":
            left_node = suffix = None
            for child in node.named_children:
                if child.type == "scalar_expression":
                    left_node = child
                elif child.type == "predicate_suffix":
                    suffix = child
            left = self.scalar(left_node)
            if suffix is None:
                return Binary("=", left, Literal(True, "TRUE", self._start_value(left)))
            return self.predicate_suffix(left, suffix)
        raise QuerySyntaxError(
            self.source,
            f"Experimental Tree-sitter Boolean construction does not yet support {node.type}.",
            self.start(node),
        )

    def predicate_suffix(self, left: Any, node) -> Any:
        node_children = node.named_children
        if len(node_children) == 2 and node_children[0].type == "comparison_operator":
            operator = self.text(node_children[0])
            operator = "!=" if operator == "<>" else operator
            comparison = node_children[1]
            if not isinstance(left, Field):
                return ScalarComparison(operator, left, self.scalar(comparison))
            return Binary(operator, left, self.predicate_literal(comparison))

        children: dict[str, list[Any]] = {}
        for child in node_children:
            children.setdefault(child.type, []).append(child)

        negated = "not_keyword" in children
        if "distinct_keyword" in children:
            right = self.scalar(children["scalar_expression"][-1])
            return ScalarComparison("IS NOT DISTINCT FROM" if negated else "IS DISTINCT FROM", left, right)
        if "null_keyword" in children:
            return IsNull(left, negated) if isinstance(left, Field) else ScalarIsNull(left, negated)
        if truth_values := children.get("truth_value"):
            operand = (
                Binary("=", left, Literal(True, "TRUE", self._start_value(left))) if isinstance(left, Field) else left
            )
            return TruthTest(operand, self.truth_value(truth_values[0]), negated)
        if "between_keyword" in children:
            values = children["literal_value"]
            return Between(left, self.predicate_literal(values[0]), self.predicate_literal(values[1]), negated)
        if "in_keyword" in children:
            values = tuple(self.predicate_literal(value) for value in children["literal_value"])
            return InList(left, values, negated)
        if text_operators := children.get("text_operator"):
            text_operator = text_operators[0]
            spelling = self.text(text_operator).upper()
            operator = (
                "CONTAINS"
                if spelling in {"CONTAIN", "CONTAINS"}
                else "MATCHES"
                if spelling
                in {
                    "MATCH",
                    "MATCHES",
                }
                else spelling
            )
            value = self.predicate_literal(children["text_value"][0])
            does_not = "does_keyword" in children
            return TextPredicate(operator, left, value, negated or does_not)
        if natural_comparisons := children.get("natural_comparison"):
            natural = natural_comparisons[0]
            spelling = " ".join(self.text(natural).upper().split())
            operator = {
                "AT LEAST": ">=",
                "AT MOST": "<=",
                "GREATER THAN": ">",
                "MORE THAN": ">",
                "OVER": ">",
                "ABOVE": ">",
                "LESS THAN": "<",
                "UNDER": "<",
                "BELOW": "<",
                "EQUAL TO": "=",
                "EQUALS": "=",
            }[spelling]
            return Binary(operator, left, self.predicate_literal(children["literal_value"][0]))

        operator_node = children["comparison_operator"][0]
        comparison = children["comparison_value"][0]
        operator = self.text(operator_node)
        operator = "!=" if operator == "<>" else operator
        if not isinstance(left, Field):
            return ScalarComparison(operator, left, self.scalar(comparison))
        return Binary(operator, left, self.predicate_literal(comparison))

    def apply_truth_test(self, value: Any, node) -> TruthTest:
        return TruthTest(
            value, self.truth_value(self._first(node, "truth_value")), self._first(node, "not_keyword") is not None
        )

    def truth_value(self, node) -> str:
        return self.text(node).upper()

    def predicate_literal(self, node) -> Any:
        if node.type in {"comparison_value", "literal_value", "text_value", "literal_sequence"}:
            value = self.literal_text(self.text(node), self.start(node))
        else:
            value = self.scalar(node)
        if isinstance(value, Field):
            return Literal(value.name, value.name, value.position, False)
        if isinstance(value, Literal) and not value.quoted:
            if value.value is None or isinstance(value.value, bool):
                return value
            raw = value.raw
            source_text = self.text(node).strip()
            if source_text.upper().startswith("-INFINITY()"):
                raw = "-INFINITY()"
            elif source_text.startswith(("+", "-")):
                raw = f"{source_text[0]} {raw.lstrip('+-').lstrip()}"
            unit = re.fullmatch(r"(\d+(?:\.\d+)?)([^\W\d_].*)", raw, re.UNICODE)
            if unit and not raw.lower().startswith(("0x", "0o", "0b")) and not re.fullmatch(r"[kKmMbB]", unit.group(2)):
                raw = f"{unit.group(1)} {unit.group(2)}"
            return Literal(raw, raw, value.position, False)
        return value

    def literal_text(self, text: str, position: int) -> Literal:
        raw = text
        stripped = text.strip()
        if stripped.startswith(("'", '"')):
            return Literal(self.unquote_string(stripped), raw, position, True)
        if stripped.upper() == "TRUE":
            return Literal(True, raw, position)
        if stripped.upper() == "FALSE":
            return Literal(False, raw, position)
        if stripped.upper() == "NULL":
            return Literal(None, raw, position)
        compact = stripped.replace("_", "")
        prefix = compact[:2].casefold()
        if prefix == "0x":
            return Literal(int(compact, 16), raw, position)
        if prefix == "0b":
            return Literal(int(compact, 2), raw, position)
        if prefix == "0o":
            return Literal(int(compact, 8), raw, position)
        if compact.isdecimal() or compact.count(".") == 1 and compact.replace(".", "").isdecimal():
            return Literal(float(compact) if "." in compact else int(compact), raw, position)
        return Literal(stripped, raw, position)

    def row_count(self, node) -> tuple[int, str]:
        text = self.text(node)
        compact = text.replace("_", "")
        if compact.lower().startswith("0x"):
            value = int(compact[2:], 16)
        elif compact.lower().startswith("0o"):
            value = int(compact[2:], 8)
        elif compact.lower().startswith("0b"):
            value = int(compact[2:], 2)
        else:
            value = int(compact, 10)
        return value, _canonical_numeric_raw(text)

    def bound_collection_reference(self, name: str, position: int) -> Any | None:
        parts = name.split(".")
        for distance, binding in enumerate(reversed(self.collection_bindings)):
            if parts[0] != binding:
                continue
            value: Any = CollectionElementReference(binding, distance, position)
            offset = len(binding)
            for member in parts[1:]:
                value = ScalarMember(value, member, position + offset)
                offset += len(member) + 1
            return value
        return None

    def identifier(self, node) -> str:
        if node.type == "identifier":
            node = self._first_meaningful(node)
        text = self.text(node)
        return text[1:-1].replace("``", "`") if node.type == "quoted_identifier" else text

    @staticmethod
    def unquote_string(text: str) -> str:
        quote = text[0]
        return text[1:-1].replace(quote * 2, quote)

    def text(self, node) -> str:
        if self.ascii_source:
            return self.source[node.start_byte : node.end_byte]
        return self.source_bytes[node.start_byte : node.end_byte].decode("utf-8")

    def start(self, node) -> int:
        return self.offset(node.start_byte)

    def end(self, node) -> int:
        return self.offset(node.end_byte)

    def offset(self, byte_offset: int) -> int:
        if self.ascii_source:
            return byte_offset
        cached = self._offsets.get(byte_offset)
        if cached is None:
            cached = len(self.source_bytes[:byte_offset].decode("utf-8"))
            self._offsets[byte_offset] = cached
        return cached

    def _children(self, node, node_type: str | None = None) -> list[Any]:
        if node is None:
            return []
        return [
            child
            for child in node.named_children
            if child.type != "comment" and (node_type is None or child.type == node_type)
        ]

    def _meaningful(self, node) -> list[Any]:
        return [child for child in self._children(node) if not child.type.endswith(_KEYWORD_SUFFIX)]

    @staticmethod
    def _first_meaningful(node):
        for child in node.named_children:
            if child.type != "comment" and not child.type.endswith(_KEYWORD_SUFFIX):
                return child
        return None

    def _first(self, node, node_type: str):
        if node is None:
            return None
        for child in node.named_children:
            if child.type == node_type:
                return child
        return None

    @staticmethod
    def _start_value(value: Any) -> int:
        if hasattr(value, "position"):
            return value.position
        if hasattr(value, "left"):
            return TreeSitterModelBuilder._start_value(value.left)
        return 0
