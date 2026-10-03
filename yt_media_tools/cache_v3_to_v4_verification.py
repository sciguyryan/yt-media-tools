"""Certification of historical cache-v3 to cache-v4 migrations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
import sqlite3

from .cache_v4_ytdlp import STABLE_COLLECTION_EQUIVALENTS, YTDLP_PROVIDER, normalise_registered_metadata


class MigrationVerificationMode(str, Enum):
    """Depth of semantic comparison after exhaustive structural checks."""

    NORMAL = "normal"
    FULL = "full"


@dataclass(frozen=True)
class MigrationCertification:
    """Successful verification accounting for one v3-to-v4 migration."""

    mode: MigrationVerificationMode
    metadata_records: int
    semantic_records_checked: int
    source_states_checked: int


def _connect_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _scalar(connection: sqlite3.Connection, sql: str, params: tuple[object, ...] = ()) -> int:
    return int(connection.execute(sql, params).fetchone()[0])


def _normalise_expected_value(value: object) -> object:
    if isinstance(value, bool):
        return int(value)
    return value


def _latest_v3_records(source: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    latest: dict[str, sqlite3.Row] = {}
    rows = source.execute(
        "SELECT source_url, video_id, fetched_at, raw_json FROM metadata_records "
        "ORDER BY fetched_at, source_url, video_id"
    )
    for row in rows:
        latest[str(row["video_id"])] = row
    return latest


def _sample_keys(keys: list[str]) -> list[str]:
    """Choose deterministic coverage across lexical and hashed identity strata."""
    if len(keys) <= 12:
        return keys
    ordered = sorted(keys)
    positions = {0, len(ordered) // 4, len(ordered) // 2, (3 * len(ordered)) // 4, len(ordered) - 1}
    selected = {ordered[index] for index in positions}
    hashed = sorted(ordered, key=lambda key: hashlib.sha256(key.encode("utf-8")).digest())
    selected.update(hashed[:7])
    return sorted(selected)


def _verify_accounting(source: sqlite3.Connection, target: sqlite3.Connection) -> int:
    metadata_records = _scalar(source, "SELECT COUNT(*) FROM metadata_records")
    expected_entities = {str(row[0]) for row in source.execute("SELECT video_id FROM metadata_records")}
    expected_entities.update(str(row[0]) for row in source.execute("SELECT video_id FROM source_entries"))
    expected_entities.update(str(row[0]) for row in source.execute("SELECT head_video_id FROM source_frontiers"))
    actual_entities = {
        str(row[0]) for row in target.execute("SELECT external_id FROM cache_v4_media_entities WHERE service='youtube'")
    }
    if actual_entities != expected_entities:
        raise RuntimeError("v4 media identity set does not match the identities represented by v3")
    for legacy, modern in (
        ("source_observations", "cache_v4_source_observations"),
        ("source_coverage", "cache_v4_source_coverage"),
        ("source_frontiers", "cache_v4_source_frontiers"),
    ):
        expected = _scalar(source, f"SELECT COUNT(*) FROM {legacy}")
        actual = _scalar(target, f"SELECT COUNT(*) FROM {modern}")
        if actual != expected:
            raise RuntimeError(f"{modern} row count {actual} does not match v3 {legacy} count {expected}")
    if _scalar(target, "SELECT COUNT(*) FROM cache_v4_source_entries") != _scalar(
        source, "SELECT COUNT(*) FROM source_entries"
    ):
        raise RuntimeError("v4 source-entry cardinality does not match v3")
    return metadata_records


def _verify_entity_metadata(source_row: sqlite3.Row, target: sqlite3.Connection) -> None:
    video_id = str(source_row["video_id"])
    fetched_at = str(source_row["fetched_at"])
    record = json.loads(str(source_row["raw_json"]))
    expected_values = normalise_registered_metadata(record)
    columns = ", ".join(f'm."{field.storage_name}"' for field in YTDLP_PROVIDER.fields)
    row = target.execute(
        f"SELECT {columns} FROM cache_v4_media_entities e "
        f"JOIN cache_v4_ytdlp_metadata m USING(entity_id) "
        "WHERE e.service='youtube' AND e.external_id=?",
        (video_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"v4 is missing registered metadata for media identity {video_id!r}")
    actual_values = tuple(row)
    expected_tuple = tuple(_normalise_expected_value(expected_values[field.name]) for field in YTDLP_PROVIDER.fields)
    if actual_values != expected_tuple:
        raise RuntimeError(f"registered metadata mismatch for media identity {video_id!r}")
    collection_row = target.execute(
        "SELECT tags_json, categories_json, formats_json, chapters_json, thumbnails_json "
        "FROM cache_v4_ytdlp_collections WHERE entity_id=("
        "SELECT entity_id FROM cache_v4_media_entities WHERE service='youtube' AND external_id=?"
        ")",
        (video_id,),
    ).fetchone()
    if collection_row is None:
        raise RuntimeError(f"v4 is missing registered collection storage for media identity {video_id!r}")
    for index, name in enumerate(("tags", "categories", "formats", "chapters", "thumbnails")):
        expected = record.get(name) if name in STABLE_COLLECTION_EQUIVALENTS else None
        actual = json.loads(str(collection_row[index])) if collection_row[index] is not None else None
        if actual != expected:
            raise RuntimeError(f"registered collection mismatch for media identity {video_id!r}: {name}")
    acquisition = target.execute(
        "SELECT a.outcome, a.last_attempt_at, a.last_success_at FROM cache_v4_acquisition_state a "
        "JOIN cache_v4_media_entities e USING(entity_id) "
        "JOIN cache_v4_providers p USING(provider_id) "
        "JOIN cache_v4_acquisition_groups g USING(acquisition_group_id) "
        "WHERE e.service='youtube' AND e.external_id=? AND p.provider_key='yt-dlp' AND g.group_key='detailed'",
        (video_id,),
    ).fetchone()
    if acquisition is None or tuple(acquisition) != ("success", fetched_at, fetched_at):
        raise RuntimeError(f"acquisition provenance/timestamp mismatch for media identity {video_id!r}")


def _verify_source_state(source: sqlite3.Connection, target: sqlite3.Connection) -> int:
    urls = sorted(
        {
            str(row[0])
            for table in ("source_observations", "source_entries", "source_coverage", "source_frontiers")
            for row in source.execute(f"SELECT DISTINCT source_url FROM {table}")
        }
    )
    for source_url in urls:
        v4_source = target.execute(
            "SELECT source_id, source_kind, facet FROM cache_v4_sources WHERE source_url=? AND facet=''",
            (source_url,),
        ).fetchone()
        if v4_source is None:
            raise RuntimeError(f"v4 is missing source state for {source_url!r}")
        source_id = int(v4_source["source_id"])
        kind_rows = []
        for table in ("source_observations", "source_coverage", "source_frontiers"):
            row = source.execute(f"SELECT source_kind FROM {table} WHERE source_url=?", (source_url,)).fetchone()
            if row is not None:
                kind_rows.append(str(row[0]))
        expected_kind = kind_rows[0] if kind_rows else "unknown"
        if str(v4_source["source_kind"]) != expected_kind or str(v4_source["facet"]) != "":
            raise RuntimeError(f"v4 source identity/kind mismatch for {source_url!r}")

        observation = source.execute(
            "SELECT last_observed_at, observed_entries FROM source_observations WHERE source_url=?", (source_url,)
        ).fetchone()
        actual_observation = target.execute(
            "SELECT last_observed_at, observed_entries FROM cache_v4_source_observations WHERE source_id=?",
            (source_id,),
        ).fetchone()
        if (tuple(observation) if observation else None) != (tuple(actual_observation) if actual_observation else None):
            raise RuntimeError(f"source observation mismatch for {source_url!r}")

        expected_entries = [
            (str(row["video_id"]), index)
            for index, row in enumerate(
                source.execute(
                    "SELECT video_id FROM source_entries WHERE source_url=? ORDER BY source_index, video_id",
                    (source_url,),
                ).fetchall()
            )
        ]
        actual_entries = [
            (str(row["external_id"]), int(row["source_index"]))
            for row in target.execute(
                "SELECT e.external_id, se.source_index FROM cache_v4_source_entries se "
                "JOIN cache_v4_media_entities e USING(entity_id) WHERE se.source_id=? "
                "ORDER BY se.source_index, e.external_id",
                (source_id,),
            ).fetchall()
        ]
        if actual_entries != expected_entries:
            raise RuntimeError(f"source ordering mismatch for {source_url!r}")

        coverage = source.execute(
            "SELECT observed_at, observed_entries, cached_entries, complete, reason "
            "FROM source_coverage WHERE source_url=?",
            (source_url,),
        ).fetchone()
        actual_coverage = target.execute(
            "SELECT observed_at, observed_entries, cached_entries, complete, reason "
            "FROM cache_v4_source_coverage WHERE source_id=?",
            (source_id,),
        ).fetchone()
        if (tuple(coverage) if coverage else None) != (tuple(actual_coverage) if actual_coverage else None):
            raise RuntimeError(f"source coverage mismatch for {source_url!r}")

        frontier = source.execute(
            "SELECT verified_at, known_entries, head_video_id, overlap_confirmations "
            "FROM source_frontiers WHERE source_url=?",
            (source_url,),
        ).fetchone()
        actual_frontier = target.execute(
            "SELECT f.verified_at, f.known_entries, e.external_id, f.overlap_confirmations "
            "FROM cache_v4_source_frontiers f JOIN cache_v4_media_entities e "
            "ON e.entity_id=f.head_entity_id WHERE f.source_id=?",
            (source_id,),
        ).fetchone()
        if (tuple(frontier) if frontier else None) != (tuple(actual_frontier) if actual_frontier else None):
            raise RuntimeError(f"source frontier mismatch for {source_url!r}")
    return len(urls)


def certify_v3_to_v4(
    source_path: Path,
    target_path: Path,
    *,
    mode: MigrationVerificationMode = MigrationVerificationMode.NORMAL,
) -> MigrationCertification:
    """Certify structural/accounting invariants and historical semantic equivalence."""
    source = _connect_read_only(source_path)
    target = _connect_read_only(target_path)
    try:
        metadata_records = _verify_accounting(source, target)
        latest = _latest_v3_records(source)
        entity_keys = sorted(latest)
        selected_entities = entity_keys if mode is MigrationVerificationMode.FULL else _sample_keys(entity_keys)
        for video_id in selected_entities:
            _verify_entity_metadata(latest[video_id], target)

        source_states = _verify_source_state(source, target)
        semantic_checked = len(selected_entities)
        return MigrationCertification(mode, metadata_records, semantic_checked, source_states)
    finally:
        target.close()
        source.close()
