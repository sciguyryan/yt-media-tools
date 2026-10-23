"""Cross-fixture relationships must remain consistent and independently testable."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "yt-sql/check_fixture_relationships.py"
spec = importlib.util.spec_from_file_location("check_fixture_relationships", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def _copy_fixtures(tmp_path: Path) -> None:
    for name in (
        "python-v6-small.json",
        "python-v6-normal.json",
        "heterogeneous-sources-v1.json",
        "heterogeneous-facets-v1.json",
    ):
        (tmp_path / name).write_bytes((ROOT / "yt-sql/datasets" / name).read_bytes())


def test_committed_relationships() -> None:
    assert module.check_relationships() == []


def test_detects_divergent_facet_records(tmp_path: Path) -> None:
    _copy_fixtures(tmp_path)
    path = tmp_path / "heterogeneous-facets-v1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["records"][0]["id"] = "different"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert any("records" in error for error in module.check_relationships(tmp_path))


def test_detects_divergent_profile_source(tmp_path: Path) -> None:
    _copy_fixtures(tmp_path)
    path = tmp_path / "python-v6-normal.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["source"] = "@different"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert any("source" in error for error in module.check_relationships(tmp_path))


def test_detects_missing_empty_relation(tmp_path: Path) -> None:
    _copy_fixtures(tmp_path)
    path = tmp_path / "heterogeneous-facets-v1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["facets"] = [f for f in data["facets"] if f["record_indices"]]
    path.write_text(json.dumps(data), encoding="utf-8")
    assert any("empty relation" in error for error in module.check_relationships(tmp_path))
