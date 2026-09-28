"""Seeded bounded parser-fuzz inputs for migration differential testing."""

from __future__ import annotations

import random

from .parser_grammar_generation import generated_valid_queries
from .parser_mutation import malformed_neighbours


_WHITESPACE = (" ", "  ", "\t", "\n")


def seeded_parser_fuzz_inputs(*, seed: int = 31415926, limit: int = 64) -> tuple[str, ...]:
    """Return reproducible grammar-aware parser stress inputs.

    Inputs combine valid grammar-anchored cases, controlled malformed neighbours
    and whitespace perturbation. The bound prevents accidental unbounded fuzzing
    in the ordinary deterministic suite.
    """
    rng = random.Random(seed)
    pool: list[str] = []
    for case in generated_valid_queries(seed=seed, rounds=3):
        pool.append(case.query)
        pool.extend(item.source for item in malformed_neighbours(case.query))
        words = case.query.split(" ")
        if len(words) > 1:
            separators = [rng.choice(_WHITESPACE) for _ in range(len(words) - 1)]
            pool.append(
                "".join(
                    word + (separators[index] if index < len(separators) else "") for index, word in enumerate(words)
                )
            )
    rng.shuffle(pool)
    return tuple(dict.fromkeys(pool))[:limit]


def shrink_by_token_deletion(source: str) -> tuple[str, ...]:
    """Return deterministic smaller candidates suitable for failure minimisation."""
    tokens = source.split()
    if len(tokens) <= 1:
        return ()
    return tuple(" ".join(tokens[:index] + tokens[index + 1 :]) for index in range(len(tokens)))
