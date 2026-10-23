"""Independently validate the portable heterogeneous source topology."""

from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "yt-sql"))
from validate_portable_dataset import _unique_pairs, _reject_constant, _validate_json_value, _require, _integer  # noqa: E402 - repository-local import follows the explicit path bootstrap


def validate(data: object) -> None:
    _require(isinstance(data, dict), "topology must be an object")
    _require(
        set(data)
        == {"version", "id", "kind", "sources", "record_count", "record_digest_sha256", "provenance", "records"},
        "invalid topology fields",
    )
    _require(_integer(data["version"]) and data["version"] == 1, "invalid topology version")
    _require(
        data["id"] == "heterogeneous-sources-v1" and data["kind"] == "source-topology", "invalid topology identity"
    )
    _validate_json_value(data)
    _require(
        isinstance(data["provenance"], dict)
        and set(data["provenance"]) == {"fixture"}
        and isinstance(data["provenance"]["fixture"], str)
        and bool(data["provenance"]["fixture"]),
        "invalid provenance",
    )
    records = data["records"]
    _require(
        isinstance(records, list) and _integer(data["record_count"]) and len(records) == data["record_count"],
        "invalid record count",
    )
    sources = data["sources"]
    _require(isinstance(sources, list) and bool(sources), "missing sources")
    seen_handles: set[str] = set()
    seen_indices: set[int] = set()
    for source in sources:
        _require(isinstance(source, dict) and set(source) == {"handle", "record_indices"}, "invalid source descriptor")
        handle = source["handle"]
        _require(
            isinstance(handle, str) and bool(handle) and handle not in seen_handles,
            "invalid or duplicate source handle",
        )
        seen_handles.add(handle)
        indices = source["record_indices"]
        _require(isinstance(indices, list) and bool(indices), "empty source relation")
        for index in indices:
            _require(
                _integer(index) and 0 <= index < len(records) and index not in seen_indices,
                "duplicate or invalid source index",
            )
            seen_indices.add(index)
            _require(
                isinstance(records[index], dict) and records[index].get("_yt_sql_source") == handle,
                "source membership mismatch",
            )
    _require(seen_indices == set(range(len(records))), "unassigned records")
    identities: set[tuple[str, str]] = set()
    digest = hashlib.sha256()
    for record in records:
        _require(
            isinstance(record, dict) and isinstance(record.get("id"), str) and bool(record["id"]), "invalid record id"
        )
        identity = (record["_yt_sql_source"], record["id"])
        _require(identity not in identities, "duplicate id within source")
        identities.add(identity)
        digest.update(
            json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
                "utf-8"
            )
            + b"\n"
        )
    _require(digest.hexdigest() == data["record_digest_sha256"], "ordered record digest mismatch")


def validate_file(path: Path) -> None:
    data = json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs, parse_constant=_reject_constant
    )
    validate(data)
    _require(data["id"] == path.stem, "filename identity mismatch")


if __name__ == "__main__":
    path = ROOT / "yt-sql/datasets/heterogeneous-sources-v1.json"
    try:
        validate_file(path)
    except (ValueError, OSError, UnicodeError) as exc:
        raise SystemExit(f"{path}: {exc}") from exc
    print(f"{path}: valid")
