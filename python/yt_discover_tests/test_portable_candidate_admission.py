"""Admission requires a reviewed candidate and never replaces expectations."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "yt-sql"))
from admit_candidate import admit  # noqa: E402
from promote_candidate import PromotionError  # noqa: E402
from record_review import record  # noqa: E402
from run_python_candidate import observe  # noqa: E402
from stage_candidate import stage  # noqa: E402
from validate_corpus import CorpusError, validate_case  # noqa: E402


@pytest.fixture
def prepared(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    root = tmp_path / "yt-sql"
    shutil.copytree(ROOT / "yt-sql" / "datasets", root / "datasets")
    case = root / "cases" / "smoke" / "source_order_limit"
    shutil.copytree(ROOT / "yt-sql" / "cases" / "smoke" / "source_order_limit", case)
    (case / "expected.json").unlink()
    with pytest.raises(CorpusError):
        validate_case(case, root=root)
    observation = tmp_path / "observed.json"
    observation.write_text(json.dumps(observe(case, root=root)), encoding="utf-8")
    candidate = tmp_path / "candidate.json"
    stage(case, observation, candidate, configuration="default", root=root)
    review = tmp_path / "review.json"
    record(
        case,
        candidate,
        review,
        reviewer="Independent reviewer",
        rationale="Verified the ordering and source data independently.",
        decision="approve",
        root=root,
    )
    return root, case, candidate, review


def test_admission_creates_valid_normative_expectation(prepared: tuple[Path, Path, Path, Path]) -> None:
    root, case, candidate, review = prepared
    assert admit(case, candidate, review, root=root) == case / "expected.json"
    assert validate_case(case, root=root) == "smoke.source_order_limit"
    assert not (case / "expected.json.before-promotion").exists()


def test_admission_never_replaces_existing_expectation(prepared: tuple[Path, Path, Path, Path]) -> None:
    root, case, candidate, review = prepared
    admit(case, candidate, review, root=root)
    original = (case / "expected.json").read_bytes()
    with pytest.raises(PromotionError, match="already exists"):
        admit(case, candidate, review, root=root)
    assert (case / "expected.json").read_bytes() == original


def test_admission_requires_approval(prepared: tuple[Path, Path, Path, Path]) -> None:
    root, case, candidate, review = prepared
    payload = json.loads(review.read_text(encoding="utf-8"))
    payload["decision"] = "reject"
    review.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PromotionError, match="approval"):
        admit(case, candidate, review, root=root)
    assert not (case / "expected.json").exists()


def test_admission_refuses_stale_temporary(prepared: tuple[Path, Path, Path, Path]) -> None:
    root, case, candidate, review = prepared
    temporary = case / "expected.json.promotion-tmp"
    temporary.write_text("existing recovery state", encoding="utf-8")
    with pytest.raises(PromotionError, match="stale"):
        admit(case, candidate, review, root=root)
    assert temporary.read_text(encoding="utf-8") == "existing recovery state"
    assert not (case / "expected.json").exists()


@pytest.mark.parametrize("invalid_version", [True, 1.0, "1"])
def test_admission_rejects_non_integer_review_version(
    prepared: tuple[Path, Path, Path, Path],
    invalid_version: object,
) -> None:
    root, case, candidate, review = prepared
    payload = json.loads(review.read_text(encoding="utf-8"))
    payload["version"] = invalid_version
    review.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PromotionError, match="approval"):
        admit(case, candidate, review, root=root)
    assert not (case / "expected.json").exists()
