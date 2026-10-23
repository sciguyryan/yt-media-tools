"""Independent review records must never modify normative expectations."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "yt-sql"))
from record_review import RecordError, record  # noqa: E402
from run_python_candidate import observe  # noqa: E402
from stage_candidate import stage  # noqa: E402


@pytest.fixture
def prepared(tmp_path: Path) -> tuple[Path, Path]:
    case = ROOT / "yt-sql/cases/smoke/source_order_limit"
    observation = tmp_path / "observation.json"
    observation.write_text(json.dumps(observe(case)), encoding="utf-8")
    candidate = tmp_path / "candidate.json"
    stage(case, observation, candidate, configuration="default")
    return case, candidate


def test_review_record_does_not_promote(prepared: tuple[Path, Path], tmp_path: Path) -> None:
    case, candidate = prepared
    before = (case / "expected.json").read_bytes()
    destination = tmp_path / "review.json"
    record(
        case,
        candidate,
        destination,
        reviewer="Independent reviewer",
        rationale="Reviewed query semantics and fixture rows independently.",
        decision="approve",
    )
    result = json.loads(destination.read_text(encoding="utf-8"))
    assert result["decision"] == "approve"
    assert result["expectation_promoted"] is False
    assert (case / "expected.json").read_bytes() == before


def test_review_requires_reason_and_reviewer(prepared: tuple[Path, Path], tmp_path: Path) -> None:
    case, candidate = prepared
    with pytest.raises(RecordError, match="rationale"):
        record(case, candidate, tmp_path / "review.json", reviewer="X", rationale="", decision="approve")


def test_review_cannot_overwrite(prepared: tuple[Path, Path], tmp_path: Path) -> None:
    case, candidate = prepared
    destination = tmp_path / "review.json"
    kwargs = {"reviewer": "X", "rationale": "Checked independently", "decision": "reject"}
    record(case, candidate, destination, **kwargs)
    with pytest.raises(RecordError, match="already exists"):
        record(case, candidate, destination, **kwargs)


def test_legacy_candidate_cannot_be_approved(prepared: tuple[Path, Path], tmp_path: Path) -> None:
    case, _ = prepared
    legacy = tmp_path / "legacy.json"
    stage(case, case / "expected.json", legacy)
    with pytest.raises(RecordError, match="version 2"):
        record(
            case, legacy, tmp_path / "review.json", reviewer="X", rationale="Checked independently", decision="approve"
        )


def test_stale_candidate_cannot_be_reviewed(prepared: tuple[Path, Path], tmp_path: Path) -> None:
    case, candidate = prepared
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    payload["query_sha256"] = "0" * 64
    candidate.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RecordError, match="digest mismatch"):
        record(
            case,
            candidate,
            tmp_path / "review.json",
            reviewer="X",
            rationale="Checked independently",
            decision="approve",
        )
