"""Controlled promotion must require a matching independent approval."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "yt-sql"))
from promote_candidate import PromotionError, promote  # noqa: E402
from record_review import record  # noqa: E402
from run_python_candidate import observe  # noqa: E402
from stage_candidate import stage  # noqa: E402


@pytest.fixture
def prepared(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    root = tmp_path / "yt-sql"
    shutil.copytree(ROOT / "yt-sql" / "datasets", root / "datasets")
    case = root / "cases" / "smoke" / "source_order_limit"
    shutil.copytree(ROOT / "yt-sql" / "cases" / "smoke" / "source_order_limit", case)
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
        rationale="Checked fixture and ordering semantics independently.",
        decision="approve",
        root=root,
    )
    return root, case, candidate, review


def test_existing_expectation_requires_explicit_replacement(prepared: tuple[Path, Path, Path, Path]) -> None:
    root, case, candidate, review = prepared
    original = (case / "expected.json").read_bytes()
    with pytest.raises(PromotionError, match="--replace"):
        promote(case, candidate, review, root=root)
    assert (case / "expected.json").read_bytes() == original


def test_explicit_replacement_retains_previous_bytes(prepared: tuple[Path, Path, Path, Path]) -> None:
    root, case, candidate, review = prepared
    original = (case / "expected.json").read_bytes()
    promote(case, candidate, review, root=root, replace=True)
    assert (case / "expected.json.before-promotion").read_bytes() == original
    assert (
        json.loads((case / "expected.json").read_text(encoding="utf-8"))
        == json.loads(candidate.read_text(encoding="utf-8"))["observed"]
    )


def test_rejected_review_cannot_promote(prepared: tuple[Path, Path, Path, Path]) -> None:
    root, case, candidate, review = prepared
    payload = json.loads(review.read_text(encoding="utf-8"))
    payload["decision"] = "reject"
    review.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PromotionError, match="approval"):
        promote(case, candidate, review, root=root, replace=True)
    assert not (case / "expected.json.before-promotion").exists()


def test_candidate_tampering_blocks_promotion(prepared: tuple[Path, Path, Path, Path]) -> None:
    root, case, candidate, review = prepared
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    payload["observed"]["rows"] = []
    candidate.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PromotionError, match="digest"):
        promote(case, candidate, review, root=root, replace=True)


def test_missing_expectation_requires_separate_admission(prepared: tuple[Path, Path, Path, Path]) -> None:
    root, case, candidate, review = prepared
    (case / "expected.json").unlink()
    with pytest.raises(PromotionError, match="expected.json"):
        promote(case, candidate, review, root=root, replace=True)
    assert not (case / "expected.json").exists()
    assert not (case / "expected.json.before-promotion").exists()


def test_stale_temporary_file_is_not_deleted(prepared: tuple[Path, Path, Path, Path]) -> None:
    root, case, candidate, review = prepared
    temporary = case / "expected.json.promotion-tmp"
    temporary.write_text("unrelated existing work", encoding="utf-8")
    before = (case / "expected.json").read_bytes()
    with pytest.raises(PromotionError, match="temporary file already exists"):
        promote(case, candidate, review, root=root, replace=True)
    assert temporary.read_text(encoding="utf-8") == "unrelated existing work"
    assert (case / "expected.json").read_bytes() == before
    assert not (case / "expected.json.before-promotion").exists()


def test_stale_backup_blocks_second_promotion(prepared: tuple[Path, Path, Path, Path]) -> None:
    root, case, candidate, review = prepared
    promote(case, candidate, review, root=root, replace=True)
    backup = case / "expected.json.before-promotion"
    before = backup.read_bytes()
    with pytest.raises(PromotionError, match="backup already exists"):
        promote(case, candidate, review, root=root, replace=True)
    assert backup.read_bytes() == before


def test_failed_rename_cleans_new_artifacts(
    prepared: tuple[Path, Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    import promote_candidate as module

    root, case, candidate, review = prepared
    before = (case / "expected.json").read_bytes()

    def fail_replace(*args: object) -> None:
        raise OSError("injected rename failure")

    monkeypatch.setattr(module.os, "replace", fail_replace)
    with pytest.raises(PromotionError, match="injected rename failure"):
        promote(case, candidate, review, root=root, replace=True)
    assert (case / "expected.json").read_bytes() == before
    assert not (case / "expected.json.before-promotion").exists()
    assert not (case / "expected.json.promotion-tmp").exists()
