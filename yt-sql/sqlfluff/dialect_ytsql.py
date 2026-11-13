"""Experimental YT-SQL dialect for the pinned SQLFluff 4.4.0 runtime.

This is a formatter grammar, not the authoritative YT-SQL parser. Keep
extensions narrow and validate every addition against the portable corpus.
"""

from sqlfluff.core.dialects import load_raw_dialect
from sqlfluff.core.parser import Bracketed, OneOf, Ref, Sequence

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
ytsql_dialect.sets("unreserved_keywords").update(
    {"ILIKE", "CONTAINS", "CONTAIN", "MATCHES", "MATCH", "DOES", "FILTER", "MAP", "COUNT"}
)
ytsql_dialect.replace(
    LikeGrammar=OneOf("LIKE", "ILIKE", "CONTAINS", "CONTAIN", "MATCHES", "MATCH"),
    LikeExpressionGrammar=Sequence(
        OneOf(Sequence("DOES", "NOT"), "NOT", optional=True),
        Ref("LikeGrammar"),
        Ref("Expression_A_Grammar"),
        Sequence("ESCAPE", Ref("Tail_Recurse_Expression_A_Grammar"), optional=True),
    ),
)


# Collection bindings are a YT-SQL extension to ordinary SQL functions.
# Keep the standard function_name/function_contents segment shape so SQLFluff
# layout rules can inspect them without special cases or suppressed checks.
class CollectionFunctionNameSegment(sqlite.get_segment("FunctionNameSegment")):
    # COUNT is deliberately shared with the aggregate keyword: its collection
    # binding form (COUNT(tags AS tag WHERE ...)) matches the binding contents
    # below, while every standard aggregate form falls through to the ordinary
    # function grammar. The two content shapes are mutually exclusive.
    match_grammar = OneOf("FILTER", "MAP", "COUNT")


class CollectionFunctionContentsSegment(sqlite.get_segment("FunctionContentsSegment")):
    match_grammar = OneOf(
        Bracketed(
            Ref("ExpressionSegment"),
            "AS",
            Ref("SingleIdentifierGrammar"),
            "WHERE",
            Ref("ExpressionSegment"),
        ),
        Bracketed(
            Ref("ExpressionSegment"),
            "AS",
            Ref("SingleIdentifierGrammar"),
            "SELECT",
            Ref("ExpressionSegment"),
        ),
    )


ytsql_dialect.add(
    CollectionFunctionNameSegment=CollectionFunctionNameSegment,
    CollectionFunctionContentsSegment=CollectionFunctionContentsSegment,
)


class FunctionSegment(sqlite.get_segment("FunctionSegment")):
    match_grammar = OneOf(
        Sequence(
            Ref("CollectionFunctionNameSegment"),
            Ref("CollectionFunctionContentsSegment"),
        ),
        sqlite.get_segment("FunctionSegment").match_grammar,
    )


ytsql_dialect.replace(FunctionSegment=FunctionSegment)
