"""Experimental YT-SQL dialect for the pinned SQLFluff 4.4.0 runtime.

This is a formatter grammar, not the authoritative YT-SQL parser. Keep
extensions narrow and validate every addition against the portable corpus.
"""

from sqlfluff.core.dialects import load_raw_dialect
from sqlfluff.core.parser import (
    AnyNumberOf,
    BaseSegment,
    Bracketed,
    Dedent,
    Indent,
    LiteralKeywordSegment,
    LiteralSegment,
    OneOf,
    Ref,
    RegexLexer,
    Sequence,
    StringParser,
    TypedParser,
    WordSegment,
)

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


# The OF facet clause is a YT-SQL extension to the table expression:
# FROM @source OF facet. Keep the standard alias and join machinery by
# extending the from-expression element with the facet form as an alternative.
class FacetSourceSegment(sqlite.get_segment("FromExpressionElementSegment")):
    """A physical source with an optional facet selection."""

    match_grammar = Sequence(
        Ref("AtSignLiteralSegment"),
        "OF",
        Ref("SingleIdentifierGrammar"),
        Ref("AliasExpressionSegment", optional=True),
    )


class FromExpressionElementSegment(sqlite.get_segment("FromExpressionElementSegment")):
    match_grammar = OneOf(
        FacetSourceSegment.match_grammar,
        sqlite.get_segment("FromExpressionElementSegment").match_grammar,
    )


ytsql_dialect.add(
    FacetSourceSegment=FacetSourceSegment,
)
ytsql_dialect.replace(
    FromExpressionElementSegment=FromExpressionElementSegment,
)


# SEMI and ANTI joins are YT-SQL existence joins: SEMI keeps matching left rows
# and ANTI keeps non-matching ones, without exposing right-side columns. They
# hook into the dialect's non-standard join-type extension point.
ytsql_dialect.sets("unreserved_keywords").update({"SEMI", "ANTI"})
ytsql_dialect.replace(
    NonStandardJoinTypeKeywordsGrammar=OneOf("SEMI", "ANTI"),
)

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

# The ANSI dialect excludes the UNKNOWN truth test (UnknownLiteralSegment is
# Nothing()), so `IS UNKNOWN` parses UNKNOWN as a column reference and the
# CP02 identifier-casing rule rewrites it. YT-SQL reserves UNKNOWN as a
# truth-test keyword (the authoritative parser's keyword set), so register it
# as reserved here and restore the IS-clause alternative; TRUE and FALSE
# already parse through the inherited BooleanLiteralGrammar.
ytsql_dialect.sets("reserved_keywords").update({"UNKNOWN"})
ytsql_dialect.replace(
    UnknownLiteralSegment=StringParser("UNKNOWN", LiteralKeywordSegment, type="null_literal"),
)


# Collection bindings are a YT-SQL extension to ordinary SQL functions.
# Keep the standard function_name/function_contents segment shape so SQLFluff
# layout rules can inspect them without special cases or suppressed checks.
# ANY and ALL name the collection quantifier form over the same binding
# shape (and ALL is already a keyword through UNION ALL); registering them
# keeps the bare-string grammar below resolvable in this dialect.
ytsql_dialect.sets("unreserved_keywords").update({"ANY", "ALL"})


class CollectionFunctionNameSegment(sqlite.get_segment("FunctionNameSegment")):
    # COUNT is deliberately shared with the aggregate keyword: its collection
    # binding form (COUNT(tags AS tag WHERE ...)) matches the binding contents
    # below, while every standard aggregate form falls through to the ordinary
    # function grammar. The two content shapes are mutually exclusive.
    match_grammar = OneOf("FILTER", "MAP", "COUNT", "ANY", "ALL")


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


# Structured access is a YT-SQL scalar extension: a column may be followed by
# tightly binding postfix [index] and .member chains (formats[1].height,
# f.video.height). Extending the column reference keeps the whole chain one
# expression element so layout rules treat it like any other reference.
class ColumnReferenceSegment(sqlite.get_segment("ColumnReferenceSegment")):
    match_grammar = Sequence(
        sqlite.get_segment("ColumnReferenceSegment").match_grammar,
        AnyNumberOf(
            Bracketed(Ref("ExpressionSegment"), bracket_type="square"),
            Sequence(Ref("DotSegment"), Ref("SingleIdentifierGrammar")),
        ),
    )


ytsql_dialect.replace(ColumnReferenceSegment=ColumnReferenceSegment)


# YT-SQL spells scalar comparisons in natural language: ABOVE, BELOW, UNDER,
# OVER, EQUALS, AT LEAST, AT MOST, GREATER/MORE/LESS THAN and EQUAL TO. These
# words are contextual in the authoritative parser (not reserved keywords)
# and the corpus stores them lowercase, so match them as comparison-operator
# words instead of keywords: casing rules must never rewrite operator
# spelling, just as they must not rewrite a literal.
def _natural_comparison_word(word: str) -> StringParser:
    return StringParser(word, WordSegment, type="comparison_operator")


