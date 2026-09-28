"""Controlled deterministic malformed-query mutations for parser migration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MalformedMutation:
    name: str
    source: str
    expected_category: str = "syntax"


def malformed_neighbours(source: str) -> tuple[MalformedMutation, ...]:
    """Return bounded malformed neighbours when the source exposes known boundaries."""
    mutations: list[MalformedMutation] = []
    replacements = (
        ("SELECT ", "SELECT", "missing-select-separator"),
        (" FROM ", " FROM", "missing-from-separator"),
        (" WHERE ", " WHERE", "missing-where-separator"),
        (" ORDER BY ", " ORDER ", "missing-order-by"),
        (" UNION ALL ", " UNION ALL", "truncated-union-right"),
        (" UNION ", " UNION", "truncated-union-right"),
        (" JOIN ", " JOIN", "truncated-join-relation"),
    )
    for needle, replacement, name in replacements:
        if needle in source:
            candidate = source.replace(needle, replacement, 1)
            if candidate != source:
                mutations.append(MalformedMutation(name, candidate))
    if "(" in source:
        mutations.append(
            MalformedMutation("missing-closing-delimiter", source.rsplit(")", 1)[0] if ")" in source else source + "(")
        )
    if "," in source:
        mutations.append(MalformedMutation("duplicate-delimiter", source.replace(",", ",,", 1)))
    return tuple(dict.fromkeys(mutations))
