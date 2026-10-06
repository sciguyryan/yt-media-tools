"""Optional Tree-sitter boundary for the yt-sql parser experiment.

The generated language package and Tree-sitter runtime are deliberately absent
from the production dependency set. This module must therefore remain safe to
import when neither optional package is installed.
"""

from __future__ import annotations

from functools import lru_cache
from importlib.util import find_spec

from .query_model import QuerySyntaxError

TREE_SITTER_ABI = 15
TREE_SITTER_RUNTIME_VERSION = "0.26.0"


class TreeSitterUnavailableError(RuntimeError):
    """Raised when the optional experimental parser has not been installed."""


def tree_sitter_available() -> bool:
    """Return whether both optional Tree-sitter packages are installed."""
    return find_spec("tree_sitter") is not None and find_spec("tree_sitter_yt_sql") is not None


@lru_cache(maxsize=1)
def _parser():
    """Construct the optional parser once for experimental measurements."""
    try:
        from tree_sitter import Language, Parser
        import tree_sitter_yt_sql
    except ImportError as error:
        raise TreeSitterUnavailableError(
            "The experimental Tree-sitter runtime and yt-sql language package are not installed."
        ) from error

    language = Language(tree_sitter_yt_sql.language())
    if language.abi_version != TREE_SITTER_ABI:
        raise TreeSitterUnavailableError(
            f"The experimental yt-sql grammar uses Tree-sitter ABI {language.abi_version}; "
            f"ABI {TREE_SITTER_ABI} is required."
        )
    return Parser(language)


def _parse_tree_sitter_tree(source: str):
    """Parse UTF-8 source without exposing the concrete tree as a public API."""
    return _parser().parse(source.encode("utf-8"))


def _character_offset(source_bytes: bytes, byte_offset: int) -> int:
    """Convert one Tree-sitter UTF-8 byte offset to a Python character offset."""
    return len(source_bytes[:byte_offset].decode("utf-8", errors="ignore"))


def _first_error_node(root):
    """Return the earliest recovery or missing node in source order."""
    pending = [root]
    failures = []
    while pending:
        node = pending.pop()
        if node.is_error or node.is_missing:
            failures.append(node)
        pending.extend(reversed(node.children))
    return min(failures, key=lambda node: (node.start_byte, node.end_byte), default=root)


def recognise_tree_sitter_query(source: str) -> None:
    """Recognise the current experimental grammar and reject recovered trees."""
    source_bytes = source.encode("utf-8")
    tree = _parser().parse(source_bytes)
    root = tree.root_node
    if root.has_error:
        failure = _first_error_node(root)
        failure_start = failure.end_byte if failure == root and failure.is_error else failure.start_byte
        raise QuerySyntaxError(
            source,
            "The query is not valid experimental Tree-sitter syntax.",
            _character_offset(source_bytes, failure_start),
            end_position=_character_offset(source_bytes, failure.end_byte),
        )
    return None
