from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

from yt_discover_tests.cli_harness import run_cli
from yt_media_tools.cache import CachedMetadata, MetadataCache, initialise_v4_cache
from yt_media_tools.cache_registry import FreshnessPolicy
from yt_media_tools.cache_registry_store import CacheV4RegistryStore
from yt_media_tools.cache_v4_ytdlp import YTDLP_FRESHNESS_FIELDS
from yt_media_tools.discover_acquisition import _cached_or_refresh_metadata
from yt_media_tools.freshness_config import load_effective_freshness_configuration
from yt_media_tools.ytdlp import AcquisitionStats


NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
PROVIDER_FIELDS = {"yt-dlp": YTDLP_FRESHNESS_FIELDS}


def _effective(path: Path):
    catalogue = load_effective_freshness_configuration(
        provider_fields=PROVIDER_FIELDS,
        requested_path=path,
    )
    policies = catalogue.provider("yt-dlp")
    assert policies is not None
    return policies


def test_cache_reuse_consumes_effective_duration_override(tmp_path: Path) -> None:
    path = tmp_path / "freshness.toml"
    path.write_text(
        """schema_version = 1
[providers."yt-dlp".fields]
availability = "12h"
""",
        encoding="utf-8",
    )
    item = CachedMetadata("example", {"availability": "public"}, NOW - timedelta(hours=2))

    assert not MetadataCache(tmp_path / "built-in.sqlite3").is_fresh(item, {"availability"}, now=NOW)
    configured = MetadataCache(tmp_path / "configured.sqlite3", freshness_policies=_effective(path))
    assert configured.is_fresh(item, {"availability"}, now=NOW)
    assert configured.freshness_policy("availability").origin == f"user override: {path}"


def test_cache_reuse_honours_immutable_and_always_refresh_modes(tmp_path: Path) -> None:
    path = tmp_path / "freshness.toml"
    path.write_text(
        """schema_version = 1
[providers."yt-dlp".fields]
title = "immutable"
availability = "always-refresh"
""",
        encoding="utf-8",
    )
    cache = MetadataCache(tmp_path / "metadata.sqlite3", freshness_policies=_effective(path))
    old = CachedMetadata("old", {"title": "Old"}, NOW - timedelta(days=10000))
    current = CachedMetadata("current", {"availability": "public"}, NOW)

    assert cache.is_fresh(old, {"title"}, now=NOW)
    assert not cache.is_fresh(current, {"availability"}, now=NOW)
    assert cache.freshness_policy("title").policy == FreshnessPolicy.immutable()
    assert cache.freshness_policy("availability").policy == FreshnessPolicy.always_refresh()


def test_cache_v4_reconciliation_uses_configured_typed_default(tmp_path: Path) -> None:
    config = tmp_path / "freshness.toml"
    config.write_text(
        """schema_version = 1
[providers."yt-dlp".fields]
availability = "12h"
""",
        encoding="utf-8",
    )
    cache_path = tmp_path / "metadata-v4.sqlite3"
    initialise_v4_cache(cache_path)

    with MetadataCache(cache_path, freshness_policies=_effective(config)):
        pass

    connection = sqlite3.connect(cache_path)
    row = connection.execute(
        "SELECT default_freshness_mode, default_max_age_seconds FROM cache_v4_fields WHERE field_name = 'availability'"
    ).fetchone()
    connection.close()
    assert row == ("max-age", 12 * 3600)


def test_persisted_cache_v4_override_retains_precedence_and_origin(tmp_path: Path) -> None:
    config = tmp_path / "freshness.toml"
    config.write_text(
        """schema_version = 1
[providers."yt-dlp".fields]
availability = "12h"
""",
        encoding="utf-8",
    )
    cache_path = tmp_path / "metadata-v4.sqlite3"
    initialise_v4_cache(cache_path)
    connection = sqlite3.connect(cache_path)
    registry = CacheV4RegistryStore(connection)
    registry.set_field_overrides("yt-dlp", "availability", freshness=FreshnessPolicy.immutable())
    connection.close()

    cache = MetadataCache(cache_path, freshness_policies=_effective(config))
    cache.open()
    resolved = cache.freshness_policy("availability")
    cache.close()

    assert resolved.policy == FreshnessPolicy.immutable()
    assert resolved.origin == "database override"


def test_verbose_stale_diagnostic_reports_effective_policy_and_origin(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    config = tmp_path / "freshness.toml"
    config.write_text(
        """schema_version = 1
[providers."yt-dlp".fields]
availability = "30m"
""",
        encoding="utf-8",
    )
    source_url = "https://www.youtube.com/@example/videos"
    cache = MetadataCache(tmp_path / "metadata.sqlite3", freshness_policies=_effective(config))
    cache.open()
    cache.put_many(source_url, ({"id": "example", "availability": "public"},), fetched_at=NOW - timedelta(hours=1))

    def fake_load(_command, *, progress, record_callback):
        record = {"id": "example", "availability": "public"}
        record_callback(record)
        return [record], AcquisitionStats(available=1)

    monkeypatch.setattr("yt_media_tools.discover_acquisition.load_metadata", fake_load)
    _cached_or_refresh_metadata(
        cache=cache,
        source_url=source_url,
        video_ids=["example"],
        required_fields={"availability"},
        verbose=2,
        cookies_file=None,
    )
    cache.close()

    assert f"availability (30m from user override: {config})" in capsys.readouterr().err


def test_explicit_invalid_configuration_fails_before_query_work(tmp_path: Path) -> None:
    missing = tmp_path / "missing.toml"
    result = run_cli("--freshness-config", str(missing), "--check-query", "SELECT id")

    assert result.returncode == 2
    assert "invalid freshness configuration" in result.stderr
    assert "unable to read freshness configuration" in result.stderr
