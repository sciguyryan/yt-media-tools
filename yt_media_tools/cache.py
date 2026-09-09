"""Persistent SQLite metadata cache for yt-discover.

The cache stores authoritative yt-dlp JSON per source/video pair. Source completeness
is tracked separately from record freshness so cached metadata cannot silently stand
in for a current source listing. D8 will later add a conservative incremental frontier
on top of these persisted source observations and coverage facts.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Self


SCHEMA_VERSION = 3
DEFAULT_DYNAMIC_MAX_AGE = timedelta(days=1)

_FIELD_MAX_AGE: dict[str, timedelta] = {
    "id": timedelta(days=3650),
    "upload_date": timedelta(days=3650),
    "release_timestamp": timedelta(days=3650),
    "timestamp": timedelta(days=3650),
    "modified_timestamp": timedelta(days=1),
    "channel_id": timedelta(days=3650),
    "uploader_id": timedelta(days=3650),
    "duration": timedelta(days=30),
    "title": timedelta(days=7),
    "uploader": timedelta(days=7),
    "channel": timedelta(days=7),
    "webpage_url": timedelta(days=30),
    "view_count": timedelta(hours=6),
    "like_count": timedelta(hours=6),
    "comment_count": timedelta(hours=6),
    "channel_follower_count": timedelta(hours=6),
    "availability": timedelta(hours=1),
    "live_status": timedelta(hours=1),
    "is_live": timedelta(hours=1),
    "was_live": timedelta(hours=1),
}

_ALIASES = {
    "views": "view_count",
    "likes": "like_count",
    "comments": "comment_count",
    "date": "upload_date",
    "url": "webpage_url",
}


@dataclass(frozen=True)
class CacheStats:
    """Cache reuse counters for one acquisition pass."""

    examined: int = 0
    hits: int = 0
    stale: int = 0
    misses: int = 0
    refreshed: int = 0
    written: int = 0


@dataclass(frozen=True)
class CachedMetadata:
    """A decoded cached yt-dlp record and its acquisition time."""

    video_id: str
    record: dict[str, Any]
    fetched_at: datetime


@dataclass(frozen=True)
class SourceFrontier:
    """Persisted trustworthy newest-first source ordering used for incremental overlap."""

    source_url: str
    source_kind: str
    verified_at: datetime
    known_entries: int
    head_video_id: str
    overlap_confirmations: int


@dataclass(frozen=True)
class SourceCoverage:
    """Persisted statement about how completely a source is represented in cache."""

    source_url: str
    source_kind: str
    observed_at: datetime
    observed_entries: int
    cached_entries: int
    complete: bool
    reason: str


def default_cache_path() -> Path:
    """Return the XDG-compatible default metadata-cache path."""
    root = os.environ.get("XDG_CACHE_HOME")
    base = Path(root).expanduser() if root else Path.home() / ".cache"
    return base / "yt-discover" / "metadata.sqlite3"


def canonical_field(name: str) -> str:
    """Return a canonical metadata field for freshness decisions."""
    lowered = name.casefold()
    if lowered.startswith("raw."):
        return "raw." + name[4:]
    return _ALIASES.get(lowered, lowered)


def field_max_age(name: str) -> timedelta:
    """Return the default maximum age for a cached field."""
    return _FIELD_MAX_AGE.get(canonical_field(name), DEFAULT_DYNAMIC_MAX_AGE)


class MetadataCache:
    """Versioned SQLite cache of source-scoped authoritative yt-dlp metadata."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser()
        self.connection: sqlite3.Connection | None = None

    def __enter__(self) -> Self:
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def open(self) -> None:
        if self.connection is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        self.connection = connection
        self._initialise_schema()

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def _db(self) -> sqlite3.Connection:
        if self.connection is None:
            raise RuntimeError("metadata cache is not open")
        return self.connection

    def _initialise_schema(self) -> None:
        db = self._db()
        with db:
            db.execute("CREATE TABLE IF NOT EXISTS cache_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            version_row = db.execute("SELECT value FROM cache_meta WHERE key = 'schema_version'").fetchone()
            if version_row is None:
                version = SCHEMA_VERSION
                db.execute("INSERT INTO cache_meta(key, value) VALUES('schema_version', ?)", (str(version),))
            else:
                try:
                    version = int(version_row[0])
                except (TypeError, ValueError) as exc:
                    raise RuntimeError("invalid metadata-cache schema version") from exc
                if version not in {1, 2, SCHEMA_VERSION}:
                    raise RuntimeError(
                        f"unsupported metadata-cache schema version {version}; expected 1, 2, or {SCHEMA_VERSION}"
                    )

            db.execute(
                """
                CREATE TABLE IF NOT EXISTS metadata_records (
                    source_url TEXT NOT NULL,
                    video_id TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    PRIMARY KEY (source_url, video_id)
                )
                """
            )
            db.execute("CREATE INDEX IF NOT EXISTS metadata_records_video_id ON metadata_records(video_id)")
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS source_observations (
                    source_url TEXT PRIMARY KEY,
                    source_kind TEXT NOT NULL,
                    last_observed_at TEXT NOT NULL,
                    observed_entries INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS source_entries (
                    source_url TEXT NOT NULL,
                    video_id TEXT NOT NULL,
                    source_index INTEGER NOT NULL,
                    observed_at TEXT NOT NULL,
                    PRIMARY KEY (source_url, video_id)
                )
                """
            )
            db.execute("CREATE INDEX IF NOT EXISTS source_entries_order ON source_entries(source_url, source_index)")
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS source_coverage (
                    source_url TEXT PRIMARY KEY,
                    source_kind TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    observed_entries INTEGER NOT NULL,
                    cached_entries INTEGER NOT NULL,
                    complete INTEGER NOT NULL,
                    reason TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS source_frontiers (
                    source_url TEXT PRIMARY KEY,
                    source_kind TEXT NOT NULL,
                    verified_at TEXT NOT NULL,
                    known_entries INTEGER NOT NULL,
                    head_video_id TEXT NOT NULL,
                    overlap_confirmations INTEGER NOT NULL
                )
                """
            )
            if version in {1, 2}:
                # Legacy schemas persisted source_entries only from complete, unfiltered
                # source observations. Seed a frontier only where the stored ordering
                # cardinality agrees with the corresponding observation, so migration cannot
                # turn a partial historical scan into a trusted incremental boundary.
                rows = db.execute(
                    """
                    SELECT o.source_url, o.source_kind, o.last_observed_at, o.observed_entries,
                           (SELECT video_id FROM source_entries e
                            WHERE e.source_url = o.source_url ORDER BY e.source_index LIMIT 1)
                    FROM source_observations o
                    WHERE o.observed_entries > 0
                      AND o.observed_entries = (SELECT COUNT(*) FROM source_entries e2 WHERE e2.source_url = o.source_url)
                    """
                ).fetchall()
                for source_url, source_kind, observed_at, observed_entries, head_video_id in rows:
                    if head_video_id:
                        db.execute(
                            """
                            INSERT OR IGNORE INTO source_frontiers(
                                source_url, source_kind, verified_at, known_entries, head_video_id, overlap_confirmations
                            ) VALUES(?, ?, ?, ?, ?, 0)
                            """,
                            (source_url, source_kind, observed_at, observed_entries, head_video_id),
                        )
                db.execute("UPDATE cache_meta SET value = ? WHERE key = 'schema_version'", (str(SCHEMA_VERSION),))

    def get(self, source_url: str, video_id: str) -> CachedMetadata | None:
        row = (
            self._db()
            .execute(
                "SELECT fetched_at, raw_json FROM metadata_records WHERE source_url = ? AND video_id = ?",
                (source_url, video_id),
            )
            .fetchone()
        )
        if row is None:
            return None
        return self._decode_item(video_id, row[0], row[1])

    def _decode_item(self, video_id: str, fetched_at_text: str, raw_json: str) -> CachedMetadata | None:
        try:
            fetched_at = datetime.fromisoformat(fetched_at_text)
            record = json.loads(raw_json)
        except (ValueError, json.JSONDecodeError, TypeError):
            return None
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        if not isinstance(record, dict):
            return None
        return CachedMetadata(video_id, record, fetched_at.astimezone(timezone.utc))

    def source_records(self, source_url: str) -> list[CachedMetadata]:
        """Return all decodable cached detailed records for one source."""
        rows = (
            self._db()
            .execute(
                """
            SELECT m.video_id, m.fetched_at, m.raw_json
            FROM metadata_records AS m
            LEFT JOIN source_entries AS s
              ON s.source_url = m.source_url AND s.video_id = m.video_id
            WHERE m.source_url = ?
            ORDER BY CASE WHEN s.source_index IS NULL THEN 1 ELSE 0 END, s.source_index, m.video_id
            """,
                (source_url,),
            )
            .fetchall()
        )
        items: list[CachedMetadata] = []
        for video_id, fetched_at, raw_json in rows:
            item = self._decode_item(video_id, fetched_at, raw_json)
            if item is not None:
                items.append(item)
        return items

    def count_source_records(self, source_url: str) -> int:
        row = self._db().execute("SELECT COUNT(*) FROM metadata_records WHERE source_url = ?", (source_url,)).fetchone()
        return int(row[0]) if row is not None else 0

    def is_fresh(
        self,
        item: CachedMetadata,
        required_fields: Iterable[str],
        *,
        now: datetime | None = None,
    ) -> bool:
        """Return whether every query-required field is fresh enough for reuse."""
        current = now or datetime.now(timezone.utc)
        age = current.astimezone(timezone.utc) - item.fetched_at
        for field in required_fields:
            if age > field_max_age(field):
                return False
            canonical = canonical_field(field)
            if canonical.startswith("raw."):
                current_value: Any = item.record
                for part in canonical[4:].split("."):
                    if not isinstance(current_value, dict) or part not in current_value:
                        return False
                    current_value = current_value[part]
        return True

    def put_many(
        self,
        source_url: str,
        records: Iterable[dict[str, Any]],
        *,
        fetched_at: datetime | None = None,
    ) -> int:
        """Atomically upsert detailed metadata records, returning rows accepted."""
        when = (fetched_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        rows: list[tuple[str, str, str, str]] = []
        for record in records:
            video_id = record.get("id")
            if not isinstance(video_id, str) or not video_id:
                continue
            rows.append((source_url, video_id, when, json.dumps(record, ensure_ascii=False, separators=(",", ":"))))
        if not rows:
            return 0
        with self._db():
            self._db().executemany(
                """
                INSERT INTO metadata_records(source_url, video_id, fetched_at, raw_json)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(source_url, video_id) DO UPDATE SET
                    fetched_at = excluded.fetched_at,
                    raw_json = excluded.raw_json
                """,
                rows,
            )
        return len(rows)

    def record_source_entries(
        self,
        source_url: str,
        video_ids: Iterable[str],
        *,
        observed_at: datetime | None = None,
    ) -> int:
        """Atomically replace the trusted newest-first ordering for one complete source view.

        Callers must not use this for bounded or otherwise partial scans. Replacement, rather
        than upsert, ensures IDs that disappeared from a later complete source observation do
        not survive as phantom frontier members.
        """
        when = (observed_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        rows = [(source_url, video_id, index, when) for index, video_id in enumerate(video_ids, start=1) if video_id]
        with self._db():
            self._db().execute("DELETE FROM source_entries WHERE source_url = ?", (source_url,))
            if rows:
                self._db().executemany(
                    """
                    INSERT INTO source_entries(source_url, video_id, source_index, observed_at)
                    VALUES(?, ?, ?, ?)
                    """,
                    rows,
                )
        return len(rows)

    def source_entry_ids(self, source_url: str) -> list[str]:
        """Return the persisted newest-first source ordering for one source."""
        rows = (
            self._db()
            .execute(
                "SELECT video_id FROM source_entries WHERE source_url = ? ORDER BY source_index",
                (source_url,),
            )
            .fetchall()
        )
        return [str(row[0]) for row in rows if row and row[0]]

    def source_frontier(self, source_url: str) -> SourceFrontier | None:
        """Return a trusted incremental frontier when one has been established."""
        row = (
            self._db()
            .execute(
                """
            SELECT source_kind, verified_at, known_entries, head_video_id, overlap_confirmations
            FROM source_frontiers WHERE source_url = ?
            """,
                (source_url,),
            )
            .fetchone()
        )
        if row is None:
            return None
        verified_at = datetime.fromisoformat(row[1])
        if verified_at.tzinfo is None:
            verified_at = verified_at.replace(tzinfo=timezone.utc)
        return SourceFrontier(
            source_url=source_url,
            source_kind=str(row[0]),
            verified_at=verified_at.astimezone(timezone.utc),
            known_entries=int(row[2]),
            head_video_id=str(row[3]),
            overlap_confirmations=int(row[4]),
        )

    def record_source_frontier(
        self,
        source_url: str,
        source_kind: str,
        video_ids: Iterable[str],
        *,
        overlap_confirmations: int,
        verified_at: datetime | None = None,
    ) -> None:
        """Persist a trusted newest-first source ordering frontier transactionally."""
        ids = [video_id for video_id in video_ids if video_id]
        if not ids:
            with self._db():
                self._db().execute("DELETE FROM source_frontiers WHERE source_url = ?", (source_url,))
            return
        when = (verified_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        with self._db():
            self._db().execute(
                """
                INSERT INTO source_frontiers(
                    source_url, source_kind, verified_at, known_entries, head_video_id, overlap_confirmations
                ) VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_url) DO UPDATE SET
                    source_kind = excluded.source_kind,
                    verified_at = excluded.verified_at,
                    known_entries = excluded.known_entries,
                    head_video_id = excluded.head_video_id,
                    overlap_confirmations = excluded.overlap_confirmations
                """,
                (source_url, source_kind, when, len(ids), ids[0], overlap_confirmations),
            )

    def record_source_observation(
        self,
        source_url: str,
        source_kind: str,
        observed_entries: int,
        *,
        observed_at: datetime | None = None,
    ) -> None:
        """Record source observation telemetry without claiming frontier completeness."""
        when = (observed_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        with self._db():
            self._db().execute(
                """
                INSERT INTO source_observations(source_url, source_kind, last_observed_at, observed_entries)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(source_url) DO UPDATE SET
                    source_kind = excluded.source_kind,
                    last_observed_at = excluded.last_observed_at,
                    observed_entries = excluded.observed_entries
                """,
                (source_url, source_kind, when, observed_entries),
            )

    def record_source_coverage(
        self,
        source_url: str,
        source_kind: str,
        observed_entries: int,
        *,
        complete: bool,
        reason: str,
        observed_at: datetime | None = None,
    ) -> None:
        """Persist explicit source/cache coverage without implying a D8 frontier."""
        when = (observed_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        cached_entries = self.count_source_records(source_url)
        with self._db():
            self._db().execute(
                """
                INSERT INTO source_coverage(
                    source_url, source_kind, observed_at, observed_entries,
                    cached_entries, complete, reason
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_url) DO UPDATE SET
                    source_kind = excluded.source_kind,
                    observed_at = excluded.observed_at,
                    observed_entries = excluded.observed_entries,
                    cached_entries = excluded.cached_entries,
                    complete = excluded.complete,
                    reason = excluded.reason
                """,
                (source_url, source_kind, when, observed_entries, cached_entries, 1 if complete else 0, reason),
            )

    def source_coverage(self, source_url: str) -> SourceCoverage | None:
        row = (
            self._db()
            .execute(
                """
            SELECT source_kind, observed_at, observed_entries, cached_entries, complete, reason
            FROM source_coverage WHERE source_url = ?
            """,
                (source_url,),
            )
            .fetchone()
        )
        if row is None:
            return None
        observed_at = datetime.fromisoformat(row[1])
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)
        return SourceCoverage(
            source_url=source_url,
            source_kind=row[0],
            observed_at=observed_at.astimezone(timezone.utc),
            observed_entries=int(row[2]),
            cached_entries=int(row[3]),
            complete=bool(row[4]),
            reason=row[5],
        )
