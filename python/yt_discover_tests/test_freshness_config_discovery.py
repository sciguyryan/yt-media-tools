from __future__ import annotations

from pathlib import Path

import pytest

from yt_media_tools.cache_registry import FreshnessPolicy
from yt_media_tools.cache_v4_ytdlp import YTDLP_FRESHNESS_FIELDS, YTDLP_FRESHNESS_POLICIES
from yt_media_tools.freshness_config import (
    FreshnessConfigurationError,
    default_user_freshness_config_path,
    load_effective_freshness_configuration,
)


PROVIDER_FIELDS = {"yt-dlp": YTDLP_FRESHNESS_FIELDS}


def _user_configuration(value: str, *, field: str = "availability") -> str:
    return f"""schema_version = 1

[providers."yt-dlp".fields]
{field} = "{value}"
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_default_user_path_follows_xdg_configuration_convention(tmp_path: Path) -> None:
    xdg_root = tmp_path / "xdg"
    assert default_user_freshness_config_path(environ={"XDG_CONFIG_HOME": str(xdg_root)}) == (
        xdg_root / "yt-discover" / "freshness.toml"
    )
    assert default_user_freshness_config_path(environ={}, home=tmp_path) == (
        tmp_path / ".config" / "yt-discover" / "freshness.toml"
    )
    assert default_user_freshness_config_path(environ={"XDG_CONFIG_HOME": ""}, home=tmp_path) == (
        tmp_path / ".config" / "yt-discover" / "freshness.toml"
    )


def test_absent_discovered_configuration_uses_complete_builtins(tmp_path: Path) -> None:
    effective = load_effective_freshness_configuration(
        provider_fields=PROVIDER_FIELDS,
        environ={},
        home=tmp_path,
    )

    assert effective == load_effective_freshness_configuration(
        provider_fields=PROVIDER_FIELDS,
        requested_path=None,
        environ={"XDG_CONFIG_HOME": str(tmp_path / "also-absent")},
    )
    assert effective.provider("yt-dlp") == YTDLP_FRESHNESS_POLICIES


def test_discovered_partial_override_changes_only_one_field(tmp_path: Path) -> None:
    path = tmp_path / "configuration" / "yt-discover" / "freshness.toml"
    _write(path, _user_configuration("12h"))

    effective = load_effective_freshness_configuration(
        provider_fields=PROVIDER_FIELDS,
        environ={"XDG_CONFIG_HOME": str(tmp_path / "configuration")},
    )
    provider = effective.provider("yt-dlp")
    assert provider is not None
    availability = provider.field("availability")
    assert availability is not None
    assert availability.policy == FreshnessPolicy.max_age(12 * 3600)
    assert availability.origin == f"user override: {path}"

    for field in YTDLP_FRESHNESS_FIELDS:
        if field == "availability":
            continue
        assert provider.field(field) == YTDLP_FRESHNESS_POLICIES.field(field)
    assert provider.default == YTDLP_FRESHNESS_POLICIES.default


def test_explicit_path_takes_precedence_over_discovered_configuration(tmp_path: Path) -> None:
    discovered = tmp_path / "configuration" / "yt-discover" / "freshness.toml"
    explicit = tmp_path / "explicit.toml"
    _write(discovered, _user_configuration("12h"))
    _write(explicit, _user_configuration("30m"))

    effective = load_effective_freshness_configuration(
        provider_fields=PROVIDER_FIELDS,
        requested_path=explicit,
        environ={"XDG_CONFIG_HOME": str(tmp_path / "configuration")},
    )
    availability = effective.policy("yt-dlp", "availability")
    assert availability is not None
    assert availability.policy == FreshnessPolicy.max_age(30 * 60)
    assert availability.origin == f"user override: {explicit}"


def test_partial_override_can_select_an_explicit_non_expiring_policy(tmp_path: Path) -> None:
    path = tmp_path / "freshness.toml"
    _write(path, _user_configuration("immutable", field="title"))

    effective = load_effective_freshness_configuration(
        provider_fields=PROVIDER_FIELDS,
        requested_path=path,
    )
    title = effective.policy("yt-dlp", "title")
    assert title is not None
    assert title.policy == FreshnessPolicy.immutable()
    assert title.origin == f"user override: {path}"


def test_provider_default_override_changes_only_the_fallback(tmp_path: Path) -> None:
    path = tmp_path / "freshness.toml"
    _write(
        path,
        """schema_version = 1

[providers."yt-dlp"]
default = "7d"
""",
    )

    effective = load_effective_freshness_configuration(
        provider_fields=PROVIDER_FIELDS,
        requested_path=path,
    )
    provider = effective.provider("yt-dlp")
    assert provider is not None
    fallback = provider.field("future_field")
    assert fallback is not None
    assert fallback.policy == FreshnessPolicy.max_age(7 * 86400)
    assert fallback.origin == f"user override: {path}"
    assert provider.field("availability") == YTDLP_FRESHNESS_POLICIES.field("availability")


def test_missing_explicit_configuration_fails_instead_of_falling_back(tmp_path: Path) -> None:
    path = tmp_path / "missing.toml"
    with pytest.raises(FreshnessConfigurationError, match="unable to read freshness configuration"):
        load_effective_freshness_configuration(
            provider_fields=PROVIDER_FIELDS,
            requested_path=path,
        )


def test_invalid_discovered_configuration_fails_instead_of_falling_back(tmp_path: Path) -> None:
    path = tmp_path / "configuration" / "yt-discover" / "freshness.toml"
    _write(path, _user_configuration("one hour"))

    with pytest.raises(FreshnessConfigurationError, match="unsupported freshness value"):
        load_effective_freshness_configuration(
            provider_fields=PROVIDER_FIELDS,
            environ={"XDG_CONFIG_HOME": str(tmp_path / "configuration")},
        )
