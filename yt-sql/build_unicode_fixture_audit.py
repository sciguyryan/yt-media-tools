"""Audit the Unicode content of the committed portable YT-SQL small fixture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATASET = ROOT / "datasets/python-v6-small.json"
REPORT = ROOT / "UNICODE-FIXTURE-AUDIT.json"


def generate() -> dict:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    records = {row["id"]: row for row in dataset["records"]}
    assert len(records) == dataset["record_count"]
    assert report["dataset_record_digest_sha256"] == dataset["record_digest_sha256"]
    for category in report["categories"]:
        assert category["record_ids"], category["id"]
        for record_id in category["record_ids"]:
            assert record_id in records, (category["id"], record_id)
            assert any(ord(c) > 127 for c in records[record_id]["title"]), record_id
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    report = generate()
    if args.check:
        print(f"{REPORT.name} is current and references valid Unicode fixture records")
    else:
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Updated {REPORT.name}")


if __name__ == "__main__":
    main()
