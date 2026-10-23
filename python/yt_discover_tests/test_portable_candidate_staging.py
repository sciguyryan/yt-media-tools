"""Provisional candidate staging must never modify normative expectations."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "yt-sql"))
spec = importlib.util.spec_from_file_location("stage_candidate", ROOT / "yt-sql/stage_candidate.py")
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_stages_provisional_candidate_without_changing_expectation(tmp_path: Path) -> None:
    case = ROOT / "yt-sql/cases/smoke/source_order_limit"
    original = (case / "expected.json").read_bytes()
    observed = tmp_path / "observed.json"
    observed.write_bytes(original)
    destination = tmp_path / "candidate.json"
    module.stage(case, observed, destination)
    result = json.loads(destination.read_text(encoding="utf-8"))
    assert result["status"] == "provisional"
    assert result["implementation"] == "python"
    assert result["observed"] == json.loads(original)
    assert set(result["datasets_sha256"]) == {"python-v6-small"}
    assert len(result["query_sha256"]) == 64
    assert (case / "expected.json").read_bytes() == original
    with pytest.raises(module.CandidateError, match="already exists"):
        module.stage(case, observed, destination)


@pytest.mark.parametrize(
    "bad",
    [
        {"version": 1, "outcome": "error", "error": {"category": "crash"}},
        {"version": 1, "outcome": "rows", "columns": [], "rows": [[1]]},
        {"version": True, "outcome": "rows", "columns": [], "rows": []},
    ],
)
def test_rejects_invalid_observations(tmp_path: Path, bad: dict) -> None:
    observed = tmp_path / "observed.json"
    observed.write_text(json.dumps(bad), encoding="utf-8")
    destination = tmp_path / "candidate.json"
    with pytest.raises(module.CandidateError):
        module.stage(ROOT / "yt-sql/cases/smoke/source_order_limit", observed, destination)
    assert not destination.exists()


def test_rejects_case_outside_corpus(tmp_path: Path) -> None:
    observed = tmp_path / "observed.json"
    observed.write_text('{"version":1,"outcome":"rows","columns":[],"rows":[]}', encoding="utf-8")
    with pytest.raises(module.CandidateError, match="inside the corpus"):
        module.stage(tmp_path, observed, tmp_path / "candidate.json")
