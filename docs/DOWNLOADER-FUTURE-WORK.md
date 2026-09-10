# Downloader future work

## Purpose

Downloader should remain a focused yt-dlp orchestrator rather than trying to replace yt-dlp. Its value is predictable typed policy, safe persistent workflows, reproducible planning, clear diagnostics and simple composition with other tools.

The major feature roadmap through audio, playlist selection, live media and partial-media derivatives is implemented. Future work should extend the machine interface conservatively and preserve the existing queue, archive, derivative-output and expert-override boundaries.

## Machine interface

The versioned machine contract and parameter-profile JSON Schema are available through `--schema-json`. Runtime configuration validation is available through `--validate-config`, environment reporting through `--capabilities` and `--capabilities-json`, and the non-executing resolved plan through versioned `--explain-json`.

The following work remains:

- define a versioned, language-neutral execution-request schema that compiles through the same typed policy and planning model as the CLI rather than accepting arbitrary command strings;
- investigate structured per-target outcomes only if yt-dlp exposes a sufficiently stable interface that is more reliable than parsing human-readable output;
- add manifest-driven retry of unresolved or failed targets only after per-target outcome semantics are trustworthy;
- define a simple versioned Discover-to-Downloader interchange format that keeps both programs independently usable and does not require shared-language libraries or direct internal calls;
- evaluate optional external-tool integrations only where they add a capability Downloader cannot sensibly provide itself and fit behind an existing typed policy boundary.

Do not introduce a plugin framework, generic scheduler, GUI, media-library database, arbitrary shell hooks, custom extractors or a bespoke RPC protocol where stdin/stdout JSON is sufficient.

## Deferred policy investigations

Language preference and filesize policy remain deferred until extractor behaviour and exact-versus-approximate size semantics can be specified conservatively.

Better failure classification and `--max-failures` depend on trustworthy per-target outcomes. The current unresolved classification must remain conservative until that boundary improves.

Run manifests should track actual associated-artefact paths only when authoritative yt-dlp events expose them reliably. Do not infer sidecar paths from output naming.

## Testing and maintenance

Anything deterministic that can be represented faithfully with controlled fixtures or simulated outcomes should be tested automatically. Keep ordinary CI fast and deterministic. Property-based testing, mutation testing, branch coverage and focused fuzzing remain useful techniques where they materially improve confidence in policy precedence, queue transitions, completion boundaries and configuration parsing.

Keep `DOWNLOADER-README.md`, help, `--examples`, `TODO.md` and `CHANGELOG.md` consistent with the implemented command surface. Remove completed work from TODO documentation rather than retaining historical roadmap sections.
