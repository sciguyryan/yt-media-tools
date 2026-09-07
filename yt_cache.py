from __future__ import annotations

import json
import pathlib
import sqlite3
import time


SCHEMA_VERSION = 1
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
            "INSERT INTO cache_meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
    elif int(row["value"]) != SCHEMA_VERSION:
        raise RuntimeError(
            f"unsupported cache schema version: {row['value']}"
        )
    connection.commit()


def load_source(
    connection: sqlite3.Connection,
    source: str,
    max_age: int = DEFAULT_MAX_AGE,
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
    if int(time.time()) - newest_fetch > max_age:
        return None

    return [json.loads(row["entry_json"]) for row in rows]


def store_source(
    connection: sqlite3.Connection,
    source: str,
    entries: list[dict[str, object]],
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
    connection.commit()


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
