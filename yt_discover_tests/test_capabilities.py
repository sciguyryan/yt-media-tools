from __future__ import annotations

from yt_media_tools.capabilities import (
    APPROXIMATE,
    EXACT,
    UNAVAILABLE,
    field_capability,
    safely_reject_lightweight,
)
from yt_media_tools.dates import DateContext
from yt_media_tools.query import parse_query


def test_field_capability_model_is_conservative() -> None:
    assert field_capability("id").youtubejs == EXACT
    assert field_capability("upload_date").youtubejs == APPROXIMATE
    assert field_capability("duration").youtubejs == UNAVAILABLE
    assert field_capability("raw.unknown").ytdlp_flat == UNAVAILABLE
    assert field_capability("raw.unknown").ytdlp_detailed == EXACT


def test_lightweight_rejection_can_prove_lower_date_failure() -> None:
    query = parse_query("WHERE upload_date >= 2026-04-01")
    record = {
        "id": "old",
        "approximate_upload_date_oldest": "2026-02-20",
        "approximate_upload_date_newest": "2026-03-20",
    }
    assert safely_reject_lightweight(query.predicate, record, DateContext())


def test_lightweight_rejection_can_prove_upper_date_failure() -> None:
    query = parse_query("WHERE upload_date <= 2026-04-30")
    record = {
        "id": "new",
        "approximate_upload_date_oldest": "2026-05-03",
        "approximate_upload_date_newest": "2026-05-20",
    }
    assert safely_reject_lightweight(query.predicate, record, DateContext())


def test_lightweight_rejection_uses_exact_title_predicates() -> None:
    query = parse_query("WHERE title CONTAINS 'Mars' AND upload_date >= 2026-01-01")
    record = {
        "id": "abc",
        "title": "A documentary about Venus",
        "approximate_upload_date_oldest": "2026-06-01",
        "approximate_upload_date_newest": "2026-06-05",
    }
    assert safely_reject_lightweight(query.predicate, record, DateContext())


def test_lightweight_rejection_retains_ambiguous_date_interval() -> None:
    query = parse_query("WHERE upload_date BETWEEN 2026-04-01 AND 2026-04-30")
    record = {
        "id": "boundary",
        "approximate_upload_date_oldest": "2026-03-20",
        "approximate_upload_date_newest": "2026-04-10",
    }
    assert not safely_reject_lightweight(query.predicate, record, DateContext())


def test_or_requires_both_branches_to_be_provably_false() -> None:
    query = parse_query("WHERE title CONTAINS 'Mars' OR duration < 10m")
    record = {"id": "abc", "title": "Venus"}
    # Duration is unavailable, so rejecting on the false title branch would be unsafe.
    assert not safely_reject_lightweight(query.predicate, record, DateContext())
