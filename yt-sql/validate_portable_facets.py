"""Validate a portable source/facet topology without running a YT-SQL engine."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "yt-sql"))

from validate_portable_topology import validate as validate_sources  # noqa: E402
from validate_portable_dataset import _unique_pairs, _reject_constant, _require, _integer  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "yt-sql/datasets/heterogeneous-facets-v1.json"


def validate(data: object) -> None:
    _require(isinstance(data, dict), "facet topology must be an object")
    _require(
        set(data)
        == {
            "version",
            "id",
            "kind",
            "provenance",
            "record_count",
            "record_digest_sha256",
            "records",
            "sources",
            "facets",
        },
        "invalid facet topology fields",
    )
    # Reuse the independently validated source-membership and digest contract.
    source_view = {key: data[key] for key in ("version", "record_count", "record_digest_sha256", "records", "sources")}
    source_view.update(
        id="heterogeneous-sources-v1", kind="source-topology", provenance={"fixture": "portable-facet-topology"}
    )
    validate_sources(source_view)
    _require(data["id"] == "heterogeneous-facets-v1" and data["kind"] == "facet-topology", "invalid facet identity")
    _require(data["provenance"] == {"source_dataset": "heterogeneous-sources-v1"}, "invalid facet provenance")
    facets = data["facets"]
    _require(isinstance(facets, list) and bool(facets), "missing facets")
    sources = {item["handle"]: set(item["record_indices"]) for item in data["sources"]}
    seen: set[tuple[str, str]] = set()
    covered: set[int] = set()
    empty = False
    for facet in facets:
        _require(
            isinstance(facet, dict) and set(facet) == {"source", "name", "record_indices"}, "invalid facet descriptor"
        )
        source, name, indices = facet["source"], facet["name"], facet["record_indices"]
        _require(
            isinstance(source, str) and source in sources and isinstance(name, str) and bool(name),
            "invalid facet source or name",
        )
        key = (source, name)
        _require(key not in seen, "duplicate facet")
        seen.add(key)
        _require(isinstance(indices, list), "invalid facet indices")
        _require(all(_integer(i) and i in sources[source] for i in indices), "facet record outside source")
        _require(len(indices) == len(set(indices)), "duplicate facet index")
        covered.update(indices)
        empty |= not indices
    _require(covered == set(range(len(data["records"]))), "records missing from facets")
    _require(empty, "fixture must exercise empty facet relations")


def validate_file(path: Path = PATH) -> None:
    data = json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs, parse_constant=_reject_constant
    )
    validate(data)
    _require(path.stem == data["id"], "filename identity mismatch")


if __name__ == "__main__":
    try:
        validate_file()
    except (ValueError, OSError, UnicodeError) as exc:
        raise SystemExit(f"{PATH}: {exc}") from exc
    print(f"{PATH}: valid")
