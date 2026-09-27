"""Deterministic coverage for the Discover 0.28 semantic property framework."""

from yt_media_tools.dates import DateContext
from yt_media_tools.query import QuerySchema, parse_query, resolve_query
from yt_media_tools.query_properties import (
    KNOWN_VALUE,
    METADATA_DETAILED,
    METADATA_ENUMERATION,
    METADATA_NONE,
    NOT_ACQUIRED,
    SQL_NULL,
    STAGE_CONSTANT,
    STAGE_DETAILED,
    STAGE_ENUMERATION,
    STAGE_GROUP,
    STRUCTURALLY_UNAVAILABLE,
    analyse_expression,
    analyse_query,
    knowledge_from_capability,
    known_value,
    not_acquired,
    sql_null,
    structurally_unavailable,
)
from yt_media_tools.source_capabilities import (
    STRUCTURALLY_UNSUPPORTED,
    FieldCapability,
    field_capability,
)


def _resolved(source: str, records: list[dict] | None = None):
    rows = records or [{"id": "a", "title": "Alpha", "view_count": 20}]
    return resolve_query(parse_query(source), QuerySchema(rows), DateContext())


def test_knowledge_states_keep_unacquired_metadata_distinct_from_sql_null() -> None:
    known = known_value(7)
    null = sql_null()
    unavailable = structurally_unavailable()
    pending = not_acquired()

    assert known.state == KNOWN_VALUE
    assert known.logically_known and not known.logically_null
    assert null.state == SQL_NULL
    assert null.logically_known and null.logically_null
    assert unavailable.state == STRUCTURALLY_UNAVAILABLE
    assert unavailable.logically_known and unavailable.logically_null
    assert pending.state == NOT_ACQUIRED
    assert not pending.logically_known and not pending.logically_null


def test_capability_knowledge_requires_explicit_structural_unavailability() -> None:
    supported = field_capability("title")
    assert knowledge_from_capability(supported).state == NOT_ACQUIRED
    assert knowledge_from_capability(supported, acquired=True, value=None).state == SQL_NULL
    assert knowledge_from_capability(supported, acquired=True, value="x").state == KNOWN_VALUE

    unsupported = FieldCapability(
        "synthetic",
        "unavailable",
        "unavailable",
        structural_support=STRUCTURALLY_UNSUPPORTED,
    )
    assert knowledge_from_capability(unsupported).state == STRUCTURALLY_UNAVAILABLE


def test_constant_expression_requires_no_metadata() -> None:
    query = _resolved("SELECT (1 + 2) * 3 AS value FROM @x")
    properties = analyse_expression(query.select[0].expression)
    assert properties.resolved_type in {"integer", "number"}
    assert properties.constant
    assert properties.deterministic
    assert properties.required_fields == frozenset()
    assert properties.earliest_stage == STAGE_CONSTANT
    assert properties.metadata_depth == METADATA_NONE
    assert properties.decidable_from_enumeration


def test_enumeration_field_expression_records_type_null_and_stage() -> None:
    query = _resolved("SELECT LOWER(title) AS value FROM @x")
    properties = analyse_expression(query.select[0].expression)
    assert properties.resolved_type == "string"
    assert properties.required_fields == frozenset({"title"})
    assert not properties.constant
    assert properties.deterministic
    assert properties.null_sensitive
    assert properties.earliest_stage == STAGE_ENUMERATION
    assert properties.metadata_depth == METADATA_ENUMERATION
    assert properties.decidable_from_enumeration


def test_approximate_enumeration_metadata_is_not_treated_as_authoritative() -> None:
    query = _resolved("SELECT id FROM @x WHERE view_count >= 10")
    predicate = analyse_expression(query.predicate)
    properties = analyse_query(query)

    assert predicate.required_fields == frozenset({"view_count"})
    assert predicate.earliest_stage == STAGE_DETAILED
    assert predicate.metadata_depth == METADATA_DETAILED
    assert not predicate.decidable_from_enumeration
    assert properties.metadata_depth == METADATA_DETAILED


def test_dynamic_metadata_requires_detailed_acquisition() -> None:
    query = _resolved(
        "SELECT description FROM @x WHERE description LIKE 'Alpha%'",
        [{"id": "a", "description": "Alpha description"}],
    )
    properties = analyse_query(query)
    assert properties.dynamic_fields == ("description",)
    assert properties.metadata_depth == METADATA_DETAILED
    assert properties.predicate_stage == STAGE_DETAILED
    assert not properties.predicate_decidable_from_enumeration


def test_seeded_random_is_reproducible_but_row_dependent() -> None:
    seeded = _resolved("SELECT RANDOM(31415926) AS value FROM @x")
    volatile = _resolved("SELECT RANDOM() AS value FROM @x")

    seeded_expression = analyse_expression(seeded.select[0].expression)
    volatile_expression = analyse_expression(volatile.select[0].expression)
    seeded_query = analyse_query(seeded)
    volatile_query = analyse_query(volatile)

    assert not seeded_expression.constant
    assert seeded_expression.deterministic
    assert seeded_expression.earliest_stage == STAGE_ENUMERATION
    assert seeded_expression.metadata_depth == METADATA_ENUMERATION
    assert seeded_query.deterministic
    assert not seeded_query.has_volatile_expressions

    assert not volatile_expression.constant
    assert not volatile_expression.deterministic
    assert not volatile_query.deterministic
    assert volatile_query.has_volatile_expressions


def test_aggregate_properties_require_group_context_and_complete_acquisition() -> None:
    query = _resolved("SELECT COUNT(*) AS count FROM @x HAVING COUNT(*) >= 1")
    aggregate = analyse_expression(query.select[0].expression)
    properties = analyse_query(query)

    assert aggregate.requires_group_context
    assert aggregate.earliest_stage == STAGE_GROUP
    assert aggregate.resolved_type == "integer"
    assert properties.requires_aggregation
    assert properties.grouping_dependent
    assert properties.requires_complete_acquisition
    assert properties.metadata_depth == METADATA_ENUMERATION
    assert "aggregate" in properties.cardinality_effects


def test_query_properties_record_sources_ordering_and_cardinality_effects() -> None:
    query = _resolved(
        "SELECT DISTINCT title FROM @alpha WHERE view_count >= 10 "
        "UNION ALL SELECT title FROM @beta ORDER BY title LIMIT 3 OFFSET 1"
    )
    properties = analyse_query(query)

    assert tuple((item.source, item.facet) for item in properties.source_dependencies) == (
        ("@alpha", None),
        ("@beta", None),
    )
    assert properties.ordering_required
    assert properties.required_order_fields == frozenset({"title"})
    assert properties.requires_complete_acquisition
    assert properties.cardinality_effects == (
        "filter",
        "distinct",
        "set-operation",
        "offset",
        "limit",
    )
