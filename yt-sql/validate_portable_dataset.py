"""Validate committed portable YT-SQL datasets without importing an engine."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "yt-sql/datasets"


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-JSON numeric constant: {value}")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _integer(value: object) -> bool:
    return type(value) is int


def _validate_json_value(value: object, path: str = "$") -> None:
    if isinstance(value, str):
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise ValueError(f"{path}: unpaired Unicode surrogate") from exc
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{path}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            _validate_json_value(key, f"{path} key")
            _validate_json_value(item, f"{path}.{key}")


def validate_dataset(data: object) -> None:
    _require(isinstance(data, dict), "dataset must be an object")
    assert isinstance(data, dict)
    allowed = {
        "version",
        "id",
        "kind",
        "generator",
        "generator_version",
        "seed",
        "size",
        "source",
        "records",
        "source_url",
        "generated_at",
        "record_count",
        "record_digest_sha256",
        "provenance",
    }
    _require(not (data.keys() - allowed), "unknown dataset fields")
    _require(_integer(data.get("version")) and data["version"] == 1, "unsupported dataset version")
    _require(isinstance(data.get("id"), str) and bool(data["id"]), "invalid dataset id")
    _require(data.get("kind") in ("static", "generated"), "invalid dataset kind")
    _validate_json_value(data)
    if data["kind"] == "generated":
        _require(isinstance(data.get("generator"), str) and bool(data["generator"]), "missing generator")
        _require(
            _integer(data.get("seed")) and _integer(data.get("size")) and data["size"] >= 0,
            "invalid generated parameters",
        )
        _require("records" not in data, "generated descriptor must not contain records")
        return
    for field in ("source", "source_url", "generated_at"):
        _require(isinstance(data.get(field), str) and bool(data[field]), f"missing {field}")
    provenance = data.get("provenance")
    _require(isinstance(provenance, dict), "missing provenance")
    assert isinstance(provenance, dict)
    _require(set(provenance) == {"generator", "generator_version", "seed", "profile"}, "invalid provenance fields")
    _require(
        all(isinstance(provenance[k], str) and bool(provenance[k]) for k in ("generator", "profile")),
        "invalid provenance strings",
    )
    _require(_integer(provenance["generator_version"]) and _integer(provenance["seed"]), "invalid provenance integers")
    records = data.get("records")
    _require(isinstance(records, list), "missing records")
    assert isinstance(records, list)
    _require(_integer(data.get("record_count")) and data["record_count"] == len(records), "record count mismatch")
    ids = set()
    digest = hashlib.sha256()
    for index, record in enumerate(records):
        _require(isinstance(record, dict), f"record {index} must be an object")
        _require(isinstance(record.get("id"), str) and bool(record["id"]), f"record {index} has invalid id")
        _require(record["id"] not in ids, f"duplicate record id: {record['id']}")
        ids.add(record["id"])
        digest.update(
            json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
                "utf-8"
            )
        )
        digest.update(b"\n")
    _require(digest.hexdigest() == data.get("record_digest_sha256"), "ordered record digest mismatch")


def validate_file(path: Path) -> None:
    data = json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs, parse_constant=_reject_constant
    )
    validate_dataset(data)
    if data["id"] != path.stem:
        raise ValueError("dataset id does not match filename")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, help="Dataset JSON files (default: committed datasets)")
    args = parser.parse_args()
    paths = args.paths or sorted(path for path in DATASETS.glob("python-v6-*.json"))
    if not paths:
        parser.error("no dataset files found")
    for path in paths:
        try:
            validate_file(path)
        except (ValueError, UnicodeError, OSError) as exc:
            parser.exit(1, f"{path}: {exc}\n")
        print(f"{path}: valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
