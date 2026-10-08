"""Versioned, optional Downloader collection continuation storage.

Completion membership is advisory and never replaces yt-dlp's download outcomes.
Keep SQLite transactions short; the collection lock is held by the caller across
its entire download invocation in later integration phases.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SCHEMA_VERSION = 2
SEQUENCE_FINGERPRINT_VERSION = 1
DATABASE_NAME = "collection-state.sqlite3"
IDENTITY_RE = re.compile(
    r"^(?:youtube-playlist:[A-Za-z0-9_-]+|yt-sql:sha256:[0-9a-f]{64}|collection-uuid:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$"
)
PLAYLIST_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def fingerprint_collection_sequence(target_ids: list[str] | tuple[str, ...]) -> str:
    """Fingerprint the original ordered target sequence, including duplicates.

    The domain tag and explicit serialisation version prevent ambiguity and
    accidental cross-purpose reuse. JSON length/escaping is deterministic and
    UTF-8 encoding preserves exact target spelling without normalisation.
    """
    if not isinstance(target_ids, (list, tuple)) or any(
        not isinstance(target, str) or not target for target in target_ids
    ):
        raise ValueError("collection sequence must contain non-empty target ID strings")
    payload = json.dumps(
        ["yt-media-tools.collection-sequence", SEQUENCE_FINGERPRINT_VERSION, target_ids],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


class CollectionStateError(RuntimeError):
    """State is unavailable or its schema is not supported."""


def state_directory() -> Path:
    """Use the platform's per-user state directory, not the source tree."""
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA")
        return (Path(root) if root else Path.home() / "AppData" / "Local") / "yt-media-tools"
    root = os.environ.get("XDG_STATE_HOME")
    return (Path(root) if root and Path(root).is_absolute() else Path.home() / ".local" / "state") / "yt-media-tools"


def resolve_collection_identity(collection: dict) -> str | None:
    """Resolve explicit identity or a verified native YouTube playlist identity.

    An arbitrary query-derived collection must not inherit the identity of its
    single underlying playlist merely because metadata contains a playlist ID.
    """
    explicit = collection.get("identity")
    if explicit is not None:
        if not isinstance(explicit, str) or not IDENTITY_RE.fullmatch(explicit):
            raise ValueError("collection.identity must be a supported namespaced identity")
        return explicit
    metadata = collection.get("metadata", {})
    playlist_id = metadata.get("id")
    url = metadata.get("webpage_url")
    if not isinstance(playlist_id, str) or not PLAYLIST_RE.fullmatch(playlist_id):
        return None
    if not isinstance(url, str):
        return None
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"www.youtube.com", "youtube.com", "m.youtube.com"}:
        return None
    if parsed.path != "/playlist" or parse_qs(parsed.query).get("list") != [playlist_id]:
        return None
    # Provenance alone does not prove an arbitrary yt-sql projection is a direct
    # playlist export. Callers must opt in explicitly to native identity.
    if collection.get("identity_kind") == "native-playlist":
        return f"youtube-playlist:{playlist_id}"
    return None


