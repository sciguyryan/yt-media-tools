from __future__ import annotations

import json
import pathlib
import sqlite3
import time

SCHEMA_VERSION = 3
DEFAULT_MAX_AGE = 24 * 60 * 60


def connect(path: pathlib.Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    initialise(connection)
    return connection


def initialise(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS cache_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS source_entries (
            source TEXT NOT NULL,
            video_id TEXT NOT NULL,
            position INTEGER NOT NULL,
            fetched_at INTEGER NOT NULL,
            entry_json TEXT NOT NULL,
            PRIMARY KEY (source, video_id)
        )
        """
    )

    row = connection.execute(
        "SELECT value FROM cache_meta WHERE key = 'schema_version'"
    ).fetchone()

    if row is None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS cached_sources (
                source TEXT PRIMARY KEY,
                backend TEXT,
                fetched_at INTEGER NOT NULL,
                entry_count INTEGER NOT NULL,
                head_video_id TEXT,
                overlap_confirmations INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.execute(
            "INSERT INTO cache_meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
    else:
        version = int(row["value"])
        if version == 1:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cached_sources (
                    source TEXT PRIMARY KEY,
                    backend TEXT,
                    fetched_at INTEGER NOT NULL,
                    entry_count INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT OR REPLACE INTO cached_sources
                    (source, backend, fetched_at, entry_count)
                SELECT
                    source,
                    NULL,
                    MAX(fetched_at),
                    COUNT(*)
                FROM source_entries
                GROUP BY source
                """
            )
            version = 2

        if version == 2:
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(cached_sources)")
            }
            if "head_video_id" not in columns:
                connection.execute(
                    "ALTER TABLE cached_sources ADD COLUMN head_video_id TEXT"
                )
            if "overlap_confirmations" not in columns:
                connection.execute(
                    """
                    ALTER TABLE cached_sources
                    ADD COLUMN overlap_confirmations INTEGER NOT NULL DEFAULT 0
                    """
                )
            connection.execute(
                """
                UPDATE cached_sources
                SET head_video_id = (
                    SELECT video_id
                    FROM source_entries
                    WHERE source_entries.source = cached_sources.source
                    ORDER BY position
                    LIMIT 1
                )
                WHERE head_video_id IS NULL
                """
            )
            connection.execute(
                "UPDATE cache_meta SET value = ? WHERE key = 'schema_version'",
                (str(SCHEMA_VERSION),),
            )
        elif version != SCHEMA_VERSION:
            raise RuntimeError(f"unsupported cache schema version: {version}")

    connection.commit()


def load_source(
    connection: sqlite3.Connection,
    source: str,
    max_age: int = DEFAULT_MAX_AGE,
    allow_stale: bool = False,
) -> list[dict[str, object]] | None:
    rows = connection.execute(
        """
        SELECT position, fetched_at, entry_json
        FROM source_entries
        WHERE source = ?
        ORDER BY position
        """,
        (source,),
    ).fetchall()
    if not rows:
        return None

    newest_fetch = max(int(row["fetched_at"]) for row in rows)
    if not allow_stale and int(time.time()) - newest_fetch > max_age:
        return None

    return [json.loads(row["entry_json"]) for row in rows]


def source_status(
    connection: sqlite3.Connection,
    source: str,
    max_age: int = DEFAULT_MAX_AGE,
) -> dict[str, object] | None:
    row = connection.execute(
        """
        SELECT source, backend, fetched_at, entry_count,
               head_video_id, overlap_confirmations
        FROM cached_sources
        WHERE source = ?
        """,
        (source,),
    ).fetchone()
    if row is None:
        return None

    age = max(0, int(time.time()) - int(row["fetched_at"]))
    return {
        "source": row["source"],
        "backend": row["backend"],
        "fetched_at": int(row["fetched_at"]),
        "entry_count": int(row["entry_count"]),
        "age": age,
        "fresh": age <= max_age,
        "head_video_id": row["head_video_id"],
        "overlap_confirmations": int(row["overlap_confirmations"]),
    }


