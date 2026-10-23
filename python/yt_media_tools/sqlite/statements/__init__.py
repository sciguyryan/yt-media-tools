"""Load canonical SQL statements from the repository's shared SQLite resources."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re

_NAME = re.compile(r"[a-z][a-z0-9_]*(?:/[a-z][a-z0-9_]*)*")
_STATEMENTS = Path(__file__).resolve().parents[4] / "common" / "sqlite" / "statements"


@lru_cache(maxsize=256)
def load_statement(name: str) -> str:
    """Load one canonical statement, rejecting unsafe names and empty resources."""
    if not isinstance(name, str) or _NAME.fullmatch(name) is None:
        raise ValueError(f"invalid SQLite statement name: {name!r}")
    resource = _STATEMENTS.joinpath(*name.split("/")).with_suffix(".sql")
    try:
        sql = resource.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise ValueError(f"unknown SQLite statement: {name}") from exc
    if not sql:
        raise ValueError(f"empty SQLite statement: {name}")
    return sql
