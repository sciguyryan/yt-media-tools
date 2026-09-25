"""Backend-neutral metadata provider capability and selection contracts."""

from __future__ import annotations

from dataclasses import dataclass

AUTH_ANONYMOUS = "anonymous"
AUTH_COOKIES = "cookies"

AUTHORITY_EXACT = "exact"
AUTHORITY_APPROXIMATE = "approximate"

GRANULARITY_SOURCE = "source"
GRANULARITY_ENTRY = "entry"
GRANULARITY_BATCH = "batch"


@dataclass(frozen=True)
class MetadataRequirement:
    """One semantic acquisition requirement awaiting physical satisfaction."""

    stage: str
    fields: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ProviderCapability:
    """One provider's declared ability to satisfy a semantic requirement.

    ``fields=None`` means that the capability covers every field represented by the
    named semantic stage. A finite field set is deliberately conservative: the
    capability is eligible only when every requested field is declared.
    """

    provider: str
    stage: str
    fields: frozenset[str] | None
    authority: str
    source_kinds: frozenset[str] | None
    required_source_traits: frozenset[str]
    authentication: frozenset[str]
    granularity: str
    cost_rank: int
    provenance: str

    def supports(self, requirement: MetadataRequirement) -> bool:
        """Return whether this capability covers the requirement semantically."""
        if self.stage != requirement.stage:
            return False
        return self.fields is None or requirement.fields <= self.fields


@dataclass(frozen=True)
class ProviderSelectionContext:
    """Known physical facts that may conservatively constrain provider eligibility."""

    resolved_source_kind: str | None = None
    source_traits: frozenset[str] = frozenset()
    authentication: str = AUTH_ANONYMOUS


@dataclass(frozen=True)
class ProviderCandidate:
    """One eligible exact provider capability in deterministic preference order."""

    capability: ProviderCapability
    reason: str


def eligible_provider_candidates(
    requirement: MetadataRequirement,
    capabilities: tuple[ProviderCapability, ...],
    *,
    context: ProviderSelectionContext = ProviderSelectionContext(),
) -> tuple[ProviderCandidate, ...]:
    """Return exact provider candidates without changing logical query semantics.

    Approximate capabilities are intentionally excluded. Unknown source identity is
    conservative: a source-specific provider cannot be selected until the source has
    been resolved sufficiently to prove its applicability. Cost is a physical-plan
    hint only and never weakens semantic authority.
    """
    candidates: list[ProviderCandidate] = []
    for capability in capabilities:
        if capability.authority != AUTHORITY_EXACT:
            continue
        if not capability.supports(requirement):
            continue
        if context.authentication not in capability.authentication:
            continue
        if not capability.required_source_traits <= context.source_traits:
            continue
        if capability.source_kinds is not None:
            if context.resolved_source_kind is None:
                continue
            if context.resolved_source_kind not in capability.source_kinds:
                continue
        candidates.append(
            ProviderCandidate(
                capability,
                (
                    f"{capability.provider} can satisfy {requirement.stage} exactly "
                    f"using {capability.granularity} acquisition at cost rank {capability.cost_rank}"
                ),
            )
        )
    candidates.sort(key=lambda item: (item.capability.cost_rank, item.capability.provider, item.capability.provenance))
    return tuple(candidates)


def select_provider_capability(
    requirement: MetadataRequirement,
    capabilities: tuple[ProviderCapability, ...],
    *,
    context: ProviderSelectionContext = ProviderSelectionContext(),
) -> ProviderCandidate | None:
    """Return the deterministic preferred exact capability, if one is eligible."""
    candidates = eligible_provider_candidates(requirement, capabilities, context=context)
    return candidates[0] if candidates else None


def selection_context_from_backend_resolution(
    resolutions: tuple[object, ...],
    *,
    authentication: str = AUTH_ANONYMOUS,
) -> ProviderSelectionContext:
    """Build provider-selection context from conservative backend resolution evidence."""
    from .source_resolution import resolved_source_kind, resolved_source_traits

    return ProviderSelectionContext(
        resolved_source_kind=resolved_source_kind(resolutions),
        source_traits=resolved_source_traits(resolutions),
        authentication=authentication,
    )


@dataclass(frozen=True)
class ProviderLowering:
    """One semantic requirement lowered to an eligible physical provider operation."""

    requirement: MetadataRequirement
    candidate: ProviderCandidate


def lower_provider_requirements(
    requirements: tuple[MetadataRequirement, ...],
    *,
    context: ProviderSelectionContext = ProviderSelectionContext(),
    capabilities: tuple[ProviderCapability, ...] | None = None,
) -> tuple[ProviderLowering, ...]:
    """Lower only wholly satisfiable requirements without inventing partial authority.

    Requirements without an eligible specialised capability are deliberately omitted;
    the established acquisition path remains responsible for them. This keeps lowering
    below yt-sql semantics and prevents a cheap provider from satisfying only part of
    a semantic stage.
    """
    available = production_provider_capabilities() if capabilities is None else capabilities
    lowered: list[ProviderLowering] = []
    for requirement in requirements:
        candidate = select_provider_capability(requirement, available, context=context)
        if candidate is not None:
            lowered.append(ProviderLowering(requirement, candidate))
    return tuple(lowered)


YOUTUBE_SOURCE_KINDS = frozenset({"youtube"})
SOURCE_TRAIT_MUSIC = "music"
YOUTUBEJS_EXACT_SCALAR_FIELDS = frozenset({"id", "title", "channel_id", "duration", "view_count"})
YTMUSICAPI_EXACT_SCALAR_FIELDS = frozenset({"id", "title", "channel_id", "duration", "view_count"})


def production_provider_capabilities() -> tuple[ProviderCapability, ...]:
    """Return production provider capabilities in declaration-independent form.

    The registry is physical planning data, not yt-sql semantics. YouTube.js is
    deliberately bounded to the exact scalar fields established by the retained
    provider investigation. In particular, publication dates and provider-native
    state flags are not advertised here. ytmusicapi is additionally constrained by a
    provider-neutral positive music-source trait and anonymous acquisition; a successful
    ``get_song()`` call cannot manufacture its own eligibility.
    """
    return (
        ProviderCapability(
            provider="youtubejs",
            stage="complete-metadata",
            fields=YOUTUBEJS_EXACT_SCALAR_FIELDS,
            authority=AUTHORITY_EXACT,
            source_kinds=YOUTUBE_SOURCE_KINDS,
            required_source_traits=frozenset(),
            authentication=frozenset({AUTH_ANONYMOUS, AUTH_COOKIES}),
            granularity=GRANULARITY_ENTRY,
            cost_rank=20,
            provenance="youtubejs:getBasicInfo",
        ),
        ProviderCapability(
            provider="ytmusicapi",
            stage="complete-metadata",
            fields=YTMUSICAPI_EXACT_SCALAR_FIELDS,
            authority=AUTHORITY_EXACT,
            source_kinds=YOUTUBE_SOURCE_KINDS,
            required_source_traits=frozenset({SOURCE_TRAIT_MUSIC}),
            authentication=frozenset({AUTH_ANONYMOUS}),
            granularity=GRANULARITY_ENTRY,
            cost_rank=30,
            provenance="ytmusicapi:YTMusic.get_song",
        ),
    )
