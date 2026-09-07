"""Shared pytest fixtures for deterministic yt-sql conformance datasets."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pytest

from yt_discover_tests.conformance.generate_dataset import (
    DATASET_SEED,
    GENERATOR_VERSION,
    PROFILE_SIZES,
    build_records,
    dataset_digest,
    write_cache,
)


@dataclass(frozen=True)
class ConformanceDataset:
    """One ephemeral generated profile and its real yt-discover cache."""

    name: str
    size: int
    seed: int
    generator_version: int
    records: list[dict[str, object]]
    cache_path: Path
    digest: str


def _announce(config: pytest.Config, message: str) -> None:
    """Write generation progress through pytest's terminal reporter when available."""
    reporter = config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_line(message)


def _build_dataset(
    *,
    name: str,
    size: int,
    seed: int,
    root: Path,
    config: pytest.Config,
) -> ConformanceDataset:
    _announce(config, f"[yt-sql] Generating {name} conformance dataset ({size:,} records, seed {seed})...")
    started = time.perf_counter()
    records = build_records(size, seed=seed)
    cache_path = root / f"{name}.sqlite3"
    write_cache(cache_path, size=size, seed=seed)
    elapsed = time.perf_counter() - started
    digest = dataset_digest(records)
    _announce(
        config,
        f"[yt-sql] {name.capitalize()} dataset ready: {size:,} records, sha256 {digest[:12]}... ({elapsed:.2f}s)",
    )
    return ConformanceDataset(name, size, seed, GENERATOR_VERSION, records, cache_path, digest)


@pytest.fixture(scope="session")
def conformance_dataset_factory(
    tmp_path_factory: pytest.TempPathFactory,
    request: pytest.FixtureRequest,
) -> Callable[..., ConformanceDataset]:
    """Lazily generate and session-cache named or exact-size datasets."""
    root = tmp_path_factory.mktemp("yt_sql_conformance")
    generated: dict[tuple[str, int, int], ConformanceDataset] = {}

    def factory(
        profile: str | None = None,
        *,
        size: int | None = None,
        seed: int = DATASET_SEED,
    ) -> ConformanceDataset:
        if (profile is None) == (size is None):
            raise ValueError("specify exactly one of profile or size")
        if profile is not None:
            if profile not in PROFILE_SIZES:
                raise ValueError(f"unknown conformance profile: {profile}")
            resolved_size = PROFILE_SIZES[profile]
            name = profile
        else:
            assert size is not None
            if size < 1:
                raise ValueError("custom conformance size must be at least 1")
            resolved_size = size
            name = f"custom-{size}"

        key = (name, resolved_size, seed)
        if key not in generated:
            generated[key] = _build_dataset(
                name=name,
                size=resolved_size,
                seed=seed,
                root=root,
                config=request.config,
            )
        return generated[key]

    return factory


@pytest.fixture(scope="session")
def conformance_small(conformance_dataset_factory: Callable[..., ConformanceDataset]) -> ConformanceDataset:
    return conformance_dataset_factory("small")


@pytest.fixture(scope="session")
def conformance_normal(conformance_dataset_factory: Callable[..., ConformanceDataset]) -> ConformanceDataset:
    return conformance_dataset_factory("normal")


@pytest.fixture(scope="session")
def conformance_large(conformance_dataset_factory: Callable[..., ConformanceDataset]) -> ConformanceDataset:
    return conformance_dataset_factory("large")


@pytest.fixture(scope="session")
def conformance_huge(conformance_dataset_factory: Callable[..., ConformanceDataset]) -> ConformanceDataset:
    return conformance_dataset_factory("huge")
