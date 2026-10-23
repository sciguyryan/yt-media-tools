"""Export committed portable fixtures from the canonical deterministic generator."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "yt-sql/datasets"
GENERATOR = ROOT / "python/yt_discover_tests/conformance/generate_dataset.py"
COMMITTED_PROFILES = ("small", "normal")


def _generator():
    spec = importlib.util.spec_from_file_location("yt_sql_dataset_generator", GENERATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load canonical dataset generator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def record_digest(records: list[dict]) -> str:
    """Hash ordered logical records using the portable UTF-8 JSON contract."""
    digest = hashlib.sha256()
    for record in records:
        digest.update(
            json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
                "utf-8"
            )
        )
        digest.update(b"\n")
    return digest.hexdigest()


def generate(profile: str = "small") -> dict:
    generator = _generator()
    if profile not in COMMITTED_PROFILES:
        raise ValueError(f"unsupported committed profile: {profile}")
    records = generator.build_records(generator.profile_size(profile), seed=generator.DATASET_SEED)
    return {
        "version": 1,
        "id": f"python-v6-{profile}",
        "kind": "static",
        "source": generator.SOURCE_HANDLE,
        "source_url": generator.SOURCE_URL,
        "generated_at": generator.GENERATED_AT,
        "record_count": len(records),
        "record_digest_sha256": record_digest(records),
        "provenance": {
            "generator": "python/yt_discover_tests/conformance/generate_dataset.py",
            "generator_version": generator.GENERATOR_VERSION,
            "seed": generator.DATASET_SEED,
            "profile": profile,
        },
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check committed fixtures without writing")
    parser.add_argument(
        "--profile", choices=(*COMMITTED_PROFILES, "all"), default="all", help="Fixture profile to export or check"
    )
    args = parser.parse_args()
    profiles = COMMITTED_PROFILES if args.profile == "all" else (args.profile,)
    stale = False
    for profile in profiles:
        destination = DATASETS / f"python-v6-{profile}.json"
        expected = json.dumps(generate(profile), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.check:
            if not destination.exists() or destination.read_text(encoding="utf-8") != expected:
                print(f"{destination.relative_to(ROOT)} needs regeneration")
                stale = True
            else:
                print(f"{destination.relative_to(ROOT)} is current")
        else:
            destination.write_text(expected, encoding="utf-8")
            print(f"Exported {destination.relative_to(ROOT)}")
    return int(stale)


if __name__ == "__main__":
    raise SystemExit(main())
