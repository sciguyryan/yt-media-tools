"""Shared deterministic fixtures for yt-discover performance benchmarks."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from yt_discover_tests.conformance.generate_dataset import DATASET_SEED, GENERATOR_VERSION, build_records
from yt_media_tools.dates import DateContext
from yt_media_tools.schema import QuerySchema

BENCHMARK_RECORD_COUNT = 1_000
BENCHMARK_NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="session")
def benchmark_records() -> list[dict[str, object]]:
    """Return a reproducible medium-sized record set for local benchmarks."""
    return build_records(BENCHMARK_RECORD_COUNT, seed=DATASET_SEED)


@pytest.fixture(scope="session")
def benchmark_schema(benchmark_records: list[dict[str, object]]) -> QuerySchema:
    """Return the schema inferred from the canonical benchmark records."""
    return QuerySchema(benchmark_records)


@pytest.fixture(scope="session")
def benchmark_dates() -> DateContext:
    """Return a fixed temporal context so benchmark work is reproducible."""
    return DateContext(now=BENCHMARK_NOW)


def pytest_benchmark_update_machine_info(config, machine_info: dict[str, object]) -> None:
    """Record benchmark-specific reproducibility metadata in JSON results."""
    machine_info["yt_sql_dataset_generator_version"] = GENERATOR_VERSION
    machine_info["yt_sql_dataset_seed"] = DATASET_SEED
    machine_info["yt_sql_benchmark_record_count"] = BENCHMARK_RECORD_COUNT
