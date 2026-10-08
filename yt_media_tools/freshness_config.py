"""Typed freshness-policy configuration independent of cache execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
import re
import tomllib
from typing import Iterable, Mapping

from .cache_registry import FreshnessPolicy


FRESHNESS_CONFIG_SCHEMA_VERSION = 1
BUILTIN_FRESHNESS_CONFIG = Path(__file__).with_name("freshness-defaults.toml")

_DURATION = re.compile(r"^([1-9][0-9]*)([mhd])$")
_DURATION_SECONDS = {"m": 60, "h": 3600, "d": 86400}


class FreshnessConfigurationError(ValueError):
    """A freshness TOML document does not satisfy the supported contract."""


@dataclass(frozen=True)
class ResolvedFreshnessPolicy:
    """One typed policy together with the configuration source which supplied it."""

    policy: FreshnessPolicy
    origin: str


@dataclass(frozen=True)
class ProviderFreshnessPolicies:
    """Configured policies for one stable provider registry key."""

    key: str
    default: ResolvedFreshnessPolicy | None
    fields: tuple[tuple[str, ResolvedFreshnessPolicy], ...]

    def field(self, name: str) -> ResolvedFreshnessPolicy | None:
        """Return an exact field policy, falling back to the provider default."""
        for field_name, policy in self.fields:
            if field_name == name:
                return policy
        return self.default


@dataclass(frozen=True)
class FreshnessPolicyCatalogue:
    """A deterministic provider-aware collection of typed freshness policies."""

    schema_version: int
    providers: tuple[ProviderFreshnessPolicies, ...]

    def provider(self, key: str) -> ProviderFreshnessPolicies | None:
        """Return the policies declared for one exact provider registry key."""
        return next((provider for provider in self.providers if provider.key == key), None)

    def policy(self, provider_key: str, field_name: str) -> ResolvedFreshnessPolicy | None:
        """Resolve one provider field without applying query-language aliases."""
        provider = self.provider(provider_key)
        return None if provider is None else provider.field(field_name)


def parse_freshness_policy(value: object, *, location: str) -> FreshnessPolicy:
    """Parse the deliberately small freshness value language."""
    if not isinstance(value, str):
        raise FreshnessConfigurationError(f"{location} must be a string freshness value")
    if value == "immutable":
        return FreshnessPolicy.immutable()
    if value == "always-refresh":
        return FreshnessPolicy.always_refresh()
    match = _DURATION.fullmatch(value)
    if match is None:
        raise FreshnessConfigurationError(
            f"{location} has unsupported freshness value {value!r}; expected a positive integer followed by m, h or d, "
            "or 'immutable' or 'always-refresh'"
        )
    amount = int(match.group(1))
    seconds = amount * _DURATION_SECONDS[match.group(2)]
    try:
        timedelta(seconds=seconds)
    except OverflowError as exc:
        raise FreshnessConfigurationError(f"{location} exceeds the supported duration range") from exc
    return FreshnessPolicy.max_age(seconds)


def _table(value: object, *, location: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise FreshnessConfigurationError(f"{location} must be a TOML table")
    return value


def _reject_unknown_keys(table: Mapping[str, object], allowed: set[str], *, location: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise FreshnessConfigurationError(f"{location} contains unsupported key(s): {', '.join(unknown)}")


def parse_freshness_configuration(
    text: str,
    *,
    origin: str,
    provider_fields: Mapping[str, Iterable[str]],
    require_complete: bool,
) -> FreshnessPolicyCatalogue:
    """Parse and validate one versioned freshness TOML document."""
    try:
        payload = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise FreshnessConfigurationError(f"{origin} is not valid TOML: {exc}") from exc

    _reject_unknown_keys(payload, {"schema_version", "providers"}, location="freshness configuration")
    schema_version = payload.get("schema_version")
    if type(schema_version) is not int or schema_version != FRESHNESS_CONFIG_SCHEMA_VERSION:
        raise FreshnessConfigurationError(
            f"freshness configuration schema_version must be {FRESHNESS_CONFIG_SCHEMA_VERSION}"
        )
    providers_table = _table(payload.get("providers"), location="providers")
    expected = {key: frozenset(fields) for key, fields in provider_fields.items()}
    unknown_providers = sorted(set(providers_table) - set(expected))
    if unknown_providers:
        raise FreshnessConfigurationError(
            f"freshness configuration contains unknown provider(s): {', '.join(unknown_providers)}"
        )
    if require_complete:
        missing_providers = sorted(set(expected) - set(providers_table))
        if missing_providers:
            raise FreshnessConfigurationError(
                f"freshness configuration is missing provider(s): {', '.join(missing_providers)}"
            )

    providers: list[ProviderFreshnessPolicies] = []
    for provider_key in sorted(providers_table):
        provider_table = _table(providers_table[provider_key], location=f"providers.{provider_key}")
        _reject_unknown_keys(provider_table, {"default", "fields"}, location=f"providers.{provider_key}")
        default = (
            None
            if "default" not in provider_table
            else ResolvedFreshnessPolicy(
                parse_freshness_policy(
                    provider_table["default"],
                    location=f"providers.{provider_key}.default",
                ),
                origin,
            )
        )
        if require_complete and default is None:
            raise FreshnessConfigurationError(f"providers.{provider_key}.default is required")
        fields_table = _table(provider_table.get("fields", {}), location=f"providers.{provider_key}.fields")
        unknown_fields = sorted(set(fields_table) - expected[provider_key])
        if unknown_fields:
            raise FreshnessConfigurationError(
                f"providers.{provider_key}.fields contains unknown field(s): {', '.join(unknown_fields)}"
            )
        if require_complete:
            missing_fields = sorted(expected[provider_key] - set(fields_table))
            if missing_fields:
                raise FreshnessConfigurationError(
                    f"providers.{provider_key}.fields is missing field(s): {', '.join(missing_fields)}"
                )
        fields = tuple(
            (
                field_name,
                ResolvedFreshnessPolicy(
                    parse_freshness_policy(
                        fields_table[field_name],
                        location=f"providers.{provider_key}.fields.{field_name}",
                    ),
                    origin,
                ),
            )
            for field_name in sorted(fields_table)
        )
        providers.append(ProviderFreshnessPolicies(provider_key, default, fields))
    return FreshnessPolicyCatalogue(schema_version, tuple(providers))


def load_freshness_configuration(
    path: Path,
    *,
    origin: str,
    provider_fields: Mapping[str, Iterable[str]],
    require_complete: bool,
) -> FreshnessPolicyCatalogue:
    """Read and parse a freshness TOML document without applying it globally."""
    expanded = path.expanduser()
    try:
        text = expanded.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise FreshnessConfigurationError(f"unable to read freshness configuration {expanded}: {exc}") from exc
    return parse_freshness_configuration(
        text,
        origin=origin,
        provider_fields=provider_fields,
        require_complete=require_complete,
    )
