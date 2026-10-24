"""Experimental YT-SQL dialect for the pinned SQLFluff 4.4.0 runtime.

This is a formatter grammar, not the authoritative YT-SQL parser. Keep
extensions narrow and validate every addition against the portable corpus.
"""

from sqlfluff.core.dialects import load_raw_dialect
from sqlfluff.core.parser import OneOf, Ref, Sequence

sqlite = load_raw_dialect("sqlite")
ytsql_dialect = sqlite.copy_as(
    "ytsql",
    formatted_name="YT-SQL (experimental)",
    docstring="YT-SQL formatting dialect; language validity is defined by Discover.",
)


class TableReferenceSegment(sqlite.get_segment("TableReferenceSegment")):
    """Accept the YT-SQL fixture source without interpreting it as a bind value."""

    match_grammar = OneOf(
        Ref("AtSignLiteralSegment"),
        sqlite.get_segment("TableReferenceSegment").match_grammar,
    )


ytsql_dialect.replace(TableReferenceSegment=TableReferenceSegment)

# SQLite narrows the inherited LIKE grammar to LIKE alone. YT-SQL also
# supports ILIKE; restore this alternative without changing SQLite linting.
ytsql_dialect.sets("unreserved_keywords").update({"ILIKE", "CONTAINS", "CONTAIN", "MATCHES", "MATCH", "DOES"})
ytsql_dialect.replace(
    LikeGrammar=OneOf("LIKE", "ILIKE", "CONTAINS", "CONTAIN", "MATCHES", "MATCH"),
    LikeExpressionGrammar=Sequence(
        OneOf(Sequence("DOES", "NOT"), "NOT", optional=True),
        Ref("LikeGrammar"),
        Ref("Expression_A_Grammar"),
        Sequence("ESCAPE", Ref("Tail_Recurse_Expression_A_Grammar"), optional=True),
    ),
)
