"""Check invariants spanning independently validated portable fixture families."""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATASETS = HERE / "datasets"


def check_relationships(directory: Path = DATASETS) -> list[str]:
    """Return cross-fixture inconsistencies without changing committed inputs."""
    errors: list[str] = []
    small = json.loads((directory / "python-v6-small.json").read_text(encoding="utf-8"))
    normal = json.loads((directory / "python-v6-normal.json").read_text(encoding="utf-8"))
    source = json.loads((directory / "heterogeneous-sources-v1.json").read_text(encoding="utf-8"))
    facets = json.loads((directory / "heterogeneous-facets-v1.json").read_text(encoding="utf-8"))

    # Profiles share a generator and seed, but record prefixes are NOT assumed
    # identical: profile size may affect deterministic generation.
    for key in ("source", "source_url", "generated_at"):
        if small[key] != normal[key]:
            errors.append(f"record profiles disagree on {key}")
    for key in ("generator_version", "seed"):
        if small["provenance"].get(key) != normal["provenance"].get(key):
            errors.append(f"record profiles disagree on provenance.{key}")

    for key in ("records", "sources", "record_count", "record_digest_sha256"):
        if source[key] != facets[key]:
            errors.append(f"facet topology differs from source topology in {key}")
    if not any(not item["record_indices"] for item in facets["facets"]):
        errors.append("facet topology has no empty relation")
    return errors


def main() -> int:
    errors = check_relationships()
    for error in errors:
        print(f"FAIL {error}")
    if not errors:
        print("PASS cross-fixture relationships")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
