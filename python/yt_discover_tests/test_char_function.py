"""Unicode code-point construction coverage for yt-sql CHAR()."""

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
    parsed = parse_query(query)
    resolved = resolve_query(
        parsed,
        QuerySchema(records),
        DateContext(date_order="dmy", now=datetime.fromisoformat(GENERATED_AT)),
    )
    return records, resolved


def test_char_constant_folding_is_observationally_equivalent() -> None:
    records, resolved = _resolve(
        "SELECT CHAR(65, 946, 128512) AS value FROM @yt_sql_fixture ORDER BY CHAR(66 - 1) LIMIT 1"
    )
    result = optimise_query(resolved)
    assert apply_query(records, result.query) == apply_query(records, resolved)
    assert result.query.select[0].field == "'Aβ😀'"
    assert result.query.order_by[0].field == "'A'"
    assert any(decision.rule == "fold-constant-function" for decision in result.decisions)
