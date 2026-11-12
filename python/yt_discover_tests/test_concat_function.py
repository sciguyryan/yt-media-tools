"""Text concatenation coverage for yt-sql CONCAT()."""

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


def test_concat_constant_folds() -> None:
    records, resolved = _resolve("SELECT CONCAT('a', ' # ', 'b') AS value FROM @yt_sql_fixture LIMIT 1")
    optimised = optimise_query(resolved)
    assert apply_query(records, optimised.query) == apply_query(records, resolved)
    assert optimised.query.select[0].field == "'a # b'"
    assert any(decision.rule == "fold-constant-function" for decision in optimised.decisions)
