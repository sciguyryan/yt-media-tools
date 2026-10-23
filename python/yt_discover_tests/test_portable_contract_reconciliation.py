"""Keep the portable corpus validator aligned with its published schema."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "yt-sql"))
from validate_corpus import CorpusError, validate_corpus  # noqa: E402


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    for folder in ("cases", "datasets", "expectations"):
        shutil.copytree(ROOT / "yt-sql" / folder, tmp_path / folder)
    return tmp_path


def _manifest(root: Path) -> Path:
    return next((root / "cases").rglob("test.json"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", "INVALID CASE"),
        ("id", "a"),
        ("datasets", ["../other"]),
        ("datasets", ["UPPER"]),
        ("description", ""),
        ("description", 12),
    ],
)
def test_reject_manifest_values_outside_schema(corpus: Path, field: str, value: object) -> None:
    path = _manifest(corpus)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest[field] = value
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(CorpusError):
        validate_corpus(corpus)


@pytest.mark.parametrize("field,value", [("issue", ""), ("issue", 17), ("category", None)])
def test_reject_invalid_override_metadata(corpus: Path, field: str, value: object) -> None:
    case_id = json.loads(_manifest(corpus).read_text(encoding="utf-8"))["id"]
    path = corpus / "expectations" / "rust.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "expectations": {
                    case_id: {
                        "status": "xfail",
                        "reason": "Known implementation difference",
                        field: value,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(CorpusError):
        validate_corpus(corpus)


def test_valid_corpus_still_passes(corpus: Path) -> None:
    assert validate_corpus(corpus) >= 1
