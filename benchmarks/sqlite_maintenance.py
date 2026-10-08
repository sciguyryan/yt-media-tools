"""Deterministic, disposable SQLite reclamation microbenchmark for #157."""

from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3
import tempfile
from time import perf_counter

from yt_media_tools.database_maintenance import incremental_maintenance, inspect_database, parse_policy


def benchmark(rows: int, page_budget: int) -> dict[str, int | float]:
    with tempfile.TemporaryDirectory(prefix="sqlite-maintenance-") as directory:
        path = Path(directory) / "test.sqlite3"
        with sqlite3.connect(path) as connection:
            connection.execute("PRAGMA auto_vacuum=INCREMENTAL")
            connection.execute("CREATE TABLE payload (value BLOB NOT NULL)")
            connection.executemany("INSERT INTO payload VALUES (?)", [(bytes(1024),)] * rows)
            connection.execute("DELETE FROM payload WHERE rowid > ?", (rows // 10,))
        before = inspect_database(path)
        policy = parse_policy(
            f"schema_version = 1\n[maintenance.incremental]\nmax_pages_per_run = {page_budget}\nmax_duration_seconds = 30\n[databases.collection_state]\nmin_reclaimable_mib = 0\nmin_free_ratio = 0\n"
        )
        start = perf_counter()
        result = incremental_maintenance(path, "collection_state", policy)
        elapsed = perf_counter() - start
        after = inspect_database(path)
        with sqlite3.connect(path) as connection:
            surviving = connection.execute("SELECT COUNT(*) FROM payload").fetchone()[0]
        assert surviving == rows // 10
        return {
            "rows": rows,
            "budget_pages": page_budget,
            "initial_bytes": before.file_bytes,
            "free_pages_before": before.freelist_count,
            "reclaimed_pages": result.pages_reclaimed,
            "final_bytes": after.file_bytes,
            "free_pages_after": after.freelist_count,
            "seconds": round(elapsed, 3),
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=10000)
    parser.add_argument("--page-budget", type=int, default=4096)
    args = parser.parse_args()
    print(benchmark(args.rows, args.page_budget))
