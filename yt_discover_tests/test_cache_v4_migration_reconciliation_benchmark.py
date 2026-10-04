from __future__ import annotations

import importlib.util
from pathlib import Path
import sqlite3
import sys


SCRIPT = Path(__file__).parents[1] / "benchmarks" / "cache_v4_migration_reconciliation.py"
SPEC = importlib.util.spec_from_file_location("cache_v4_migration_reconciliation", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_v3_shape_is_deterministic_and_preserves_historical_fixture_contract(tmp_path: Path) -> None:
    first = tmp_path / "first.sqlite3"
    second = tmp_path / "second.sqlite3"
    MODULE.build_v3_shape(first, 12)
    MODULE.build_v3_shape(second, 12)

    def rows(path: Path) -> list[tuple[str, str, str, str]]:
        connection = sqlite3.connect(path)
        try:
            return connection.execute(
                "SELECT source_url, video_id, fetched_at, raw_json FROM metadata_records ORDER BY source_url, video_id"
            ).fetchall()
        finally:
            connection.close()

    assert rows(first) == rows(second)
    assert len(rows(first)) == 18


def test_real_migration_benchmark_measures_preflight_churn_and_compaction(tmp_path: Path) -> None:
    result = MODULE.run_benchmark("test", 20, tmp_path)

    assert result.source_sha256_before == result.source_sha256_after
    assert result.preflight_required_bytes > 0
    assert result.migration_seconds > 0
    assert result.peak_observed_file_bytes >= result.before_compaction.file_bytes
    assert result.before_compaction.page_count >= result.before_compaction.freelist_pages
    assert result.after_compaction.freelist_pages == 0
    assert result.after_compaction.file_bytes <= result.before_compaction.file_bytes
    assert result.preflight_to_peak_ratio > 0
    assert result.preflight_to_final_ratio > 0
    assert result.phase_seconds
