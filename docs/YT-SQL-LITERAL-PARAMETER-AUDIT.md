# yt-sql literal and parameter audit

This temporary audit records the 0.29.6 review of the literal and parameter contract for issue #79. Its durable conclusions belong in the canonical language documentation during issue #80; this file should then be removed rather than retained as historical narrative.

## Settled literal forms

yt-sql retains decimal, hexadecimal, octal and binary integer literals. Numeric separators remain underscores with strict placement: separators may occur only between digits, including digits within non-decimal literals. Mixed-base integer arithmetic remains valid wherever ordinary numeric scalar expressions are valid.

String literals retain the existing single-quoted and double-quoted forms. SQL-style doubled quote characters and the established backslash escapes remain sufficient; no additional string literal form is justified by the current language. `TRUE`, `FALSE` and `NULL` are reserved literal words by contract.

A leading sign is not part of an integer literal. `-42` and `-0xff` are unary-minus expressions whose operands are the positive literals `42` and `0xff`. This keeps sign handling in the expression grammar.

## Parameters

The established parameter spelling is `:name`, with names matching `[A-Za-z_][A-Za-z0-9_]*` case-insensitively at the CLI binding boundary. `--param NAME=VALUE` remains the binding interface. Substitution occurs outside quoted strings, values are safely quoted before parsing, missing and unused bindings are errors, duplicate names are rejected case-insensitively, and no alternative parameter syntax is required.

The current implementation performs this binding immediately before parsing rather than representing parameters as parser AST nodes. The audit found no present semantic limitation that requires changing that boundary. The syntax contract should nevertheless remain explicit so a future parser implementation can preserve the same observable behaviour.

## Numeric, temporal-unit and identifier boundaries

The lexer gives dates, datetimes, times and explicit temporal expressions their own token classes before ordinary numbers and identifiers. A decimal number followed by alphabetic text is tokenised as a number followed by an identifier, allowing field-directed literal parsing to interpret established duration and count forms while ordinary scalar-expression contexts reject an unexpected trailing identifier. Non-decimal prefixes are consumed as one numeric token so invalid base digits are diagnosed as malformed base literals rather than being reinterpreted as identifiers.

The reviewed boundaries are deterministic for the established forms. Examples such as `1h`, `1_0h` and `1.5h` do not become identifiers, while `0xFFh` remains one malformed hexadecimal token and is rejected as such. The audit found no unresolved number, temporal-unit or identifier ambiguity requiring an implementation issue.

## Canonical formatting

Parsed integer literals retain their original lexical spelling in `Literal.raw`, and canonical formatting emits that spelling. Consequently `0xff`, `0o755`, `0b101010` and their valid underscore/case variants are not silently converted to decimal merely by parse-and-format canonicalisation. Unary minus likewise preserves the operand's representation.

Optimiser-created constants are new derived literals and may use a canonical decimal representation. This does not rewrite the spelling of an unchanged source literal and is therefore distinct from canonical formatting silently changing the base of a literal supplied by the user. The audit found no base-preservation defect requiring implementation work.

## Diagnostics

Invalid base digits and malformed non-decimal prefixes already receive deterministic numeric-literal diagnostics. Misplaced numeric underscores are rejected rather than guessed. Invalid parameter names, missing values, duplicate bindings, missing bindings and unused bindings are also diagnosed deterministically.

An unterminated string currently fails lexically with the general unexpected-character diagnostic. That behaviour is deterministic, but it does not satisfy the agreed preference for a dedicated malformed-string diagnostic where practical. This is a diagnostic-quality gap and should be tracked separately if the project wants the literal contract to promise a specific unterminated-string diagnostic.

## Defect found: reserved literal words

Although `TRUE`, `FALSE` and `NULL` are recognised as literals in scalar-expression positions, the tokenizer currently emits them as ordinary identifier tokens and some grammar positions accept them as aliases. For example, `SELECT id AS TRUE FROM @example` and `SELECT id FROM @example AS NULL` can currently parse successfully.

That conflicts with the settled contract that `TRUE`, `FALSE` and `NULL` are always reserved literals rather than context-dependent identifiers. The implementation now gives these words a dedicated lexical token class, retains their literal meaning in expression and predicate positions, and rejects them in identifier-only grammar positions. Deterministic conformance coverage protects both sides of that contract.

## Audit disposition

The current integer bases, underscore rules, string forms, parameter spelling, unary-sign model, lexical numeric/temporal boundaries, reserved literal words and base-preserving parse-and-format behaviour can be frozen without language expansion. A dedicated unterminated-string diagnostic remains a concrete diagnostics decision to resolve before issue #80 documents the final malformed-literal contract.
