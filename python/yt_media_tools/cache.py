"""Persistent SQLite metadata cache for yt-discover.

Schema v3 stores source-scoped yt-dlp JSON records. Schema v4 stores registered
provider metadata and source state against deduplicated media identities.
"""

from __future__ import annotations

from .sqlite import load_statement

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Self

from .cache_entity_store import CacheV4EntityStore
from .cache_registry import FreshnessMode
from .cache_registry_store import CacheV4RegistryStore
from .cache_v4_ytdlp import (
    YTDLP_FRESHNESS_POLICIES,
    YTDLP_PROVIDER,
    STABLE_COLLECTION_EQUIVALENTS,
    build_ytdlp_provider,
    normalise_registered_metadata,
)
from .freshness_config import ProviderFreshnessPolicies, ResolvedFreshnessPolicy


SCHEMA_VERSION = 3
CURRENT_SCHEMA_VERSION = 4
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
    return base / "yt-discover" / "metadata-v4.sqlite3"


def initialise_v4_cache(path: Path) -> None:
    """Create a fresh complete cache-v4 database at a path that does not yet exist."""
    target = path.expanduser()
    if target.exists():
        raise RuntimeError("cache-v4 destination already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        # Establish incremental vacuum before creating the fresh v4 schema.
        connection.execute("PRAGMA auto_vacuum=INCREMENTAL")
        connection.execute(load_statement("cache_v4/create_cache_meta"))
        registry = CacheV4RegistryStore(connection)
        registry.reconcile((YTDLP_PROVIDER,))
        CacheV4EntityStore(connection, registry).initialise((YTDLP_PROVIDER,))
        connection.execute(load_statement("cache_v4/create_ytdlp_collections"))
        with connection:
            connection.execute(load_statement("cache_v4/initial_schema_version"))
            connection.execute(load_statement("cache_v4/initial_migration_state"))
    except BaseException:
        connection.close()
        target.unlink(missing_ok=True)
        raise
    finally:
        if connection:
            connection.close()


def canonical_field(name: str) -> str:
    """Return a canonical metadata field for freshness decisions."""
    lowered = name.casefold()
    return _ALIASES.get(lowered, lowered)


def field_max_age(
    name: str,
    policies: ProviderFreshnessPolicies = YTDLP_FRESHNESS_POLICIES,
) -> timedelta:
    """Return the maximum age for one canonical yt-dlp field."""
    resolved = policies.field(canonical_field(name))
    assert resolved is not None
    assert resolved.policy.max_age_seconds is not None
    return timedelta(seconds=resolved.policy.max_age_seconds)


class MetadataCache:
    """Versioned SQLite cache of source-scoped authoritative yt-dlp metadata."""

    def __init__(
        self,
        path: Path,
        *,
        freshness_policies: ProviderFreshnessPolicies = YTDLP_FRESHNESS_POLICIES,
    ) -> None:
        self.path = path.expanduser()
        self.configured_freshness_policies = freshness_policies
        self.freshness_policies = freshness_policies
        self.ytdlp_provider = build_ytdlp_provider(freshness_policies)
        self.connection: sqlite3.Connection | None = None
        self.schema_version: int | None = None

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
        connection.row_factory = sqlite3.Row
        self.connection = connection
        version = self._existing_schema_version()
        if version == CURRENT_SCHEMA_VERSION:
            state = connection.execute(load_statement("common/cache_migration_state")).fetchone()
            if state is None or str(state[0]) != "complete":
                self.close()
                raise RuntimeError("cache-v4 database is not a complete migration target")
            registry = CacheV4RegistryStore(connection)
            try:
                registry.reconcile((self.ytdlp_provider,))
                self._apply_persisted_freshness_overrides(registry)
            except BaseException:
                self.close()
                raise
            self.schema_version = CURRENT_SCHEMA_VERSION
            return
        self._initialise_schema()
        self._apply_persisted_freshness_overrides(CacheV4RegistryStore(connection))
        self.schema_version = SCHEMA_VERSION

    def _existing_schema_version(self) -> int | None:
        """Return an existing schema version without creating or mutating cache state."""
        db = self._db()
        row = db.execute(load_statement("common/cache_meta_table_exists")).fetchone()
        if row is None:
            return None
        version_row = db.execute(load_statement("common/cache_schema_version")).fetchone()
        if version_row is None:
            return None
        try:
            return int(version_row[0])
        except (TypeError, ValueError) as exc:
            raise RuntimeError("invalid metadata-cache schema version") from exc

    def _is_v4(self) -> bool:
        return self.schema_version == CURRENT_SCHEMA_VERSION

    def _v4_store(self) -> CacheV4EntityStore:
        registry = CacheV4RegistryStore(self._db())
        return CacheV4EntityStore(self._db(), registry)

    def _apply_persisted_freshness_overrides(self, registry: CacheV4RegistryStore) -> None:
        overrides = dict(registry.field_freshness_overrides("yt-dlp"))
        fields = dict(self.configured_freshness_policies.fields)
        for name, policy in overrides.items():
            if name in fields:
                fields[name] = ResolvedFreshnessPolicy(policy, "database override")
        self.freshness_policies = ProviderFreshnessPolicies(
            key=self.configured_freshness_policies.key,
            default=self.configured_freshness_policies.default,
            fields=tuple(sorted(fields.items())),
        )

    def _v4_source(self, source_url: str):
        row = (
            self._db()
            .execute(
                load_statement("cache_v4/source_by_url_unfaceted"),
                (source_url,),
            )
            .fetchone()
        )
        if row is None:
            return None
        from .cache_entity_store import SourceIdentity

        return SourceIdentity(int(row[0]), str(row[1]), str(row[2]), str(row[3]) or None)

    def _v4_cached_item(self, source_url: str, video_id: str) -> CachedMetadata | None:
        row = (
            self._db()
            .execute(
                load_statement("cache_v4/select_youtube_detailed_entity_metadata"),
                (video_id,),
            )
            .fetchone()
        )
        if row is None:
            return None
        record: dict[str, Any] = {}
        for name in STABLE_COLLECTION_EQUIVALENTS:
            payload = row[f"{name}_json"]
            if payload is not None:
                try:
                    record[name] = json.loads(str(payload))
                except (TypeError, json.JSONDecodeError):
                    pass
        for field in self.ytdlp_provider.fields:
            if field.storage_name in row.keys():
                record[field.name] = row[field.storage_name]
        record.setdefault("id", video_id)
        fetched_at = datetime.fromisoformat(str(row["last_success_at"]))
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        return CachedMetadata(video_id, record, fetched_at.astimezone(timezone.utc))

    def _sync_v4_source_state(self, source_url: str | None = None) -> None:
        """Mirror transitional v3 source state into the v4 entity-backed model."""
        registry = CacheV4RegistryStore(self._db())
        registry.reconcile((self.ytdlp_provider,))
        store = CacheV4EntityStore(self._db(), registry)
        store.initialise((self.ytdlp_provider,))
        store.import_legacy_source_state(source_urls=(source_url,) if source_url is not None else None)

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
            db.execute(load_statement("cache_v3/create_cache_meta_legacy"))
            version_row = db.execute(load_statement("common/cache_schema_version")).fetchone()
            if version_row is None:
                version = SCHEMA_VERSION
                db.execute(load_statement("common/cache_insert_schema_version"), (str(version),))
            else:
                try:
                    version = int(version_row[0])
                except (TypeError, ValueError) as exc:
                    raise RuntimeError("invalid metadata-cache schema version") from exc
                if version not in {1, 2, SCHEMA_VERSION}:
                    raise RuntimeError(
                        f"unsupported metadata-cache schema version {version}; expected 1, 2, or {SCHEMA_VERSION}"
                    )

            db.execute(load_statement("cache_v3/create_metadata_records"))
            db.execute(load_statement("cache_v3/create_metadata_records_video_id_index"))
            db.execute(load_statement("cache_v3/create_legacy_ytdlp_collections"))
            db.execute(load_statement("cache_v3/create_source_observations"))
            db.execute(load_statement("cache_v3/create_source_entries"))
            db.execute(load_statement("cache_v3/create_source_entries_order_index"))
            db.execute(load_statement("cache_v3/create_source_coverage"))
            db.execute(load_statement("cache_v3/create_source_frontiers"))
            if version in {1, 2}:
                # Legacy schemas persisted source_entries only from complete, unfiltered
                # source observations. Seed a frontier only where the stored ordering
                # cardinality agrees with the corresponding observation, so migration cannot
                # turn a partial historical scan into a trusted incremental boundary.
                rows = db.execute(load_statement("cache_v3/legacy_frontier_candidates")).fetchall()
                for source_url, source_kind, observed_at, observed_entries, head_video_id in rows:
                    if head_video_id:
                        db.execute(
                            load_statement("cache_v3/legacy_frontier_insert"),
                            (source_url, source_kind, observed_at, observed_entries, head_video_id),
                        )
                db.execute(load_statement("common/cache_set_schema_version"), (str(SCHEMA_VERSION),))

        self._sync_v4_source_state()

    def get(self, source_url: str, video_id: str) -> CachedMetadata | None:
        if self._is_v4():
            return self._v4_cached_item(source_url, video_id)
        row = (
            self._db()
            .execute(
                load_statement("cache_v3/record_by_source_and_id"),
                (source_url, video_id),
            )
            .fetchone()
        )
        if row is None:
            return None
        return self._decode_item(video_id, row[0], row[1])

    def get_many(self, source_url: str, video_ids: Iterable[str]) -> dict[str, CachedMetadata]:
        """Return decodable source-scoped records for a set of video IDs using bounded queries."""
        unique_ids = tuple(dict.fromkeys(video_ids))
        if not unique_ids:
            return {}
        if self._is_v4():
            return {
                video_id: item
                for video_id in unique_ids
                if (item := self._v4_cached_item(source_url, video_id)) is not None
            }

        # Stay below SQLite builds with the historical 999-variable default while leaving
        # one bind parameter available for the source URL.
        max_ids_per_query = 900
        items: dict[str, CachedMetadata] = {}
        db = self._db()
        for start in range(0, len(unique_ids), max_ids_per_query):
            chunk = unique_ids[start : start + max_ids_per_query]
            placeholders = ",".join("?" for _ in chunk)
            rows = db.execute(
                f"SELECT video_id, fetched_at, raw_json FROM metadata_records "
                f"WHERE source_url = ? AND video_id IN ({placeholders})",
                (source_url, *chunk),
            ).fetchall()
            for video_id, fetched_at, raw_json in rows:
                item = self._decode_item(video_id, fetched_at, raw_json)
                if item is not None:
                    items[video_id] = item
        return items

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
        if self._is_v4():
            rows = (
                self._db()
                .execute(
                    load_statement("cache_v4/source_record_ids"),
                    (source_url,),
                )
                .fetchall()
            )
            return [item for row in rows if (item := self._v4_cached_item(source_url, str(row[0]))) is not None]
        rows = (
            self._db()
            .execute(
                load_statement("cache_v3/source_records"),
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
        if self._is_v4():
            row = (
                self._db()
                .execute(
                    load_statement("cache_v4/count_detailed_source_records"),
                    (source_url,),
                )
                .fetchone()
            )
            return int(row[0]) if row is not None else 0
        row = self._db().execute(load_statement("cache_v3/count_source_records"), (source_url,)).fetchone()
        return int(row[0]) if row is not None else 0

    def is_fresh(
        self,
        item: CachedMetadata,
        required_fields: Iterable[str],
        *,
        now: datetime | None = None,
    ) -> bool:
        """Return whether every query-required field is fresh enough for reuse."""
        return not self.stale_fields(item, required_fields, now=now)

    def freshness_policy(self, field: str) -> ResolvedFreshnessPolicy:
        """Return the effective typed policy and origin for one yt-dlp field."""
        resolved = self.freshness_policies.field(canonical_field(field))
        assert resolved is not None
        return resolved

    def stale_fields(
        self,
        item: CachedMetadata,
        required_fields: Iterable[str],
        *,
        now: datetime | None = None,
    ) -> frozenset[str]:
        """Return the required fields whose effective policies reject an observation."""
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        age = current - item.fetched_at
        stale = set()
        for field in required_fields:
            policy = self.freshness_policy(field).policy
            if policy.mode is FreshnessMode.ALWAYS_REFRESH:
                stale.add(field)
            elif policy.mode is FreshnessMode.MAX_AGE:
                assert policy.max_age_seconds is not None
                if age > timedelta(seconds=policy.max_age_seconds):
                    stale.add(field)
        return frozenset(stale)

    def _normalise_record_into_v4(
        self,
        _source_url: str,
        record: dict[str, Any],
        *,
        acquired_at: datetime,
        entity_video_id: str | None = None,
        commit: bool = True,
        historical_timestamp: str | None = None,
    ) -> bool:
        """Normalise one accepted legacy backend record into registered v4 metadata."""
        video_id = entity_video_id if entity_video_id is not None else record.get("id")
        if not isinstance(video_id, str) or not video_id:
            return False
        registry = CacheV4RegistryStore(self._db())
        if commit:
            registry.reconcile((self.ytdlp_provider,))
        store = CacheV4EntityStore(self._db(), registry)
        if commit:
            store.initialise((self.ytdlp_provider,))
        entity = store.get_or_create_entity("youtube", video_id, commit=commit)
        values = normalise_registered_metadata(record)
        store.write_provider_metadata(self.ytdlp_provider, entity.entity_id, values, commit=commit)
        store.record_acquisition_success(
            self.ytdlp_provider,
            entity.entity_id,
            "detailed",
            acquired_at=acquired_at,
            commit=commit,
        )
        if historical_timestamp is not None:
            self._db().execute(
                load_statement("cache_v4/update_historical_detailed_acquisition"),
                (historical_timestamp, historical_timestamp, entity.entity_id),
            )
        collections = {
            name: (json.dumps(record[name], ensure_ascii=False, separators=(",", ":")) if name in record else None)
            for name in STABLE_COLLECTION_EQUIVALENTS
        }
        self._db().execute(
            load_statement("cache_v4/upsert_ytdlp_collections"),
            (
                entity.entity_id,
                collections["tags"],
                collections["categories"],
                collections["formats"],
                collections["chapters"],
                collections["thumbnails"],
            ),
        )
        if commit:
            self._db().commit()
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
        records = tuple(records)
        if self._is_v4():
            acquired_at = datetime.fromisoformat(when)
            accepted = 0
            for record in records:
                if self._normalise_record_into_v4(source_url, record, acquired_at=acquired_at) is not None:
                    accepted += 1
            return accepted
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
                load_statement("cache_v3/upsert_metadata_record"),
                rows,
            )
        acquired_at = datetime.fromisoformat(when)
        for record in records:
            self._normalise_record_into_v4(source_url, record, acquired_at=acquired_at)
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
        when_dt = (observed_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if self._is_v4():
            ids = [video_id for video_id in video_ids if video_id]
            store = self._v4_store()
            source = self._v4_source(source_url) or store.get_or_create_source(source_url, "unknown")
            entity_ids = [store.get_or_create_entity("youtube", video_id).entity_id for video_id in ids]
            return store.replace_source_entries(source, entity_ids)
        when = when_dt.isoformat()
        rows = [(source_url, video_id, index, when) for index, video_id in enumerate(video_ids, start=1) if video_id]
        with self._db():
            self._db().execute(load_statement("cache_v3/delete_source_entries"), (source_url,))
            if rows:
                self._db().executemany(
                    load_statement("cache_v3/insert_source_entry"),
                    rows,
                )
        self._sync_v4_source_state(source_url)
        return len(rows)

    def source_entry_ids(self, source_url: str) -> list[str]:
        """Return the persisted newest-first source ordering for one source."""
        if self._is_v4():
            rows = (
                self._db()
                .execute(
                    load_statement("cache_v4/source_record_ids"),
                    (source_url,),
                )
                .fetchall()
            )
            return [str(row[0]) for row in rows]
        rows = (
            self._db()
            .execute(
                load_statement("cache_v3/source_entry_ids"),
                (source_url,),
            )
            .fetchall()
        )
        return [str(row[0]) for row in rows if row and row[0]]

    def source_frontier(self, source_url: str) -> SourceFrontier | None:
        """Return a trusted incremental frontier when one has been established."""
        if self._is_v4():
            row = (
                self._db()
                .execute(
                    load_statement("cache_v4/source_frontier_by_url"),
                    (source_url,),
                )
                .fetchone()
            )
            if row is None:
                return None
            verified_at = datetime.fromisoformat(str(row[1]))
            return SourceFrontier(
                source_url, str(row[0]), verified_at.astimezone(timezone.utc), int(row[2]), str(row[3]), int(row[4])
            )
        row = (
            self._db()
            .execute(
                load_statement("cache_v3/source_frontier_by_url"),
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
        if self._is_v4():
            source = self._v4_store().get_or_create_source(source_url, source_kind)
            if not ids:
                with self._db():
                    self._db().execute(load_statement("cache_v4/delete_source_frontier"), (source.source_id,))
                return
            store = self._v4_store()
            head = store.get_or_create_entity("youtube", ids[0])
            store.record_source_frontier(
                source,
                head.entity_id,
                len(ids),
                overlap_confirmations=overlap_confirmations,
                verified_at=(verified_at or datetime.now(timezone.utc)),
            )
            return
        if not ids:
            with self._db():
                self._db().execute(load_statement("cache_v3/delete_source_frontier"), (source_url,))
            self._sync_v4_source_state(source_url)
            return
        when = (verified_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        with self._db():
            self._db().execute(
                load_statement("cache_v3/upsert_source_frontier"),
                (source_url, source_kind, when, len(ids), ids[0], overlap_confirmations),
            )
        self._sync_v4_source_state(source_url)

    def record_source_observation(
        self,
        source_url: str,
        source_kind: str,
        observed_entries: int,
        *,
        observed_at: datetime | None = None,
    ) -> None:
        """Record source observation telemetry without claiming frontier completeness."""
        when_dt = (observed_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if self._is_v4():
            store = self._v4_store()
            source = store.get_or_create_source(source_url, source_kind)
            store.record_source_observation(source, observed_entries, observed_at=when_dt)
            return
        when = when_dt.isoformat()
        with self._db():
            self._db().execute(
                load_statement("cache_v3/upsert_source_observation"),
                (source_url, source_kind, when, observed_entries),
            )
        self._sync_v4_source_state(source_url)

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
        when_dt = (observed_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        cached_entries = self.count_source_records(source_url)
        if self._is_v4():
            store = self._v4_store()
            source = store.get_or_create_source(source_url, source_kind)
            store.record_source_coverage(
                source, observed_entries, cached_entries, complete=complete, reason=reason, observed_at=when_dt
            )
            return
        when = when_dt.isoformat()
        with self._db():
            self._db().execute(
                load_statement("cache_v3/upsert_source_coverage"),
                (source_url, source_kind, when, observed_entries, cached_entries, 1 if complete else 0, reason),
            )
        self._sync_v4_source_state(source_url)

    def source_coverage(self, source_url: str) -> SourceCoverage | None:
        if self._is_v4():
            row = (
                self._db()
                .execute(
                    load_statement("cache_v4/source_coverage_by_url"),
                    (source_url,),
                )
                .fetchone()
            )
            if row is None:
                return None
            observed_at = datetime.fromisoformat(str(row[1]))
            return SourceCoverage(
                source_url,
                str(row[0]),
                observed_at.astimezone(timezone.utc),
                int(row[2]),
                int(row[3]),
                bool(row[4]),
                str(row[5]),
            )
        row = (
            self._db()
            .execute(
                load_statement("cache_v3/source_coverage_by_url"),
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