def store_source(
    connection: sqlite3.Connection,
    source: str,
    entries: list[dict[str, object]],
    backend: str | None = None,
) -> None:
    fetched_at = int(time.time())
    connection.execute("DELETE FROM source_entries WHERE source = ?", (source,))
    connection.executemany(
        """
        INSERT INTO source_entries
            (source, video_id, position, fetched_at, entry_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (
                source,
                str(entry.get("id") or ""),
                position,
                fetched_at,
                json.dumps(entry, separators=(",", ":")),
            )
            for position, entry in enumerate(entries)
            if entry.get("id")
        ],
    )
    connection.execute(
        """
        INSERT OR REPLACE INTO cached_sources
            (
                source, backend, fetched_at, entry_count,
                head_video_id, overlap_confirmations
            )
        VALUES (?, ?, ?, ?, ?, 0)
        """,
        (
            source,
            backend,
            fetched_at,
            len(entries),
            str(entries[0].get("id")) if entries and entries[0].get("id") else None,
        ),
    )
    connection.commit()


def append_new_entries(
    connection: sqlite3.Connection,
    source: str,
    observed_entries: list[dict[str, object]],
    backend: str | None = None,
) -> tuple[list[dict[str, object]], int]:
    """Merge a newest-first observation only when it overlaps the cached frontier.

    Entries before the first cached ID are new. Once overlap is found, the
    existing cached tail remains authoritative for ordering. If no overlap is
    observed, the function refuses to guess and leaves the cache unchanged.
    """
    existing = load_source(connection, source, allow_stale=True)
    if existing is None:
        store_source(connection, source, observed_entries, backend=backend)
        return observed_entries, len(observed_entries)

    existing_ids = {str(entry.get("id")) for entry in existing if entry.get("id")}
    overlap_index = None
    for index, entry in enumerate(observed_entries):
        video_id = entry.get("id")
        if video_id and str(video_id) in existing_ids:
            overlap_index = index
            break

    if overlap_index is None:
        raise RuntimeError(
            "incremental refresh could not confirm overlap with the cached source"
        )

    prefix: list[dict[str, object]] = []
    prefix_ids: set[str] = set()
    for entry in observed_entries[:overlap_index]:
        video_id = entry.get("id")
        if not video_id:
            continue
        key = str(video_id)
        if key in existing_ids or key in prefix_ids:
            continue
        prefix_ids.add(key)
        prefix.append(entry)

    merged = prefix + existing
    fetched_at = int(time.time())

    if prefix:
        connection.execute(
            "UPDATE source_entries SET position = position + ? WHERE source = ?",
            (len(prefix), source),
        )
        connection.executemany(
            """
            INSERT INTO source_entries
                (source, video_id, position, fetched_at, entry_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    source,
                    str(entry["id"]),
                    position,
                    fetched_at,
                    json.dumps(entry, separators=(",", ":")),
                )
                for position, entry in enumerate(prefix)
            ],
        )

    head_video_id = str(merged[0].get("id")) if merged and merged[0].get("id") else None
    connection.execute(
        """
        UPDATE cached_sources
        SET backend = COALESCE(?, backend),
            fetched_at = ?,
            entry_count = ?,
            head_video_id = ?,
            overlap_confirmations = overlap_confirmations + 1
        WHERE source = ?
        """,
        (backend, fetched_at, len(merged), head_video_id, source),
    )
    connection.commit()
    return merged, len(prefix)


def update_entries(
    connection: sqlite3.Connection,
    source: str,
    entries: list[dict[str, object]],
) -> None:
    """Replace cached metadata for selected source entries without reordering them."""
    fetched_at = int(time.time())
    for entry in entries:
        video_id = entry.get("id")
        if not video_id:
            continue
        connection.execute(
            """
            UPDATE source_entries
            SET fetched_at = ?, entry_json = ?
            WHERE source = ? AND video_id = ?
            """,
            (
                fetched_at,
                json.dumps(entry, separators=(",", ":")),
                source,
                str(video_id),
            ),
        )
    connection.commit()
