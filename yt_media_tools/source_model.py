"""Stable physical and logical source identity for yt-discover."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceSpec:
    """Resolved physical source and, when selected, its logical facet."""

    kind: str
    original: str
    canonical_url: str
    identifier: str | None = None
    facet: str | None = None


@dataclass(frozen=True)
class PhysicalSourceIdentity:
    """Stable identity of the underlying physical collection before facet selection."""

    kind: str
    adapter: str
    canonical_url: str
    identifier: str | None = None


@dataclass(frozen=True)
class LogicalSourceIdentity:
    """Stable identity of the logical collection actually queried and cached."""

    physical: PhysicalSourceIdentity
    canonical_url: str
    facet: str | None = None

    @property
    def cache_key(self) -> str:
        """Return the existing source-scoped cache/frontier identity."""
        return self.canonical_url

    @property
    def provenance_key(self) -> str:
        """Return the existing source URL used to identify provenance."""
        return self.canonical_url
