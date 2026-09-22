# Backend source and extractor resolution

Discover distinguishes the source expression written by the user from the source information reported by an acquisition backend. The distinction is important because a URL's spelling is not authoritative evidence of which extractor ultimately handled it.

## yt-dlp observations

yt-dlp information dictionaries expose `extractor` and `extractor_key` fields, together with source-related fields such as `webpage_url`, `webpage_url_domain` and `original_url`. Discover retains these values as backend provenance when they are present. yt-dlp documents `extractor` and `extractor_key` as output fields, and its extractor registry is ordered so the first suitable extractor handles a URL, with the generic extractor kept as the fallback.

Discover does not currently perform an additional network request solely to discover an extractor before acquisition. Resolution evidence is collected from information dictionaries already returned by the acquisition being performed. This keeps observability from adding acquisition cost.

## Resolution model

One observed resolution can contain:

- the provider that reported it, currently `yt-dlp`;
- the raw extractor name;
- the raw extractor key;
- a conservative extractor-family namespace derived from the extractor name;
- the backend result type;
- the reported webpage domain; and
- the domain of the backend's original URL where available.

The extractor family is deliberately weaker than a semantic platform identity. For example, an extractor named `youtube:tab` has the family `youtube`, but Discover does not turn that string into a yt-sql language rule. The `generic` extractor has no family because it does not establish a service-specific identity.

## Presentation and provenance

At verbose interactive output, Discover reports each distinct backend resolution observed for a source. Query rows remain on stdout and resolution diagnostics remain on stderr.

Machine-readable query provenance records the same observations under each physical source's `backend_resolution` array. Multiple observations are retained rather than silently selecting one when a source passes through more than one extractor.

Static `--explain` output continues to describe the logical source known before acquisition. It does not claim a backend extractor that has not yet run. A future planner may use sufficiently reliable resolution evidence to constrain provider eligibility, but that is separate work.

## Semantic boundary

Backend extractor names are implementation provenance, not yt-sql semantics. Discover must not make query meaning depend directly on a particular yt-dlp class name. Source-kind or platform assertions require a separately defined mapping with explicit reliability rules.

This also means unexpected resolution remains visible. If a source the user expected to be handled by one service is reported through another extractor or through yt-dlp's generic fallback, the provenance is preserved so the discrepancy can be diagnosed rather than hidden.
