"""Code-owned cache-v4 provider and field registry contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re

from .query_types import QueryType

_REGISTRY_KEY = re.compile(r"^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$")
_STORAGE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


def _require_registry_key(value: str, *, label: str) -> None:
    if not _REGISTRY_KEY.fullmatch(value):
        raise ValueError(f"{label} must be a stable lower-case registry key: {value!r}.")


def _require_storage_name(value: str, *, label: str) -> None:
    if not _STORAGE_NAME.fullmatch(value):
        raise ValueError(f"{label} must be a lower-case storage identifier: {value!r}.")


class FreshnessMode(str, Enum):
    """How long one cached field observation remains current by default."""

    MAX_AGE = "max-age"
    IMMUTABLE = "immutable"
    ALWAYS_REFRESH = "always-refresh"


@dataclass(frozen=True)
class FreshnessPolicy:
    """Validated runtime freshness semantics for one provider field."""

    mode: FreshnessMode
    max_age_seconds: int | None = None

    def __post_init__(self) -> None:
        if self.mode is FreshnessMode.MAX_AGE:
            if self.max_age_seconds is None or self.max_age_seconds <= 0:
                raise ValueError("max-age freshness requires a positive max_age_seconds value.")
        elif self.max_age_seconds is not None:
            raise ValueError(f"{self.mode.value} freshness cannot declare max_age_seconds.")

    @classmethod
    def max_age(cls, seconds: int) -> "FreshnessPolicy":
        return cls(FreshnessMode.MAX_AGE, seconds)

    @classmethod
    def immutable(cls) -> "FreshnessPolicy":
        return cls(FreshnessMode.IMMUTABLE)

    @classmethod
    def always_refresh(cls) -> "FreshnessPolicy":
        return cls(FreshnessMode.ALWAYS_REFRESH)


@dataclass(frozen=True)
class ProviderApplicability:
    """Stable semantic conditions under which a provider definition can apply."""

    services: frozenset[str] | None = None
    source_kinds: frozenset[str] | None = None
    facets: frozenset[str] | None = None
    required_source_traits: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        for label, values in (
            ("service", self.services),
            ("source kind", self.source_kinds),
            ("facet", self.facets),
            ("source trait", self.required_source_traits),
        ):
            if values is not None:
                for value in values:
                    _require_registry_key(value, label=label)


@dataclass(frozen=True)
class AcquisitionGroupDefinition:
    """One provider fetch boundary used by later acquisition-state storage."""

    key: str

    def __post_init__(self) -> None:
        _require_registry_key(self.key, label="Acquisition group key")


@dataclass(frozen=True)
class ProviderFieldDefinition:
    """One logical yt-sql field claimed by a cache provider."""

    name: str
    value_type: QueryType
    acquisition_group: str
    storage_name: str
    freshness: FreshnessPolicy

    def __post_init__(self) -> None:
        if not self.name or self.name != self.name.strip():
            raise ValueError("Provider field names must be non-empty and have no surrounding whitespace.")
        _require_registry_key(self.acquisition_group, label="Acquisition group key")
        _require_storage_name(self.storage_name, label="Field storage name")


@dataclass(frozen=True)
class ProviderDefinition:
    """The installed semantic and storage contract for one cache provider.

    Deployment policy such as enabled state, provider priority and persistent
    registration order deliberately does not live here. Cache-v4 persistence owns
    that state and reconciles it with these declarations.
    """

    key: str
    schema_revision: int
    metadata_table: str
    acquisition_groups: tuple[AcquisitionGroupDefinition, ...]
    fields: tuple[ProviderFieldDefinition, ...]
    applicability: ProviderApplicability = ProviderApplicability()

    def __post_init__(self) -> None:
        _require_registry_key(self.key, label="Provider key")
        if self.schema_revision <= 0:
            raise ValueError("Provider schema_revision must be a positive integer.")
        _require_storage_name(self.metadata_table, label="Provider metadata table")

        group_keys = tuple(group.key for group in self.acquisition_groups)
        if len(set(group_keys)) != len(group_keys):
            raise ValueError(f"Provider {self.key!r} declares duplicate acquisition groups.")
        field_names = tuple(field.name for field in self.fields)
        if len(set(field_names)) != len(field_names):
            raise ValueError(f"Provider {self.key!r} declares duplicate logical fields.")
        storage_names = tuple(field.storage_name for field in self.fields)
        if len(set(storage_names)) != len(storage_names):
            raise ValueError(f"Provider {self.key!r} declares duplicate field storage names.")

        groups = set(group_keys)
        for field in self.fields:
            if field.acquisition_group not in groups:
                raise ValueError(
                    f"Provider field {field.name!r} references undeclared acquisition group "
                    f"{field.acquisition_group!r}."
                )

    def field(self, name: str) -> ProviderFieldDefinition | None:
        """Return this provider's exact logical-field declaration, if present."""
        return next((field for field in self.fields if field.name == name), None)
