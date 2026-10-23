"""Export a portable heterogeneous source topology from the established fixture."""

from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "python/yt_discover_tests/conformance/multi_source_fixture.py"
DESTINATION = ROOT / "yt-sql/datasets/heterogeneous-sources-v1.json"


def generate() -> dict:
    spec = importlib.util.spec_from_file_location("heterogeneous_fixture", SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load source fixture")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    records = module.heterogeneous_records()
    sources = [module.YOUTUBE_CHANNEL, module.YOUTUBE_PLAYLIST, module.TWITCH_ARCHIVE]
    digest = hashlib.sha256()
    for record in records:
        digest.update(
            json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
                "utf-8"
            )
            + b"\n"
        )
    return {
        "version": 1,
        "id": "heterogeneous-sources-v1",
        "kind": "source-topology",
        "sources": [
            {
                "handle": handle,
                "record_indices": [i for i, record in enumerate(records) if record["_yt_sql_source"] == handle],
            }
            for handle in sources
        ],
        "record_count": len(records),
        "record_digest_sha256": digest.hexdigest(),
        "provenance": {"fixture": "python/yt_discover_tests/conformance/multi_source_fixture.py"},
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check committed fixture without writing")
    args = parser.parse_args()
    expected = json.dumps(generate(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.check:
        if not DESTINATION.exists() or DESTINATION.read_text(encoding="utf-8") != expected:
            print(f"{DESTINATION.relative_to(ROOT)} needs regeneration")
            return 1
        print(f"{DESTINATION.relative_to(ROOT)} is current")
    else:
        DESTINATION.write_text(expected, encoding="utf-8")
        print(f"Exported {DESTINATION.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
