"""Canonical formatting coverage for the settled temporal grammar."""

from datetime import datetime, timezone

import pytest

from yt_media_tools.dates import DateContext
from yt_media_tools.query import apply_query, format_query, parse_query, resolve_query
from yt_media_tools.schema import QuerySchema


CONTEXT = DateContext(date_order="dmy", now=datetime(2026, 9, 20, 12, 34, 56, tzinfo=timezone.utc))
RECORDS = [
    {
        "id": "fixture",
        "upload_date": "20240131",
        "release_timestamp": datetime(2024, 1, 31, 18, 30, tzinfo=timezone.utc).timestamp(),
        "duration": 3600,
    }
]
SCHEMA = QuerySchema(RECORDS)


def _resolved(text: str):
    return resolve_query(parse_query(text), SCHEMA, CONTEXT)


@pytest.mark.parametrize(
    ("source", "canonical"),
    [
        ("WHERE upload_date >= TODAY() - 1YRS", "SELECT id WHERE upload_date >= TODAY()-1year"),
        ("WHERE upload_date >= TODAY()-2MISOEDD", "SELECT id WHERE upload_date >= TODAY()-2mis"),
        ("WHERE release_timestamp >= NOW() - 24HRS", "SELECT id WHERE release_timestamp >= NOW()-24hour"),
        ("WHERE upload_date >= 2024/1/31", "SELECT id WHERE upload_date >= 2024-01-31"),
        ("WHERE upload_date >= 31.1.2024", "SELECT id WHERE upload_date >= 2024-01-31"),
        ("WHERE upload_date >= 31 January 2024", "SELECT id WHERE upload_date >= 2024-01-31"),
        (
            "WHERE release_timestamp >= 2024-01-31T18:30:00+00:00",
            "SELECT id WHERE release_timestamp >= 2024-01-31T18:30:00Z",
        ),
        ("WHERE duration >= 1hr", "SELECT id WHERE duration >= 3600s"),
        ("WHERE duration >= 60 munudau", "SELECT id WHERE duration >= 3600s"),
    ],
)
def test_resolved_temporal_spellings_have_one_canonical_form(source: str, canonical: str) -> None:
    assert format_query(_resolved(source)) == canonical


def test_temporal_relative_aliases_normalise_before_resolution() -> None:
    assert format_query(parse_query("WHERE upload_date >= TODAY() - 3YRS")) == "WHERE upload_date >= TODAY()-3year"


@pytest.mark.parametrize(
    "source",
    [
        "WHERE upload_date >= TODAY()-1yr",
        "WHERE upload_date >= 31/01/2024",
        "WHERE release_timestamp >= 2024-01-31T18:30:00+00:00",
        "WHERE duration >= 1hr",
    ],
)
def test_temporal_canonicalisation_is_semantically_stable(source: str) -> None:
    first = _resolved(source)
    canonical = format_query(first)
    second = _resolved(canonical)
    assert apply_query(RECORDS, second) == apply_query(RECORDS, first)
    assert format_query(second) == canonical
