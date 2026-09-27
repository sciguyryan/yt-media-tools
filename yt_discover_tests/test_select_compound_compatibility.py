import pytest

from yt_media_tools.query_parser import QuerySyntaxError, parse_query


@pytest.mark.parametrize(
    ("source", "clause"),
    (
        ("SELECT id FROM source GROUP BY id WHERE id = 1", "WHERE"),
        ("SELECT id FROM source HAVING COUNT(id) > 0 GROUP BY id", "GROUP BY"),
        ("SELECT id FROM source ORDER BY id WHERE id = 1", "WHERE"),
        ("SELECT id FROM source LIMIT 1 ORDER BY id", "ORDER BY"),
        ("SELECT id FROM source OFFSET 1 LIMIT 1", "LIMIT"),
        ("SELECT id FROM source ORDER BY id ORDER BY id", "ORDER BY"),
        ("SELECT id FROM source LIMIT 1 LIMIT 2", "LIMIT"),
        ("SELECT id FROM source OFFSET 1 OFFSET 2", "OFFSET"),
    ),
)
def test_repeated_or_backwards_clauses_report_clause_order(source: str, clause: str) -> None:
    with pytest.raises(
        QuerySyntaxError, match=rf"{clause} is repeated or appears outside the canonical SELECT clause order"
    ):
        parse_query(source)


def test_completed_compound_tail_remains_valid() -> None:
    query = parse_query("SELECT id FROM left_source UNION ALL SELECT id FROM right_source ORDER BY id LIMIT 2 OFFSET 1")
    assert query.order_by
    assert query.limit == 2
    assert query.offset == 1


def test_grouped_branch_local_tail_remains_valid() -> None:
    query = parse_query("SELECT id FROM left_source UNION ALL (SELECT id FROM right_source ORDER BY id LIMIT 1)")
    assert query.set_operations[0].grouped is True
    assert query.set_operations[0].query.order_by
    assert query.set_operations[0].query.limit == 1


def test_contextual_keyword_identifier_remains_valid() -> None:
    query = parse_query("SELECT limit AS offset FROM source ORDER BY offset")
    assert query.select[0].field == "limit"
    assert query.select[0].alias == "offset"


def test_quoted_clause_keyword_identifier_remains_valid() -> None:
    query = parse_query("SELECT `ORDER` AS `LIMIT` FROM source ORDER BY `LIMIT`")
    assert query.select[0].alias == "LIMIT"
