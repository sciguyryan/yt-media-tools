"""Unicode semantics and regression coverage for the yt-sql text surface."""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from datetime import datetime


from yt_discover_tests.conformance.generate_dataset import GENERATED_AT
from yt_discover_tests.conformance.test_records import cached_records
from yt_media_tools.dates import DateContext
from yt_media_tools.metadata import normalise_record
from yt_media_tools.optimizer import optimise_query
from yt_media_tools.output import write_records
from yt_media_tools.query import apply_query, parse_query, resolve_query
from yt_media_tools.schema import QuerySchema


def _records() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for source_index, raw in enumerate(cached_records("small"), start=1):
        record = normalise_record(dict(raw))
        record["source_index"] = source_index
        records.append(record)
    return records


def _resolve(query: str):
    records = _records()
    context = DateContext(date_order="dmy", now=datetime.fromisoformat(GENERATED_AT))
    parsed = parse_query(query)
    resolved = resolve_query(parsed, QuerySchema(records), context)
    return records, parsed, resolved


def _ids(query: str) -> list[str]:
    records, _, resolved = _resolve(query)
    return [str(record["id"]) for record in apply_query(records, resolved)]


def test_unicode_scalar_constant_folding_is_observationally_equivalent() -> None:
    records, parsed, original = _resolve(
        "SELECT LOWER('İ') AS lo, UPPER('straße') AS hi, LENGTH('👩‍👩‍👧‍👦') AS n FROM @yt_sql_fixture LIMIT 1"
    )
    optimised = optimise_query(original).query
    assert apply_query(records, original) == apply_query(records, optimised)

    original_stream = io.StringIO()
    with redirect_stdout(original_stream):
        write_records(apply_query(records, original), original, "jsonl", None, explicit_select=bool(parsed.select))
    optimised_stream = io.StringIO()
    with redirect_stdout(optimised_stream):
        write_records(apply_query(records, optimised), optimised, "jsonl", None, explicit_select=bool(parsed.select))
    assert optimised_stream.getvalue() == original_stream.getvalue()
    assert "İ".lower() in original_stream.getvalue()


def test_unicode_jsonl_output_preserves_text_without_ascii_escaping() -> None:
    records, parsed, resolved = _resolve(
        "SELECT id, title FROM @yt_sql_fixture WHERE id IN ('vid040','vid049','vid050','vid051') ORDER BY source_index"
    )
    stream = io.StringIO()
    with redirect_stdout(stream):
        write_records(apply_query(records, resolved), resolved, "jsonl", None, explicit_select=bool(parsed.select))
    text = stream.getvalue()
    assert "😀" in text
    assert "東京" in text
    assert "مرحبا" in text
    assert "שלום" in text
