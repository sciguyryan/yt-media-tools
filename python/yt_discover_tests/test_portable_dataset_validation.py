"""Check that the portable dataset contract fails closed on corrupted fixtures."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "yt-sql/validate_portable_dataset.py"
spec = importlib.util.spec_from_file_location("portable_dataset_validation", SCRIPT)
assert spec is not None and spec.loader is not None
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)
DATASET = json.loads((ROOT / "yt-sql/datasets/python-v6-small.json").read_text(encoding="utf-8"))


def test_committed_dataset_validates() -> None:
    validator.validate_dataset(DATASET)
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data.update(record_count=59),
        lambda data: data["records"][0].update(title="changed"),
        lambda data: data["records"][1].update(id=data["records"][0]["id"]),
        lambda data: data.update(version=True),
        lambda data: data["records"][0].update(title="\ud800"),
        lambda data: data.update(unexpected="field"),
        lambda data: data.update(provenance={"seed": 1}),
    ],
)
def test_corrupted_dataset_rejected(mutation) -> None:
    data = copy.deepcopy(DATASET)
    mutation(data)
    with pytest.raises(ValueError):
        validator.validate_dataset(data)


def test_duplicate_json_keys_rejected(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text('{"version": 1, "version": 1}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON key"):
        validator.validate_file(path)
