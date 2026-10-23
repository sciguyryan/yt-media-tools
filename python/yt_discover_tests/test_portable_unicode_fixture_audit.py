"""Guard the Unicode fixture review inventory and representative edge cases."""

from __future__ import annotations

import json
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_unicode_fixture_audit() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "yt-sql/build_unicode_fixture_audit.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((ROOT / "yt-sql/UNICODE-FIXTURE-AUDIT.json").read_text(encoding="utf-8"))
    dataset = json.loads((ROOT / "yt-sql/datasets/python-v6-small.json").read_text(encoding="utf-8"))
    titles = {record["id"]: record["title"] for record in dataset["records"]}
    assert len(report["categories"]) >= 20
    assert titles["vid037"] != titles["vid038"]
    assert "é" in titles["vid037"]
    assert "e\u0301" in titles["vid038"]
    assert unicodedata.normalize("NFC", "e\u0301") == "é"
    assert unicodedata.is_normalized("NFC", titles["vid037"])
    assert not unicodedata.is_normalized("NFC", titles["vid038"])
    assert "\u200d" in titles["vid041"]
    assert "\u200f" in titles["vid054"]
    assert "\u2028" in titles["vid058"]
    assert any(ord(ch) > 0xFFFF for ch in titles["vid056"])
