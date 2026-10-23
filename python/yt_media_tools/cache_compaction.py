"""Compatibility imports for Discover's existing explicit compaction interface.

All execution and measurement logic lives in database_maintenance.
"""

from yt_media_tools.database_maintenance import (
    CacheCompactionResult,
    SQLiteStorageMeasurement,
    manual_full_vacuum as compact_cache,
    measure_sqlite_storage,
)

__all__ = ["CacheCompactionResult", "SQLiteStorageMeasurement", "compact_cache", "measure_sqlite_storage"]
