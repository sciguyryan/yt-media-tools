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
