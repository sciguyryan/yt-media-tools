"""Check portable fixture integrity without loading the YT-SQL engine."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "yt-sql/datasets/python-v6-small.json"


def test_portable_fixture_integrity() -> None:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    assert dataset["kind"] == "static"
    records = dataset["records"]
    assert len(records) == dataset["record_count"] == 60
    assert len({record["id"] for record in records}) == len(records)
    digest = hashlib.sha256()
    for record in records:
        digest.update(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
    assert digest.hexdigest() == dataset["record_digest_sha256"]
    assert records[0]["id"] == "vid001"
    assert records[-1]["id"] == "vid060"


def test_portable_fixture_matches_generator() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "yt-sql/export_portable_dataset.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
