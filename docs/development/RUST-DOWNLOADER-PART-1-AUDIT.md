# Rust Downloader, Part 1: architecture and compatibility audit

## Basis and limits

This audit examines `yt-media-tools-parser-optimisation-final.zip`, the latest complete combined-project candidate available in this working environment. It contains `yt-download.py` version **1.23.0**, according to `PROGRAM_VERSION` and `docs/DOWNLOADER-README.md`. It is not proof that this is the user's latest accepted canonical tree. Confirm that before treating this audit as final or making source changes. No Rust implementation has been created and no tests have been run.

The objective is a native Rust implementation of **our Downloader application**, not a replacement for yt-dlp. The Python application remains the production entry point and behavioural reference until an explicitly approved cutover.

## What the current application actually contains

The approximately 195 KB `yt-download.py` script is more substantial than a thin command wrapper. It defines typed `DownloadPolicy`, `OutputProfile`, `Profile`, `ResolvedProfileSettings`, `InputSource` and `DownloadPlan` structures, with approximately 96 module-level functions. Its responsibilities overlap in one file, but the observable behaviour should not be confused with that source layout.

| Area | Existing implementation and contracts | Rust consideration |
| --- | --- | --- |
| CLI | `build_parser`, `main`, typed validation, examples, machine contract and capability reporting | Preserve flags, help-sensitive behaviour, error status and output; consider `clap` only after comparing its parsing and diagnostics |
| Configuration | `load_profiles`, `resolve_profile_settings`, `merge_profile_settings`, `resolve_profile_policy`, JSON schema and validation | Preserve versioned profile format, `$values`, `$defaults`, inheritance, validation and explicit CLI precedence; `serde`/`serde_json` are plausible candidates |
| Input | `resolve_input`, `_batch_file_source`, `load_collection_input`, collection reconciliation, stdin and direct targets | Preserve input-source selection, order, duplicates and physical line semantics; avoid unreviewed normalisation |
| Planning | `create_download_plan`, `build_yt_dlp_command`, `explain_plan_payload`, `format_plan_explanation` | Make the plan independently testable; compare actual argv arrays and machine output with Python |
| Execution | `run`, `validate_environment`, `yt_dlp_version`, external-tool diagnostics and redaction | Keep yt-dlp external; use direct process invocation rather than a shell; preserve stderr/stdout, status and redaction |
| Persistence | `remove_completed_id`, `remove_completed_row`, archive filtering, `atomic_write_bytes`, reports and manifests | Preserve successful-completion gates, row versus ID semantics, empty files, atomicity and recovery |
| Collections | `yt_media_tools/collection_state.py` and `collection_interchange.py` | Treat collection identity, sequence fingerprints and interchange formats as real compatibility surfaces |
| Shared external tools | `yt_media_tools/external_tools.py` and `ytdlp_runtime.py` | Audit their contracts before copying behaviour or creating shared Rust crates |

The test suite already has dedicated coverage in `yt_downloader_tests/`, including profiles, CLI configuration, command planning, input sources, collection state, interchange, machine contracts, output layout, run manifests, queue reconciliation, external-tool diagnostics, playlist policy, audio/format policy, live policy and partial-media policy. These tests should be inventoried case by case as we implement the Rust equivalent. Some Python tests inspect internal structures; cross-language comparisons should concentrate on observable results and stable structured representations rather than forcing the same internal design.

## Compatibility traps worth preserving deliberately

