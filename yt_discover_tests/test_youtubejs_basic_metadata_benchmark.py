from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "benchmark_youtubejs_basic_metadata.py"


def _module():
    spec = importlib.util.spec_from_file_location("youtubejs_basic_benchmark", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_agreement_distinguishes_equal_different_and_missing_values() -> None:
    benchmark = _module()
    result = benchmark._agreement(
        {"id": "abc", "title": "Title", "channel_id": "chan", "duration": 42, "view_count": None},
        {"id": "abc", "title": "Other", "channel_id": "chan", "duration": 42, "view_count": 7},
    )
    assert result == {
        "id": "equal",
        "title": "different",
        "channel_id": "equal",
        "duration": "equal",
        "view_count": "missing",
    }


def test_index_ignores_rows_without_video_identity() -> None:
    benchmark = _module()
    assert benchmark._index([{"id": "abc", "title": "A"}, {"title": "missing"}]) == {"abc": {"id": "abc", "title": "A"}}


def test_comparison_fields_cover_phase_three_scalar_boundary() -> None:
    benchmark = _module()
    assert benchmark.COMPARISON_FIELDS == ("id", "title", "channel_id", "duration", "view_count")
