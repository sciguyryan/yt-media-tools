"""JOIN Phase 4 predicate resolution and validation coverage."""

import pytest

from yt_media_tools.query import QuerySemanticError, RelationField, parse_query, resolve_join_references, resolve_query
from yt_media_tools.schema import QuerySchema


def _schema(record: dict[str, object]) -> QuerySchema:
    return QuerySchema([record])


def _schemas() -> tuple[QuerySchema, dict[tuple[str, str | None], QuerySchema]]:
    left = _schema({"id": "left", "left_only": 1})
    middle = _schema({"id": "middle", "middle_only": 2})
    right = _schema({"id": "right", "right_only": 3})
    return left, {("@left", None): left, ("@middle", None): middle, ("@right", None): right}


def test_join_predicate_resolves_visible_relation_fields() -> None:
    left, schemas = _schemas()
    query = parse_query("SELECT l.id FROM @left AS l JOIN @right AS r ON l.id = r.id")
    resolved = resolve_join_references(query, left, source_schemas=schemas)
    predicate = resolved.joins[0].predicate
    assert isinstance(predicate.left, RelationField)
    assert isinstance(predicate.right, RelationField)
    assert predicate.left.qualifier == "l"
    assert predicate.right.qualifier == "r"


def test_join_predicate_can_reference_previously_joined_relation() -> None:
    left, schemas = _schemas()
    query = parse_query("SELECT l.id FROM @left AS l JOIN @middle AS m ON l.id = m.id JOIN @right AS r ON m.id = r.id")
    resolved = resolve_join_references(query, left, source_schemas=schemas)
    assert resolved.joins[1].predicate.left.qualifier == "m"
    assert resolved.joins[1].predicate.right.qualifier == "r"


def test_join_predicate_cannot_reference_later_relation() -> None:
    left, schemas = _schemas()
    query = parse_query("SELECT l.id FROM @left AS l JOIN @middle AS m ON l.id = r.id JOIN @right AS r ON m.id = r.id")
    with pytest.raises(QuerySemanticError, match="Unknown relation alias 'r'"):
        resolve_join_references(query, left, source_schemas=schemas)


def test_join_predicate_rejects_ambiguous_unqualified_field() -> None:
    left, schemas = _schemas()
    query = parse_query("SELECT l.id FROM @left AS l JOIN @right AS r ON id = r.id")
    with pytest.raises(QuerySemanticError, match="Ambiguous field 'id'"):
        resolve_join_references(query, left, source_schemas=schemas)


def test_join_predicate_rejects_aggregate_function() -> None:
    left, schemas = _schemas()
    query = parse_query("SELECT l.id FROM @left AS l JOIN @right AS r ON COUNT(r.id) = 1")
    with pytest.raises(QuerySemanticError, match="Aggregate functions are not allowed in JOIN ON predicates"):
        resolve_join_references(query, left, source_schemas=schemas)


def test_join_predicate_rejects_random() -> None:
    left, schemas = _schemas()
    query = parse_query("SELECT l.id FROM @left AS l JOIN @right AS r ON RANDOM() > 0")
    with pytest.raises(QuerySemanticError, match="RANDOM is not allowed in JOIN ON predicates"):
        resolve_join_references(query, left, source_schemas=schemas)


def test_validated_left_join_reaches_execution() -> None:
    left, schemas = _schemas()
    query = parse_query("SELECT l.id FROM @left AS l LEFT JOIN @right AS r ON l.id = r.id")
    resolved = resolve_query(query, left, source_schemas=schemas)
    assert resolved.joins[0].kind.value == "LEFT"