ytsql_dialect.replace(
    ComparisonOperatorGrammar=OneOf(
        sqlite.get_grammar("ComparisonOperatorGrammar"),
        Sequence(
            _natural_comparison_word("GREATER"),
            _natural_comparison_word("THAN"),
        ),
        Sequence(_natural_comparison_word("MORE"), _natural_comparison_word("THAN")),
        Sequence(_natural_comparison_word("LESS"), _natural_comparison_word("THAN")),
        Sequence(_natural_comparison_word("AT"), _natural_comparison_word("LEAST")),
        Sequence(_natural_comparison_word("AT"), _natural_comparison_word("MOST")),
        Sequence(_natural_comparison_word("EQUAL"), _natural_comparison_word("TO")),
        _natural_comparison_word("ABOVE"),
        _natural_comparison_word("BELOW"),
        _natural_comparison_word("UNDER"),
        _natural_comparison_word("OVER"),
        _natural_comparison_word("EQUALS"),
    ),
)


# Count and duration values extend a numeric literal with unit words. The
# authoritative lexer scans the whole value -- including underscore groups,
# the decimal part and the unit suffix -- as one NUMBER token (1_500_000,
# 1.5m, 0.5k, 2d, 59m59s), while SQLFluff's numeric lexer stops at underscores
# and word boundaries and its word lexer then claims the remainder. Scan these
# forms before the word lexer; plain numerics still lex through the inherited
# numeric_literal matcher, which precedes this entry. Clock durations
# (59:59.999) are one authoritative TIME token, so they also scan whole:
# LT01 would otherwise require whitespace between the parts.
ytsql_dialect.insert_lexer_matchers(
    [
        RegexLexer(
            "ytsql_clock_literal",
            r"\d{1,3}:\d{1,2}(?::\d{1,2})?(?:\.\d{1,3})?",
            LiteralSegment,
            segment_kwargs={"type": "clock_literal"},
        ),
    ],
    before="numeric_literal",
)
ytsql_dialect.insert_lexer_matchers(
    [
        RegexLexer(
            "ytsql_value_literal",
            r"(?:\d[\d_]*(?:\.\d[\d_]*)?[a-zA-Z]*)+",
            LiteralSegment,
            segment_kwargs={"type": "numeric_literal"},
        ),
    ],
    before="colon_literal",
)


# A value literal with trailing unit words: the unit (3599 sec, 1 wythnos)
# and, for relative dates, the AGO marker (2d ago, 1 baktun ago). The unit
# suffix forms (1.5m, 2d) already lex as a single numeric literal above. The
# trailing words stay identifiers so casing rules see their committed
# lowercase spelling.
class YtValueLiteralSegment(BaseSegment):
    type = "duration_literal"
    match_grammar = Sequence(
        Ref("NumericLiteralSegment"),
        Ref("NakedIdentifierSegment", optional=True),
        Ref("NakedIdentifierSegment", optional=True),
    )


# Clock durations scan as one token matching the authoritative TIME form
# (mm:ss(.mmm) and h:mm:ss): 59:59.4, 59:59.999.
YtClockLiteralSegment = TypedParser(
    "clock_literal",
    LiteralSegment,
    type="clock_literal",
)


ytsql_dialect.add(
    YtValueLiteralSegment=YtValueLiteralSegment,
    YtClockLiteralSegment=YtClockLiteralSegment,
)
ytsql_dialect.replace(
    LiteralGrammar=OneOf(
        sqlite.get_grammar("LiteralGrammar"),
        Ref("YtClockLiteralSegment"),
        Ref("YtValueLiteralSegment"),
    ),
)


# A bare OFFSET page window: YT-SQL allows OFFSET without LIMIT
# (semantics.offset_without_limit) after ORDER BY or FROM, and without the
# ANSI ROWS terminator. OFFSET keeps the committed numeral spelling through
# the numeric lexer above.
class OffsetClauseSegment(sqlite.get_segment("OffsetClauseSegment")):
    type = "offset_clause"
    match_grammar = Sequence(
        "OFFSET",
        Indent,
        Ref("NumericLiteralSegment"),
        Dedent,
    )


ytsql_dialect.replace(OffsetClauseSegment=OffsetClauseSegment)


class SelectStatementSegment(sqlite.get_segment("SelectStatementSegment")):
    match_grammar = sqlite.get_segment("SelectStatementSegment").match_grammar.copy(
        insert=[Ref("OffsetClauseSegment", optional=True)]
    )


ytsql_dialect.replace(
    SelectStatementSegment=SelectStatementSegment,
    OrderByClauseTerminators=OneOf(
        sqlite.get_grammar("OrderByClauseTerminators"),
        Ref("OffsetClauseSegment"),
    ),
)
