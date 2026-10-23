"""Portable named-parameter contract tests."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "yt-sql"))
from parameters import ParameterError, validate_parameters  # noqa: E402
from validate_corpus import CorpusError, validate_corpus  # noqa: E402


def test_valid_parameter_encodings() -> None:
    validate_parameters(
        {
            "name": "Café",
            "empty": None,
            "flag": False,
            "n": {"type": "integer", "value": "-12"},
            "d": {"type": "decimal", "value": "1.250"},
            "at": {"type": "timestamp", "value": "2026-01-01T00:00:00Z"},
        }
    )
    validate_parameters({})


@pytest.mark.parametrize(
    "bindings",
    [
        {"bad-name": None},
        {"": None},
        {"1bad": None},
        {"a": 1},
        {"a": 1.25},
        {"a": {"type": "integer", "value": "01"}},
        {"a": {"type": "timestamp", "value": "2026-01-01"}},
        {"a": "\ud800"},
        [],
    ],
)
def test_invalid_parameters(bindings: object) -> None:
    with pytest.raises(ParameterError):
        validate_parameters(bindings)


def test_corpus_checks_parameter_contract(tmp_path: Path) -> None:
    source = ROOT / "yt-sql"
    for folder in ("cases", "datasets", "expectations"):
        shutil.copytree(source / folder, tmp_path / folder)
    path = next((tmp_path / "cases").rglob("test.json"))
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["parameters"] = {"valid": {"type": "integer", "value": "9"}}
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert validate_corpus(tmp_path) >= 1
    manifest["parameters"] = {"invalid": 9}
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(CorpusError, match="untagged JSON numbers"):
        validate_corpus(tmp_path)