- Profile version 3 supports `$values`, `$defaults` and single-parent inheritance while retaining supported older profile behaviour. Invalid values must not become permissive because Rust deserialisation is convenient.
- `--remove-completed-ids` and `--remove-completed-rows` have different semantics. The latter removes the complete physical row after successful completion and preserves a zero-byte queue file if the final row is removed.
- The application has collection-specific completion and interchange behaviour, not just plain ID lists. Collection identity and fingerprints must not change accidentally.
- Machine-readable contract, capability, plan, report and manifest outputs are compatibility surfaces. JSON field types, omission rules, ordering where specified, and diagnostic separation require comparison.
- Redaction of extractor arguments, cookie handling and safe subprocess execution are security-sensitive. Preserve established disclosure boundaries.
- Paths are interpreted relative to different locations depending on their purpose. The current documentation identifies `archive.txt` relative to the working directory and `cookies.txt` beside the script; do not collapse these into one Rust executable-relative rule without explicit review.
- Downloader's defaults and yt-dlp argument generation include many media-specific choices. Preserve typed policy rather than introducing arbitrary JSON-to-yt-dlp passthrough.

## Licensing and current Rust standards

The examined archive contains a root `LICENSE` with the **GNU Lesser General Public License, version 2.1** text. This is evidence of the licence document present in the candidate, but a licence text alone does not establish whether the intended project expression is `LGPL-2.1-only`, `LGPL-2.1-or-later`, or a different explicit grant elsewhere. Inspect repository history, headers and the maintainer's intended terms before writing the Cargo `license` field. Do not invent an `-or-later` grant. Cargo's `license-file` can point to the repository licence where an SPDX expression is not established, subject to the final package layout.

Target the **latest stable Rust toolchain viable at implementation time**, using its supported edition and current Cargo manifest conventions. Pin or document the toolchain choice for reproducibility; choose and declare `rust-version` once the actual dependency set and supported platforms are known. Commit `Cargo.lock` for the application. Prefer `cargo fmt`, `cargo clippy` and `cargo test` in development and CI, supplemented by dependency licence and vulnerability review. Check the current stable release at the time of Part 2 rather than freezing a version number in this audit.

External crates are allowed where they earn their place. Initial candidates for evaluation include `clap` for CLI parsing, `serde`/`serde_json` for profiles and machine contracts, and a well-maintained temporary-file utility for safe file replacement. None is selected yet. Assess their licence compatibility, security history, supported Rust version, diagnostic behaviour and practical complexity. A small native implementation may be preferable where a dependency brings little value.

## Proposed initial architecture

Start with one independent Rust Downloader binary and a library for testable policy, input, planning, execution and persistence code. A dedicated workspace under `rust/` is a reasonable location, but its precise shape should follow the current repository and build needs. Keep Python files and entry points untouched. Avoid extracting a shared Rust crate for Discover until a genuine common boundary appears.

The strongest early seam is **policy and planning without executing yt-dlp**. It permits deterministic comparisons of input, profile resolution, effective policy, command arguments and explain output. Only then add live process execution and state-changing queue workflows. Keep subprocess execution behind a narrow interface so tests can use a controlled fake executable rather than the network.

## Recommended next steps

1. Confirm this candidate against the latest accepted canonical combined project tree, especially versions, licence grants, Downloader changes and tests.
2. Build a compatibility matrix from the existing `yt_downloader_tests/` fixtures, recording the exact expected outputs and gaps. Include exit codes, stderr/stdout, argv, JSON, queue bytes and filesystem results.
3. Decide the initial Rust CLI/JSON/temp-file dependencies using small compatibility spikes where necessary, not a framework-wide commitment.
4. Begin Part 2 with a buildable Rust skeleton and differential harness. Then revisit the remaining sub-issue boundaries using evidence from the audit and the first working implementation.

The eight previously drafted sub-issues remain a useful provisional map. This audit supports their broad areas, but does not justify fixing all later internal module boundaries in advance.

## Proposed commit message

No source changes were made, so no code commit is required for this audit alone. If the audit is committed as project documentation:

```text
Document the Rust Downloader architecture and compatibility audit.

[docs] Inventory Downloader's policy, input, execution and persistence boundaries.
[docs] Record compatibility risks, licensing checks and Rust toolchain direction.
[docs] Outline the next implementation and differential-testing steps.
```
