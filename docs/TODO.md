# Downloader TODO

- Define a versioned machine-readable execution-request schema backed by Downloader's typed policy and planning model.
- Investigate reliable structured per-target outcomes from yt-dlp without parsing human-readable output.
- Add manifest-driven retry only after structured outcome semantics are reliable.
- Define a simple versioned Discover-to-Downloader interchange format.
- Revisit language preference and filesize policy when extractor semantics can be specified conservatively.
- Investigate authoritative associated-artefact path reporting for run manifests.
- Evaluate property-based, mutation and focused fuzz testing where they materially improve deterministic coverage.
- Evaluate optional external-tool integrations only where they add clear utility behind an existing typed policy boundary.
- Consider the low-impact `El Psy Kongroo` easter egg only if it cannot affect scripting, help, errors or machine-readable output.
- Investigate optional playback-aware rate limiting that derives an approximate download rate from the actually selected media formats, applies configurable headroom for variable bitrate and network jitter, degrades gracefully when reliable bitrate information is unavailable, and exposes the calculation through planning and explain output. Keep existing download-speed behaviour unchanged by default; the goal is considerate bandwidth and server-load behaviour resembling ordinary real-time playback.

# Discover TODO

- Investigate whether a Rust implementation or selective Rust acceleration would provide sufficient practical performance benefit to justify the additional implementation, packaging and maintenance cost, while preserving yt-sql semantics, deterministic behaviour, diagnostics, portability and the existing conformance contract. Treat this as an evidence-driven design investigation rather than a planned rewrite.
