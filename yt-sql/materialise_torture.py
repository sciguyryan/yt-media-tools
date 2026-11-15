"""Materialise reviewed-expectation lexical variants as portable YT-SQL cases.

This is an authoring tool, never a requirement for executing the normative corpus.
It copies approved expectations, not implementation observations. Review the
resulting queries and their semantic equivalence before accepting a commit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from torture_metamorphic import lexical_variants
from validate_corpus import ROOT, _load, validate_corpus

SEED = 6404
GENERATOR_VERSION = 1


def materialise(root: Path, *, check: bool = False) -> int:
    source_paths = sorted(path for path in (root / "cases").rglob("test.json") if "torture-portable" not in path.parts)
    output_root = root / "cases" / "torture-portable"
    expected_paths: set[Path] = set()
    for path in source_paths:
        source = path.parent
        manifest = _load(path)
        source_query = (source / "query.ysql").read_text(encoding="utf-8")
        case_seed = int.from_bytes(hashlib.sha256(manifest["id"].encode()).digest()[:8], "big") ^ SEED
        variants = lexical_variants(source_query, case_seed, 4)
        # Choose a genuine perturbation where possible, with deterministic ordering.
        query = next((variant for variant in variants if variant != source_query), variants[0])
        # Whitespace perturbation may replace the file-final newline; every
        # materialised file must still end with one.
        if not query.endswith("\n"):
            query += "\n"
        identifier = "torture." + manifest["id"]
        destination = output_root / manifest["id"].replace(".", "/")
        new_manifest = dict(manifest)
        new_manifest["id"] = identifier
        new_manifest["description"] = f"Seeded lexical stress of {manifest['id']}; approved expectation unchanged"
        new_manifest["features"] = sorted(set(manifest.get("features", [])) | {"torture.lexical"})
        provenance = {
            "version": 1,
            "generator": "materialise_torture.py",
            "generator_version": GENERATOR_VERSION,
            "seed": SEED,
            "source_case": manifest["id"],
            "source_query_sha256": hashlib.sha256(source_query.encode()).hexdigest(),
            "transformation": "lexical keyword case and existing whitespace only",
            "expectation": "copied verbatim from independently approved source case",
        }
        payloads = {
            "query.ysql": query.encode("utf-8"),
            "test.json": (json.dumps(new_manifest, indent=2, ensure_ascii=False) + "\n").encode(),
            "expected.json": (source / "expected.json").read_bytes(),
            "provenance.json": (json.dumps(provenance, indent=2) + "\n").encode(),
        }
        for name, content in payloads.items():
            target = destination / name
            expected_paths.add(target)
            if check:
                if not target.exists() or target.read_bytes() != content:
                    raise ValueError(f"Materialised torture fixture drift: {target}")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
    if check:
        actual_paths = {p for p in output_root.rglob("*") if p.is_file()}
        if actual_paths != expected_paths:
            raise ValueError("Materialised torture fixture set differs from approved source inventory")
    return len(source_paths)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    count = materialise(args.root, check=args.check)
    validate_corpus(args.root)
    print(f"{'Verified' if args.check else 'Materialised'} {count} portable torture fixtures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
