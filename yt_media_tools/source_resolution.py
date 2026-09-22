"""Backend-reported source and extractor resolution provenance."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True, order=True)
class BackendSourceResolution:
    """One distinct source-resolution observation reported by an acquisition backend.

    Backend extractor names are provenance, not yt-sql semantics. ``extractor_family``
    is a conservative namespace derived from yt-dlp's own extractor name and must not
    be treated as a platform assertion by the logical planner.
    """

    provider: str
    extractor: str | None = None
    extractor_key: str | None = None
    extractor_family: str | None = None
    result_type: str | None = None
    webpage_domain: str | None = None
    original_domain: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        """Return a stable machine-readable representation."""
        return asdict(self)


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _domain(value: object) -> str | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return urlsplit(text).hostname
    except ValueError:
        return None


def _extractor_family(extractor: str | None) -> str | None:
    """Return yt-dlp's extractor namespace without claiming platform semantics."""
    if extractor is None:
        return None
    family = extractor.split(":", 1)[0].strip().casefold()
    if not family or family == "generic":
        return None
    return family


def resolution_from_ytdlp_record(record: dict) -> BackendSourceResolution | None:
    """Extract stable yt-dlp resolution provenance already present in an info dict."""
    extractor = _text(record.get("extractor"))
    extractor_key = _text(record.get("extractor_key"))
    webpage_domain = _text(record.get("webpage_url_domain")) or _domain(record.get("webpage_url"))
    original_domain = _domain(record.get("original_url"))
    result_type = _text(record.get("_type")) or "video"
    if not any((extractor, extractor_key, webpage_domain, original_domain)):
        return None
    return BackendSourceResolution(
        provider="yt-dlp",
        extractor=extractor,
        extractor_key=extractor_key,
        extractor_family=_extractor_family(extractor),
        result_type=result_type,
        webpage_domain=webpage_domain,
        original_domain=original_domain,
    )


def observed_ytdlp_resolutions(records: list[dict]) -> tuple[BackendSourceResolution, ...]:
    """Return deterministic distinct backend-resolution observations from records."""
    observed = {resolution for record in records if (resolution := resolution_from_ytdlp_record(record)) is not None}
    return tuple(sorted(observed))


def format_backend_resolution(resolution: BackendSourceResolution) -> str:
    """Render concise human-readable backend resolution provenance."""
    parts = [f"provider={resolution.provider}"]
    if resolution.extractor is not None:
        parts.append(f"extractor={resolution.extractor}")
    if resolution.extractor_key is not None:
        parts.append(f"extractor-key={resolution.extractor_key}")
    if resolution.extractor_family is not None:
        parts.append(f"extractor-family={resolution.extractor_family}")
    if resolution.result_type is not None:
        parts.append(f"result-type={resolution.result_type}")
    if resolution.webpage_domain is not None:
        parts.append(f"webpage-domain={resolution.webpage_domain}")
    return ", ".join(parts)
