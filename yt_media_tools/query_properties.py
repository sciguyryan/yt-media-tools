"""Semantic property analysis for optimisation and acquisition planning.

This module describes facts that are true of a resolved yt-sql query independently
of any particular optimisation decision.  It intentionally separates semantic
knowledge from acquisition policy so later optimiser passes can demand explicit
proofs rather than inferring safety from incidental execution behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Any

from .query_model import (
    AggregateFunction,
    Between,
    Binary,
    CollectionElementReference,
    CollectionPredicate,
    Field,
    InList,
    IsNull,
    Literal,
    Query,
    ScalarBinary,
    ScalarCase,
    ScalarComparison,
    ScalarFunction,
    ScalarIndex,
    ScalarMember,
    ScalarIsNull,
    ScalarUnary,
    TextPredicate,
    Unary,
)
from .query_semantics import _contains_aggregate, query_physical_source_requests
from .schema import ALIASES, KNOWN_FIELD_TYPES
from .source_capabilities import (
    EXACT,
    STRUCTURALLY_UNSUPPORTED,
    FieldCapability,
    field_capability,
    selected_facet_capabilities,
)
from .source_model import SourceSpec


# Evaluation stages are ordered from information requiring no acquired rows through
# relation-wide evaluation.  String constants keep explain/snapshot output stable and
# avoid coupling the public analysis API to enum serialisation details.
STAGE_CONSTANT = "constant"
STAGE_ENUMERATION = "enumeration"
STAGE_DETAILED = "detailed"
STAGE_GROUP = "group"
STAGE_RELATION = "relation"

METADATA_NONE = "none"
METADATA_ENUMERATION = "enumeration"
METADATA_DETAILED = "detailed"

KNOWN_VALUE = "known-value"
SQL_NULL = "sql-null"
STRUCTURALLY_UNAVAILABLE = "structurally-unavailable"
NOT_ACQUIRED = "not-acquired"

_STAGE_RANK = {
    STAGE_CONSTANT: 0,
    STAGE_ENUMERATION: 1,
    STAGE_DETAILED: 2,
    STAGE_GROUP: 3,
    STAGE_RELATION: 4,
}
_METADATA_RANK = {
    METADATA_NONE: 0,
    METADATA_ENUMERATION: 1,
    METADATA_DETAILED: 2,
}


@dataclass(frozen=True)
class KnowledgeState:
    """Internal knowledge about one logical value before SQL evaluation.

    ``STRUCTURALLY_UNAVAILABLE`` and ``SQL_NULL`` both imply a logical SQL NULL,
    but they remain distinct because the former is a source-capability proof while
    the latter is an acquired value.  ``NOT_ACQUIRED`` never implies SQL NULL.
    """

    state: str
    value: Any = None

    @property
    def logically_known(self) -> bool:
        """Return whether the logical SQL value is already proven."""
        return self.state in {KNOWN_VALUE, SQL_NULL, STRUCTURALLY_UNAVAILABLE}

    @property
    def logically_null(self) -> bool:
        """Return whether the logical SQL value is proven to be NULL."""
        return self.state in {SQL_NULL, STRUCTURALLY_UNAVAILABLE}


def known_value(value: Any) -> KnowledgeState:
    """Return knowledge for an acquired, non-NULL scalar value."""
    if value is None:
        raise ValueError("known_value requires a non-NULL value")
    return KnowledgeState(KNOWN_VALUE, value)


def sql_null() -> KnowledgeState:
    """Return knowledge for an acquired SQL NULL value."""
    return KnowledgeState(SQL_NULL)


def structurally_unavailable() -> KnowledgeState:
    """Return knowledge proving that a logical field is necessarily SQL NULL."""
    return KnowledgeState(STRUCTURALLY_UNAVAILABLE)


def not_acquired() -> KnowledgeState:
    """Return knowledge for a supported value that has not yet been acquired."""
    return KnowledgeState(NOT_ACQUIRED)


_MISSING = object()


def knowledge_from_capability(
    capability: FieldCapability,
    *,
    acquired: bool = False,
    value: Any = _MISSING,
) -> KnowledgeState:
    """Classify field knowledge without conflating unacquired metadata with SQL NULL."""
    if capability.structural_support == STRUCTURALLY_UNSUPPORTED:
        return structurally_unavailable()
    if not acquired or value is _MISSING:
        return not_acquired()
    if value is None:
        return sql_null()
    return known_value(value)


@dataclass(frozen=True)
class IndexedFieldRequirement:
    """One direct positional collection access relevant to acquisition planning."""

    field: str
    index: int | None


@dataclass(frozen=True)
class StructuredMemberRequirement:
    """One structured member path rooted at a physical metadata field."""

    field: str
    members: tuple[str, ...]
    index: int | None = None
    indexed: bool = False


@dataclass(frozen=True)
class ExpressionProperties:
    """Semantic properties of one resolved scalar or predicate expression."""

    required_fields: frozenset[str]
    resolved_type: str | None
    constant: bool
    deterministic: bool
    null_sensitive: bool
    may_return_null: bool
    requires_group_context: bool
    earliest_stage: str
    metadata_depth: str
    decidable_from_enumeration: bool
    indexed_requirements: tuple[IndexedFieldRequirement, ...] = ()
    member_requirements: tuple[StructuredMemberRequirement, ...] = ()
    whole_fields: frozenset[str] = frozenset()


@dataclass(frozen=True)
class SourceDependency:
    """One physical source/facet relation referenced by a query."""

    source: str
    facet: str | None


@dataclass(frozen=True)
class QueryProperties:
    """Stable semantic requirements derived from a resolved query."""

    required_fields: frozenset[str]
    dynamic_fields: tuple[str, ...]
    requires_aggregation: bool
    source: SourceSpec | None = None
    source_dependencies: tuple[SourceDependency, ...] = ()
    resolved_output_types: tuple[str | None, ...] = ()
    deterministic: bool = True
    has_volatile_expressions: bool = False
    null_sensitive: bool = False
    cardinality_effects: tuple[str, ...] = ()
    ordering_required: bool = False
    required_order_fields: frozenset[str] = frozenset()
    grouping_dependent: bool = False
    metadata_depth: str = METADATA_NONE
    predicate_stage: str = STAGE_CONSTANT
    predicate_decidable_from_enumeration: bool = True
    requires_complete_acquisition: bool = False
    indexed_requirements: tuple[IndexedFieldRequirement, ...] = ()
    member_requirements: tuple[StructuredMemberRequirement, ...] = ()
    whole_fields: frozenset[str] = frozenset()

    def field_capability(self, field: str) -> FieldCapability:
        """Return the selected source contract when available, otherwise the stable default."""
        if self.source is not None:
            return selected_facet_capabilities(self.source).field(field)
        return field_capability(field)


def _max_stage(*stages: str) -> str:
    return max(stages, key=_STAGE_RANK.__getitem__, default=STAGE_CONSTANT)


def _max_metadata(*depths: str) -> str:
    return max(depths, key=_METADATA_RANK.__getitem__, default=METADATA_NONE)


def _literal_kind(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, date):
        return "date"
    if isinstance(value, timedelta):
        return "duration"
    if isinstance(value, str):
        return "string"
    return "mixed"


def _capability_for_field(field: Field, source: SourceSpec | None) -> FieldCapability:
    if source is not None:
        return selected_facet_capabilities(source).field(field.name)
    return field_capability(field.name)


def _field_properties(field: Field, source: SourceSpec | None) -> ExpressionProperties:
    capability = _capability_for_field(field, source)
    enumeration = capability.ytdlp_flat == EXACT
    stage = STAGE_ENUMERATION if enumeration else STAGE_DETAILED
    metadata = METADATA_ENUMERATION if enumeration else METADATA_DETAILED
    return ExpressionProperties(
        frozenset({field.name.casefold()}),
        field.kind or capability.logical_kind,
        False,
        True,
        capability.nullable,
        capability.nullable,
        False,
        stage,
        metadata,
        enumeration,
        (),
        (),
        frozenset({field.name.casefold()}),
    )


def _combine(
    children: tuple[ExpressionProperties, ...],
    *,
    resolved_type: str | None,
    constant: bool | None = None,
    deterministic: bool | None = None,
    null_sensitive: bool | None = None,
    may_return_null: bool | None = None,
    requires_group_context: bool | None = None,
    earliest_stage: str | None = None,
    metadata_depth: str | None = None,
) -> ExpressionProperties:
    fields = frozenset().union(*(child.required_fields for child in children)) if children else frozenset()
    child_constant = all(child.constant for child in children)
    child_deterministic = all(child.deterministic for child in children)
    child_null_sensitive = any(child.null_sensitive for child in children)
    child_may_null = any(child.may_return_null for child in children)
    child_group = any(child.requires_group_context for child in children)
    stage = earliest_stage or _max_stage(*(child.earliest_stage for child in children))
    depth = metadata_depth or _max_metadata(*(child.metadata_depth for child in children))
    decidable = stage in {STAGE_CONSTANT, STAGE_ENUMERATION} and all(
        child.decidable_from_enumeration for child in children
    )
    indexed = tuple(requirement for child in children for requirement in child.indexed_requirements)
    members = tuple(requirement for child in children for requirement in child.member_requirements)
    whole_fields = frozenset().union(*(child.whole_fields for child in children)) if children else frozenset()
    return ExpressionProperties(
        fields,
        resolved_type,
        child_constant if constant is None else constant,
        child_deterministic if deterministic is None else deterministic,
        child_null_sensitive if null_sensitive is None else null_sensitive,
        child_may_null if may_return_null is None else may_return_null,
        child_group if requires_group_context is None else requires_group_context,
        stage,
        depth,
        decidable,
        indexed,
        members,
        whole_fields,
    )


def _constant_nonnegative_integer(expression: Any) -> int | None:
    """Return a statically provable non-negative integer index, otherwise None."""
    if isinstance(expression, Literal):
        value = expression.value
    elif isinstance(expression, ScalarUnary) and expression.operator in {"+", "-"}:
        operand = _constant_nonnegative_integer(expression.operand)
        if operand is None:
            return None
        value = operand if expression.operator == "+" else -operand
    elif isinstance(expression, ScalarBinary) and expression.operator in {"+", "-", "*", "%"}:
        left = _constant_nonnegative_integer(expression.left)
        right = _constant_nonnegative_integer(expression.right)
        if left is None or right is None:
            return None
        if expression.operator == "+":
            value = left + right
        elif expression.operator == "-":
            value = left - right
        elif expression.operator == "*":
            value = left * right
        else:
            if right == 0:
                return None
            value = left % right
    else:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _structured_member_requirement(expression: ScalarMember) -> StructuredMemberRequirement | None:
    """Return one precise field/member path when the postfix chain has a physical-field root."""
    members: list[str] = []
    node: Any = expression
    while isinstance(node, ScalarMember):
        members.append(node.member)
        node = node.value
    members.reverse()

    index: int | None = None
    if isinstance(node, ScalarIndex) and isinstance(node.collection, Field):
        index_properties = analyse_expression(node.index)
        if not index_properties.constant:
            return StructuredMemberRequirement(node.collection.name.casefold(), tuple(members), None, True)
        index = _constant_nonnegative_integer(node.index)
        return StructuredMemberRequirement(node.collection.name.casefold(), tuple(members), index, True)
    if isinstance(node, Field):
        return StructuredMemberRequirement(node.name.casefold(), tuple(members), None, False)
    return None


def analyse_expression(expression: Any, *, source: SourceSpec | None = None) -> ExpressionProperties:
    """Return deterministic semantic properties for a resolved expression tree."""
    if expression is None:
        return ExpressionProperties(
            frozenset(),
            None,
            True,
            True,
            False,
            False,
            False,
            STAGE_CONSTANT,
            METADATA_NONE,
            True,
        )
    if isinstance(expression, CollectionElementReference):
        resolved_type = expression.resolved_type
        return ExpressionProperties(
            frozenset(),
            expression.kind,
            False,
            True,
            bool(resolved_type is None or resolved_type.nullable),
            bool(resolved_type is None or resolved_type.nullable),
            False,
            STAGE_DETAILED,
            METADATA_NONE,
            True,
        )
    if isinstance(expression, CollectionPredicate):
        collection = analyse_expression(expression.collection, source=source)
        predicate = analyse_expression(expression.predicate, source=source)
        return _combine(
            (collection, predicate),
            resolved_type="boolean",
            null_sensitive=True,
            may_return_null=collection.may_return_null or predicate.may_return_null,
        )
    if isinstance(expression, Field):
        return _field_properties(expression, source)
    if isinstance(expression, Literal):
        return ExpressionProperties(
            frozenset(),
            _literal_kind(expression.value),
            True,
            True,
            expression.value is None,
            expression.value is None,
            False,
            STAGE_CONSTANT,
            METADATA_NONE,
            True,
        )
    if isinstance(expression, (ScalarUnary, Unary)):
        child = analyse_expression(expression.operand, source=source)
        kind = getattr(expression, "kind", None)
        if isinstance(expression, Unary):
            kind = "boolean"
        return _combine((child,), resolved_type=kind, null_sensitive=True, may_return_null=child.may_return_null)
    if isinstance(expression, (ScalarBinary, ScalarComparison, Binary)):
        left = analyse_expression(expression.left, source=source)
        right = analyse_expression(expression.right, source=source)
        kind = getattr(expression, "kind", None)
        if isinstance(expression, (ScalarComparison, Binary)):
            kind = "boolean"
        return _combine(
            (left, right),
            resolved_type=kind,
            null_sensitive=True,
            may_return_null=left.may_return_null or right.may_return_null,
        )
    if isinstance(expression, Between):
        children = (
            analyse_expression(expression.field, source=source),
            analyse_expression(expression.lower, source=source),
            analyse_expression(expression.upper, source=source),
        )
        return _combine(
            children,
            resolved_type="boolean",
            null_sensitive=True,
            may_return_null=children[0].may_return_null,
        )
    if isinstance(expression, InList):
        children = (analyse_expression(expression.field, source=source),) + tuple(
            analyse_expression(item, source=source) for item in expression.values
        )
        return _combine(
            children,
            resolved_type="boolean",
            null_sensitive=True,
            may_return_null=any(child.may_return_null for child in children),
        )
    if isinstance(expression, IsNull):
        child = analyse_expression(expression.field, source=source)
        return _combine((child,), resolved_type="boolean", may_return_null=False)
    if isinstance(expression, TextPredicate):
        field = analyse_expression(expression.field, source=source)
        value = analyse_expression(expression.value, source=source)
        return _combine(
            (field, value),
            resolved_type="boolean",
            null_sensitive=True,
            may_return_null=field.may_return_null or value.may_return_null,
        )
    if isinstance(expression, ScalarIsNull):
        child = analyse_expression(expression.expression, source=source)
        return _combine((child,), resolved_type="boolean", may_return_null=False)
    if isinstance(expression, ScalarMember):
        value = analyse_expression(expression.value, source=source)
        combined = _combine(
            (value,),
            resolved_type=expression.kind,
            null_sensitive=True,
            may_return_null=bool(expression.resolved_type is None or expression.resolved_type.nullable),
        )
        requirement = _structured_member_requirement(expression)
        if requirement is None:
            return combined
        member_requirements = tuple(
            item
            for item in combined.member_requirements
            if not (
                item.field == requirement.field
                and item.index == requirement.index
                and item.indexed == requirement.indexed
                and len(item.members) < len(requirement.members)
                and requirement.members[: len(item.members)] == item.members
            )
        )
        return replace(
            combined,
            member_requirements=member_requirements + (requirement,),
            whole_fields=combined.whole_fields - {requirement.field},
        )
    if isinstance(expression, ScalarIndex):
        collection = analyse_expression(expression.collection, source=source)
        index = analyse_expression(expression.index, source=source)
        combined = _combine(
            (collection, index),
            resolved_type=expression.kind,
            null_sensitive=True,
            may_return_null=True,
        )
        if isinstance(expression.collection, Field):
            indexed_value = _constant_nonnegative_integer(expression.index) if index.constant else None
            field_name = expression.collection.name.casefold()
            requirement = IndexedFieldRequirement(field_name, indexed_value)
            return replace(
                combined,
                indexed_requirements=combined.indexed_requirements + (requirement,),
                whole_fields=combined.whole_fields - {field_name},
            )
        return combined
    if isinstance(expression, ScalarFunction):
        children = tuple(analyse_expression(arg, source=source) for arg in expression.args)
        if expression.name == "RANDOM":
            # RANDOM(seed) is reproducible for a stable row identity, but neither seeded
            # nor unseeded RANDOM is a constant expression because both depend on the row.
            deterministic = bool(expression.args) and all(child.deterministic for child in children)
            return _combine(
                children,
                resolved_type=expression.kind,
                constant=False,
                deterministic=deterministic,
                null_sensitive=False,
                may_return_null=False,
                earliest_stage=STAGE_ENUMERATION,
                metadata_depth=METADATA_ENUMERATION,
            )
        if expression.name == "COALESCE":
            # COALESCE consumes NULL deliberately rather than propagating it.  It can
            # still return NULL when every argument may be NULL.
            may_null = bool(children) and all(child.may_return_null for child in children)
            return _combine(
                children,
                resolved_type=expression.kind,
                may_return_null=may_null,
            )
        if expression.name == "NULLIF":
            return _combine(children, resolved_type=expression.kind, null_sensitive=True, may_return_null=True)
        return _combine(children, resolved_type=expression.kind, null_sensitive=True)
    if isinstance(expression, AggregateFunction):
        children = tuple(analyse_expression(arg, source=source) for arg in expression.args)
        if expression.filter_predicate is not None:
            children += (analyse_expression(expression.filter_predicate, source=source),)
        return _combine(
            children,
            resolved_type=expression.kind,
            constant=False,
            null_sensitive=True,
            may_return_null=expression.name != "COUNT",
            requires_group_context=True,
            earliest_stage=STAGE_GROUP,
        )
    if isinstance(expression, ScalarCase):
        children: list[ExpressionProperties] = []
        for branch in expression.whens:
            children.append(analyse_expression(branch.condition, source=source))
            children.append(analyse_expression(branch.result, source=source))
        if expression.else_result is not None:
            children.append(analyse_expression(expression.else_result, source=source))
        result_children = tuple(children)
        return _combine(
            result_children,
            resolved_type=expression.kind,
            null_sensitive=True,
            may_return_null=expression.else_result is None or any(child.may_return_null for child in result_children),
        )
    # Unknown expression nodes are treated conservatively.  Resolved production queries
    # should not reach this branch, but returning a safe property record keeps analysis
    # robust for future syntax while preventing premature acquisition decisions.
    return ExpressionProperties(
        frozenset(),
        None,
        False,
        False,
        True,
        True,
        False,
        STAGE_DETAILED,
        METADATA_DETAILED,
        False,
    )


def _fields_in_predicate(node: Any) -> set[str]:
    return set(analyse_expression(node).required_fields)


def _fields_in_scalar(expression: Any) -> set[str]:
    return set(analyse_expression(expression).required_fields)


def _fields_in_having(node: Any) -> set[str]:
    return set(analyse_expression(node).required_fields)


def _required_body_fields(query: Query) -> set[str]:
    fields = _fields_in_predicate(query.predicate)
    for term in query.order_by:
        fields.update(_fields_in_scalar(term.expression) if term.expression is not None else {term.field.casefold()})
    for term in query.select or ():
        fields.update(_fields_in_scalar(term.expression) if term.expression is not None else {term.field.casefold()})
    for expression in query.group_by:
        fields.update(_fields_in_scalar(expression))
    fields.update(_fields_in_having(query.having))
    if not query.select:
        fields.add("id")
    return fields


def required_query_fields(query: Query) -> set[str]:
    """Return physical-source fields needed by a query, CTEs and UNION branches."""
    cte_names = {cte.name.casefold() for cte in query.ctes}
    fields: set[str] = set()

    def visit(candidate: Query) -> None:
        if (candidate.from_source or "").casefold() not in cte_names:
            fields.update(_required_body_fields(candidate))
        for operation in candidate.set_operations:
            visit(operation.query)

    for cte in query.ctes:
        visit(cte.query)
    visit(query)
    return fields


def _query_expressions(query: Query) -> tuple[Any, ...]:
    expressions: list[Any] = [query.predicate, query.having]
    expressions.extend(query.group_by)
    expressions.extend(term.expression for term in query.select if term.expression is not None)
    expressions.extend(term.expression for term in query.order_by if term.expression is not None)
    for cte in query.ctes:
        expressions.extend(_query_expressions(cte.query))
    for operation in query.set_operations:
        expressions.extend(_query_expressions(operation.query))
    return tuple(expression for expression in expressions if expression is not None)


def _cardinality_effects(query: Query, requires_aggregation: bool) -> tuple[str, ...]:
    effects: list[str] = []
    if query.predicate is not None:
        effects.append("filter")
    if requires_aggregation:
        effects.append("aggregate")
    if query.distinct:
        effects.append("distinct")
    if query.set_operations:
        effects.append("set-operation")
    if query.offset:
        effects.append("offset")
    if query.limit is not None:
        effects.append("limit")
    return tuple(effects)


def analyse_query(query: Query, *, source: SourceSpec | None = None) -> QueryProperties:
    """Derive semantic properties without performing source acquisition."""
    fields = required_query_fields(query)
    dynamic = tuple(
        sorted(
            field for field in fields if field.casefold() not in KNOWN_FIELD_TYPES and field.casefold() not in ALIASES
        )
    )
    aggregate = bool(
        query.group_by
        or query.having is not None
        or any(_contains_aggregate(term.expression) for term in query.select + query.order_by)
    )
    expression_properties = tuple(
        analyse_expression(expression, source=source) for expression in _query_expressions(query)
    )
    deterministic = all(item.deterministic for item in expression_properties)
    predicate_properties = analyse_expression(query.predicate, source=source)

    select_terms = query.select or ()
    output_types = tuple(
        analyse_expression(term.expression, source=source).resolved_type if term.expression is not None else term.kind
        for term in select_terms
    )
    order_fields = frozenset(
        field
        for term in query.order_by
        for field in (
            analyse_expression(term.expression, source=source).required_fields
            if term.expression is not None
            else frozenset({term.field.casefold()})
        )
    )

    metadata_depth = _max_metadata(*(item.metadata_depth for item in expression_properties))
    field_depths = tuple(
        (
            METADATA_ENUMERATION
            if (
                selected_facet_capabilities(source).field(field) if source is not None else field_capability(field)
            ).ytdlp_flat
            == EXACT
            else METADATA_DETAILED
        )
        for field in fields
    )
    metadata_depth = _max_metadata(metadata_depth, *field_depths)
    dependencies = tuple(SourceDependency(name, facet) for name, facet in query_physical_source_requests(query))
    # Even COUNT(*) and row-dependent functions require the source relation to be
    # enumerated although they may not require a named metadata field.
    if dependencies:
        metadata_depth = _max_metadata(metadata_depth, METADATA_ENUMERATION)

    complete = bool(aggregate or query.distinct or query.order_by or query.ctes or query.set_operations)

    indexed_requirements = tuple(
        dict.fromkeys(requirement for item in expression_properties for requirement in item.indexed_requirements)
    )
    member_requirements = tuple(
        dict.fromkeys(requirement for item in expression_properties for requirement in item.member_requirements)
    )
    whole_fields = frozenset().union(*(item.whole_fields for item in expression_properties))

    return QueryProperties(
        required_fields=frozenset(fields),
        dynamic_fields=dynamic,
        requires_aggregation=aggregate,
        source=source,
        source_dependencies=dependencies,
        resolved_output_types=output_types,
        deterministic=deterministic,
        has_volatile_expressions=not deterministic,
        null_sensitive=any(item.null_sensitive for item in expression_properties),
        cardinality_effects=_cardinality_effects(query, aggregate),
        ordering_required=bool(query.order_by),
        required_order_fields=order_fields,
        grouping_dependent=aggregate,
        metadata_depth=metadata_depth,
        predicate_stage=predicate_properties.earliest_stage,
        predicate_decidable_from_enumeration=predicate_properties.decidable_from_enumeration,
        requires_complete_acquisition=complete,
        indexed_requirements=indexed_requirements,
        member_requirements=member_requirements,
        whole_fields=whole_fields,
    )
