"""Deterministic code-point-level fixtures for yt-sql Unicode identifiers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IdentifierFixture:
    """One identifier spelling whose code points are intentionally significant."""

    name: str
    spelling: str
    valid_unquoted: bool
    description: str

    @property
    def codepoints(self) -> tuple[int, ...]:
        return tuple(ord(character) for character in self.spelling)


IDENTIFIER_FIXTURES = (
    IdentifierFixture("precomposed_acute", "\u00e1", True, "precomposed Latin small a with acute"),
    IdentifierFixture("decomposed_acute", "a\u0301", True, "Latin a followed by combining acute"),
    IdentifierFixture("combining_chain", "a\u0301\u0323\u0308", True, "base followed by three combining marks"),
    IdentifierFixture("zwj_combining", "a\u200d\u0301", True, "base, zero-width joiner and combining acute"),
    IdentifierFixture("zwnj_combining", "a\u200c\u0301", True, "base, zero-width non-joiner and combining acute"),
    IdentifierFixture("variation_selector", "a\ufe0f", True, "base followed by variation selector-16"),
    IdentifierFixture("devanagari_joined", "\u0915\u094d\u200d\u0937", True, "Devanagari conjunct containing ZWJ"),
    IdentifierFixture("deseret_supplementary", "\U00010400name", True, "supplementary-plane XID start"),
    IdentifierFixture("latin_confusable", "scope", True, "Latin spelling used in a confusable pair"),
    IdentifierFixture("cyrillic_confusable", "sc\u043epe", True, "visually similar spelling containing Cyrillic o"),
    IdentifierFixture(
        "middle_dot_continue", "a\u00b7b", True, "XID continuation outside ordinary ASCII word characters"
    ),
    IdentifierFixture("leading_combining", "\u0301mark", False, "combining mark cannot begin an ordinary identifier"),
    IdentifierFixture("emoji_continue", "a\U0001f600", False, "emoji is not an ordinary identifier continuation"),
    IdentifierFixture("rlo_continue", "a\u202eb", False, "right-to-left override is not an XID continuation"),
    IdentifierFixture("bom_continue", "a\ufeffb", False, "zero-width no-break space/BOM is not an XID continuation"),
)

FIXTURES_BY_NAME = {fixture.name: fixture for fixture in IDENTIFIER_FIXTURES}
