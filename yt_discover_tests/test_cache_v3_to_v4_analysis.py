"""Historical v3-to-v4 mapping and composition-aware preflight tests."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sqlite3

from yt_media_tools.cache_v3_to_v4_analysis import analyse_v3_composition, estimate_v4_space


FIXTURE = Path(__file__).parent / "fixtures" / "cache_v3" / "canonical-valid-v3.sqlite3"


def test_composition_accounts_for_source_state_and_surviving_raw_material(tmp_path: Path) -> None:
    source = tmp_path / "v3.sqlite3"
    shutil.copy2(FIXTURE, source)
    composition = analyse_v3_composition(source)
    assert composition.metadata_records > 0
    assert composition.distinct_media > 0
    assert composition.source_observations > 0
    assert composition.source_entries > 0
    assert composition.raw_json_bytes > 0
    assert 0 <= composition.compatibility_json_bytes < composition.raw_json_bytes


def test_estimate_is_explainable_sum_of_schema_data_and_index_reserve(tmp_path: Path) -> None:
    source = tmp_path / "v3.sqlite3"
    shutil.copy2(FIXTURE, source)
    estimate = estimate_v4_space(source)
    assert estimate.fixed_schema_bytes > 0
    assert estimate.migrated_data_bytes > 0
    assert estimate.index_and_page_reserve_bytes > 0
    assert estimate.required_bytes == (
        estimate.fixed_schema_bytes + estimate.migrated_data_bytes + estimate.index_and_page_reserve_bytes
    )


def test_similarly_sized_v3_files_can_have_different_v4_estimates(tmp_path: Path) -> None:
    first = tmp_path / "first.sqlite3"
    second = tmp_path / "second.sqlite3"
    shutil.copy2(FIXTURE, first)
    shutil.copy2(FIXTURE, second)

    connection = sqlite3.connect(second)
    try:
        source_url, video_id, raw_json = connection.execute(
            "SELECT source_url, video_id, raw_json FROM metadata_records ORDER BY source_url, video_id LIMIT 1"
        ).fetchone()
        record = json.loads(raw_json)
        # Inflate material that v4 deliberately discards rather than compatibility material.
        record["_yt_sql_transient_padding"] = "x" * 12000
        with connection:
            connection.execute(
                "UPDATE metadata_records SET raw_json=? WHERE source_url=? AND video_id=?",
                (json.dumps(record), source_url, video_id),
            )
    finally:
        connection.close()

    # SQLite page allocation makes the physical files comparable but not necessarily byte-identical.
    assert abs(first.stat().st_size - second.stat().st_size) < 32768
    first_estimate = estimate_v4_space(first)
    second_estimate = estimate_v4_space(second)
    assert second_estimate.composition.raw_json_bytes > first_estimate.composition.raw_json_bytes
    assert second_estimate.composition.compatibility_json_bytes == first_estimate.composition.compatibility_json_bytes
    # Discarded internal raw material must not inflate the expected durable v4 representation.
    assert second_estimate.required_bytes == first_estimate.required_bytes
