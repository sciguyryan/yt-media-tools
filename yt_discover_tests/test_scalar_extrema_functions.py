"""Coverage for NULLIF(), GREATEST() and LEAST()."""

from __future__ import annotations

from datetime import datetime

import pytest

from yt_discover_tests.conformance.generate_dataset import GENERATED_AT, PROFILE_SIZES, build_records
from yt_media_tools.dates import DateContext
from yt_media_tools.metadata import normalise_record
from yt_media_tools.optimizer import optimise_query
from yt_media_tools.query import QuerySyntaxError, apply_query, canonical_record_value, parse_query, resolve_query
from yt_media_tools.schema import QuerySchema


def _records() -> list[dict[str, object]]:
    records = []
    for source_index, raw in enumerate(build_records(PROFILE_SIZES["small"]), start=1):
        record = normalise_record(dict(raw))
        record["source_index"] = source_index
        records.append(record)
    return records


def _resolve(query: str):
    records = _records()
    resolved = resolve_query(
        parse_query(query),
        QuerySchema(records),
        DateContext(date_order="dmy", now=datetime.fromisoformat(GENERATED_AT)),
    )
    return records, resolved


def _project(query: str) -> object:
    records, resolved = _resolve(query)
    row = apply_query(records, resolved)[0]
    return canonical_record_value(row, resolved.select[0])


def test_nullif_only_nulls_on_true_equality() -> None:
    assert _project("SELECT NULLIF('same','same') AS value FROM @yt_sql_fixture LIMIT 1") is None
    assert _project("SELECT NULLIF('same','different') AS value FROM @yt_sql_fixture LIMIT 1") == "same"
    assert _project("SELECT NULLIF('same',NULL) AS value FROM @yt_sql_fixture LIMIT 1") == "same"
    assert _project("SELECT NULLIF(NULL,'same') AS value FROM @yt_sql_fixture LIMIT 1") is None


def test_nullif_is_unicode_normalisation_sensitive() -> None:
    assert _project("SELECT NULLIF('é','é') AS value FROM @yt_sql_fixture LIMIT 1") == "é"
    assert _project("SELECT NULLIF('é','é') AS value FROM @yt_sql_fixture LIMIT 1") is None


def test_greatest_and_least_numeric_values() -> None:
    assert _project("SELECT GREATEST(10, 0x20, 0b11) AS value FROM @yt_sql_fixture LIMIT 1") == 32
    assert _project("SELECT LEAST(10, 0x20, 0b11) AS value FROM @yt_sql_fixture LIMIT 1") == 3


def test_greatest_and_least_use_exact_unicode_ordering() -> None:
    values = ("é", "e\u0301", "ß")
    assert _project("SELECT GREATEST('é','é','ß') AS value FROM @yt_sql_fixture LIMIT 1") == max(values)
    assert _project("SELECT LEAST('é','é','ß') AS value FROM @yt_sql_fixture LIMIT 1") == min(values)


@pytest.mark.parametrize("name", ("GREATEST", "LEAST"))
def test_extrema_null_propagates(name: str) -> None:
    assert _project(f"SELECT {name}(1,NULL,3) AS value FROM @yt_sql_fixture LIMIT 1") is None


@pytest.mark.parametrize(
    ("query", "message"),
    (
        ("SELECT NULLIF(1) FROM @yt_sql_fixture", "NULLIF requires exactly two arguments"),
        ("SELECT NULLIF(1,2,3) FROM @yt_sql_fixture", "NULLIF requires exactly two arguments"),
        ("SELECT GREATEST(1) FROM @yt_sql_fixture", "GREATEST requires at least two arguments"),
        ("SELECT LEAST(1) FROM @yt_sql_fixture", "LEAST requires at least two arguments"),
        ("SELECT GREATEST(1,'x') FROM @yt_sql_fixture", "compatible types"),
        ("SELECT LEAST('x',1) FROM @yt_sql_fixture", "compatible types"),
        ("SELECT NULLIF(1,'1') FROM @yt_sql_fixture", "compatible types"),
    ),
)
def test_new_scalar_functions_reject_invalid_arity_or_types(query: str, message: str) -> None:
    with pytest.raises(QuerySyntaxError, match=message):
        _resolve(query)


def test_field_dependent_extrema_and_nullif_work_in_projection_and_ordering() -> None:
    records, resolved = _resolve(
        "SELECT id, NULLIF(title, 'Duplicate') AS cleaned, GREATEST(view_count, 0) AS views "
        "FROM @yt_sql_fixture ORDER BY LEAST(duration, 3600) DESC, id LIMIT 12"
    )
    selected = apply_query(records, resolved)
    assert selected
    for row in selected:
        assert canonical_record_value(row, resolved.select[1]) is None or isinstance(
            canonical_record_value(row, resolved.select[1]), str
        )
        views = canonical_record_value(row, resolved.select[2])
        assert views is None or views >= 0


def test_new_scalar_functions_constant_fold() -> None:
    records, resolved = _resolve(
        "SELECT NULLIF(1,1) AS n, GREATEST(1,2,3) AS hi, LEAST('β','α') AS lo "
        "FROM @yt_sql_fixture ORDER BY GREATEST(1,2) LIMIT 1"
    )
    optimised = optimise_query(resolved)
    assert apply_query(records, optimised.query) == apply_query(records, resolved)
    assert [term.field for term in optimised.query.select] == ["NULL", "3", "'α'"]
    assert optimised.query.order_by[0].field == "2"
    assert sum(decision.rule == "fold-constant-function" for decision in optimised.decisions) >= 4
