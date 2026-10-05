"""Deterministic parser-migration corpus shared by differential tests.

The corpus complements the larger execution conformance suite with parser-level
examples chosen to exercise grammar boundaries directly.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AcceptedParserCase:
    name: str
    query: str


@dataclass(frozen=True, slots=True)
class RejectedParserCase:
    name: str
    query: str
    category: str
    reason: str


ACCEPTED_PARSER_CASES = (
    AcceptedParserCase("implicit-select", "FROM @fixture WHERE duration < 1h"),
    AcceptedParserCase("predicate-only", "duration < 1h AND title IS NOT NULL"),
    AcceptedParserCase("whitespace-negation", "NOT\t(title IS NULL\nOR duration < 60)"),
    AcceptedParserCase("distinct-from-field", "FROM @fixture WHERE title IS NOT DISTINCT FROM other"),
    AcceptedParserCase("unicode-identifiers", "SELECT Δelta, δelta FROM @fixture"),
    AcceptedParserCase("precedence", "SELECT alpha + beta * gamma FROM @fixture"),
    AcceptedParserCase("postfix-chain", "SELECT formats[0].height FROM @fixture"),
    AcceptedParserCase(
        "case-expression", "SELECT CASE WHEN duration > 1h THEN 'long' ELSE 'short' END AS class FROM @fixture"
    ),
    AcceptedParserCase("facet-source", "SELECT id FROM @fixture OF videos, live"),
    AcceptedParserCase("join", "SELECT a.id FROM @left AS a LEFT JOIN @right AS b ON a.id = b.id"),
    AcceptedParserCase(
        "cte", "WITH recent AS (SELECT id FROM @fixture WHERE upload_date >= 2025-01-01) SELECT id FROM recent"
    ),
    AcceptedParserCase("compound", "SELECT id FROM @a UNION ALL SELECT id FROM @b ORDER BY id LIMIT 5 OFFSET 1"),
    AcceptedParserCase("grouped-compound", "(SELECT id FROM @a ORDER BY id LIMIT 2) UNION SELECT id FROM @b"),
    AcceptedParserCase("non-decimal", "SELECT 0xff + 0b10 + 0o7 FROM @fixture"),
)


REJECTED_PARSER_CASES = (
    RejectedParserCase("unterminated-string", "SELECT 'broken FROM @fixture", "lexical", "unterminated-string"),
    RejectedParserCase("missing-projection", "SELECT FROM @fixture", "syntax", "missing-clause-separator"),
    RejectedParserCase("missing-source", "SELECT id FROM", "syntax", "missing-source"),
    RejectedParserCase("missing-facet", "SELECT id FROM @fixture OF", "syntax", "missing-facet"),
    RejectedParserCase("missing-join-relation", "SELECT id FROM @fixture LEFT JOIN", "syntax", "missing-source"),
    RejectedParserCase("missing-join-on", "SELECT id FROM @fixture LEFT JOIN @other", "syntax", "missing-join-on"),
    RejectedParserCase("dangling-union", "SELECT id FROM @fixture UNION", "syntax", "incomplete-union"),
    RejectedParserCase("empty-cte", "WITH x AS () SELECT id FROM x", "syntax", "empty-query"),
    RejectedParserCase(
        "repeated-where", "SELECT id FROM @fixture WHERE id = 'x' WHERE id = 'y'", "syntax", "clause-order"
    ),
    RejectedParserCase("backwards-limit", "SELECT id FROM @fixture LIMIT 2 ORDER BY id", "syntax", "clause-order"),
    RejectedParserCase("broken-postfix", "SELECT formats[].height FROM @fixture", "syntax", "missing-index-expression"),
    RejectedParserCase(
        "missing-distinct-from-separator",
        "FROM @fixture WHERE title IS NOT DISTINCT FROMother",
        "syntax",
        "invalid",
    ),
)
