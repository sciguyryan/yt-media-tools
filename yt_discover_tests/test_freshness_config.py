from __future__ import annotations

from datetime import timedelta

import pytest

from yt_media_tools.cache import field_max_age
from yt_media_tools.cache_registry import FreshnessMode, FreshnessPolicy
from yt_media_tools.cache_v4_ytdlp import YTDLP_FRESHNESS_POLICIES, YTDLP_PROVIDER
from yt_media_tools.freshness_config import FreshnessConfigurationError, parse_freshness_configuration


EXPECTED_YTDLP_MAX_AGES = {
    "id": 3650 * 86400,
    "title": 7 * 86400,
    "upload_date": 3650 * 86400,
    "duration": 30 * 86400,
    "view_count": 6 * 3600,
    "like_count": 6 * 3600,
    "comment_count": 6 * 3600,
    "channel_follower_count": 6 * 3600,
    "uploader": 7 * 86400,
    "uploader_id": 3650 * 86400,
    "channel": 7 * 86400,
    "channel_id": 3650 * 86400,
    "live_status": 3600,
    "availability": 3600,
    "is_live": 3600,
    "was_live": 3600,
    "webpage_url": 30 * 86400,
    "playlist_id": 86400,
    "playlist_title": 86400,
    "timestamp": 3650 * 86400,
    "release_timestamp": 3650 * 86400,
    "modified_timestamp": 86400,
}


def _partial(value: str) -> str:
    return f"""schema_version = 1

[providers."yt-dlp".fields]
availability = {value}
"""


def _parse(text: str):
    return parse_freshness_configuration(
        text,
        origin="test",
        provider_fields={"yt-dlp": {"availability"}},
        require_complete=False,
    )


def test_builtin_toml_reproduces_active_ytdlp_freshness_values_exactly() -> None:
    assert YTDLP_FRESHNESS_POLICIES.default is not None
    assert YTDLP_FRESHNESS_POLICIES.default.policy == FreshnessPolicy.max_age(86400)
    assert YTDLP_FRESHNESS_POLICIES.default.origin == "built-in"
    assert {name for name, _policy in YTDLP_FRESHNESS_POLICIES.fields} == set(EXPECTED_YTDLP_MAX_AGES)

    for field, seconds in EXPECTED_YTDLP_MAX_AGES.items():
        resolved = YTDLP_FRESHNESS_POLICIES.field(field)
        assert resolved is not None
        assert resolved.policy == FreshnessPolicy.max_age(seconds)
        assert resolved.origin == "built-in"
        assert field_max_age(field) == timedelta(seconds=seconds)

    assert field_max_age("unregistered_scalar") == timedelta(days=1)


def test_provider_registry_uses_the_same_builtin_policies_as_cache_reuse() -> None:
    assert {field.name for field in YTDLP_PROVIDER.fields} == set(EXPECTED_YTDLP_MAX_AGES)
    for field in YTDLP_PROVIDER.fields:
        resolved = YTDLP_FRESHNESS_POLICIES.field(field.name)
        assert resolved is not None
        assert field.freshness == resolved.policy


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ('"30m"', FreshnessPolicy.max_age(1800)),
        ('"1h"', FreshnessPolicy.max_age(3600)),
        ('"12h"', FreshnessPolicy.max_age(43200)),
        ('"7d"', FreshnessPolicy.max_age(604800)),
        ('"immutable"', FreshnessPolicy.immutable()),
        ('"always-refresh"', FreshnessPolicy.always_refresh()),
    ],
)
def test_supported_freshness_values_produce_typed_policies(value: str, expected: FreshnessPolicy) -> None:
    resolved = _parse(_partial(value)).policy("yt-dlp", "availability")
    assert resolved is not None
    assert resolved.policy == expected
    assert resolved.origin == "test"


@pytest.mark.parametrize(
    "value",
    ['""', '"0m"', '"01h"', '"-1h"', '"1.5h"', '"1 h"', '"1H"', '"1s"', '"forever"', "1"],
)
def test_invalid_freshness_values_fail_deterministically(value: str) -> None:
    with pytest.raises(FreshnessConfigurationError, match="providers.yt-dlp.fields.availability"):
        _parse(_partial(value))


def test_duration_overflow_is_rejected() -> None:
    with pytest.raises(FreshnessConfigurationError, match="exceeds the supported duration range"):
        _parse(_partial('"1000000000d"'))


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            'schema_version = 1\nunsupported = true\n[providers."yt-dlp".fields]\navailability = "1h"\n',
            "unsupported key",
        ),
        (
            'schema_version = 1\n[providers.unknown.fields]\navailability = "1h"\n',
            "unknown provider",
        ),
        (
            'schema_version = 1\n[providers."yt-dlp"]\nunsupported = true\n',
            "unsupported key",
        ),
        (
            'schema_version = 1\n[providers."yt-dlp".fields]\ntitle = "1h"\n',
            "unknown field",
        ),
        (
            'schema_version = 2\n[providers."yt-dlp".fields]\navailability = "1h"\n',
            "schema_version must be 1",
        ),
        (
            'schema_version = 1\n[providers."yt-dlp".fields\navailability = "1h"\n',
            "is not valid TOML",
        ),
    ],
)
def test_invalid_configuration_structure_fails_deterministically(text: str, message: str) -> None:
    with pytest.raises(FreshnessConfigurationError, match=message):
        _parse(text)


def test_complete_configuration_requires_every_provider_field_and_default() -> None:
    with pytest.raises(FreshnessConfigurationError, match="missing provider.*yt-dlp"):
        parse_freshness_configuration(
            "schema_version = 1\n[providers]\n",
            origin="test",
            provider_fields={"yt-dlp": {"availability"}},
            require_complete=True,
        )

    with pytest.raises(FreshnessConfigurationError, match="default is required"):
        parse_freshness_configuration(
            _partial('"1h"'),
            origin="test",
            provider_fields={"yt-dlp": {"availability"}},
            require_complete=True,
        )

    with pytest.raises(FreshnessConfigurationError, match="missing field.*title"):
        parse_freshness_configuration(
            'schema_version = 1\n[providers."yt-dlp"]\ndefault = "1d"\n'
            '[providers."yt-dlp".fields]\navailability = "1h"\n',
            origin="test",
            provider_fields={"yt-dlp": {"availability", "title"}},
            require_complete=True,
        )


def test_freshness_modes_remain_explicit_in_typed_results() -> None:
    immutable = _parse(_partial('"immutable"')).policy("yt-dlp", "availability")
    always = _parse(_partial('"always-refresh"')).policy("yt-dlp", "availability")
    assert immutable is not None and immutable.policy.mode is FreshnessMode.IMMUTABLE
    assert always is not None and always.policy.mode is FreshnessMode.ALWAYS_REFRESH