class CollectionState:
    """Short-lived connections for transactional completion membership."""

    def __init__(self, directory: Path | None = None):
        self.directory = directory if directory is not None else state_directory()
        self.path = self.directory / DATABASE_NAME

    @contextlib.contextmanager
    def connect(self):
        try:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            connection = sqlite3.connect(self.path, timeout=15)
        except (OSError, sqlite3.Error) as exc:
            raise CollectionStateError(f"unable to open collection state: {exc}") from exc
        try:
            connection.execute("PRAGMA busy_timeout = 15000")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if version == 0 and not tables:
                with connection:
                    connection.execute(
                        "CREATE TABLE completed_targets (collection_id TEXT NOT NULL, target_id TEXT NOT NULL, completed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')), PRIMARY KEY (collection_id, target_id))"
                    )
                    connection.execute(
                        "CREATE TABLE collection_observations (collection_id TEXT PRIMARY KEY, fingerprint_version INTEGER NOT NULL, sequence_fingerprint TEXT NOT NULL, target_count INTEGER NOT NULL CHECK (target_count >= 0), observed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')))"
                    )
                    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            elif version == 1 and tables == {"completed_targets"}:
                legacy_columns = [row[1] for row in connection.execute("PRAGMA table_info(completed_targets)")]
                if legacy_columns != ["collection_id", "target_id", "completed_at"]:
                    raise CollectionStateError(
                        "invalid legacy collection-state table layout; existing data has been preserved"
                    )
                # Upgrade in one transaction; completion membership is preserved.
                with connection:
                    connection.execute(
                        "CREATE TABLE collection_observations (collection_id TEXT PRIMARY KEY, fingerprint_version INTEGER NOT NULL, sequence_fingerprint TEXT NOT NULL, target_count INTEGER NOT NULL CHECK (target_count >= 0), observed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')))"
                    )
                    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            elif version != SCHEMA_VERSION or tables != {"completed_targets", "collection_observations"}:
                raise CollectionStateError(
                    "unsupported collection-state database schema; existing data has been preserved"
                )
            columns = [row[1] for row in connection.execute("PRAGMA table_info(completed_targets)")]
            if columns != ["collection_id", "target_id", "completed_at"]:
                raise CollectionStateError("invalid collection-state table layout; existing data has been preserved")
            observation_columns = [row[1] for row in connection.execute("PRAGMA table_info(collection_observations)")]
            if observation_columns != [
                "collection_id",
                "fingerprint_version",
                "sequence_fingerprint",
                "target_count",
                "observed_at",
            ]:
                raise CollectionStateError(
                    "invalid collection observation table layout; existing data has been preserved"
                )
            yield connection
        except sqlite3.Error as exc:
            raise CollectionStateError(f"collection-state database error: {exc}") from exc
        finally:
            connection.close()

    def completed(self, collection_id: str) -> set[str]:
        with self.connect() as connection:
            return {
                row[0]
                for row in connection.execute(
                    "SELECT target_id FROM completed_targets WHERE collection_id = ?", (collection_id,)
                )
            }

    def record(self, collection_id: str, target_id: str) -> None:
        if not target_id:
            raise ValueError("completed target ID must not be empty")
        with self.connect() as connection, connection:
            connection.execute(
                "INSERT OR IGNORE INTO completed_targets (collection_id, target_id) VALUES (?, ?)",
                (collection_id, target_id),
            )

    def clear(self, collection_id: str) -> None:
        with self.connect() as connection, connection:
            connection.execute("DELETE FROM completed_targets WHERE collection_id = ?", (collection_id,))

    def observation(self, collection_id: str) -> tuple[int, str, int] | None:
        """Return the last observation without changing it or completion state."""
        with self.connect() as connection:
            row = connection.execute(
                "SELECT fingerprint_version, sequence_fingerprint, target_count "
                "FROM collection_observations WHERE collection_id = ?",
                (collection_id,),
            ).fetchone()
            return (int(row[0]), str(row[1]), int(row[2])) if row is not None else None

    def record_observation(self, collection_id: str, target_ids: list[str] | tuple[str, ...]) -> None:
        """Atomically replace the latest observed revision of a logical collection."""
        if not IDENTITY_RE.fullmatch(collection_id):
            raise ValueError("observation requires a supported namespaced collection identity")
        fingerprint = fingerprint_collection_sequence(target_ids)
        with self.connect() as connection, connection:
            connection.execute(
                "INSERT INTO collection_observations "
                "(collection_id, fingerprint_version, sequence_fingerprint, target_count) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(collection_id) DO UPDATE SET "
                "fingerprint_version = excluded.fingerprint_version, "
                "sequence_fingerprint = excluded.sequence_fingerprint, "
                "target_count = excluded.target_count, "
                "observed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
                (collection_id, SEQUENCE_FINGERPRINT_VERSION, fingerprint, len(target_ids)),
            )

    @contextlib.contextmanager
    def collection_lock(self, collection_id: str):
        """Serialise an entire collection invocation, not just SQLite writes."""
        import hashlib

        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_path = self.directory / (
            "collection-" + hashlib.sha256(collection_id.encode("utf-8")).hexdigest() + ".lock"
        )
        with lock_path.open("a+b") as handle:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                if handle.read(1) == b"":
                    handle.seek(0)
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
