# yt-sql canonical formatting contract

Canonical formatting is a language-level yt-sql contract. It is independent of the implementation details of the current recursive-descent parser and must remain implementable by any future parser without formatting parser-library-specific trees.

For every supported query with a canonical representation, parsing and formatting must preserve semantic structure:

```text
parse(query) -> format -> parse
```

The reparsed query must retain every meaningful language distinction even though incidental source spelling may change. Canonical formatting is also idempotent:

```text
format(parse(format(parse(query)))) == format(parse(query))
```

These properties are part of parser differential testing. Source positions and other non-semantic parser bookkeeping are not required to survive formatting.

## Parentheses and precedence

The formatter removes parentheses when yt-sql precedence and associativity prove them unnecessary. It adds or retains parentheses whenever omitting them would change the reparsed expression structure or semantic meaning. In scalar arithmetic, higher-precedence multiplication, division and remainder bind more tightly than addition and subtraction, unary signs bind more tightly than binary arithmetic, and postfix indexing and member access bind most tightly.

Parenthesised compound-query boundaries are different from incidental scalar grouping. A branch-local `ORDER BY`, `LIMIT` or `OFFSET`, a grouped left query primary, or any other grouping that changes compound-query structure must retain an explicit parenthesised boundary. The formatter must not flatten such a boundary merely because the resulting text appears simpler.

## Postfix expressions

Postfix chains are compact. Indexing and structured-member access do not acquire incidental whitespace, so a chain such as `formats[0].height` retains that form. Parentheses are emitted around a postfix base only where they are required to preserve the expression that the postfix operation applies to or to distinguish explicit member access from the established dotted-field syntax.

## Relational and compound layout

Ordinary single-relation queries may remain on one line. Queries containing JOINs, CTEs, explicit set operations or a grouped left query primary use a deterministic multiline layout so relation and compound boundaries remain visible.

JOINs place the joined relation on its own line and indent the `ON` predicate by two spaces. Canonical `INNER JOIN` is written as `JOIN`; `LEFT OUTER JOIN` is written as `LEFT JOIN`. Relation aliases continue to use explicit `AS`.

CTE bodies are placed on indented lines inside their parentheses. `UNION` and `UNION ALL` operators occupy their own lines. Grouped set branches use an explicit parenthesised block. Trailing completed-result `ORDER BY`, `LIMIT` and `OFFSET` remain outside the branch block to which they do not belong.

## Literals and spellings

Canonical strings use single quotes regardless of the accepted source quote style. Embedded single quotes are doubled, and supported control and backslash escapes are emitted deterministically from the literal value. LIKE and ILIKE patterns retain their pattern-level backslash escapes rather than having those escapes reinterpreted as ordinary string escapes.

Integer base is meaningful formatting information and is preserved. Hexadecimal, octal and binary values remain hexadecimal, octal and binary rather than being rewritten in decimal. Incidental spelling within the chosen base is normalised: base prefixes use lowercase, hexadecimal digits use lowercase, and numeric separator underscores are removed. Decimal numeric separator underscores are likewise removed.

Reserved Boolean and NULL literals use uppercase `TRUE`, `FALSE` and `NULL`. Established temporal and duration canonicalisation remains unchanged: accepted equivalent temporal and unit spellings may be normalised to the language's existing canonical forms.

Canonical formatting intentionally does not preserve keyword case, redundant whitespace, accepted alternative string quote style, numeric separator placement, equivalent accepted temporal or unit spellings, or unnecessary parentheses. Identifier spelling remains exact and follows the separate identifier quoting contract.

## Comments

Comments are not currently part of the yt-sql lexical or grammatical language. Canonical comment preservation or placement is therefore outside this contract. If comments are added to the language later, their formatting semantics must be defined deliberately rather than inferred from a parser library.

## Formatter ownership

Every accepted syntax form must have one deterministic canonical representation. New grammar work is incomplete until its formatter representation and parse-format-parse/idempotence behaviour are defined and tested.

The semantic round-trip oracle must include all meaningful query structure. In particular, relation aliases, JOIN kind and predicates, source/facet identity, CTEs, set-operation grouping and facet-expansion identity cannot be ignored merely because source positions or display-only metadata are excluded.
