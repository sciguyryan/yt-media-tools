# yt-sql identifier and keyword audit

This audit records the current implementation against the identifier and keyword policy agreed in issue #14. It is temporary working material for issue #87. Durable conclusions belong in the canonical language and testing documentation when issue #88 freezes the contract.

## Intended contract

The agreed direction is deliberately conservative. Identifier spelling is case-sensitive and preserved exactly. Keywords are case-insensitive. Only a small explicit vocabulary is permanently reserved, while contextual keywords remain usable as identifiers where the grammar is unambiguous. Unicode identifiers are supported without implicit normalisation. Ordinary unquoted identifiers should follow a documented Unicode identifier rule, with narrowly stated yt-sql exceptions. Backticks provide the quoted-identifier escape hatch. Aliases, structured members and raw backend keys should follow the same coherent naming model, with quoted segments available where ordinary identifier syntax is insufficient.

## Current lexical model

The lexer does not currently have a general keyword token class. Most language words are emitted as `IDENT` and recognised case-insensitively by parser position. This already gives yt-sql a broadly contextual keyword model: words such as `SELECT`, `JOIN`, `SEMI`, `ANTI`, `FORMAT`, `ANY` and `ALL` can remain ordinary identifier text in positions where the grammar expects an identifier and no structural interpretation is required.

`TRUE`, `FALSE` and `NULL` are the exception. They have a dedicated case-insensitive `LITERAL_WORD` token and are explicitly rejected inside dotted identifier tokens. They are therefore the current globally reserved literal vocabulary. `UNKNOWN` is recognised contextually after `IS` but is not currently globally reserved.

Keyword matching uses case-insensitive comparison, so structural spellings such as `SELECT`, `select` and `SeLeCt` are equivalent. This part of the intended contract is already satisfied.

The parser does not maintain a single declarative inventory of structural/contextual keywords. Recognition is distributed across grammar methods and a small member-terminator set. The eventual frozen contract should therefore introduce an explicit, testable classification rather than treating every parser-recognised word as globally reserved.

## Identifier case sensitivity

The current implementation is mixed and does not satisfy the proposed case-sensitive identifier contract.

Collection bindings and explicit relation qualifier matching are case-sensitive in important paths. However, ordinary schema field lookup case-folds names, SELECT output duplicate detection case-folds output names, SELECT aliases used by HAVING and ORDER BY are stored and resolved by case-folded spelling, CTE names are stored and resolved by case-folded spelling, relation identity keys case-fold relation names, and resolved field identity keys case-fold canonical field names.

Consequently identifiers that differ only by case are not consistently distinct today. This is a genuine implementation discrepancy and should be resolved before the contract is frozen.

## Unicode identifiers

The current `IDENT` token is Unicode-aware through Python regular-expression character classes. Its first component uses a non-digit word-character test and later characters use `\w`, with hyphen also explicitly permitted. This accepts many useful non-ASCII names, but it is not a deliberate implementation of Unicode `XID_Start` followed by `XID_Continue`.

The current grammar also permits unquoted hyphens inside identifier components. That is a yt-sql-specific extension rather than an XID rule and creates a lexical design choice because `a-b` is currently one identifier while spaced `a - b` is subtraction.

Python's `\w` behaviour is not an adequate normative definition for the language contract. The implementation therefore needs an explicit Unicode identifier policy and enforcement before #88 can claim XID-style identifiers. The audit does not recommend silently removing established hyphenated identifiers; the implementation issue should first reconcile compatibility with the agreed ordinary-identifier grammar.

No identifier normalisation is performed by the lexer. This matches the intended no-implicit-normalisation principle and should remain explicit in the frozen contract.

## Quoted identifiers

Backtick-quoted identifiers are not currently implemented. A backtick is rejected as an unexpected character. The agreed quoted-identifier escape hatch is therefore a missing language capability rather than a documentation-only change.

The implementation needs one focused issue defining tokenisation, embedded-backtick escaping, exact spelling preservation, formatter output and use in aliases, field/member components, relation aliases, CTE names and raw backend-key paths. Quoting must change syntactic admissibility only: quoted and unquoted forms of the same spelling must identify the same name rather than creating separate namespaces.

## Dotted fields, structured members and raw keys

Legacy dotted field paths are currently tokenised as one `IDENT`, while postfix member access can also construct structured-member nodes after an explicit dot. Ordinary dotted components inherit the current identifier token rules.

`raw.*` lookup preserves the supplied path text when traversing backend data, but the `raw` prefix itself is recognised case-insensitively. Quoted path segments do not exist, so raw keys containing spaces, punctuation outside the current identifier grammar, or otherwise unrepresentable components cannot be addressed through the agreed quoted form.

The frozen contract should distinguish exact backend-key spelling from language-level recognition of the `raw` namespace and should specify how quoted member segments compose with `raw.*` and structured access.

## Canonical formatting

Current formatting generally emits stored identifier and alias text directly, so it does not intentionally case-fold displayed spellings. That is compatible with exact spelling preservation, but it cannot yet represent quoted identifiers and resolution may already have canonicalised a field through case-insensitive schema lookup.

Once identifier resolution and quoting are corrected, deterministic parse-format-parse coverage should prove that formatting preserves identifier spelling and emits quoting whenever the ordinary identifier grammar cannot represent the name safely.

## Diagnostics

The existing reserved literal words receive deterministic identifier-position failures, and an unsupported backtick currently receives the generic unexpected-character diagnostic. Once quoted identifiers exist, malformed quoted identifiers need dedicated deterministic diagnostics, including unterminated quoting and invalid escape forms if escaping is supported.

Case-only collisions and duplicate-name diagnostics must also follow the final case-sensitive policy rather than the current case-folded behaviour.

## Findings requiring implementation

The audit identifies three implementation areas that must be resolved before issue #88 freezes the contract.

1. Identifier resolution was not consistently case-sensitive. Issue #89 removes identifier case-folding from field, alias, CTE and semantic identity resolution while preserving case-insensitive keyword recognition.
2. Issue #90 replaces the implementation-defined ordinary Unicode identifier grammar with explicit XID-style recognition, retains `_` as an ordinary start character and deliberately preserves the established unquoted-hyphen extension for compatibility.
3. Issue #91 adds backtick-quoted identifiers across fields, aliases, CTEs, relation qualification, structured members and raw backend-key segments, with deterministic escaping, formatting and malformed-input diagnostics.

The keyword model itself does not require a broad lexer rewrite. Existing parser-position recognition already provides useful contextual-keyword behaviour. The durable contract should instead make the reserved/contextual classification explicit and machine-testable. `TRUE`, `FALSE` and `NULL` are currently globally reserved; `UNKNOWN` remains contextual and should be considered alongside the separate reserved-terms work rather than changed incidentally here.

## Conclusion

The broad keyword architecture is compatible with issue #14: case-insensitive grammar words can remain contextual by default, with a deliberately small globally reserved set. Unicode is already accepted in practice and no implicit normalisation is performed.

Issues #89, #90 and #91 resolve all three implementation discrepancies identified by this audit: case-sensitive identifier resolution, an explicit Unicode ordinary-identifier grammar and backtick-quoted identifiers. No implementation dependency remains before #88 freezes the identifier and keyword contract. The temporary audit can then be retired when its durable conclusions are reconciled into `YT-SQL.md` and `YT-SQL-TEST-COVERAGE.md`.
