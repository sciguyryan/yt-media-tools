"""Conservative backwards dependency propagation through non-recursive CTEs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .query_model import Query, SelectTerm
from .query_properties import analyse_expression


@dataclass(frozen=True)
class CteDependency:
    """Physical input requirements proven for one materialised CTE producer."""

    name: str
    required_outputs: frozenset[str]
    retained_outputs: frozenset[str]
    pruned_outputs: frozenset[str]
    input_fields: frozenset[str]
    pruning_applied: bool
    reason: str


@dataclass(frozen=True)
class CteDependencyPlan:
    """Backwards field requirements for all CTEs in declaration order."""

    dependencies: tuple[CteDependency, ...]

    def for_cte(self, name: str) -> CteDependency | None:
        """Return the dependency record for one CTE name."""
        key = name.casefold()
        return next((item for item in self.dependencies if item.name.casefold() == key), None)


def _expression_fields(node: Any) -> set[str]:
    if node is None:
        return set()
    return set(analyse_expression(node).required_fields)


def _select_fields(term: SelectTerm) -> set[str]:
    if term.expression is not None:
        return _expression_fields(term.expression)
    return {term.field.casefold()}


def _non_projection_fields(query: Query) -> set[str]:
    """Return fields required by producer semantics independently of exported columns."""
    fields = _expression_fields(query.predicate)
    fields.update(_expression_fields(query.having))
    for expression in query.group_by:
        fields.update(_expression_fields(expression))

    aliases = {term.output_name.casefold(): term for term in query.select}
    for term in query.order_by:
        if term.expression is not None:
            if getattr(term.expression, "name", "").casefold() in aliases:
                fields.update(_select_fields(aliases[term.expression.name.casefold()]))
            else:
                fields.update(_expression_fields(term.expression))
        elif term.field.casefold() in aliases:
            fields.update(_select_fields(aliases[term.field.casefold()]))
        else:
            fields.add(term.field.casefold())
    return fields


def _query_relation_references(query: Query, relation: str) -> set[str]:
    """Return output fields consumed from one logical relation by this composed query."""
    key = relation.casefold()
    fields: set[str] = set()

    def visit(candidate: Query) -> None:
        if (candidate.from_source or "").casefold() == key:
            fields.update(_non_projection_fields(candidate))
            for term in candidate.select:
                fields.update(_select_fields(term))
            if not candidate.select:
                fields.add("id")
        for operation in candidate.set_operations:
            visit(operation.query)

    visit(query)
    return fields


def _contains_volatile_projection(query: Query) -> bool:
    return any(
        term.expression is not None and not analyse_expression(term.expression).deterministic for term in query.select
    )


def _producer_input_fields(
    query: Query,
    required_outputs: frozenset[str],
) -> tuple[frozenset[str], frozenset[str], frozenset[str], bool, str]:
    """Return fields required from a CTE producer's input relation.

    Projection pruning is intentionally refused across DISTINCT and set composition because
    changing exported columns there can change row identity or positional reconciliation.
    The query tree itself is not rewritten, so volatile output expressions keep their normal
    materialisation/evaluation count.
    """
    outputs = {term.output_name.casefold(): term for term in query.select}
    all_outputs = frozenset(outputs)

    if query.distinct:
        fields = _non_projection_fields(query)
        for term in query.select:
            fields.update(_select_fields(term))
        return (
            frozenset(fields),
            all_outputs,
            frozenset(),
            False,
            "DISTINCT makes producer projection part of row identity",
        )

    if query.set_operations:
        # Positional UNION reconciliation makes branch-wise projection trimming a separate proof problem.
        fields = _non_projection_fields(query)
        for term in query.select:
            fields.update(_select_fields(term))
        for operation in query.set_operations:
            fields.update(_non_projection_fields(operation.query))
            for term in operation.query.select:
                fields.update(_select_fields(term))
        return (
            frozenset(fields),
            all_outputs,
            frozenset(),
            False,
            "UNION projection is preserved until positional branch propagation is proven",
        )

    unknown = required_outputs - all_outputs
    if unknown:
        fields = _non_projection_fields(query)
        for term in query.select:
            fields.update(_select_fields(term))
        return (
            frozenset(fields),
            all_outputs,
            frozenset(),
            False,
            "consumer requirements include an output not exported by the producer",
        )

    retained = set(required_outputs)
    for term in query.select:
        if term.expression is not None and not analyse_expression(term.expression).deterministic:
            retained.add(term.output_name.casefold())

    fields = _non_projection_fields(query)
    for name in retained:
        term = outputs.get(name)
        if term is not None:
            fields.update(_select_fields(term))

    pruned = all_outputs - retained
    if pruned:
        reason = "unused deterministic CTE outputs do not contribute physical metadata requirements"
    elif _contains_volatile_projection(query):
        reason = "volatile CTE outputs are retained to preserve materialisation evaluation count"
    else:
        reason = "all exported CTE outputs are required by downstream consumers"
    return frozenset(fields), frozenset(retained), frozenset(pruned), True, reason


def plan_cte_dependencies(query: Query) -> CteDependencyPlan:
    """Propagate downstream output requirements backwards through earlier CTE producers."""
    if not query.ctes:
        return CteDependencyPlan(())

    names = [cte.name.casefold() for cte in query.ctes]
    required: dict[str, set[str]] = {name: set() for name in names}

    # Main query consumption seeds the backwards walk.
    for cte in query.ctes:
        required[cte.name.casefold()].update(_query_relation_references(query, cte.name))

    planned: dict[str, CteDependency] = {}
    # CTEs may reference only earlier CTEs, so a reverse walk propagates requirements transitively.
    for cte in reversed(query.ctes):
        key = cte.name.casefold()
        needed = frozenset(required[key])
        input_fields, retained, pruned, applied, reason = _producer_input_fields(cte.query, needed)
        planned[key] = CteDependency(cte.name, needed, retained, pruned, input_fields, applied, reason)

        source_name = (cte.query.from_source or "").casefold()
        if source_name in required:
            required[source_name].update(input_fields)

    return CteDependencyPlan(tuple(planned[name] for name in names))
