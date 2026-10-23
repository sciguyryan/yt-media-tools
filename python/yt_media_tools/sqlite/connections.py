"""Small SQLite connection and result helpers without implicit schema changes."""

from __future__ import annotations

from pathlib import Path
import sqlite3


def open_read_only(path: Path, *, timeout: float = 5.0, rows: bool = False) -> sqlite3.Connection:
    """Open an existing database without permitting creation or mutation."""
    connection = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True, timeout=timeout)
    try:
        connection.execute("PRAGMA query_only=ON")
        if rows:
            connection.row_factory = sqlite3.Row
    except BaseException:
        connection.close()
        raise
    return connection


def scalar(connection: sqlite3.Connection, statement: str, parameters: tuple[object, ...] = ()) -> object:
    """Read the first value of a statement that must return exactly one row."""
    row = connection.execute(statement, parameters).fetchone()
    if row is None:
        raise ValueError("SQLite scalar statement returned no rows")
    return row[0]
