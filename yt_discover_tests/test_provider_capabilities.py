"""Provider-capability contract tests for backend-neutral acquisition planning."""

from itertools import combinations

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
    service_families: frozenset[str] | None = None,
    required_source_traits: frozenset[str] = frozenset(),
    authentication: frozenset[str] = frozenset({AUTH_ANONYMOUS}),
    granularity: str = GRANULARITY_ENTRY,
    cost_rank: int = 100,
) -> ProviderCapability:
    return ProviderCapability(
        provider=provider,
        stage="complete-metadata",
        fields=fields,
        authority=authority,
        service_families=service_families,
        required_source_traits=required_source_traits,
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
    youtube = capability("youtube-provider", service_families=frozenset({"youtube"}), cost_rank=1)

    assert select_provider_capability(requirement, (youtube,)) is None
    assert (
        select_provider_capability(
            requirement,
            (youtube,),
            context=ProviderSelectionContext(resolved_service_family="twitch"),
        )
        is None
    )
    selected = select_provider_capability(
        requirement,
        (youtube,),
        context=ProviderSelectionContext(resolved_service_family="youtube"),
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
    youtube = capability("youtube-provider", service_families=frozenset({"youtube"}), cost_rank=1)
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
    youtube = capability("youtube-provider", service_families=frozenset({"youtube"}), cost_rank=1)
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
    anonymous = capability("anonymous-youtube", service_families=frozenset({"youtube"}), cost_rank=1)
    cookies = capability(
        "cookie-youtube",
        service_families=frozenset({"youtube"}),
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


def test_production_youtubejs_exact_scalar_capability_is_deliberately_bounded() -> None:
    from yt_media_tools.provider_capabilities import (
        YOUTUBEJS_EXACT_SCALAR_FIELDS,
        production_provider_capabilities,
    )

    capability = production_provider_capabilities()[0]

    assert capability.provider == "youtubejs"
    assert capability.provenance == "youtubejs:getBasicInfo"
    assert capability.fields == YOUTUBEJS_EXACT_SCALAR_FIELDS
    assert capability.fields == frozenset({"id", "title", "channel_id", "duration", "view_count"})
    assert "upload_date" not in capability.fields
    assert "date" not in capability.fields
    assert "is_live" not in capability.fields


def test_youtubejs_exact_scalar_requires_resolved_youtube_source() -> None:
    from yt_media_tools.provider_capabilities import production_provider_capabilities

    requirement = MetadataRequirement("complete-metadata", frozenset({"duration", "view_count"}))
    capabilities = production_provider_capabilities()

    assert select_provider_capability(requirement, capabilities) is None
    assert (
        select_provider_capability(
            requirement,
            capabilities,
            context=ProviderSelectionContext(resolved_service_family="vimeo"),
        )
        is None
    )
    selected = select_provider_capability(
        requirement,
        capabilities,
        context=ProviderSelectionContext(resolved_service_family="youtube"),
    )
    assert selected is not None
    assert selected.capability.provider == "youtubejs"


def test_youtubejs_exact_scalar_rejects_mixed_unsupported_requirement() -> None:
    from yt_media_tools.provider_capabilities import production_provider_capabilities

    requirement = MetadataRequirement("complete-metadata", frozenset({"duration", "upload_date"}))

    assert (
        select_provider_capability(
            requirement,
            production_provider_capabilities(),
            context=ProviderSelectionContext(resolved_service_family="youtube"),
        )
        is None
    )


def test_youtubejs_exact_scalar_accepts_cookie_context_without_exposing_cookie_data() -> None:
    from yt_media_tools.provider_capabilities import production_provider_capabilities

    requirement = MetadataRequirement("complete-metadata", frozenset({"channel_id"}))
    selected = select_provider_capability(
        requirement,
        production_provider_capabilities(),
        context=ProviderSelectionContext(resolved_service_family="youtube", authentication=AUTH_COOKIES),
    )

    assert selected is not None
    assert selected.capability.provenance == "youtubejs:getBasicInfo"
    assert "cookie" not in selected.reason.casefold()


def test_production_lowering_maps_only_wholly_supported_youtubejs_requirement() -> None:
    from yt_media_tools.provider_capabilities import (
        MetadataRequirement,
        ProviderSelectionContext,
        lower_provider_requirements,
    )

    requirements = (
        MetadataRequirement("complete-metadata", frozenset({"duration", "view_count"})),
        MetadataRequirement("complete-metadata", frozenset({"duration", "upload_date"})),
        MetadataRequirement("formats", frozenset({"formats"})),
    )
    lowered = lower_provider_requirements(
        requirements,
        context=ProviderSelectionContext(resolved_service_family="youtube"),
    )

    assert len(lowered) == 1
    assert lowered[0].requirement == requirements[0]
    assert lowered[0].candidate.capability.provider == "youtubejs"
    assert lowered[0].candidate.capability.provenance == "youtubejs:getBasicInfo"


def test_production_lowering_does_not_select_youtubejs_without_resolved_youtube_evidence() -> None:
    from yt_media_tools.provider_capabilities import MetadataRequirement, lower_provider_requirements

    requirements = (MetadataRequirement("complete-metadata", frozenset({"title", "duration"})),)

    assert lower_provider_requirements(requirements) == ()


def test_youtubejs_exact_scalar_all_nonempty_field_subsets_are_eligible() -> None:
    """Every subset of the closed authority surface must lower identically."""
    from itertools import combinations

    from yt_media_tools.provider_capabilities import (
        YOUTUBEJS_EXACT_SCALAR_FIELDS,
        production_provider_capabilities,
    )

    fields = sorted(YOUTUBEJS_EXACT_SCALAR_FIELDS)
    context = ProviderSelectionContext(resolved_service_family="youtube")
    capabilities = production_provider_capabilities()
    for size in range(1, len(fields) + 1):
        for subset in combinations(fields, size):
            requirement = MetadataRequirement("complete-metadata", frozenset(subset))
            selected = select_provider_capability(requirement, capabilities, context=context)
            assert selected is not None, subset
            assert selected.capability.provider == "youtubejs"


def test_youtubejs_exact_scalar_unsupported_fields_poison_complete_lowering() -> None:
    """One unsupported field must keep the whole semantic stage off YouTube.js."""
    from yt_media_tools.provider_capabilities import production_provider_capabilities

    context = ProviderSelectionContext(resolved_service_family="youtube")
    for unsupported in (
        "upload_date",
        "date",
        "description",
        "keywords",
        "is_live",
        "is_private",
        "is_unlisted",
        "category",
    ):
        requirement = MetadataRequirement("complete-metadata", frozenset({"duration", unsupported}))
        assert (
            select_provider_capability(
                requirement,
                production_provider_capabilities(),
                context=context,
            )
            is None
        ), unsupported


def test_source_trait_requirement_is_positive_and_conservative() -> None:
    requirement = MetadataRequirement("complete-metadata", frozenset({"duration"}))
    music = capability(
        "music-provider",
        service_families=frozenset({"youtube"}),
        required_source_traits=frozenset({"music"}),
        cost_rank=1,
    )

    assert (
        select_provider_capability(
            requirement,
            (music,),
            context=ProviderSelectionContext(resolved_service_family="youtube"),
        )
        is None
    )
    selected = select_provider_capability(
        requirement,
        (music,),
        context=ProviderSelectionContext(
            resolved_service_family="youtube",
            source_traits=frozenset({"music"}),
        ),
    )
    assert selected is not None
    assert selected.capability.provider == "music-provider"


def test_production_ytmusicapi_capability_requires_positive_music_evidence() -> None:
    from yt_media_tools.provider_capabilities import (
        SOURCE_TRAIT_MUSIC,
        YTMUSICAPI_EXACT_SCALAR_FIELDS,
        production_provider_capabilities,
    )

    capabilities = production_provider_capabilities()
    ytmusicapi = next(item for item in capabilities if item.provider == "ytmusicapi")
    requirement = MetadataRequirement("complete-metadata", frozenset({"duration", "view_count"}))

    assert ytmusicapi.provenance == "ytmusicapi:YTMusic.get_song"
    assert ytmusicapi.fields == YTMUSICAPI_EXACT_SCALAR_FIELDS
    assert ytmusicapi.fields == frozenset({"id", "title", "channel_id", "duration", "view_count"})
    assert ytmusicapi.required_source_traits == frozenset({SOURCE_TRAIT_MUSIC})
    assert ytmusicapi.authentication == frozenset({AUTH_ANONYMOUS})
    assert "upload_date" not in ytmusicapi.fields
    assert "description" not in ytmusicapi.fields
    assert "musicVideoType" not in ytmusicapi.fields

    youtube_only = ProviderSelectionContext(resolved_service_family="youtube")
    assert all(
        candidate.capability.provider != "ytmusicapi"
        for candidate in eligible_provider_candidates(requirement, capabilities, context=youtube_only)
    )

    music_context = ProviderSelectionContext(
        resolved_service_family="youtube",
        source_traits=frozenset({SOURCE_TRAIT_MUSIC}),
    )
    assert any(
        candidate.capability.provider == "ytmusicapi"
        for candidate in eligible_provider_candidates(requirement, capabilities, context=music_context)
    )


def test_ytmusicapi_cannot_self_authorise_from_unsupported_or_provider_native_fields() -> None:
    from yt_media_tools.provider_capabilities import SOURCE_TRAIT_MUSIC, production_provider_capabilities

    context = ProviderSelectionContext(
        resolved_service_family="youtube",
        source_traits=frozenset({SOURCE_TRAIT_MUSIC}),
    )
    capabilities = production_provider_capabilities()
    for unsupported in ("upload_date", "description", "keywords", "category", "is_live", "musicVideoType"):
        requirement = MetadataRequirement("complete-metadata", frozenset({"duration", unsupported}))
        assert all(
            candidate.capability.provider != "ytmusicapi"
            for candidate in eligible_provider_candidates(requirement, capabilities, context=context)
        ), unsupported


def test_ytmusicapi_browser_or_cookie_authentication_is_not_a_production_requirement() -> None:
    from yt_media_tools.provider_capabilities import SOURCE_TRAIT_MUSIC, production_provider_capabilities

    requirement = MetadataRequirement("complete-metadata", frozenset({"duration"}))
    context = ProviderSelectionContext(
        resolved_service_family="youtube",
        source_traits=frozenset({SOURCE_TRAIT_MUSIC}),
        authentication=AUTH_COOKIES,
    )
    assert all(
        candidate.capability.provider != "ytmusicapi"
        for candidate in eligible_provider_candidates(requirement, production_provider_capabilities(), context=context)
    )


def test_backend_resolution_context_derives_music_trait_only_from_confirmed_music_origin() -> None:
    from yt_media_tools.provider_capabilities import SOURCE_TRAIT_MUSIC, selection_context_from_backend_resolution
    from yt_media_tools.source_resolution import observed_ytdlp_resolutions

    resolutions = observed_ytdlp_resolutions(
        [
            {
                "extractor": "youtube",
                "extractor_key": "Youtube",
                "original_url": "https://music.youtube.com/watch?v=example",
                "webpage_url": "https://www.youtube.com/watch?v=example",
            }
        ]
    )
    context = selection_context_from_backend_resolution(resolutions)

    assert context.resolved_service_family == "youtube"
    assert context.source_traits == frozenset({SOURCE_TRAIT_MUSIC})


def test_confirmed_music_origin_makes_ytmusicapi_eligible_without_provider_self_evidence() -> None:
    from yt_media_tools.provider_capabilities import (
        production_provider_capabilities,
        selection_context_from_backend_resolution,
    )
    from yt_media_tools.source_resolution import observed_ytdlp_resolutions

    requirement = MetadataRequirement("complete-metadata", frozenset({"duration", "view_count"}))
    resolutions = observed_ytdlp_resolutions(
        [
            {
                "extractor": "youtube",
                "extractor_key": "Youtube",
                "original_url": "https://music.youtube.com/watch?v=example",
            }
        ]
    )
    context = selection_context_from_backend_resolution(resolutions)

    assert any(
        candidate.capability.provider == "ytmusicapi"
        for candidate in eligible_provider_candidates(requirement, production_provider_capabilities(), context=context)
    )


def test_ytmusicapi_every_non_empty_authoritative_field_subset_is_eligible_with_music_evidence() -> None:
    from yt_media_tools.provider_capabilities import (
        SOURCE_TRAIT_MUSIC,
        YTMUSICAPI_EXACT_SCALAR_FIELDS,
        production_provider_capabilities,
    )

    capabilities = production_provider_capabilities()
    context = ProviderSelectionContext(
        resolved_service_family="youtube",
        source_traits=frozenset({SOURCE_TRAIT_MUSIC}),
    )
    fields = sorted(YTMUSICAPI_EXACT_SCALAR_FIELDS)
    for size in range(1, len(fields) + 1):
        for subset in combinations(fields, size):
            requirement = MetadataRequirement("complete-metadata", frozenset(subset))
            candidates = eligible_provider_candidates(requirement, capabilities, context=context)
            assert any(candidate.capability.provider == "ytmusicapi" for candidate in candidates), subset


def test_ytmusicapi_unsupported_field_contamination_rejects_the_whole_capability() -> None:
    from yt_media_tools.provider_capabilities import (
        SOURCE_TRAIT_MUSIC,
        YTMUSICAPI_EXACT_SCALAR_FIELDS,
        production_provider_capabilities,
    )

    capabilities = production_provider_capabilities()
    context = ProviderSelectionContext(
        resolved_service_family="youtube",
        source_traits=frozenset({SOURCE_TRAIT_MUSIC}),
    )
    unsupported_fields = (
        "upload_date",
        "date",
        "description",
        "keywords",
        "category",
        "is_live",
        "is_private",
        "is_unlisted",
        "musicVideoType",
    )
    for supported in sorted(YTMUSICAPI_EXACT_SCALAR_FIELDS):
        for unsupported in unsupported_fields:
            requirement = MetadataRequirement("complete-metadata", frozenset({supported, unsupported}))
            candidates = eligible_provider_candidates(requirement, capabilities, context=context)
            assert all(candidate.capability.provider != "ytmusicapi" for candidate in candidates), (
                supported,
                unsupported,
            )


def test_ytmusicapi_candidate_order_is_independent_of_capability_declaration_order() -> None:
    from yt_media_tools.provider_capabilities import SOURCE_TRAIT_MUSIC, production_provider_capabilities

    requirement = MetadataRequirement("complete-metadata", frozenset({"duration", "view_count"}))
    context = ProviderSelectionContext(
        resolved_service_family="youtube",
        source_traits=frozenset({SOURCE_TRAIT_MUSIC}),
    )
    capabilities = production_provider_capabilities()

    forward = eligible_provider_candidates(requirement, capabilities, context=context)
    reverse = eligible_provider_candidates(requirement, tuple(reversed(capabilities)), context=context)

    assert (
        [candidate.capability.provenance for candidate in forward]
        == [candidate.capability.provenance for candidate in reverse]
        == ["youtubejs:getBasicInfo", "ytmusicapi:YTMusic.get_song"]
    )


def test_logical_source_and_facet_constraints_are_independent_of_service_evidence() -> None:
    requirement = MetadataRequirement("complete-metadata", frozenset({"duration"}))
    constrained = ProviderCapability(
        provider="facet-provider",
        stage="complete-metadata",
        fields=frozenset({"duration"}),
        authority=AUTHORITY_EXACT,
        service_families=frozenset({"youtube"}),
        required_source_traits=frozenset(),
        authentication=frozenset({AUTH_ANONYMOUS}),
        granularity=GRANULARITY_ENTRY,
        cost_rank=1,
        provenance="test:facet-provider",
        logical_source_kinds=frozenset({"channel"}),
        logical_facets=frozenset({"shorts"}),
    )

    assert (
        select_provider_capability(
            requirement,
            (constrained,),
            context=ProviderSelectionContext(
                resolved_service_family="youtube",
                logical_source_kind="channel",
                logical_facet="videos",
            ),
        )
        is None
    )
    selected = select_provider_capability(
        requirement,
        (constrained,),
        context=ProviderSelectionContext(
            resolved_service_family="youtube",
            logical_source_kind="channel",
            logical_facet="shorts",
        ),
    )
    assert selected is not None
    assert selected.capability.provider == "facet-provider"
