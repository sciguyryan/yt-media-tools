"""Characterise existing ordering paths before agreeing a mixed-type policy.

These assertions describe current Python behaviour, not portable YT-SQL semantics.
"""

import pytest

from yt_media_tools.query import apply_query, parse_query, resolve_query
from yt_media_tools.schema import QuerySchema


def _run(sql: str, values: tuple[object, ...]) -> list[dict[str, object]]:
    records = [{"id": f"v{index}", "view_count": value, "_yt_sql_source": "@a"} for index, value in enumerate(values)]
    schema = QuerySchema(records)
    query = resolve_query(parse_query(sql), schema, source_schemas={("@a", None): schema})
    return apply_query(records, query)


ORDINARY = "SELECT id, view_count FROM @a ORDER BY view_count ASC"
GROUPED = "SELECT view_count, COUNT(*) AS n FROM @a GROUP BY view_count ORDER BY view_count ASC"
WRAPPED = "(SELECT id, view_count FROM @a) ORDER BY view_count ASC"
COMPOUND = "SELECT id, view_count FROM @a UNION ALL SELECT id, view_count FROM @a ORDER BY view_count ASC"


@pytest.mark.parametrize("sql", [ORDINARY, GROUPED, WRAPPED, COMPOUND])
def test_homogeneous_numeric_values_sort_numerically(sql: str) -> None:
    rows = _run(sql, (2, 10, 3))
    assert [row["view_count"] for row in rows] == ([2, 2, 3, 3, 10, 10] if sql == COMPOUND else [2, 3, 10])


@pytest.mark.parametrize("sql", [ORDINARY, GROUPED, WRAPPED, COMPOUND])
def test_null_values_sort_last_in_ascending_order(sql: str) -> None:
    rows = _run(sql, (None, 10, 2))
    assert [row["view_count"] for row in rows] == ([2, 2, 10, 10, None, None] if sql == COMPOUND else [2, 10, None])


@pytest.mark.parametrize("sql", [ORDINARY, GROUPED, WRAPPED, COMPOUND])
def test_incompatible_ordering_values_are_rejected_consistently(sql: str) -> None:
    with pytest.raises(TypeError, match="ORDER BY contains values that cannot be compared"):
        _run(sql, (2, 10, "3"))


@pytest.mark.parametrize("sql", [ORDINARY, GROUPED, WRAPPED, COMPOUND])
def test_current_text_order_is_case_and_normalisation_sensitive(sql: str) -> None:
    rows = _run(sql, ("é", "e\u0301", "Z", "a"))
    expected = ["Z", "a", "e\u0301", "é"]
    assert [row["view_count"] for row in rows] == (
        [value for value in expected for _ in range(2)] if sql == COMPOUND else expected
    )


@pytest.mark.parametrize("sql", [ORDINARY, GROUPED, WRAPPED, COMPOUND])
def test_null_values_sort_last_in_descending_order(sql: str) -> None:
    rows = _run(sql.replace("ORDER BY view_count ASC", "ORDER BY view_count DESC"), (None, 10, 2))
    assert [row["view_count"] for row in rows] == ([10, 10, 2, 2, None, None] if sql == COMPOUND else [10, 2, None])
