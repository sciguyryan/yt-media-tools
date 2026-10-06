"""Bounded deterministic query generation anchored to the formal grammar.

This is deliberately a conformance generator, not a second parser. Each family
names the EBNF production it exercises; loading validates that the production
still exists in the authoritative grammar before examples are emitted.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import random
import re

GRAMMAR_PATH = Path(__file__).parents[1] / "docs" / "YT-SQL-GRAMMAR.ebnf"
_PRODUCTION_RE = re.compile(r"^([a-z][a-z0-9-]*)\s*=", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class GrammarGeneratedCase:
    production: str
    query: str


_FAMILIES: dict[str, tuple[str, ...]] = {
    "select-query": (
        "SELECT id FROM @fixture",
        "SELECT DISTINCT title, duration FROM @fixture WHERE duration > 0 ORDER BY title LIMIT 5 OFFSET 1",
    ),
    "predicate-only-query": ("duration >= 1h", "NOT (title IS NULL OR duration < 60)"),
    "predicate-suffix": (
        "FROM @fixture WHERE duration NOT BETWEEN 10 AND 20",
        "FROM @fixture WHERE title NOT IN ('a', 'b')",
        "FROM @fixture WHERE title DOES NOT CONTAIN 'x'",
        "FROM @fixture WHERE title IS NOT DISTINCT FROM other",
    ),
    "truth-test": ("FROM @fixture WHERE (title IS NULL) IS NOT FALSE",),
    "postfix-expression": ("SELECT formats[0].height FROM @fixture", "SELECT thumbnails[1].url FROM @fixture"),
    "case-expression": ("SELECT CASE WHEN duration > 1h THEN 'long' ELSE 'short' END FROM @fixture",),
    "collection-predicate": ("SELECT id FROM @fixture WHERE ANY(formats AS f WHERE f.height >= 1080)",),
    "relation-reference": ("SELECT id FROM @fixture OF videos, live",),
    "join-clause": ("SELECT a.id FROM @a AS a JOIN @b AS b ON a.id = b.id",),
    "with-clause": ("WITH x AS (SELECT id FROM @fixture) SELECT id FROM x",),
    "union-operator": ("SELECT id FROM @a UNION ALL SELECT id FROM @b",),
    "scalar-function": ("SELECT COALESCE(title, 'missing'), RANDOM(7) FROM @fixture",),
    "aggregate-function": ("SELECT COUNT(*), AVG(duration) FROM @fixture",),
    "aggregate-filter": ("SELECT COUNT(*) FILTER (WHERE duration > 10) FROM @fixture",),
    "having-expression": ("SELECT uploader_id, COUNT(*) FROM @fixture GROUP BY uploader_id HAVING NOT COUNT(*) > 1",),
    "order-by-clause": ("SELECT id FROM @fixture ORDER BY id DESC",),
    "number": ("SELECT 255, 0xff, 0o377, 0b11111111 FROM @fixture",),
}


def grammar_productions() -> frozenset[str]:
    """Return production names declared by the authoritative EBNF."""
    return frozenset(_PRODUCTION_RE.findall(GRAMMAR_PATH.read_text()))


def generated_valid_queries(*, seed: int = 31415926, rounds: int = 2) -> tuple[GrammarGeneratedCase, ...]:
    """Return reproducible bounded valid cases tied to named grammar productions."""
    productions = grammar_productions()
    missing = sorted(set(_FAMILIES) - productions)
    if missing:
        raise AssertionError(f"Generator references missing grammar productions: {', '.join(missing)}")
    rng = random.Random(seed)
    result: list[GrammarGeneratedCase] = []
    names = sorted(_FAMILIES)
    for _ in range(max(1, rounds)):
        rng.shuffle(names)
        for name in names:
            result.append(GrammarGeneratedCase(name, rng.choice(_FAMILIES[name])))
    return tuple(result)
