# yt-sql diagnostic and source-span contract

This document defines the parser-independent diagnostic contract for yt-sql. It belongs to the language rather than to the current recursive-descent parser or any future parser library.

## Diagnostic categories

A lexical error means that source text cannot be tokenised according to the yt-sql lexical contract. Examples include an unexpected source character, an unterminated quoted identifier or string, an incomplete terminal string escape, and a malformed numeric literal. Lexical rejection is represented by the `lexical` diagnostic category.

A syntax error means that individually valid yt-sql tokens cannot form a legal grammatical structure. Missing required clauses or delimiters, repeated or reordered clauses, invalid grouping and other grammar-shape failures belong to the `syntax` category.

A semantic error means that a parsed grammatical structure is invalid in its meaning or resolved context. Name resolution, unknown fields or members, incompatible types, invalid calendar values, unsupported source or facet capabilities and similar meaning-level failures belong to the `semantic` category. A parser migration must not move an established semantic failure into lexical or syntax rejection merely because a candidate parser can reject it earlier.

`QueryLexicalError` and `QuerySemanticError` remain subclasses of `QuerySyntaxError` for compatibility with callers that historically caught the common query error class. The structured diagnostic category, not the Python inheritance hierarchy, is the authoritative error classification.

## Primary location and spans

Every lexical and syntax diagnostic must have a deterministic primary source location containing a zero-based absolute character offset and one-based line and column numbers. Semantic diagnostics should identify the most specific user-written source location available rather than defaulting to the beginning of the query.

Structured diagnostics use half-open source spans: the start position is inclusive and the end position is exclusive. A diagnostic whose implementation knows only a primary position uses a zero-width span whose start and end are the same location. Lexical tokens retain exact half-open absolute spans. Parser and semantic code may progressively retain wider spans without changing the meaning of the primary failure location.

User-written AST structures that can participate in diagnostics, semantic validation or tooling must retain enough source position information to recover their relevant source origin. The current model's established `position` fields remain the compatibility representation for node starts. Composite nodes that do not own a dedicated position derive diagnostic locations from their user-written children. A future parser may retain exact end positions more broadly, but must not discard established source origins during AST construction or transformation. Optimiser-created nodes are not required to pretend that generated syntax was user-written; where they can later produce a user-facing diagnostic, they should preserve or inherit the relevant source origin.

## Human-facing rendering

Terminal diagnostics stop at the first useful deterministic error. yt-sql does not attempt parser recovery merely to produce several potentially cascading errors from one malformed command-line query.

The human message should explain the yt-sql problem rather than expose parser implementation terminology. Expected-token information may be retained in structured diagnostics when a small curated set clarifies the failure, but raw parser-library token sets, rule stacks and exception names are not public output. Existing wording may improve when the result is clearer, provided the diagnostic category, source meaning and broad intent remain equivalent.

Line and column are always part of rendered lexical and syntax diagnostics. The existing source-line and caret presentation remains a supported terminal form. Absolute offsets and end spans are structured data and need not be printed in ordinary terminal output.

## Parser migration equivalence

A replacement parser must preserve the accepted and rejected language first. For rejected input, compatibility means preserving the diagnostic category, the source region identified as the primary failure, the semantic meaning of the error and its broad human-facing intent. Exact prose is not frozen when clearer wording is possible.

A parser implementation must translate its native failures into yt-sql diagnostics. Library-specific exception types, generated rule names, internal token identifiers, parser state dumps and recovery artefacts must not escape as the public interface.

Differential parser tests should compare structured diagnostic meaning rather than requiring byte-for-byte equality of implementation-native messages. Exact wording should be asserted only where yt-sql deliberately defines a specific diagnostic message as part of a language boundary.

## Machine-readable diagnostics

The diagnostic model is intentionally structured so a future machine-readable interface can expose category, stable reason, message, primary location, absolute span and curated expected tokens without parsing terminal prose. The stable reason is parser-independent and deliberately separate from editable human-facing wording. Issue #15 does not add a new public machine-readable CLI mode. Such a surface should be versioned and designed with the wider Discover machine-interface contract rather than introduced incidentally during parser preparation.
