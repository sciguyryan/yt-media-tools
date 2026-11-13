"""Constant-folding coverage for the retained NULLIF(), GREATEST() and LEAST() optimiser path."""

from __future__ import annotations

from datetime import datetime

from yt_discover_tests.conformance.generate_dataset import GENERATED_AT
from yt_discover_tests.conformance.test_records import cached_records
from yt_media_tools.dates import DateContext
from yt_media_tools.metadata import normalise_record
from yt_media_tools.optimizer import optimise_query
from yt_media_tools.query import apply_query, parse_query, resolve_query
from yt_media_tools.schema import QuerySchema


def _records() -> list[dict[str, object]]:
    records = []
    for source_index, raw in enumerate(cached_records("small"), start=1):
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
