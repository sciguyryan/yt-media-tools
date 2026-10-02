"""Read-only cache-v4 status and presentation tests."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

from yt_media_tools.cache import MetadataCache
from yt_media_tools.cache_entity_store import CacheV4EntityStore
from yt_media_tools.cache_maintenance import CacheRetentionPolicy
from yt_media_tools.cache_registry_store import CacheV4RegistryStore, REGISTRY_SCHEMA_REVISION
from yt_media_tools.cache_status import collect_cache_status, format_cache_status
from yt_media_tools.cache_v4_ytdlp import YTDLP_PROVIDER

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


def _populated_cache(path: Path) -> sqlite3.Connection:
    with MetadataCache(path):
        pass
    connection = sqlite3.connect(path)
    registry = CacheV4RegistryStore(connection)
    registry.reconcile((YTDLP_PROVIDER,))
    store = CacheV4EntityStore(connection, registry)
    store.initialise((YTDLP_PROVIDER,))
    old = store.get_or_create_entity("youtube", "old")
    fresh = store.get_or_create_entity("youtube", "fresh")
    store.write_provider_metadata(YTDLP_PROVIDER, old.entity_id, {"title": "Old"})
    store.write_provider_metadata(YTDLP_PROVIDER, fresh.entity_id, {"title": "Fresh"})
    store.record_acquisition_success(YTDLP_PROVIDER, old.entity_id, "detailed", acquired_at=NOW - timedelta(days=90))
    store.record_acquisition_success(YTDLP_PROVIDER, fresh.entity_id, "detailed", acquired_at=NOW - timedelta(days=2))
    source = store.get_or_create_source("https://example.invalid/channel", "channel", facet="videos")
    store.record_source_observation(source, observed_at=NOW - timedelta(days=90), observed_entries=2)
    return connection


def test_status_reports_logical_registry_retention_and_sqlite_state(tmp_path: Path) -> None:
    path = tmp_path / "metadata.sqlite3"
    connection = _populated_cache(path)
    policy = CacheRetentionPolicy(provider_max_age=timedelta(days=30), source_max_age=timedelta(days=30))
    before = connection.total_changes

    status = collect_cache_status(connection, path, (YTDLP_PROVIDER,), retention=policy, now=NOW)

    assert connection.total_changes == before
    assert status.cache_schema_version == 3
    assert status.registry_schema_revision == REGISTRY_SCHEMA_REVISION
    assert status.entities == 2
    assert status.acquisition_records == 2
    assert len(status.providers) == 1
    provider = status.providers[0]
    assert provider.key == "yt-dlp"
    assert provider.available
    assert provider.revision_current
    assert provider.metadata_records == 2
    assert provider.successful_acquisitions == 2
    assert provider.failed_acquisitions == 0
    assert provider.retention_eligible_contributions == 1
    assert status.source.sources == 1
    assert status.source.observations == 1
    assert status.source.retention_eligible_sources == 1
    assert status.sqlite.journal_mode == "wal"
    assert status.sqlite.page_size > 0
    assert status.sqlite.page_count > 0
    assert status.sqlite.database_bytes is not None
    connection.close()


def test_status_default_retention_is_disabled_and_needs_no_clock(tmp_path: Path) -> None:
    path = tmp_path / "metadata.sqlite3"
    connection = _populated_cache(path)
    status = collect_cache_status(connection, path, (YTDLP_PROVIDER,))
    assert not status.retention.enabled
    assert status.providers[0].retention_eligible_contributions == 0
    assert status.source.retention_eligible_sources == 0
    connection.close()


def test_status_marks_persisted_provider_unavailable_when_not_installed(tmp_path: Path) -> None:
    path = tmp_path / "metadata.sqlite3"
    connection = _populated_cache(path)
    connection.execute("UPDATE cache_v4_providers SET declared = 0 WHERE provider_key = 'yt-dlp'")
    connection.commit()
    status = collect_cache_status(connection, path, ())
    assert not status.providers[0].available
    assert status.providers[0].installed_schema_revision is None
    connection.close()


def test_status_reports_revision_mismatch_without_reconciling_it(tmp_path: Path) -> None:
    path = tmp_path / "metadata.sqlite3"
    connection = _populated_cache(path)
    connection.execute(
        "UPDATE cache_v4_providers SET schema_revision = schema_revision + 1 WHERE provider_key = 'yt-dlp'"
    )
    connection.commit()
    before = connection.total_changes
    status = collect_cache_status(connection, path, (YTDLP_PROVIDER,))
    assert not status.providers[0].revision_current
    assert connection.total_changes == before
    connection.close()


def test_status_json_payload_uses_seconds_for_retention_windows(tmp_path: Path) -> None:
    path = tmp_path / "metadata.sqlite3"
    connection = _populated_cache(path)
    status = collect_cache_status(
        connection,
        path,
        (YTDLP_PROVIDER,),
        retention=CacheRetentionPolicy(provider_max_age=timedelta(days=30)),
        now=NOW,
    )
    payload = status.to_dict()
    assert payload["retention"]["provider_max_age"] == 30 * 86400
    assert payload["retention"]["source_max_age"] is None
    connection.close()


def test_text_status_exposes_unavailable_provider_and_physical_facts(tmp_path: Path) -> None:
    path = tmp_path / "metadata.sqlite3"
    connection = _populated_cache(path)
    connection.execute("UPDATE cache_v4_providers SET declared = 0 WHERE provider_key = 'yt-dlp'")
    connection.commit()
    rendered = format_cache_status(collect_cache_status(connection, path, ()))
    assert "unavailable" in rendered
    assert "Retention: provider disabled, source disabled" in rendered
    assert "SQLite: journal=wal" in rendered
    assert "reusable=" in rendered
    assert "WAL=" in rendered
    connection.close()


def test_cache_status_cli_reads_existing_cache_without_source(monkeypatch, tmp_path: Path, capsys) -> None:
    from yt_media_tools.discover_application import main

    path = tmp_path / "metadata.sqlite3"
    connection = _populated_cache(path)
    connection.close()

    assert main(["--cache-status", "--cache", str(path)]) == 0
    output = capsys.readouterr().out
    assert "Cache schema: 3" in output
    assert "yt-dlp:" in output
    assert "Source state:" in output
    assert "SQLite: journal=wal" in output


def test_cache_status_cli_can_emit_machine_readable_json(tmp_path: Path, capsys) -> None:
    import json
    from yt_media_tools.discover_application import main

    path = tmp_path / "metadata.sqlite3"
    connection = _populated_cache(path)
    connection.close()

    assert main(["--cache-status", "--cache", str(path), "--cache-status-format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["cache_schema_version"] == 3
    assert payload["providers"][0]["key"] == "yt-dlp"
    assert payload["providers"][0]["available"] is True
    assert payload["providers"][0]["revision_current"] is True
    assert payload["retention"]["provider_max_age"] is None
    assert payload["sqlite"]["journal_mode"] == "wal"
