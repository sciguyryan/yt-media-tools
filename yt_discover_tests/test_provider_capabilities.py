"""Provider-capability contract tests for backend-neutral acquisition planning."""

from yt_media_tools.provider_capabilities import (
    AUTH_ANONYMOUS,
    AUTH_COOKIES,
    AUTHORITY_APPROXIMATE,
    AUTHORITY_EXACT,
    GRANULARITY_BATCH,
    GRANULARITY_ENTRY,
    MetadataRequirement,
    ProviderCapability,
    ProviderSelectionContext,
    eligible_provider_candidates,
    select_provider_capability,
)


def capability(
    provider: str,
    *,
    fields: frozenset[str] | None = None,
    authority: str = AUTHORITY_EXACT,
    source_kinds: frozenset[str] | None = None,
    authentication: frozenset[str] = frozenset({AUTH_ANONYMOUS}),
    granularity: str = GRANULARITY_ENTRY,
    cost_rank: int = 100,
) -> ProviderCapability:
    return ProviderCapability(
        provider=provider,
        stage="complete-metadata",
        fields=fields,
        authority=authority,
        source_kinds=source_kinds,
        authentication=authentication,
        granularity=granularity,
        cost_rank=cost_rank,
        provenance=f"test:{provider}",
    )


def test_selection_prefers_lower_cost_exact_capability() -> None:
    requirement = MetadataRequirement("complete-metadata", frozenset({"duration", "view_count"}))
    candidates = (
        capability("broad", cost_rank=100),
        capability("narrow", fields=requirement.fields, granularity=GRANULARITY_BATCH, cost_rank=20),
    )

    selected = select_provider_capability(requirement, candidates)

    assert selected is not None
    assert selected.capability.provider == "narrow"


def test_approximate_capability_never_satisfies_exact_requirement() -> None:
    requirement = MetadataRequirement("complete-metadata", frozenset({"view_count"}))
    candidates = (capability("approximate", authority=AUTHORITY_APPROXIMATE, cost_rank=1),)

    assert select_provider_capability(requirement, candidates) is None


def test_finite_field_capability_must_cover_every_required_field() -> None:
    requirement = MetadataRequirement("complete-metadata", frozenset({"duration", "view_count"}))
    candidates = (capability("duration-only", fields=frozenset({"duration"}), cost_rank=1),)

    assert select_provider_capability(requirement, candidates) is None


def test_source_specific_provider_requires_matching_resolved_identity() -> None:
    requirement = MetadataRequirement("complete-metadata", frozenset({"duration"}))
    youtube = capability("youtube-provider", source_kinds=frozenset({"youtube"}), cost_rank=1)

    assert select_provider_capability(requirement, (youtube,)) is None
    assert (
        select_provider_capability(
            requirement,
            (youtube,),
            context=ProviderSelectionContext(resolved_source_kind="twitch"),
        )
        is None
    )
    selected = select_provider_capability(
        requirement,
        (youtube,),
        context=ProviderSelectionContext(resolved_source_kind="youtube"),
    )
    assert selected is not None
    assert selected.capability.provider == "youtube-provider"


def test_cookie_requirement_excludes_anonymous_only_provider() -> None:
    requirement = MetadataRequirement("complete-metadata", frozenset({"duration"}))
    anonymous = capability("anonymous", cost_rank=1)
    cookies = capability(
        "cookies",
        authentication=frozenset({AUTH_ANONYMOUS, AUTH_COOKIES}),
        cost_rank=2,
    )

    selected = select_provider_capability(
        requirement,
        (anonymous, cookies),
        context=ProviderSelectionContext(authentication=AUTH_COOKIES),
    )

    assert selected is not None
    assert selected.capability.provider == "cookies"


def test_candidate_order_is_deterministic_for_equal_cost() -> None:
    requirement = MetadataRequirement("complete-metadata", frozenset({"duration"}))
    candidates = (
        capability("zeta", cost_rank=10),
        capability("alpha", cost_rank=10),
    )

    eligible = eligible_provider_candidates(requirement, candidates)

    assert [item.capability.provider for item in eligible] == ["alpha", "zeta"]


def test_stage_mismatch_is_not_eligible() -> None:
    requirement = MetadataRequirement("formats", frozenset({"formats"}))

    assert select_provider_capability(requirement, (capability("metadata"),)) is None


def test_physical_plan_projects_existing_stages_into_provider_requirements() -> None:
    from yt_media_tools.acquisition_plan import plan_physical_acquisition
    from yt_media_tools.source_model import SourceSpec

    plan = plan_physical_acquisition(
        source=SourceSpec("generic", "https://example.invalid/source", "https://example.invalid/source"),
        required_fields=frozenset({"id", "duration"}),
        enumeration_fields=frozenset({"id"}),
        detailed_fields=frozenset({"duration"}),
    )

    assert [(item.stage, item.fields) for item in plan.provider_requirements] == [
        ("enumerate-identities", frozenset({"id"})),
        ("complete-metadata", frozenset({"duration"})),
    ]


def test_backend_resolution_constrains_source_specific_provider_eligibility() -> None:
    from yt_media_tools.provider_capabilities import selection_context_from_backend_resolution
    from yt_media_tools.source_resolution import observed_ytdlp_resolutions

    requirement = MetadataRequirement("complete-metadata", frozenset({"duration"}))
    youtube = capability("youtube-provider", source_kinds=frozenset({"youtube"}), cost_rank=1)
    generic = capability("generic-provider", cost_rank=50)
    resolutions = observed_ytdlp_resolutions([{"extractor": "youtube:tab", "extractor_key": "YoutubeTab"}])

    selected = select_provider_capability(
        requirement,
        (generic, youtube),
        context=selection_context_from_backend_resolution(resolutions),
    )

    assert selected is not None
    assert selected.capability.provider == "youtube-provider"


def test_unresolved_backend_identity_preserves_generic_fallback() -> None:
    from yt_media_tools.provider_capabilities import selection_context_from_backend_resolution
    from yt_media_tools.source_resolution import observed_ytdlp_resolutions

    requirement = MetadataRequirement("complete-metadata", frozenset({"duration"}))
    youtube = capability("youtube-provider", source_kinds=frozenset({"youtube"}), cost_rank=1)
    generic = capability("generic-provider", cost_rank=50)
    resolutions = observed_ytdlp_resolutions(
        [{"extractor": "generic", "extractor_key": "Generic", "webpage_url_domain": "youtube.com"}]
    )

    selected = select_provider_capability(
        requirement,
        (generic, youtube),
        context=selection_context_from_backend_resolution(resolutions),
    )

    assert selected is not None
    assert selected.capability.provider == "generic-provider"


def test_cookie_requirement_is_preserved_when_resolution_context_is_built() -> None:
    from yt_media_tools.provider_capabilities import selection_context_from_backend_resolution
    from yt_media_tools.source_resolution import observed_ytdlp_resolutions

    requirement = MetadataRequirement("complete-metadata", frozenset({"duration"}))
    anonymous = capability("anonymous-youtube", source_kinds=frozenset({"youtube"}), cost_rank=1)
    cookies = capability(
        "cookie-youtube",
        source_kinds=frozenset({"youtube"}),
        authentication=frozenset({AUTH_COOKIES}),
        cost_rank=2,
    )
    resolutions = observed_ytdlp_resolutions([{"extractor": "youtube", "extractor_key": "Youtube"}])

    selected = select_provider_capability(
        requirement,
        (anonymous, cookies),
        context=selection_context_from_backend_resolution(resolutions, authentication=AUTH_COOKIES),
    )

    assert selected is not None
    assert selected.capability.provider == "cookie-youtube"
