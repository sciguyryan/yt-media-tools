"""Reusable differential oracles for a future yt-sql candidate parser."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Callable

from yt_media_tools.parser_equivalence import normalised_diagnostic, normalised_parser_model, user_origin_positions
from yt_media_tools.query_formatter import format_query
from yt_media_tools.query_model import Query, QuerySyntaxError

ParserCallable = Callable[[str], Query]


@dataclass(frozen=True, slots=True)
class ParserOutcome:
    model: object | None
    origins: tuple[tuple[str, int], ...]
    diagnostic: tuple[object, ...] | None


@dataclass(frozen=True, slots=True)
class ParserTiming:
    label: str
    queries: int
    iterations: int
    elapsed_seconds: float

    @property
    def parses_per_second(self) -> float:
        return (self.queries * self.iterations) / self.elapsed_seconds if self.elapsed_seconds else float("inf")


def capture_outcome(parser: ParserCallable, source: str) -> ParserOutcome:
    """Capture one parser result without exposing implementation-specific trees."""
    try:
        query = parser(source)
    except QuerySyntaxError as error:
        return ParserOutcome(None, (), normalised_diagnostic(error))
    return ParserOutcome(normalised_parser_model(query), user_origin_positions(query), None)


def canonical_round_trip(parser: ParserCallable, source: str) -> tuple[object, str]:
    """Return the normalised model and canonical text after one parser round trip."""
    parsed = parser(source)
    canonical = format_query(parsed)
    reparsed = parser(canonical)
    if normalised_parser_model(parsed) != normalised_parser_model(reparsed):
        raise AssertionError("parse-format-parse changed the normalised yt-sql model")
    if format_query(reparsed) != canonical:
        raise AssertionError("canonical formatting is not idempotent")
    return normalised_parser_model(parsed), canonical


def benchmark_parser(
    parser: ParserCallable, queries: tuple[str, ...], *, label: str, iterations: int = 100
) -> ParserTiming:
    """Measure a parser workload without imposing a migration acceptance threshold."""
    started = perf_counter()
    for _ in range(iterations):
        for source in queries:
            try:
                parser(source)
            except QuerySyntaxError:
                pass
    elapsed = perf_counter() - started
    return ParserTiming(label, len(queries), iterations, elapsed)
