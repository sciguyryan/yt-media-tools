"""Experimental Lark parser boundary for yt-sql grammar revision 1.

This module is intentionally not wired into the production parser path. The
formal EBNF remains authoritative; this Lark grammar is an implementation
artefact used to investigate issue #143.
"""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files

from lark import Lark
from lark.exceptions import LarkError

from .query_model import QuerySyntaxError


@lru_cache(maxsize=1)
def _parser() -> Lark:
    """Build the experimental parser once per process."""
    grammar = files("yt_media_tools").joinpath("yt_sql_lark.lark").read_text(encoding="utf-8")
    return Lark(grammar, parser="earley", propagate_positions=True, maybe_placeholders=False)


def recognise_lark_query(source: str) -> None:
    """Recognise *source* without exposing parser-library objects to callers."""
    try:
        _parser().parse(source)
        return None
    except LarkError as error:
        position = getattr(error, "pos_in_stream", None)
        if not isinstance(position, int):
            position = len(source)
        raise QuerySyntaxError(source, "Experimental declarative parser rejected the query.", position) from error
