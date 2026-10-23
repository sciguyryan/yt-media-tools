"""Phase 5 review preflight must not grant semantic approval."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "yt-sql"))
spec = importlib.util.spec_from_file_location("review_candidate", ROOT / "yt-sql/review_candidate.py")
assert spec is not None and spec.loader is not None
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def _candidate(tmp_path: Path) -> tuple[Path, Path]:
    from stage_candidate import stage

    case = ROOT / "yt-sql/cases/smoke/source_order_limit"
    candidate = tmp_path / "candidate.json"
    stage(case, case / "expected.json", candidate)
    return case, candidate


def test_review_preflight_does_not_approve(tmp_path: Path) -> None:
    case, candidate = _candidate(tmp_path)
    expected_before = (case / "expected.json").read_bytes()
    result = review.inspect(case, candidate)
    assert result["provenance"] == "file-digests-verified"
    assert result["observation_matches_current_expected"] is True
    assert result["semantic_review"] == "required"
    assert result["approval"] == "not-granted"
    assert (case / "expected.json").read_bytes() == expected_before


@pytest.mark.parametrize("field", ["query_sha256", "manifest_sha256", "datasets_sha256"])
def test_review_rejects_stale_provenance(tmp_path: Path, field: str) -> None:
    case, candidate = _candidate(tmp_path)
    value = json.loads(candidate.read_text())
    value[field] = {} if field == "datasets_sha256" else "0" * 64
    candidate.write_text(json.dumps(value))
    with pytest.raises(review.ReviewError, match="digest mismatch"):
        review.inspect(case, candidate)


def test_review_rejects_unrecognised_fields(tmp_path: Path) -> None:
    case, candidate = _candidate(tmp_path)
    value = json.loads(candidate.read_text())
    value["approved"] = True
    candidate.write_text(json.dumps(value))
    with pytest.raises(review.ReviewError, match="unsupported provisional candidate shape"):
        review.inspect(case, candidate)


def test_configuration_verified_candidate_remains_provisional(tmp_path: Path) -> None:
    from run_python_candidate import observe
    from stage_candidate import stage

    case = ROOT / "yt-sql/cases/smoke/source_order_limit"
    observation = tmp_path / "observation.json"
    observation.write_text(json.dumps(observe(case)), encoding="utf-8")
    candidate = tmp_path / "candidate.json"
    stage(case, observation, candidate, configuration="default")
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    assert payload["version"] == 2
    assert payload["execution_configuration"] == {"id": "default", "settings": {}}
    summary = review.inspect(case, candidate)
    assert summary["execution_configuration_provenance"] == "verified-by-re-execution-at-staging"
    assert summary["approval"] == "not-granted"


def test_staging_rejects_falsely_labelled_configuration(tmp_path: Path) -> None:
    from stage_candidate import CandidateError, stage

    case = ROOT / "yt-sql/cases/smoke/source_order_limit"
    observation = tmp_path / "observation.json"
    observation.write_text(
        json.dumps({"version": 1, "outcome": "rows", "columns": [], "rows": []}),
        encoding="utf-8",
    )
    destination = tmp_path / "candidate.json"
    with pytest.raises(CandidateError, match="differs"):
        stage(case, observation, destination, configuration="default")
    assert not destination.exists()


def test_review_rejects_configuration_tampering(tmp_path: Path) -> None:
    from run_python_candidate import observe
    from stage_candidate import stage

    case = ROOT / "yt-sql/cases/smoke/source_order_limit"
    observation = tmp_path / "observation.json"
    observation.write_text(json.dumps(observe(case)), encoding="utf-8")
    candidate = tmp_path / "candidate.json"
    stage(case, observation, candidate, configuration="default")
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    payload["execution_configuration"]["settings"]["optimisation"] = "disabled"
    candidate.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(review.ReviewError, match="execution configuration"):
        review.inspect(case, candidate)
