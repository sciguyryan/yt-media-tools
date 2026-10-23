"""Verify the committed portable small and normal fixture profiles."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATASETS = ROOT / "yt-sql/datasets"
VALIDATOR_PATH = ROOT / "yt-sql/validate_portable_dataset.py"
spec = importlib.util.spec_from_file_location("portable_dataset_profiles_validator", VALIDATOR_PATH)
assert spec is not None and spec.loader is not None
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


@pytest.mark.parametrize(("profile", "size"), [("small", 60), ("normal", 1000)])
def test_materialised_profile_is_portable(profile: str, size: int) -> None:
    path = DATASETS / f"python-v6-{profile}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    validator.validate_file(path)
    assert data["kind"] == "static"
    assert data["record_count"] == size
    assert data["provenance"]["profile"] == profile
    assert data["provenance"]["seed"] == 31415926
    assert data["records"][0]["id"] == "vid001"
    assert len({record["id"] for record in data["records"]}) == size


def test_all_committed_profiles_reproduce() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "yt-sql/export_portable_dataset.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
