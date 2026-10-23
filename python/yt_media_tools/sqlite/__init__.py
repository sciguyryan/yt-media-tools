"""Shared SQLite connections and versioned, named statement resources.

Database owners retain their schemas, migration policy and transaction boundaries.
"""

from .connections import open_read_only, scalar
from .statements import load_statement

__all__ = ["load_statement", "open_read_only", "scalar"]
