"""Reconciliation checks for the Discover 0.27.x architectural boundaries."""

from yt_media_tools import capabilities, source_capabilities, source_model, sources


def test_capability_compatibility_exports_are_identity_preserving():
    assert capabilities.EXACT is source_capabilities.EXACT
    assert capabilities.APPROXIMATE is source_capabilities.APPROXIMATE
    assert capabilities.UNAVAILABLE is source_capabilities.UNAVAILABLE
    assert capabilities.FieldCapability is source_capabilities.FieldCapability
    assert capabilities.field_capability is source_capabilities.field_capability
    assert capabilities.capabilities_for_fields is source_capabilities.capabilities_for_fields


def test_source_compatibility_exports_are_identity_preserving():
    assert sources.SourceSpec is source_model.SourceSpec
    assert sources.LogicalSourceIdentity is source_model.LogicalSourceIdentity
    assert sources.PhysicalSourceIdentity is source_model.PhysicalSourceIdentity
    assert sources.SourceCapabilities is source_capabilities.SourceCapabilities
    assert sources.source_capabilities is source_capabilities.source_capabilities
    assert sources.selected_facet_capabilities is source_capabilities.selected_facet_capabilities
    assert sources.logical_source_identity is source_capabilities.logical_source_identity
