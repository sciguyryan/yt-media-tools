"""Session-process cache for deterministic conformance records used by tests.

The generator's public ``build_records`` function intentionally returns a fresh
population. Most semantic tests only read that population, so rebuilding the
same small or normal corpus in every helper adds test-suite cost without adding
coverage. This module keeps that optimisation test-side and explicit.
"""

from __future__ import annotations

from functools import cache

from yt_discover_tests.conformance.generate_dataset import DATASET_SEED, PROFILE_SIZES, build_records


@cache
def cached_records(profile: str, *, seed: int = DATASET_SEED) -> tuple[dict[str, object], ...]:
    """Return one process-local immutable-container view of a generated profile.

    Callers must treat the contained record mappings as read-only. Tests that
    intentionally mutate generator output should continue to call
    ``build_records`` directly so mutation cannot leak between tests.
    """
    try:
        size = PROFILE_SIZES[profile]
    except KeyError as exc:
        raise ValueError(f"unknown conformance profile: {profile}") from exc
    return tuple(build_records(size, seed=seed))
