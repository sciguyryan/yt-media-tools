"""Contract tests for the code-owned cache-v4 registry vocabulary."""

from dataclasses import replace

import pytest

from yt_media_tools.cache_registry import (
    AcquisitionGroupDefinition,
    FreshnessMode,
    FreshnessPolicy,
    ProviderApplicability,
    ProviderDefinition,
    ProviderFieldDefinition,
)
from yt_media_tools.query_types import QueryType


def _provider(**changes: object) -> ProviderDefinition:
    base = ProviderDefinition(
        key="youtubejs",
        schema_revision=1,
        metadata_table="provider_youtubejs",
        acquisition_groups=(AcquisitionGroupDefinition("basic-info"),),
        fields=(
            ProviderFieldDefinition(
                name="duration",
                value_type=QueryType.scalar("duration"),
                acquisition_group="basic-info",
                storage_name="duration",
                freshness=FreshnessPolicy.max_age(30 * 24 * 60 * 60),
            ),
        ),
        applicability=ProviderApplicability(services=frozenset({"youtube"})),
    )
    return replace(base, **changes)


def test_provider_definition_carries_semantic_contract_without_runtime_policy() -> None:
    provider = _provider()
    assert provider.key == "youtubejs"
    assert provider.schema_revision == 1
    assert provider.metadata_table == "provider_youtubejs"
    assert provider.field("duration") is provider.fields[0]
    assert provider.field("title") is None
    assert not hasattr(provider, "priority")
    assert not hasattr(provider, "enabled")
    assert not hasattr(provider, "registration_order")


def test_freshness_modes_are_explicit_and_self_consistent() -> None:
    assert FreshnessPolicy.max_age(60).mode is FreshnessMode.MAX_AGE
    assert FreshnessPolicy.immutable().mode is FreshnessMode.IMMUTABLE
    assert FreshnessPolicy.always_refresh().mode is FreshnessMode.ALWAYS_REFRESH
    with pytest.raises(ValueError, match="positive"):
        FreshnessPolicy.max_age(0)
    with pytest.raises(ValueError, match="cannot declare"):
        FreshnessPolicy(FreshnessMode.IMMUTABLE, 60)


def test_provider_schema_revision_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        _provider(schema_revision=0)


def test_registry_identifiers_are_stable_and_storage_names_are_sql_safe() -> None:
    with pytest.raises(ValueError, match="stable lower-case"):
        _provider(key="YouTubeJS")
    with pytest.raises(ValueError, match="storage identifier"):
        _provider(metadata_table="provider-youtubejs")


def test_provider_rejects_duplicate_groups_fields_and_storage_names() -> None:
    group = AcquisitionGroupDefinition("basic-info")
    with pytest.raises(ValueError, match="duplicate acquisition groups"):
        _provider(acquisition_groups=(group, group))
    field = _provider().fields[0]
    with pytest.raises(ValueError, match="duplicate logical fields"):
        _provider(fields=(field, field))
    other = replace(field, name="title")
    with pytest.raises(ValueError, match="duplicate field storage names"):
        _provider(fields=(field, other))


def test_field_must_reference_a_declared_acquisition_group() -> None:
    field = replace(_provider().fields[0], acquisition_group="formats")
    with pytest.raises(ValueError, match="undeclared acquisition group"):
        _provider(fields=(field,))


def test_applicability_reuses_stable_source_vocabulary_without_provider_priority() -> None:
    applicability = ProviderApplicability(
        services=frozenset({"youtube"}),
        source_kinds=frozenset({"youtube-channel"}),
        facets=frozenset({"videos", "live"}),
        required_source_traits=frozenset({"music"}),
    )
    assert applicability.services == frozenset({"youtube"})
    assert applicability.required_source_traits == frozenset({"music"})


def test_field_type_is_the_existing_yt_sql_query_type_contract() -> None:
    field = _provider().fields[0]
    assert field.value_type == QueryType.scalar("duration")
    assert field.value_type.describe() == "duration?"
