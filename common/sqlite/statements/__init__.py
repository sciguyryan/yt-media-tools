"""Named, packaged SQL statements, resolved independently of the working directory."""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files
import re

_NAME = re.compile(r"[a-z][a-z0-9_]*(?:/[a-z][a-z0-9_]*)*")


@lru_cache(maxsize=256)
def load_statement(name: str) -> str:
    """Load one reviewed SQL statement; reject path traversal and empty resources."""
    if not isinstance(name, str) or _NAME.fullmatch(name) is None:
        raise ValueError(f"invalid SQLite statement name: {name!r}")
    resource = files(__package__).joinpath(*name.split("/")).with_name(name.split("/")[-1] + ".sql")
    try:
        sql = resource.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise ValueError(f"unknown SQLite statement: {name}") from exc
    if not sql:
        raise ValueError(f"empty SQLite statement: {name}")
    return sql
