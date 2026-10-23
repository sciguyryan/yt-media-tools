"""Static ownership contracts for shared SQLite statement references."""

from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STATEMENTS = ROOT / "common" / "sqlite" / "statements"
SOURCES = ROOT / "python" / "yt_media_tools"


def test_all_literal_statement_references_resolve_to_nonempty_resources() -> None:
    """No implementation may refer to a missing canonical SQL resource."""
    references: list[tuple[str, str]] = []
    for source in SOURCES.glob("*.py"):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id != "load_statement" or not node.args:
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                references.append((source.name, arg.value))
    assert references
    missing = [
        (owner, name)
        for owner, name in references
        if not (STATEMENTS / f"{name}.sql").is_file()
        or not (STATEMENTS / f"{name}.sql").read_text(encoding="utf-8").strip()
    ]
    assert not missing, f"Missing or empty canonical SQLite statements: {missing}"


def test_source_and_acquisition_schema_scripts_are_canonical() -> None:
    """Ordered DDL scripts must retain the complete source and trigger definitions."""
    sources = (STATEMENTS / "cache_v4" / "schema_source_state.sql").read_text(encoding="utf-8")
    triggers = (STATEMENTS / "cache_v4" / "schema_acquisition_triggers.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS cache_v4_source_entries" in sources
    assert "CREATE TABLE IF NOT EXISTS cache_v4_source_frontiers" in sources
    assert "CREATE TRIGGER IF NOT EXISTS cache_v4_acquisition_state_provider_insert" in triggers
    assert "CREATE TRIGGER IF NOT EXISTS cache_v4_acquisition_state_provider_update" in triggers


def test_canonical_statement_names_are_descriptive() -> None:
    """Generated hash identifiers must not become part of the shared SQL API."""
    root = STATEMENTS
    offenders = sorted(
        str(path.relative_to(root)) for path in root.rglob("*.sql") if re.search(r"_[0-9a-f]{8}\.sql$", path.name)
    )
    assert not offenders, f"Opaque canonical SQL filenames: {offenders}"
