from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


SCRIPT = Path(__file__).parents[1] / "benchmarks" / "cache_v4_runtime_reconciliation.py"
SPEC = importlib.util.spec_from_file_location("cache_v4_runtime_reconciliation", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_runtime_benchmark_exercises_fallback_retention_and_compaction(tmp_path: Path) -> None:
    result = MODULE.run_benchmark(tmp_path / "metadata.sqlite3", "test", 20)

    assert result.resolution_calls == 100
    assert result.fallback_resolutions == 50
    assert result.stale_fallback_resolutions == 25
    assert result.selected_provider_contributions == 5
    assert result.removed_provider_contributions == 5
    assert result.collected_entities == 5
