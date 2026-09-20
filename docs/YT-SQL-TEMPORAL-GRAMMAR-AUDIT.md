# yt-sql temporal grammar audit

This document records the temporary implementation audit for issue #84. It exists to verify the agreed temporal-language decisions against the current parser, resolver, formatter and unit registry before the temporal grammar is frozen. Its durable conclusions should be reconciled into the canonical language and test documentation by issue #85, after which this audit should be removed.

## Audit conclusion

The established temporal model is coherent and should be retained. Query temporal context is captured once, date and timestamp types remain distinct, temporal infinity is typed rather than represented by loose scalar sentinels, multilingual units are data-driven and globally unambiguous, and unit recognition does not reserve ordinary identifier spellings.

The audit identified one concrete discrepancy before the temporal contract could be frozen: canonical formatting preserved accepted temporal source spellings instead of normalising equivalent spellings. Issue #86 resolves that discrepancy by canonicalising resolved date, timestamp and duration literals and by normalising relative `TODAY()`/`NOW()` unit aliases without replacing symbolic relative expressions with captured absolute values.

No additional temporal form is justified by this audit, and no unresolved implementation dependency remains from issue #84.

## Duration and unit forms

The unit registry is case-insensitive and data-driven through the repository `units/` files. Every canonical name and alias is globally unique across all loaded files. Definitions resolve recursively to either fixed seconds or Gregorian calendar months, and registry loading rejects duplicate tokens, unknown references, cycles and malformed definitions.

The shipped registry currently contains English fixed and calendar units, Welsh equivalents and aliases, calendar-aware decade/century/millennium definitions, and exact fixed-day Maya Long Count units. These are deliberate language features rather than parser accidents and should remain supported.

Duration parsing remains field-aware. Fixed units may describe media durations; calendar units are rejected for media-duration fields. Temporal arithmetic accepts fixed or calendar units where the resulting temporal type permits them. `TODAY()` requires fixed units to resolve to whole days, while `NOW()` may use sub-day fixed units.

The accepted unit vocabulary is therefore explicit and unambiguous for a given registry. Multilingual unit support remains viable without changing the grammar.

## Unit and identifier boundaries

Unit names are not globally tokenised as reserved unit tokens. Ordinary identifiers retain their normal lexical meaning outside a field-aware duration or temporal-literal position. Within `TODAY()`/`NOW()` relative syntax, the unit occupies a dedicated unit position; within duration literals, the resolver interprets the literal against the expected duration type.

Consequently a unit spelling such as `day`, `month`, `dydd` or `mis` does not steal the same spelling from an otherwise valid identifier position. The current design satisfies the requirement that unit recognition must not create context-dependent identifier ambiguity.

## Relative temporal expressions and captured context

`DateContext` captures the local clock once per query run. `TODAY()` is derived from that captured local date and `NOW()` from the same captured local timestamp, so repeated evaluation cannot drift during a query.

`TODAY()` is valid for date comparisons and `NOW()` for timestamp comparisons. The resolver rejects cross-kind use rather than silently coercing between date and timestamp. Relative arithmetic applies a single optional `+` or `-` unit quantity to the captured base. Calendar units shift Gregorian calendar months with end-of-month clamping; fixed units use exact elapsed seconds or whole days as required by the target type.

The parser also retains established readable relative-date forms such as `today`, `yesterday`, `tomorrow` and `<count> <unit> ago`. These resolve through the same captured temporal context and unit registry.

## Date and timestamp forms

Date resolution accepts the established deterministic families: compact `YYYYMMDD`, year-first numeric dates using `-`, `/` or `.`, configured local numeric dates, named-month dates and the documented relative-date forms. Ambiguous local numeric order is controlled by the configured date order rather than guessed.

Timestamp resolution accepts ISO datetime input through Python's ISO parser, including `Z` and explicit offsets. A timestamp without an explicit offset is assigned the captured local timezone. `NOW()` relative expressions are typed timestamp expressions.

The lexer gives ISO-shaped dates, datetimes and explicit `TODAY()`/`NOW()` relative expressions dedicated token forms where applicable. Other established human-readable date forms are deliberately collected as field-aware literals and interpreted by the resolver. This division is deterministic even though not every accepted date spelling has a dedicated lexer token.

## Typed temporal infinity

`INFINITY()` and `-INFINITY()` resolve to `TemporalInfinity` carrying both sign and temporal kind. Date infinity compares only with dates and timestamp infinity only with datetimes. The resolver rejects temporal infinity for duration, count and other non-temporal fields.

NULL remains distinct from temporal infinity and retains ordinary SQL-like NULL behaviour. The implementation therefore satisfies the requirement that unbounded temporal values remain typed and are not replaced by strings or numeric sentinels.

## Temporal arithmetic and precedence

The current temporal relative form is an atomic temporal literal rather than general scalar arithmetic. Its grammar permits one optional signed unit quantity after `TODAY()` or `NOW()`. The sign inside that form is therefore not competing with the general scalar additive or multiplicative precedence hierarchy.

General scalar arithmetic retains its existing precedence independently. Constructs that would imply a richer temporal arithmetic expression, such as chained relative adjustments or multiplication of a unit quantity, are not established temporal grammar and should not be inferred from scalar precedence rules.

No temporal-specific precedence defect was found. The later general precedence audit should still verify the complete expression hierarchy, but there is no temporal ambiguity that needs to block this contract.

## Canonical formatting

Canonical formatting now normalises established temporal spellings rather than retaining arbitrary accepted aliases. Resolved dates use ISO `YYYY-MM-DD`; resolved timestamps use ISO datetime spelling with `Z` for UTC; resolved media durations use seconds; and relative `TODAY()`/`NOW()` expressions retain their symbolic base while normalising spacing, case and the unit token to the canonical name defined by its unit definition.

This preserves query-captured temporal semantics: formatting `TODAY()-1yr` does not replace the expression with the date captured during resolution. Multilingual unit definitions retain their own canonical names while aliases of the same definition converge on that name. Field-aware date forms such as configured local numeric and named dates are normalised after semantic resolution, when their meaning is known.

Deterministic parse-format-parse coverage verifies semantic stability across relative expressions, multilingual aliases, local and named dates, timestamps and duration aliases. The formatting discrepancy identified by the audit is therefore resolved by issue #86.

## Syntax and semantic failure boundary

The current architecture provides a principled boundary between malformed grammar and invalid typed temporal meaning. Structurally malformed query syntax is rejected by the parser. A literal that is grammatically admissible in a temporal value position but has an invalid calendar value, unknown unit, incompatible unit kind, incompatible date/timestamp kind or otherwise invalid typed operation is rejected during semantic resolution.

This means an ISO-shaped but impossible calendar date is a semantic error rather than a lexical error: its spelling belongs to the date grammar, but its value cannot exist. Likewise an unknown unit in an otherwise structured relative expression is a semantic unit-resolution failure. Inputs that do not form the required query or literal structure remain syntax errors.

This boundary matches the agreed principle when "malformed" is understood structurally rather than as every invalid temporal value. The canonical documentation should state this distinction explicitly so differential parsers reproduce the same rejection class rather than moving calendar and type validation arbitrarily into lexical analysis.

## Required follow-up before freeze

Issue #86 resolves the only implementation discrepancy identified by this audit. Issue #85 can now freeze the temporal grammar contract, incorporate these durable conclusions into `YT-SQL.md` and `YT-SQL-TEST-COVERAGE.md`, and remove this temporary audit document.
