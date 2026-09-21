# Discover acquisition progress

## Purpose

This document records the acquisition-progress audit and the backend-neutral progress contract established for issue #81. It describes the boundary that later presentation work should use without changing acquisition semantics.

## Audit findings

Discover already has two separate progress mechanisms. Lightweight enumeration uses `_enumeration_progress()`, while detailed yt-dlp extraction uses `_acquisition_progress()`. Both ultimately consume backend callback strings and `AcquisitionStats` directly.

Lightweight enumeration can report coarse progress even at normal verbosity. It reports every 100 observed entries by default, every 25 entries with `-v`, and every entry with `-vv`. A first-item message is also available with `-v`. Large-source warnings are independent of verbose mode.

Detailed metadata extraction has a different visibility boundary. Its progress callback is installed only when verbose mode is enabled. With `-v`, it reports the first available entry and then every tenth available entry. With `-vv`, it reports every available entry. The transition message announcing detailed cache refresh or full detailed acquisition is also verbose-only.

This difference explains the reported apparent stall. A bounded enumeration can visibly make progress and then hand a potentially large candidate set to detailed extraction, after which normal non-verbose execution can remain silent until the detailed stage completes. The backend is still working, but the presentation no longer exposes that semantic stage.

The existing callbacks are also backend-shaped rather than semantic. Their event names such as `enumerated`, `available` and `skipped` describe low-level observations. They do not provide a stable application-level stage transition model, and the detailed callback does not know the total candidate count even when orchestration does.

## Progress contract

User-facing progress should be derived from semantic acquisition stages rather than backend implementation details. The initial stable stages are:

- `enumeration`: discover candidate identities and lightweight metadata;
- `detailed-metadata`: acquire authoritative detailed metadata for candidates that require it.

The initial event kinds are:

- `stage-started`;
- `stage-progress`;
- `stage-completed`;
- `entry-skipped`.

Each event may carry a completed count and an optional total. Unknown totals are valid and must degrade cleanly. A detail string may provide diagnostic context, but presentation must not depend on backend-specific text to understand the stage or count.

The semantic event model lives in `yt_media_tools.acquisition_progress`. The audit does not replace the established callbacks or change user-visible output. The follow-up implementation should adapt orchestration and backend telemetry to this model before changing normal interactive presentation.

## Presentation requirements

Meaningful stage transitions should become visible during normal interactive execution. A transition into detailed metadata acquisition should not require `-vv`. Long-running stages should emit bounded periodic progress without producing one line per item at normal verbosity.

Progress belongs on standard error and must never contaminate query results or machine-readable output. Existing output-format, colour, Unicode and redirection behaviour must remain authoritative. Machine-readable modes must not gain progress records merely because semantic events exist internally.

The renderer should prefer known totals where orchestration can provide them. For example, after bounded enumeration has produced a detailed candidate set, detailed acquisition can report progress against that candidate count even if yt-dlp itself does not know the total.

Time-based progress may be useful for stages whose item rate is slow or irregular, but tests must not depend on wall-clock timing. Any time threshold should be injected or otherwise isolated so deterministic tests can exercise it without sleeping.

`-v` should continue to provide additional operational detail and `-vv` may retain per-entry diagnostics. Normal progress must remain concise enough for interactive use and must not turn ordinary execution into a detailed acquisition log.

## Semantic boundaries

Progress reporting must not alter acquisition ordering, batching, cache decisions, backend selection, early termination, retry behaviour or yt-sql evaluation. It observes work that the acquisition plan already requires.

Backend adapters may report implementation telemetry, but yt-dlp and YouTube.js names must not become semantic progress stages. A future backend should be able to satisfy the same acquisition stage without changing the user-facing progress vocabulary.

Skipped or inaccessible entries remain important acquisition telemetry. They should be represented separately from successful stage progress so later rendering can preserve concise summaries at normal verbosity and detailed diagnostics at higher verbosity.

## Implementation acceptance targets

The follow-up implementation should add deterministic coverage demonstrating that semantic stage transitions are rendered at the intended interactive level, detailed work with known and unknown totals remains visibly active when sufficiently long-running, `-vv` retains useful per-entry diagnostics, and query-result or machine-readable output remains uncontaminated.
