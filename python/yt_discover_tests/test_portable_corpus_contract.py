"""Exercise the engine-independent portable corpus structural validator."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "yt-sql"))  # noqa: E402
from validate_corpus import CorpusError, validate_corpus  # noqa: E402


def test_committed_corpus() -> None:
    assert validate_corpus() >= 1


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    source = ROOT / "yt-sql"
    for folder in ("cases", "datasets", "expectations"):
        shutil.copytree(source / folder, tmp_path / folder)
    return tmp_path


def _case(root: Path) -> Path:
    return next((root / "cases").rglob("expected.json"))


@pytest.mark.parametrize("change", ["mixed", "missing", "width", "category", "unknown"])
def test_reject_invalid_outcome(corpus: Path, change: str) -> None:
    path = _case(corpus)
    value = json.loads(path.read_text(encoding="utf-8"))
    if change == "mixed":
        value["error"] = {"category": "syntax"}
    elif change == "missing":
        del value["columns"]
    elif change == "width":
        value["rows"][0].append("extra")
    elif change == "category":
        value = {"version": 1, "outcome": "error", "error": {"category": ""}}
    else:
        value["outcome"] = "other"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(CorpusError):
        validate_corpus(corpus)


def test_reject_duplicate_json_keys(corpus: Path) -> None:
    path = _case(corpus)
    path.write_text('{"version":1,"version":1,"outcome":"rows"}', encoding="utf-8")
    with pytest.raises(CorpusError, match="duplicate key"):
        validate_corpus(corpus)


def test_reject_unknown_xfail(corpus: Path) -> None:
    path = corpus / "expectations" / "rust.json"
    path.write_text(
        json.dumps({"version": 1, "expectations": {"missing.case": {"status": "xfail", "reason": "missing"}}}),
        encoding="utf-8",
    )
    with pytest.raises(CorpusError, match="unknown case ID"):
        validate_corpus(corpus)
