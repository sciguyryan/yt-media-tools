"""Deterministic YT-SQL conformance dataset generation."""

from __future__ import annotations

import random

GENERATOR_VERSION = 2
SEED = 31415926

PROFILE_SIZES = {
    "small": 12,
    "normal": 64,
    "large": 512,
    "huge": 4096,
}

UPLOADERS = ("Example One", "Example Two", "Example Three", None)
TITLE_WORDS = ("Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta")
TITLE_KINDS = ("Launch", "Review", "Notes", "Live", "Archive", "Update")


def resolve_size(profile: str | None = None, exact_size: int | None = None) -> int:
    """Resolve a named profile or explicit entry count."""

    if exact_size is not None:
        if exact_size <= 0:
            raise ValueError("exact_size must be a positive integer")
        return exact_size

    selected = profile or "small"
    try:
        return PROFILE_SIZES[selected]
    except KeyError as exc:
        valid = ", ".join(PROFILE_SIZES)
        raise ValueError(f"unknown dataset profile: {selected}; expected one of {valid}") from exc


def generate_rows(
    profile: str | None = None,
    *,
    exact_size: int | None = None,
    seed: int = SEED,
) -> list[dict[str, object]]:
    """Generate reproducible rows for the requested profile or exact size."""

    size = resolve_size(profile, exact_size)
    rng = random.Random(seed)
    rows: list[dict[str, object]] = []

    for index in range(size):
        title = f"{TITLE_WORDS[index % len(TITLE_WORDS)]} {TITLE_KINDS[(index // 2) % len(TITLE_KINDS)]}"
        uploader = UPLOADERS[index % len(UPLOADERS)]
        duration = None if index % 11 == 0 else 30 + rng.randrange(0, 570)
        date = None if index % 13 == 0 else f"2024-{1 + (index % 12):02d}-{1 + (index % 28):02d}"
        live = index % 9 == 0

        rows.append(
            {
                "id": f"video{index:05d}",
                "title": title,
                "uploader": uploader,
                "duration": duration,
                "date": date,
                "live": live,
                "source_index": index,
            }
        )

    return rows
