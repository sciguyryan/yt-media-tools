//! Recursive-descent port of the yt-sql parser (`query_parser.Parser`).
//!
//! Every parser method is ported with the same structure, diagnostics,
//! positions and reasons as the Python reference, including:
//! * the clause-order diagnostics and the `statement clause at current`
//!   contextual detection,
//! * the stop-keyword literal gluing in `parse_literal` (load-bearing for the
//!   `Could not understand count '10 GROUP BY ...'` behaviour),
//! * the backtracking LPAREN attempts in `parse_primary` and
//!   `parse_having_not` (including the quirk that the successful scalar
//!   attempt is returned without a truth-test suffix),
//! * collection bindings (FILTER/MAP/COUNT `OF`-style `AS ... WHERE/SELECT`
//!   scopes with lexical shadowing), quantifiers ANY/ALL, scalar functions
//!   with per-function argument-shape rules, postfix `[index]`/`.member`
//!   chains, CASE WHEN, arithmetic precedence, GROUP BY/HAVING/ORDER BY/
//!   LIMIT/OFFSET, DISTINCT, OF facet UNION ALL sugar, CTEs, UNION/UNION ALL,
//!   JOIN kinds with their rejection diagnostics, derived relations and
//!   relation wildcards.
//!
//! The canonical scalar/Boolean expression formatter pieces the parser needs
//! (`format_scalar_expression`, `format_expression` and their helpers) are
//! ported here from `query_formatter.py` because the Python parser calls them
//! while building SELECT and ORDER BY terms.
//!
//! Deliberate deviations, all forced by the fixed `crate::model` contracts and
//! all preserving the conformance outcomes of the committed corpus:
//! * Python's WHERE-level comparisons (`Binary(operator, Field, Literal)`)
//!   are represented as `BoolExpr::ScalarComparison` because the Rust
//!   `BoolExpr::Binary` node only carries `BoolExpr` operands. The `IS TRUE`/
//!   `IS FALSE`/`IS UNKNOWN` field sugar and the bare `NOT` sugar therefore
//!   wrap `ScalarComparison("=", Field, Literal(TRUE))` instead of
//!   `Binary("=", ...)`. AND/OR still use `BoolExpr::Binary`.
//! * Numeric literals are stored as `LiteralValue::Text(raw)` (the Rust
//!   `LiteralValue` has no numeric variant); numeric validity is still
//!   enforced with the same `_parse_number_text` errors, and canonical
//!   formatting uses `_canonical_numeric_raw` on the raw spelling.
//! * `SelectTerm.expression` stays `None` for `qualifier.*` relation
//!   wildcards because `Expr` has no `RelationWildcard` variant; the wildcard
//!   remains fully recoverable from `SelectTerm.field`.
//! * `TruthTest` operands that Python stores as bare scalar expressions (an
//!   AST shape unreachable in the committed corpus) are stored as
//!   `Literal` for literal operands and otherwise as the equality comparison
//!   `ScalarComparison("=", expr, Literal(TRUE))`.
//! * The `expected` token labels attached to Python `QuerySyntaxError`s are
//!   dropped because `QueryError::syntax` does not model an expected set.
//! * Integer literals saturate at `i64` bounds instead of growing without
//!   bound (Python integers are arbitrary precision).
//! * `parse_regex_literal` validates with the `regex` crate; patterns that
//!   Python's `re` accepts but the Rust crate rejects (backreferences,
//!   lookaround) would be rejected here. The committed corpus contains none.
//! * `casefold()` is approximated with `to_lowercase()`; Unicode case folding
//!   differences (`ß`, `ſ`) do not occur in the corpus vocabulary.

use crate::lexer::{is_python_alpha, is_python_digit, is_python_space, python_repr, tokenise};
use crate::model::{
    AggregateFunction, Between, Binary, BoolExpr, CaseWhen, CollectionCount,
    CollectionElementReference, CollectionFilter, CollectionPredicate, CollectionProjection,
    CommonTableExpression, DerivedRelation, Expr, Field, InList, IsNull, JoinClause, JoinKind,
    Literal, LiteralValue, OrderTerm, Query, QueryError, RelationReference, ScalarBinary,
    ScalarCase, ScalarComparison, ScalarFunction, ScalarIndex, ScalarIsNull, ScalarMember,
    ScalarUnary, SelectTerm, SetOperation, TOKEN_ATIDENT, TOKEN_COMMA, TOKEN_DATE, TOKEN_DATETIME,
    TOKEN_DOT, TOKEN_EOF, TOKEN_IDENT, TOKEN_LBRACKET, TOKEN_LITERAL_WORD, TOKEN_LPAREN,
    TOKEN_MINUS, TOKEN_NUMBER, TOKEN_OP, TOKEN_PERCENT, TOKEN_PLUS, TOKEN_QIDENT, TOKEN_RBRACKET,
    TOKEN_RPAREN, TOKEN_SLASH, TOKEN_STAR, TOKEN_STRING, TOKEN_TEMPORAL, TOKEN_TIME, TextPredicate,
    Token, TruthTest, Unary, WindowFunction, WindowSpecification,
};

/// Reserved literal words an ordinary identifier component may not spell.
const RESERVED_LITERAL_WORDS: [&str; 3] = ["TRUE", "FALSE", "NULL"];

/// Window functions are parsed as dedicated scalar atoms carrying their OVER
/// specification. The set is the extension point for future window functions;
/// each name must remain an ordinary identifier where no function call follows.
const WINDOW_FUNCTION_NAMES: [&str; 1] = ["ROW_NUMBER"];

/// Keywords that terminate a bare dotted member access after an explicit dot.
const MEMBER_TERMINATOR_KEYWORDS: [&str; 16] = [
    "AS", "FROM", "WHERE", "GROUP", "HAVING", "ORDER", "LIMIT", "OFFSET", "UNION", "JOIN", "INNER",
    "LEFT", "OUTER", "SEMI", "ANTI", "ON",
];

/// Default clause-leading keywords that terminate a glued literal value.
const DEFAULT_STOP_KEYWORDS: [&str; 15] = [
    "AND", "OR", "UNION", "ORDER", "LIMIT", "OFFSET", "THEN", "WHEN", "ELSE", "END", "GROUP",
    "HAVING", "WHERE", "FROM", "SELECT",
];

fn is_reserved_literal_word(word: &str) -> bool {
    RESERVED_LITERAL_WORDS.contains(&word.to_uppercase().as_str())
}

// ---------------------------------------------------------------------------
// Numeric literal text helpers (ports of the `_parse_*_text` functions).
// ---------------------------------------------------------------------------

/// `\d+(?:_\d+)*` — decimal digit groups separated by single underscores.
/// Returns the consumed byte length, or `None` when no complete group is present.
fn decimal_digits_group(text: &str) -> Option<usize> {
    let mut any_digit = false;
    let mut previous_underscore = false;
    let mut previous_digit = false;
    let mut end = 0;
    for (offset, character) in text.char_indices() {
        if is_python_digit(character) {
            any_digit = true;
            previous_digit = true;
            previous_underscore = false;
            end = offset + character.len_utf8();
        } else if character == '_' && previous_digit {
            previous_underscore = true;
            previous_digit = false;
        } else {
            break;
        }
    }
    if any_digit && !previous_underscore {
        Some(end)
    } else {
        None
    }
}

/// The decoded numeric value domain of `_parse_number_text`.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum NumericLiteral {
    Int(i64),
    Float(f64),
}

fn strip_sign(text: &str) -> &str {
    text.strip_prefix(['+', '-']).unwrap_or(text)
}

/// `[+-]?\d+(?:_\d+)*` full match.
fn is_decimal_integer_text(text: &str) -> bool {
    let body = strip_sign(text);
    decimal_digits_group(body) == Some(body.len())
}

/// `[+-]?\d+(?:_\d+)*(?:\.(?:\d+(?:_\d+)*))?` full match.
fn is_decimal_number_text(text: &str) -> bool {
    let body = strip_sign(text);
    let Some(after_integer) = decimal_digits_group(body) else {
        return false;
    };
    let rest = &body[after_integer..];
    if rest.is_empty() {
        return true;
    }
    match rest.strip_prefix('.') {
        Some(fraction) => decimal_digits_group(fraction) == Some(fraction.len()),
        None => false,
    }
}

/// `[+-]?0[xXoObB]` prefix match.
fn starts_base_prefix(text: &str) -> bool {
    let body = strip_sign(text);
    let mut characters = body.chars();
    let zero = characters.next();
    let prefix = characters.next();
    zero == Some('0')
        && matches!(
            prefix,
            Some('x') | Some('X') | Some('o') | Some('O') | Some('b') | Some('B')
        )
}

/// `[+-]?(0[xX]|0[oO]|0[bB])[0-9A-Za-z]+(?:_[0-9A-Za-z]+)*` full match.
/// Returns the sign, the two-character prefix and the digit body.
fn split_base_integer(compact: &str) -> Option<(bool, &'static str, &str)> {
    let (negative, body) = match compact.strip_prefix('-') {
        Some(rest) => (true, rest),
        None => (false, compact.strip_prefix('+').unwrap_or(compact)),
    };
    if body.len() < 3 {
        return None;
    }
    let prefix = match &body[..2] {
        "0x" | "0X" => "0x",
        "0o" | "0O" => "0o",
        "0b" | "0B" => "0b",
        _ => return None,
    };
    let digits = &body[2..];
    let mut valid = false;
    let mut previous_underscore = false;
    let mut previous_alphanumeric = false;
    for character in digits.chars() {
        if character.is_ascii_alphanumeric() {
            valid = true;
            previous_alphanumeric = true;
            previous_underscore = false;
        } else if character == '_' && previous_alphanumeric {
            previous_underscore = true;
            previous_alphanumeric = false;
        } else {
            return None;
        }
    }
    if !valid || previous_underscore {
        return None;
    }
    Some((negative, prefix, digits))
}

/// Parse a sign-and-magnitude decimal that already passed shape validation,
/// saturating at `i64` bounds (Python integers are unbounded).
fn parse_signed_decimal(digits: &str) -> i64 {
    let (negative, magnitude) = match digits.strip_prefix('-') {
        Some(rest) => (true, rest),
        None => (false, digits.strip_prefix('+').unwrap_or(digits)),
    };
    let magnitude = magnitude.parse::<i128>().unwrap_or(i128::MAX);
    let clamped = magnitude.clamp(i64::MIN as i128, i64::MAX as i128);
    let signed = if negative { -clamped } else { clamped };
    signed as i64
}

/// Port of `_parse_integer_literal_text`.
pub fn parse_integer_literal_text(
    text: &str,
    source: &str,
    position: usize,
) -> Result<i64, QueryError> {
    let compact: String = text
        .chars()
        .filter(|character| !is_python_space(*character))
        .collect();
    if is_decimal_integer_text(&compact) {
        let digits = compact.replace('_', "");
        return Ok(parse_signed_decimal(&digits));
    }
    if let Some((negative, prefix, digit_body)) = split_base_integer(&compact) {
        let (base, radix) = match prefix {
            "0x" => (16, 16u32),
            "0o" => (8, 8u32),
            _ => (2, 2u32),
        };
        let digits = digit_body.replace('_', "");
        let valid = match base {
            16 => digits
                .chars()
                .all(|character| character.is_ascii_hexdigit()),
            8 => digits
                .chars()
                .all(|character| ('0'..='7').contains(&character)),
            _ => digits
                .chars()
                .all(|character| character == '0' || character == '1'),
        };
        if !valid {
            return Err(QueryError::lexical(
                source,
                format!("Invalid base-{base} integer literal {}.", python_repr(text)),
                position,
                None,
                "invalid",
            ));
        }
        // Saturate at `i64` bounds (Python integers are unbounded).
        let magnitude = i128::from_str_radix(&digits, radix).unwrap_or(i128::MAX);
        let clamped = magnitude.clamp(0, i64::MAX as i128);
        let signed = if negative { -clamped } else { clamped };
        return Ok(signed as i64);
    }
    if starts_base_prefix(&compact) {
        return Err(QueryError::lexical(
            source,
            format!("Invalid non-decimal integer literal {}.", python_repr(text)),
            position,
            None,
            "invalid",
        ));
    }
    Err(QueryError::lexical(
        source,
        format!("Could not understand integer value {}.", python_repr(text)),
        position,
        None,
        "invalid",
    ))
}

/// Port of `_parse_number_text`, returning the decoded int/float value.
pub fn parse_number_text(
    text: &str,
    source: &str,
    position: usize,
) -> Result<NumericLiteral, QueryError> {
    let compact: String = text
        .chars()
        .filter(|character| !is_python_space(*character))
        .collect();
    if starts_base_prefix(&compact) {
        return parse_integer_literal_text(&compact, source, position).map(NumericLiteral::Int);
    }
    if is_decimal_integer_text(&compact) {
        return Ok(NumericLiteral::Int(parse_signed_decimal(
            &compact.replace('_', ""),
        )));
    }
    if compact.contains('.') && is_decimal_number_text(&compact) {
        let rendered = compact.replace('_', "");
        return match rendered.parse::<f64>() {
            Ok(value) => Ok(NumericLiteral::Float(value)),
            // Unreachable for text that passed `_DECIMAL_NUMBER_RE` shape
            // validation; treated as the reference's "could not understand"
            // failure rather than a panic.
            Err(_) => Err(QueryError::lexical(
                source,
                format!("Could not understand numeric value {}.", python_repr(text)),
                position,
                None,
                "invalid",
            )),
        };
    }
    Err(QueryError::lexical(
        source,
        format!("Could not understand numeric value {}.", python_repr(text)),
        position,
        None,
        "invalid",
    ))
}

/// Port of `_canonical_numeric_raw`.
fn canonical_numeric_raw(raw: &str) -> String {
    let compact: String = raw.chars().filter(|character| *character != '_').collect();
    if let Some(normalised) = base_literal_shape(&compact) {
        return normalised;
    }
    compact
}

/// `(?P<sign>[+-]?)(?P<prefix>0[xX]|0[oO]|0[bB])(?P<digits>[0-9A-Fa-f]+)` full
/// match, rendered with a lowercase base prefix and lowercase hex digits.
fn base_literal_shape(compact: &str) -> Option<String> {
    let (sign, body) = match compact.strip_prefix('-') {
        Some(rest) => ("-", rest),
        None => ("", compact.strip_prefix('+').unwrap_or(compact)),
    };
    if body.len() < 3 {
        return None;
    }
    let prefix = match &body[..2] {
        "0x" | "0X" => "0x",
        "0o" | "0O" => "0o",
        "0b" | "0B" => "0b",
        _ => return None,
    };
    let digits = &body[2..];
    if digits.is_empty()
        || !digits
            .chars()
            .all(|character| character.is_ascii_hexdigit())
    {
        return None;
    }
    let rendered_digits = if prefix == "0x" {
        digits.to_lowercase()
    } else {
        digits.to_string()
    };
    Some(format!("{sign}{prefix}{rendered_digits}"))
}

// ---------------------------------------------------------------------------
// Canonical scalar/Boolean formatting (port of the `query_formatter` pieces
// the parser calls while building SELECT and ORDER BY terms).
// ---------------------------------------------------------------------------

/// Port of `_is_identifier_component`.
fn is_identifier_component(value: &str) -> bool {
    let mut characters = value.chars();
    let Some(first) = characters.next() else {
        return false;
    };
    if !(first == '_' || crate::lexer::is_xid_start(first)) {
        return false;
    }
    characters.all(|character| crate::lexer::is_xid_continue(character) || character == '-')
}

/// Port of `_format_identifier_component`.
fn format_identifier_component(value: &str) -> String {
    if is_identifier_component(value) && !is_reserved_literal_word(value) {
        return value.to_string();
    }
    format!("`{}`", value.replace('`', "``"))
}

/// Port of `_format_identifier`.
fn format_identifier(value: &str) -> String {
    value
        .split('.')
        .map(format_identifier_component)
        .collect::<Vec<_>>()
        .join(".")
}

/// Port of `_format_string`.
fn format_string_literal(value: &str) -> String {
    let escaped = value
        .replace('\\', "\\\\")
        .replace('\n', "\\n")
        .replace('\t', "\\t")
        .replace('\'', "''");
    format!("'{escaped}'")
}

/// Port of `_format_like_pattern`.
fn format_like_pattern(value: &str) -> String {
    format!("'{}'", value.replace('\'', "''"))
}

fn skip_python_spaces(text: &str) -> &str {
    let mut end = 0;
    for (offset, character) in text.char_indices() {
        if !is_python_space(character) {
            return &text[offset..];
        }
        end = offset + character.len_utf8();
    }
    let _ = end;
    ""
}

fn digits_run(text: &str) -> usize {
    let mut end = 0;
    for (offset, character) in text.char_indices() {
        if !is_python_digit(character) {
            break;
        }
        end = offset + character.len_utf8();
    }
    end
}

/// Port of `dates.canonicalise_temporal_expression`.
///
/// The unit lookup uses the default unit registry. Python raises `ValueError`
/// for unknown units (which crashes the reference adapter before any
/// observation is produced); this port treats such literals as
/// non-canonical and formats their raw spelling instead.
fn canonicalise_temporal_expression(text: &str) -> Option<String> {
    let raw = text.split_whitespace().collect::<Vec<_>>().join(" ");
    let (base_is_today, rest) = if let Some(rest) = strip_case_prefix(&raw, "TODAY") {
        (true, rest)
    } else {
        let rest = strip_case_prefix(&raw, "NOW")?;
        (false, rest)
    };
    let rest = rest.strip_prefix("()")?;
    let rest = skip_python_spaces(rest);
    if rest.is_empty() {
        return Some(if base_is_today { "TODAY()" } else { "NOW()" }.to_string());
    }
    let operator = rest.chars().next()?;
    if operator != '+' && operator != '-' {
        return None;
    }
    let after_operator = skip_python_spaces(&rest[operator.len_utf8()..]);
    let count_bytes = digits_run(after_operator);
    if count_bytes == 0 {
        return None;
    }
    let mut consumed = count_bytes;
    if let Some(fraction) = after_operator[count_bytes..].strip_prefix('.') {
        let fraction_bytes = digits_run(fraction);
        if fraction_bytes > 0 {
            consumed += 1 + fraction_bytes;
        }
    }
    let count_text = &after_operator[..consumed];
    let unit_text = skip_python_spaces(&after_operator[consumed..]);
    let unit_bytes = unit_run_bytes(unit_text)?;
    if unit_bytes != unit_text.len() {
        return None;
    }
    let unit = &unit_text[..unit_bytes];
    let canonical_unit = crate::units::load_default_unit_registry()
        .canonical_name(unit)
        .ok()?;
    let base = if base_is_today { "TODAY" } else { "NOW" };
    Some(format!("{base}(){operator}{count_text}{canonical_unit}"))
}

/// `[^\W\d_]+(?:-[^\W\d_]+)*` full match; returns the consumed byte length.
fn unit_run_bytes(text: &str) -> Option<usize> {
    let bytes = text.as_bytes();
    let mut index = 0;
    let mut count = 0;
    while index < bytes.len() {
        let (character, length) = match text.get(index..).and_then(|rest| rest.chars().next()) {
            Some(character) => (character, character.len_utf8()),
            None => break,
        };
        if !is_python_alpha(character) {
            break;
        }
        index += length;
        count += 1;
    }
    if count == 0 {
        return None;
    }
    while index < bytes.len() {
        if bytes[index] != b'-' {
            break;
        }
        let mut probe = index + 1;
        let mut run = 0;
        while probe < bytes.len() {
            let Some(character) = text.get(probe..).and_then(|rest| rest.chars().next()) else {
                break;
            };
            if !is_python_alpha(character) {
                break;
            }
            probe += character.len_utf8();
            run += 1;
        }
        if run == 0 {
            break;
        }
        index = probe;
    }
    Some(index)
}

fn strip_case_prefix<'a>(text: &'a str, word: &str) -> Option<&'a str> {
    let slice = text.get(..word.len())?;
    if slice.eq_ignore_ascii_case(word) {
        Some(&text[word.len()..])
    } else {
        None
    }
}

/// Port of `_format_literal` with `expected_kind=None` (parser-time fields
/// carry no resolved kind). `numeric` selects the int/float branch: scalar
/// expression literals are exactly the NUMBER atoms, while Boolean-side
/// literals always carry textual values.
fn format_literal(literal: &Literal, numeric: bool) -> String {
    match &literal.value {
        LiteralValue::Null => "NULL".to_string(),
        LiteralValue::Bool(value) => {
            if *value {
                "TRUE".to_string()
            } else {
                "FALSE".to_string()
            }
        }
        LiteralValue::Text(text) if literal.quoted => format_string_literal(text),
        _ => {
            if let Some(temporal) = canonicalise_temporal_expression(&literal.raw) {
                return temporal;
            }
            if numeric {
                canonical_numeric_raw(&literal.raw)
            } else {
                literal.raw.clone()
            }
        }
    }
}

/// Port of `_format_field_literal`.
fn format_field_literal(field: &Field, literal: &Literal) -> String {
    let _ = field; // field.kind is always None at parse time.
    format_literal(literal, false)
}

fn scalar_binary_precedence(operator: &str) -> i32 {
    if matches!(operator, "*" | "/" | "%") {
        20
    } else {
        10
    }
}

/// Port of `_format_scalar_binary_child`.
fn format_scalar_binary_child(expression: &Expr, parent_operator: &str, right: bool) -> String {
    let text = format_scalar_expression(expression);
    let Expr::Binary(child) = expression else {
        return text;
    };
    let child_precedence = scalar_binary_precedence(&child.operator);
    let parent_precedence = scalar_binary_precedence(parent_operator);
    if child_precedence < parent_precedence || (right && child_precedence == parent_precedence) {
        format!("({text})")
    } else {
        text
    }
}

/// Python `str()` of the literal value domain, for the regex validation path.
fn literal_value_text(literal: &Literal) -> String {
    match &literal.value {
        LiteralValue::Text(text) => text.clone(),
        LiteralValue::Null => "None".to_string(),
        LiteralValue::Bool(true) => "True".to_string(),
        LiteralValue::Bool(false) => "False".to_string(),
        LiteralValue::Raw => literal.raw.clone(),
    }
}

/// Port of `format_scalar_expression`.
fn format_scalar_expression(expression: &Expr) -> String {
    match expression {
        Expr::Field(field) => format_identifier(&field.name),
        Expr::RelationField(field) => {
            format!(
                "{}.{}",
                format_identifier_component(&field.qualifier),
                format_identifier(&field.name)
            )
        }
        Expr::Literal(literal) => format_literal(literal, true),
        Expr::Unary(unary) => {
            let operand = format_scalar_expression(&unary.operand);
            let operand = if matches!(&*unary.operand, Expr::Binary(_)) {
                format!("({operand})")
            } else {
                operand
            };
            format!("{}{}", unary.operator, operand)
        }
        Expr::Binary(binary) => {
            let left = format_scalar_binary_child(&binary.left, &binary.operator, false);
            let right = format_scalar_binary_child(&binary.right, &binary.operator, true);
            format!("{left} {} {right}", binary.operator)
        }
        Expr::Index(index) => {
            let collection = format_scalar_expression(&index.collection);
            let collection = if matches!(&*index.collection, Expr::Binary(_) | Expr::Unary(_)) {
                format!("({collection})")
            } else {
                collection
            };
            format!("{collection}[{}]", format_scalar_expression(&index.index))
        }
        Expr::Member(member) => {
            let value = format_scalar_expression(&member.value);
            let value = if matches!(
                &*member.value,
                Expr::Field(_) | Expr::Literal(_) | Expr::Unary(_) | Expr::Case(_)
            ) {
                format!("({value})")
            } else {
                value
            };
            format!("{value}.{}", format_identifier_component(&member.member))
        }
        Expr::CollectionElement(element) => format_identifier_component(&element.binding),
        Expr::CollectionCount(count) => format!(
            "COUNT({} AS {} WHERE {})",
            format_scalar_expression(&count.collection),
            format_identifier_component(&count.binding),
            format_expression(&count.predicate)
        ),
        Expr::CollectionFilter(filter) => format!(
            "FILTER({} AS {} WHERE {})",
            format_scalar_expression(&filter.collection),
            format_identifier_component(&filter.binding),
            format_expression(&filter.predicate)
        ),
        Expr::CollectionProjection(projection) => format!(
            "MAP({} AS {} SELECT {})",
            format_scalar_expression(&projection.collection),
            format_identifier_component(&projection.binding),
            format_scalar_expression(&projection.projection)
        ),
        Expr::Window(window) => {
            let mut parts: Vec<String> = Vec::new();
            if !window.specification.partition_by.is_empty() {
                let items = window
                    .specification
                    .partition_by
                    .iter()
                    .map(format_scalar_expression)
                    .collect::<Vec<_>>()
                    .join(", ");
                parts.push(format!("PARTITION BY {}", items));
            }
            if !window.specification.order_by.is_empty() {
                let terms = window
                    .specification
                    .order_by
                    .iter()
                    .map(|term| {
                        format!(
                            "{} {}",
                            term.field,
                            if term.descending { "DESC" } else { "ASC" }
                        )
                    })
                    .collect::<Vec<_>>()
                    .join(", ");
                parts.push(format!("ORDER BY {}", terms));
            }
            format!("{}() OVER ({})", window.name, parts.join(" "))
        }
        Expr::Function(function) => format!(
            "{}({})",
            function.name,
            function
                .args
                .iter()
                .map(format_scalar_expression)
                .collect::<Vec<_>>()
                .join(", ")
        ),
        Expr::Aggregate(aggregate) => {
            let inner = if aggregate.count_star {
                "*".to_string()
            } else {
                aggregate
                    .args
                    .iter()
                    .map(format_scalar_expression)
                    .collect::<Vec<_>>()
                    .join(", ")
            };
            let mut text = format!("{}({})", aggregate.name, inner);
            if let Some(predicate) = &aggregate.filter_predicate {
                text.push_str(&format!(" FILTER (WHERE {})", format_expression(predicate)));
            }
            text
        }
        Expr::Case(case) => {
            let mut parts = vec!["CASE".to_string()];
            for branch in &case.whens {
                parts.push(format!(
                    "WHEN {} THEN {}",
                    format_expression(&branch.condition),
                    format_scalar_expression(&branch.result)
                ));
            }
            if let Some(else_result) = &case.else_result {
                parts.push(format!("ELSE {}", format_scalar_expression(else_result)));
            }
            parts.push("END".to_string());
            parts.join(" ")
        }
    }
}

/// Port of `format_expression` (the Boolean formatter the parser reaches
/// through collection COUNT/FILTER/MAP formatting).
fn format_expression(node: &BoolExpr) -> String {
    match node {
        BoolExpr::Literal(literal) => format_literal(literal, false),
        BoolExpr::Unary(unary) => format!("NOT ({})", format_expression(&unary.operand)),
        BoolExpr::Binary(binary) => {
            if binary.operator == "AND" || binary.operator == "OR" {
                format!(
                    "({} {} {})",
                    format_expression(&binary.left),
                    binary.operator,
                    format_expression(&binary.right)
                )
            } else {
                // WHERE-level comparisons are represented as
                // `BoolExpr::ScalarComparison` (see the module documentation);
                // a non-AND/OR `BoolExpr::Binary` cannot occur from this parser.
                format!(
                    "{} {} {}",
                    format_expression(&binary.left),
                    binary.operator,
                    format_expression(&binary.right)
                )
            }
        }
        BoolExpr::Between(between) => {
            let not_part = if between.negated { " NOT" } else { "" };
            format!(
                "{}{} BETWEEN {} AND {}",
                between.field.name,
                not_part,
                format_field_literal(&between.field, &between.lower),
                format_field_literal(&between.field, &between.upper)
            )
        }
        BoolExpr::InList(in_list) => {
            let not_part = if in_list.negated { " NOT" } else { "" };
            let values = in_list
                .values
                .iter()
                .map(|value| format_field_literal(&in_list.field, value))
                .collect::<Vec<_>>()
                .join(", ");
            format!("{}{} IN ({})", in_list.field.name, not_part, values)
        }
        BoolExpr::IsNull(is_null) => {
            let not_part = if is_null.negated { "NOT " } else { "" };
            format!("{} IS {}NULL", is_null.field.name, not_part)
        }
        BoolExpr::TextPredicate(predicate) => {
            let not_part = if predicate.negated { " NOT" } else { "" };
            let value = if matches!(predicate.operator.as_str(), "LIKE" | "ILIKE")
                && predicate.value.quoted
            {
                format_like_pattern(&literal_value_text(&predicate.value))
            } else {
                format_field_literal(&predicate.field, &predicate.value)
            };
            format!(
                "{}{} {} {}",
                predicate.field.name, not_part, predicate.operator, value
            )
        }
        BoolExpr::CollectionPredicate(predicate) => format!(
            "{}({} AS {} WHERE {})",
            predicate.quantifier,
            format_scalar_expression(&predicate.collection),
            predicate.binding,
            format_expression(&predicate.predicate)
        ),
        BoolExpr::ScalarComparison(comparison) => {
            let right = match (&*comparison.left, &*comparison.right) {
                (Expr::Field(field), Expr::Literal(literal)) => {
                    format_field_literal(field, literal)
                }
                _ => format_scalar_expression(&comparison.right),
            };
            format!(
                "{} {} {}",
                format_scalar_expression(&comparison.left),
                comparison.operator,
                right
            )
        }
        BoolExpr::TruthTest(truth) => {
            // Preserve the established compact Boolean-field spelling.
            let compact_field = match &*truth.operand {
                BoolExpr::ScalarComparison(comparison) if comparison.operator == "=" => {
                    match (&*comparison.left, &*comparison.right) {
                        (Expr::Field(field), Expr::Literal(literal))
                            if literal.value == LiteralValue::Bool(true) =>
                        {
                            Some(field.name.clone())
                        }
                        _ => None,
                    }
                }
                _ => None,
            };
            let operand = match compact_field {
                Some(name) => name,
                None => format!("({})", format_expression(&truth.operand)),
            };
            let not_part = if truth.negated { "NOT " } else { "" };
            format!("{} IS {}{}", operand, not_part, truth.truth)
        }
        BoolExpr::ScalarIsNull(is_null) => {
            let not_part = if is_null.negated { "NOT " } else { "" };
            format!(
                "{} IS {}NULL",
                format_scalar_expression(&is_null.expression),
                not_part
            )
        }
    }
}

/// Python's `Literal(True, "TRUE", field.position)` used by the Boolean-field
/// truth-test sugar. Rust represents that sugar's `Binary("=", field, TRUE)`
/// operand as `ScalarComparison`; see the module documentation.
fn boolean_field_equality(field: &Field) -> BoolExpr {
    BoolExpr::ScalarComparison(ScalarComparison {
        operator: "=".to_string(),
        left: Box::new(Expr::Field(field.clone())),
        right: Box::new(Expr::Literal(Literal {
            value: LiteralValue::Bool(true),
            raw: "TRUE".to_string(),
            position: field.position,
            quoted: false,
        })),
    })
}

fn truth_test_on_boolean_field(field: &Field, truth: &str, negated: bool) -> BoolExpr {
    BoolExpr::TruthTest(TruthTest {
        operand: Box::new(boolean_field_equality(field)),
        truth: truth.to_string(),
        negated,
    })
}

/// Wrap a scalar expression as a Boolean operand for a `TruthTest`. Python
/// stores bare scalar expressions there directly; see the module
/// documentation for the representation used here.
fn scalar_as_boolean(expression: Expr) -> BoolExpr {
    match expression {
        Expr::Literal(literal) => BoolExpr::Literal(literal),
        other => BoolExpr::ScalarComparison(ScalarComparison {
            operator: "=".to_string(),
            left: Box::new(other),
            right: Box::new(Expr::Literal(Literal {
                value: LiteralValue::Bool(true),
                raw: "TRUE".to_string(),
                position: 0,
                quoted: false,
            })),
        }),
    }
}

fn normalise_comparison_operator(operator: &str) -> String {
    if operator == "<>" {
        "!=".to_string()
    } else {
        operator.to_string()
    }
}

fn empty_token(source: &str) -> Token {
    Token {
        kind: TOKEN_EOF,
        text: String::new(),
        position: source.len(),
        value: None,
        end_position: source.len(),
    }
}

/// Recursive-descent parser. It deliberately knows no yt-dlp field schema.
pub struct Parser {
    source: String,
    tokens: Vec<Token>,
    index: usize,
    collection_bindings: Vec<String>,
}

impl Parser {
    pub fn new(source: &str) -> Result<Self, QueryError> {
        Ok(Self {
            source: source.to_string(),
            tokens: tokenise(source)?,
            index: 0,
            collection_bindings: Vec::new(),
        })
    }

    pub fn parse_query(&mut self) -> Result<Query, QueryError> {
        self.parse_query_mode(false, false, true, false)
    }

    pub fn parse_where(&mut self) -> Result<Query, QueryError> {
        self.parse_query_mode(true, false, true, false)
    }

    fn token_at(&self, offset: usize) -> Token {
        self.tokens
            .get(self.index + offset)
            .cloned()
            .unwrap_or_else(|| empty_token(&self.source))
    }

    fn token_before(&self) -> Token {
        match self
            .index
            .checked_sub(1)
            .and_then(|index| self.tokens.get(index))
        {
            Some(token) => token.clone(),
            None => empty_token(&self.source),
        }
    }

    fn current(&self) -> Token {
        self.token_at(0)
    }

    fn advance(&mut self) -> Token {
        let token = self.current();
        if token.kind != TOKEN_EOF {
            self.index += 1;
        }
        token
    }

    fn keyword(&self, word: &str) -> bool {
        let token = self.current();
        (token.kind == TOKEN_IDENT || token.kind == TOKEN_LITERAL_WORD)
            && token.text.to_uppercase() == word
    }

    fn consume_keyword(&mut self, word: &str) -> Option<Token> {
        if self.keyword(word) {
            Some(self.advance())
        } else {
            None
        }
    }

    fn expect_keyword(
        &mut self,
        word: &str,
        message: Option<&str>,
        reason: &str,
    ) -> Result<Token, QueryError> {
        match self.consume_keyword(word) {
            Some(token) => Ok(token),
            None => {
                let token = self.current();
                let fallback = format!("Expected {word}.");
                let message = message.unwrap_or(fallback.as_str());
                Err(QueryError::syntax(
                    &self.source,
                    message,
                    token.position,
                    Some(token.end_position),
                    reason,
                ))
            }
        }
    }

    fn expect(&mut self, kind: &'static str, message: &str) -> Result<Token, QueryError> {
        let token = self.current();
        if token.kind != kind {
            return Err(QueryError::syntax(
                &self.source,
                message,
                token.position,
                Some(token.end_position),
                "invalid",
            ));
        }
        Ok(self.advance())
    }

    /// Consume an ordinary or backtick-quoted identifier token.
    fn expect_identifier(&mut self, message: &str) -> Result<Token, QueryError> {
        let token = self.current();
        if token.kind != TOKEN_IDENT && token.kind != TOKEN_QIDENT {
            return Err(QueryError::syntax(
                &self.source,
                message,
                token.position,
                Some(token.end_position),
                "invalid",
            ));
        }
        let token = self.advance();
        if token.kind == TOKEN_QIDENT {
            let value = token.value.clone().unwrap_or_default();
            return Ok(Token {
                kind: TOKEN_QIDENT,
                text: value.clone(),
                position: token.position,
                value: Some(value),
                end_position: token.end_position,
            });
        }
        Ok(token)
    }

    fn at_end(&self, stop_at_rparen: bool) -> bool {
        let token = self.current();
        token.kind == TOKEN_EOF || (stop_at_rparen && token.kind == TOKEN_RPAREN)
    }

    // -----------------------------------------------------------------------
    // Statement shape
    // -----------------------------------------------------------------------

    fn parse_query_mode(
        &mut self,
        where_only: bool,
        stop_at_rparen: bool,
        allow_with: bool,
        set_branch: bool,
    ) -> Result<Query, QueryError> {
        let mut predicate: Option<BoolExpr> = None;
        let mut order_by: Vec<OrderTerm> = Vec::new();
        let mut limit: Option<i64> = None;
        let mut limit_literal: Option<String> = None;
        let mut select: Vec<SelectTerm> = Vec::new();
        let mut from_source: Option<String> = None;
        let mut from_facet: Option<String> = None;
        let mut additional_from_facets: Vec<(String, usize)> = Vec::new();
        let mut from_alias: Option<String> = None;
        let mut from_relation: Option<RelationReference> = None;
        let mut joins: Vec<JoinClause> = Vec::new();
        let mut distinct = false;
        let mut offset: i64 = 0;
        let mut offset_literal: Option<String> = None;
        let mut group_by: Vec<Expr> = Vec::new();
        let mut having: Option<BoolExpr> = None;
        let mut ctes: Vec<CommonTableExpression> = Vec::new();
        let mut set_operations: Vec<SetOperation> = Vec::new();
        let mut left_query: Option<Query> = None;

        if !where_only && !allow_with && self.keyword("WITH") {
            return Err(QueryError::syntax(
                &self.source,
                "Nested WITH clauses are not supported.",
                self.current().position,
                None,
                "invalid",
            ));
        }

        if !where_only && allow_with && self.consume_keyword("WITH").is_some() {
            if self.consume_keyword("RECURSIVE").is_some() {
                return Err(QueryError::syntax(
                    &self.source,
                    "Recursive CTEs are not supported.",
                    self.current().position,
                    None,
                    "invalid",
                ));
            }
            let mut seen_names: Vec<String> = Vec::new();
            loop {
                let name_token = self.expect_identifier("Expected a CTE name after WITH.")?;
                if seen_names.contains(&name_token.text) {
                    return Err(QueryError::syntax(
                        &self.source,
                        format!("Duplicate CTE name {}.", python_repr(&name_token.text)),
                        name_token.position,
                        None,
                        "invalid",
                    ));
                }
                seen_names.push(name_token.text.clone());
                self.expect_keyword("AS", Some("Expected AS after CTE name."), "invalid")?;
                self.expect(TOKEN_LPAREN, "Expected '(' before CTE query.")?;
                let current = self.current();
                if current.kind == TOKEN_RPAREN {
                    return Err(QueryError::syntax(
                        &self.source,
                        "CTE query cannot be empty.",
                        current.position,
                        None,
                        "empty-query",
                    ));
                }
                let subquery = self.parse_query_mode(false, true, false, false)?;
                self.expect(TOKEN_RPAREN, "Expected ')' after CTE query.")?;
                ctes.push(CommonTableExpression {
                    name: name_token.text,
                    query: Box::new(subquery),
                    position: name_token.position,
                });
                if self.current().kind != TOKEN_COMMA {
                    break;
                }
                self.advance();
            }
        }

        if where_only {
            if !self.at_end(stop_at_rparen) {
                predicate = Some(self.parse_or()?);
            }
        } else {
            if self.current().kind == TOKEN_LPAREN {
                self.advance();
                let current = self.current();
                if current.kind == TOKEN_RPAREN {
                    return Err(QueryError::syntax(
                        &self.source,
                        "Parenthesised query cannot be empty.",
                        current.position,
                        None,
                        "invalid",
                    ));
                }
                left_query = Some(self.parse_query_mode(false, true, false, false)?);
                self.expect(TOKEN_RPAREN, "Expected ')' after parenthesised query.")?;
            } else if self.consume_keyword("SELECT").is_some() {
                distinct = self.consume_keyword("DISTINCT").is_some();
                select = self.parse_select_list()?;
            }

            if left_query.is_none() && self.consume_keyword("FROM").is_some() {
                let relations = self.parse_relation_references()?;
                let Some(relation) = relations.first().cloned() else {
                    return Err(QueryError::syntax(
                        &self.source,
                        "Expected a channel/playlist identifier after FROM or JOIN. Quote full URLs.",
                        self.current().position,
                        None,
                        "missing-source",
                    ));
                };
                from_source = relation.source.clone();
                from_facet = relation.facet.clone();
                for item in &relations[1..] {
                    if let Some(facet) = &item.facet {
                        additional_from_facets.push((facet.clone(), item.position));
                    }
                }
                from_alias = relation.alias.clone();
                if relation.derived.is_some() {
                    from_relation = Some(relation);
                }
                while self.join_starts_here() {
                    joins.push(self.parse_join_clause()?);
                }
            }

            if left_query.is_none() {
                if self.consume_keyword("WHERE").is_some() {
                    let current = self.current();
                    if self.at_end(stop_at_rparen)
                        || self.keyword("GROUP")
                        || self.keyword("HAVING")
                        || self.keyword("UNION")
                        || self.keyword("ORDER")
                        || self.keyword("LIMIT")
                        || self.keyword("OFFSET")
                    {
                        return Err(QueryError::syntax(
                            &self.source,
                            "WHERE requires an expression.",
                            current.position,
                            None,
                            "invalid",
                        ));
                    }
                    predicate = Some(self.parse_or()?);
                } else if !self.keyword("GROUP")
                    && !self.keyword("HAVING")
                    && !self.keyword("UNION")
                    && !self.keyword("ORDER")
                    && !self.keyword("LIMIT")
                    && !self.keyword("OFFSET")
                    && !self.at_end(stop_at_rparen)
                {
                    if !select.is_empty() || from_source.is_some() {
                        return Err(QueryError::syntax(
                            &self.source,
                            "Expected WHERE, GROUP BY, HAVING, ORDER BY, LIMIT, OFFSET, or end of query.",
                            self.current().position,
                            None,
                            "missing-clause-separator",
                        ));
                    }
                    predicate = Some(self.parse_or()?);
                }
            }
        }

        if left_query.is_none() && self.consume_keyword("GROUP").is_some() {
            self.expect_keyword("BY", Some("Expected BY after GROUP."), "invalid")?;
            group_by = self.parse_group_by()?;
        }

        if left_query.is_none() && self.consume_keyword("HAVING").is_some() {
            if group_by.is_empty() && select.is_empty() {
                return Err(QueryError::syntax(
                    &self.source,
                    "HAVING requires an aggregate SELECT or GROUP BY.",
                    self.current().position,
                    None,
                    "invalid",
                ));
            }
            having = Some(self.parse_having_or()?);
        }

        if !where_only
            && set_branch
            && (self.at_end(stop_at_rparen)
                || self.keyword("UNION")
                || self.keyword("ORDER")
                || self.keyword("LIMIT")
                || self.keyword("OFFSET"))
        {
            return Ok(Query {
                predicate: predicate.map(Box::new),
                order_by,
                limit,
                source: self.source.clone(),
                select,
                from_source,
                distinct,
                offset,
                group_by,
                having: having.map(Box::new),
                ctes,
                set_operations: Vec::new(),
                from_facet,
                from_alias,
                joins,
                left_query: None,
                from_relation,
                limit_literal: None,
                offset_literal: None,
            });
        }

        if !where_only && !set_branch {
            for (facet, facet_position) in &additional_from_facets {
                set_operations.push(SetOperation {
                    query: Box::new(Query {
                        predicate: predicate.clone().map(Box::new),
                        order_by: Vec::new(),
                        limit: None,
                        source: self.source.clone(),
                        select: select.clone(),
                        from_source: from_source.clone(),
                        distinct,
                        offset: 0,
                        group_by: group_by.clone(),
                        having: having.clone().map(Box::new),
                        ctes: Vec::new(),
                        set_operations: Vec::new(),
                        from_facet: Some(facet.clone()),
                        from_alias: from_alias.clone(),
                        joins: joins.clone(),
                        left_query: None,
                        from_relation: from_relation.clone(),
                        limit_literal: None,
                        offset_literal: None,
                    }),
                    all: true,
                    position: *facet_position,
                    facet_expansion: true,
                    grouped: false,
                });
            }

            while self.consume_keyword("UNION").is_some() {
                let union_position = self.token_before().position;
                let union_all = self.consume_keyword("ALL").is_some();
                let grouped = self.current().kind == TOKEN_LPAREN;
                let branch = if grouped {
                    self.advance();
                    let current = self.current();
                    if current.kind == TOKEN_RPAREN {
                        return Err(QueryError::syntax(
                            &self.source,
                            "Parenthesised UNION branch cannot be empty.",
                            current.position,
                            None,
                            "invalid",
                        ));
                    }
                    let branch = self.parse_query_mode(false, true, false, false)?;
                    self.expect(
                        TOKEN_RPAREN,
                        "Expected ')' after parenthesised UNION branch.",
                    )?;
                    branch
                } else {
                    self.parse_query_mode(false, stop_at_rparen, false, true)?
                };
                if branch.select.is_empty() && branch.left_query.is_none() {
                    return Err(QueryError::syntax(
                        &self.source,
                        "UNION requires a SELECT query on both sides.",
                        union_position,
                        None,
                        "incomplete-union",
                    ));
                }
                set_operations.push(SetOperation {
                    query: Box::new(branch),
                    all: union_all,
                    position: union_position,
                    facet_expansion: false,
                    grouped,
                });
            }
        }

        if self.consume_keyword("ORDER").is_some() {
            self.expect_keyword("BY", Some("Expected BY after ORDER."), "invalid")?;
            order_by = self.parse_order_by()?;
        }

        if self.consume_keyword("LIMIT").is_some() {
            let token = self.current();
            let integer_shape = token.kind == TOKEN_NUMBER
                && (is_decimal_integer_text(&token.text) || starts_base_prefix(&token.text));
            if !integer_shape {
                return Err(QueryError::syntax(
                    &self.source,
                    "LIMIT requires a positive integer.",
                    token.position,
                    None,
                    "invalid",
                ));
            }
            let parsed = parse_integer_literal_text(&token.text, &self.source, token.position)?;
            if parsed <= 0 {
                return Err(QueryError::syntax(
                    &self.source,
                    "LIMIT must be greater than zero.",
                    token.position,
                    None,
                    "invalid",
                ));
            }
            limit = Some(parsed);
            limit_literal = Some(canonical_numeric_raw(&token.text));
            self.advance();
        }

        if self.consume_keyword("OFFSET").is_some() {
            let token = self.current();
            if token.kind == TOKEN_MINUS {
                return Err(QueryError::syntax(
                    &self.source,
                    "OFFSET requires a non-negative integer.",
                    token.position,
                    None,
                    "invalid",
                ));
            }
            let integer_shape = token.kind == TOKEN_NUMBER
                && (is_decimal_integer_text(&token.text) || starts_base_prefix(&token.text));
            if !integer_shape {
                return Err(QueryError::syntax(
                    &self.source,
                    "OFFSET requires a non-negative integer.",
                    token.position,
                    None,
                    "invalid",
                ));
            }
            offset = parse_integer_literal_text(&token.text, &self.source, token.position)?;
            offset_literal = Some(canonical_numeric_raw(&token.text));
            self.advance();
        }

        if !self.at_end(stop_at_rparen) {
            if let Some(clause) = self.statement_clause_at_current() {
                return Err(QueryError::syntax(
                    &self.source,
                    format!(
                        "{clause} is repeated or appears outside the canonical SELECT clause order."
                    ),
                    self.current().position,
                    None,
                    "clause-order",
                ));
            }
            let current = self.current();
            return Err(QueryError::syntax(
                &self.source,
                format!("Unexpected token {}.", python_repr(&current.text)),
                current.position,
                None,
                "invalid",
            ));
        }

        Ok(Query {
            predicate: predicate.map(Box::new),
            order_by,
            limit,
            source: self.source.clone(),
            select,
            from_source,
            distinct,
            offset,
            group_by,
            having: having.map(Box::new),
            ctes,
            set_operations,
            from_facet,
            from_alias,
            joins,
            left_query: left_query.map(Box::new),
            from_relation,
            limit_literal,
            offset_literal,
        })
    }

    /// Return a statement-level clause introducer at the current token.
    fn statement_clause_at_current(&self) -> Option<&'static str> {
        if self.keyword("WHERE") {
            return Some("WHERE");
        }
        let next = self.token_at(1);
        if self.keyword("GROUP") && next.kind == TOKEN_IDENT && next.text.to_uppercase() == "BY" {
            return Some("GROUP BY");
        }
        if self.keyword("HAVING") {
            return Some("HAVING");
        }
        if self.keyword("ORDER") && next.kind == TOKEN_IDENT && next.text.to_uppercase() == "BY" {
            return Some("ORDER BY");
        }
        if self.keyword("LIMIT") {
            return Some("LIMIT");
        }
        if self.keyword("OFFSET") {
            return Some("OFFSET");
        }
        None
    }

    fn parse_select_list(&mut self) -> Result<Vec<SelectTerm>, QueryError> {
        let mut terms: Vec<SelectTerm> = Vec::new();
        loop {
            if self.current().kind == TOKEN_STAR {
                let star = self.advance();
                if !terms.is_empty() || self.current().kind == TOKEN_COMMA {
                    return Err(QueryError::syntax(
                        &self.source,
                        "SELECT * must be used by itself; it cannot be mixed with explicit projections.",
                        star.position,
                        None,
                        "invalid",
                    ));
                }
                terms.push(SelectTerm {
                    field: "*".to_string(),
                    alias: None,
                    position: star.position,
                    kind: None,
                    expression: None,
                });
                return Ok(terms);
            }
            let position = self.current().position;
            let expression: Option<Box<Expr>>;
            let field_text: String;
            let current = self.current();
            let next = self.token_at(1);
            let after_next = self.token_at(2);
            if (current.kind == TOKEN_IDENT || current.kind == TOKEN_QIDENT)
                && next.kind == TOKEN_DOT
                && after_next.kind == TOKEN_STAR
            {
                let qualifier_token = self.advance();
                let qualifier = if qualifier_token.kind == TOKEN_QIDENT {
                    qualifier_token.value.clone().unwrap_or_default()
                } else {
                    qualifier_token.text.clone()
                };
                self.advance();
                self.advance();
                // The relation wildcard cannot be represented in `Expr` (see the
                // module documentation); the canonical field text carries it.
                expression = None;
                if qualifier_token.kind == TOKEN_QIDENT {
                    field_text = format!("`{}`.*", qualifier.replace('`', "``"));
                } else {
                    field_text = format!("{qualifier}.*");
                }
                if self.keyword("AS") {
                    return Err(QueryError::syntax(
                        &self.source,
                        "A relation wildcard cannot have an AS alias.",
                        self.current().position,
                        None,
                        "invalid",
                    ));
                }
            } else {
                let parsed = self.parse_scalar_expression()?;
                field_text = format_scalar_expression(&parsed);
                expression = Some(Box::new(parsed));
            }
            let mut alias = None;
            if self.consume_keyword("AS").is_some() {
                let alias_token = self.expect_identifier("Expected an alias name after AS.")?;
                alias = Some(alias_token.text);
            }
            terms.push(SelectTerm {
                field: field_text,
                alias,
                position,
                kind: None,
                expression,
            });
            if self.current().kind != TOKEN_COMMA {
                break;
            }
            self.advance();
        }
        Ok(terms)
    }

    // -----------------------------------------------------------------------
    // Scalar expressions
    // -----------------------------------------------------------------------

    /// Parse a scalar expression using SQL-like arithmetic precedence.
    fn parse_scalar_expression(&mut self) -> Result<Expr, QueryError> {
        self.parse_scalar_additive()
    }

    fn parse_scalar_additive(&mut self) -> Result<Expr, QueryError> {
        let mut node = self.parse_scalar_multiplicative()?;
        while matches!(self.current().kind, kind if kind == TOKEN_PLUS || kind == TOKEN_MINUS) {
            let token = self.advance();
            let right = self.parse_scalar_multiplicative()?;
            node = Expr::Binary(ScalarBinary {
                operator: token.text,
                left: Box::new(node),
                right: Box::new(right),
                position: token.position,
                kind: None,
            });
        }
        Ok(node)
    }

    fn parse_scalar_multiplicative(&mut self) -> Result<Expr, QueryError> {
        let mut node = self.parse_scalar_unary()?;
        while matches!(self.current().kind, kind if kind == TOKEN_STAR || kind == TOKEN_SLASH || kind == TOKEN_PERCENT)
        {
            let token = self.advance();
            let right = self.parse_scalar_unary()?;
            node = Expr::Binary(ScalarBinary {
                operator: token.text,
                left: Box::new(node),
                right: Box::new(right),
                position: token.position,
                kind: None,
            });
        }
        Ok(node)
    }

    fn parse_scalar_unary(&mut self) -> Result<Expr, QueryError> {
        if matches!(self.current().kind, kind if kind == TOKEN_PLUS || kind == TOKEN_MINUS) {
            let token = self.advance();
            let operand = self.parse_scalar_unary()?;
            return Ok(Expr::Unary(ScalarUnary {
                operator: token.text,
                operand: Box::new(operand),
                position: token.position,
                kind: None,
            }));
        }
        self.parse_scalar_postfix()
    }

    /// Parse tightly binding postfix indexing and structured member access.
    fn parse_scalar_postfix(&mut self) -> Result<Expr, QueryError> {
        let mut node = self.parse_scalar_atom()?;
        while matches!(self.current().kind, kind if kind == TOKEN_LBRACKET || kind == TOKEN_DOT) {
            if self.current().kind == TOKEN_LBRACKET {
                let bracket = self.advance();
                if self.current().kind == TOKEN_RBRACKET {
                    return Err(QueryError::syntax(
                        &self.source,
                        "Collection indexing requires an index expression.",
                        bracket.position,
                        None,
                        "missing-index-expression",
                    ));
                }
                let index = self.parse_scalar_expression()?;
                self.expect(
                    TOKEN_RBRACKET,
                    "Expected ']' to close the collection index.",
                )?;
                node = Expr::Index(ScalarIndex {
                    collection: Box::new(node),
                    index: Box::new(index),
                    position: bracket.position,
                    kind: None,
                    resolved_type: None,
                });
                continue;
            }

            let dot = self.advance();
            let current = self.current();
            let member_ok = (current.kind == TOKEN_IDENT || current.kind == TOKEN_QIDENT)
                && !(current.kind == TOKEN_IDENT
                    && MEMBER_TERMINATOR_KEYWORDS.contains(&current.text.to_uppercase().as_str()));
            if !member_ok {
                return Err(QueryError::syntax(
                    &self.source,
                    "Expected a member name after '.'.",
                    current.position,
                    None,
                    "invalid",
                ));
            }
            let member_token = self.advance();
            let member_text = if member_token.kind == TOKEN_QIDENT {
                member_token.value.clone().unwrap_or_default()
            } else {
                member_token.text.clone()
            };
            // After an explicit postfix dot, split any dotted token into successive
            // member operations so expressions such as formats[0].video.height remain
            // composable without changing the established parsing of bare dotted
            // fields.
            let mut offset = 0;
            for member in member_text.split('.') {
                let position = if offset == 0 {
                    dot.position
                } else {
                    member_token.position + offset - 1
                };
                node = Expr::Member(ScalarMember {
                    value: Box::new(node),
                    member: member.to_string(),
                    position,
                    kind: None,
                    resolved_type: None,
                });
                offset += member.len() + 1;
            }
        }
        Ok(node)
    }

    /// Return a scoped element reference when `token` begins with a binding.
    fn bound_collection_reference(&self, token: &Token) -> Option<Expr> {
        let parts: Vec<&str> = token.text.split('.').collect();
        let head = parts[0];
        for (distance, binding) in self.collection_bindings.iter().rev().enumerate() {
            if head != binding.as_str() {
                continue;
            }
            let mut node = Expr::CollectionElement(CollectionElementReference {
                binding: binding.clone(),
                scope_distance: distance,
                position: token.position,
                kind: None,
                resolved_type: None,
            });
            let mut offset = binding.len();
            for member in &parts[1..] {
                node = Expr::Member(ScalarMember {
                    value: Box::new(node),
                    member: (*member).to_string(),
                    position: token.position + offset,
                    kind: None,
                    resolved_type: None,
                });
                offset += member.len() + 1;
            }
            return Some(node);
        }
        None
    }

    fn parse_scalar_atom(&mut self) -> Result<Expr, QueryError> {
        let token = self.current();
        if self.keyword("CASE") {
            return self.parse_scalar_case();
        }
        if token.kind == TOKEN_LPAREN {
            self.advance();
            let node = self.parse_scalar_expression()?;
            self.expect(TOKEN_RPAREN, "Expected ')' to close the scalar expression.")?;
            return Ok(node);
        }
        if token.kind == TOKEN_LITERAL_WORD {
            self.advance();
            let value = match token.text.to_uppercase().as_str() {
                "NULL" => LiteralValue::Null,
                "TRUE" => LiteralValue::Bool(true),
                _ => LiteralValue::Bool(false),
            };
            return Ok(Expr::Literal(Literal {
                value,
                raw: token.text.clone(),
                position: token.position,
                quoted: false,
            }));
        }
        if token.kind == TOKEN_QIDENT {
            self.advance();
            let mut name = token.value.clone().unwrap_or_default();
            while self.current().kind == TOKEN_DOT && self.index + 1 < self.tokens.len() {
                let next = self.token_at(1);
                if next.kind != TOKEN_IDENT && next.kind != TOKEN_QIDENT {
                    break;
                }
                self.advance();
                let component = self.advance();
                let component_name = if component.kind == TOKEN_QIDENT {
                    component.value.clone().unwrap_or_default()
                } else {
                    component.text.clone()
                };
                name.push('.');
                name.push_str(&component_name);
            }
            if name.to_lowercase().starts_with("raw.") {
                return Err(QueryError::syntax(
                    &self.source,
                    "The raw.* metadata namespace has been removed; use a registered query field.",
                    token.position,
                    None,
                    "invalid",
                ));
            }
            return Ok(Expr::Field(Field {
                name,
                position: token.position,
                kind: None,
            }));
        }
        if token.kind == TOKEN_IDENT {
            for part in token.text.split('.') {
                if is_reserved_literal_word(part) {
                    return Err(QueryError::syntax(
                        &self.source,
                        format!(
                            "{} contains a reserved literal word and cannot be used as an identifier.",
                            python_repr(&token.text)
                        ),
                        token.position,
                        None,
                        "invalid",
                    ));
                }
            }
            self.advance();
            if self.current().kind == TOKEN_LPAREN {
                if WINDOW_FUNCTION_NAMES.contains(&token.text.to_uppercase().as_str()) {
                    return self.parse_window_function(token);
                }
                return self.parse_scalar_function(token);
            }
            let lowered = token.text.to_lowercase();
            if lowered == "raw" || lowered.starts_with("raw.") {
                return Err(QueryError::syntax(
                    &self.source,
                    "The raw.* metadata namespace has been removed; use a registered query field.",
                    token.position,
                    None,
                    "invalid",
                ));
            }
            if let Some(bound) = self.bound_collection_reference(&token) {
                return Ok(bound);
            }
            return Ok(Expr::Field(Field {
                name: token.text.clone(),
                position: token.position,
                kind: None,
            }));
        }
        if token.kind == TOKEN_STRING {
            self.advance();
            return Ok(Expr::Literal(Literal {
                value: LiteralValue::Text(token.value.clone().unwrap_or_default()),
                raw: token.text.clone(),
                position: token.position,
                quoted: true,
            }));
        }
        if token.kind == TOKEN_NUMBER {
            self.advance();
            // Numeric validity is enforced with the reference `_parse_number_text`
            // diagnostics; the value is kept as its raw spelling (see the module
            // documentation).
            parse_number_text(&token.text, &self.source, token.position)?;
            return Ok(Expr::Literal(Literal {
                value: LiteralValue::Text(token.text.clone()),
                raw: token.text.clone(),
                position: token.position,
                quoted: false,
            }));
        }
        Err(QueryError::syntax(
            &self.source,
            "Expected a scalar field, literal, function, or parenthesised expression.",
            token.position,
            None,
            "invalid",
        ))
    }

    /// Parse a searched CASE expression. Simple CASE is intentionally unsupported.
    fn parse_scalar_case(&mut self) -> Result<Expr, QueryError> {
        let case_token = self.expect_keyword("CASE", None, "invalid")?;
        if !self.keyword("WHEN") {
            if self.current().kind == TOKEN_EOF {
                return Err(QueryError::syntax(
                    &self.source,
                    "CASE requires at least one WHEN clause.",
                    case_token.position,
                    None,
                    "invalid",
                ));
            }
            return Err(QueryError::syntax(
                &self.source,
                "Only searched CASE is supported; write CASE WHEN <condition> THEN <value> ... END.",
                self.current().position,
                None,
                "invalid",
            ));
        }

        let mut whens: Vec<CaseWhen> = Vec::new();
        while self.consume_keyword("WHEN").is_some() {
            let when_position = self.token_before().position;
            if self.keyword("THEN")
                || self.keyword("WHEN")
                || self.keyword("ELSE")
                || self.keyword("END")
            {
                return Err(QueryError::syntax(
                    &self.source,
                    "CASE WHEN requires a condition before THEN.",
                    self.current().position,
                    None,
                    "invalid",
                ));
            }
            let condition = self.parse_or()?;
            self.expect_keyword(
                "THEN",
                Some("Expected THEN after CASE WHEN condition."),
                "invalid",
            )?;
            if self.keyword("WHEN")
                || self.keyword("ELSE")
                || self.keyword("END")
                || self.current().kind == TOKEN_EOF
            {
                return Err(QueryError::syntax(
                    &self.source,
                    "CASE THEN requires a scalar result expression.",
                    self.current().position,
                    None,
                    "invalid",
                ));
            }
            let result = self.parse_scalar_expression()?;
            whens.push(CaseWhen {
                condition: Box::new(condition),
                result: Box::new(result),
                position: when_position,
            });
        }

        let mut else_result = None;
        if self.consume_keyword("ELSE").is_some() {
            if self.keyword("END") || self.current().kind == TOKEN_EOF {
                return Err(QueryError::syntax(
                    &self.source,
                    "CASE ELSE requires a scalar result expression.",
                    self.current().position,
                    None,
                    "invalid",
                ));
            }
            else_result = Some(Box::new(self.parse_scalar_expression()?));
        }

        self.expect_keyword(
            "END",
            Some("Expected END to close CASE expression."),
            "invalid",
        )?;
        Ok(Expr::Case(ScalarCase {
            whens,
            else_result,
            position: case_token.position,
            kind: None,
        }))
    }

    fn parse_scalar_function(&mut self, name_token: Token) -> Result<Expr, QueryError> {
        let name = name_token.text.to_uppercase();
        const AGGREGATE_NAMES: [&str; 5] = ["COUNT", "SUM", "MIN", "MAX", "AVG"];
        const SCALAR_NAMES: [&str; 14] = [
            "LOWER",
            "UPPER",
            "LENGTH",
            "CARDINALITY",
            "FILTER",
            "MAP",
            "COALESCE",
            "CONCAT",
            "CHAR",
            "NULLIF",
            "GREATEST",
            "LEAST",
            "RANDOM",
            "POSITION",
        ];
        let is_aggregate = AGGREGATE_NAMES.contains(&name.as_str());
        let is_scalar = SCALAR_NAMES.contains(&name.as_str());
        if !is_aggregate && !is_scalar {
            return Err(QueryError::syntax(
                &self.source,
                format!(
                    "Unsupported scalar function {}.",
                    python_repr(&name_token.text)
                ),
                name_token.position,
                None,
                "invalid",
            ));
        }
        self.expect(TOKEN_LPAREN, "Expected '(' after function name.")?;
        if is_aggregate {
            let mut count_star = false;
            let mut args: Vec<Expr> = Vec::new();
            if name == "COUNT" && self.current().kind == TOKEN_STAR {
                self.advance();
                count_star = true;
            } else if self.current().kind != TOKEN_RPAREN {
                let first_arg = self.parse_scalar_expression()?;
                if name == "COUNT" && self.consume_keyword("AS").is_some() {
                    let binding_token = self.expect_identifier(
                        "Expected an element binding name after AS in collection COUNT.",
                    )?;
                    if binding_token.text.contains('.') {
                        return Err(QueryError::syntax(
                            &self.source,
                            "Collection element bindings must be simple identifiers.",
                            binding_token.position,
                            None,
                            "invalid",
                        ));
                    }
                    self.expect_keyword(
                        "WHERE",
                        Some("Expected WHERE after the collection COUNT element binding."),
                        "invalid",
                    )?;
                    self.collection_bindings.push(binding_token.text.clone());
                    let parsed = self.parse_or();
                    self.collection_bindings.pop();
                    let predicate = parsed?;
                    self.expect(
                        TOKEN_RPAREN,
                        "Expected ')' to close the collection COUNT expression.",
                    )?;
                    return Ok(Expr::CollectionCount(CollectionCount {
                        collection: Box::new(first_arg),
                        binding: binding_token.text,
                        predicate: Box::new(predicate),
                        position: name_token.position,
                        kind: None,
                        resolved_type: None,
                    }));
                }
                args.push(first_arg);
                if self.current().kind == TOKEN_COMMA {
                    return Err(QueryError::syntax(
                        &self.source,
                        format!("{name} requires exactly one argument."),
                        self.current().position,
                        None,
                        "invalid",
                    ));
                }
            }
            self.expect(TOKEN_RPAREN, "Expected ')' after aggregate arguments.")?;
            if name == "COUNT" {
                if !count_star && args.len() != 1 {
                    return Err(QueryError::syntax(
                        &self.source,
                        "COUNT requires * or exactly one argument.",
                        name_token.position,
                        None,
                        "invalid",
                    ));
                }
            } else if args.len() != 1 {
                return Err(QueryError::syntax(
                    &self.source,
                    format!("{name} requires exactly one argument."),
                    name_token.position,
                    None,
                    "invalid",
                ));
            }
            let mut filter_predicate = None;
            if self.consume_keyword("FILTER").is_some() {
                self.expect(TOKEN_LPAREN, "Expected '(' after FILTER.")?;
                self.expect_keyword(
                    "WHERE",
                    Some("Expected WHERE inside aggregate FILTER."),
                    "invalid",
                )?;
                let predicate = self.parse_or()?;
                self.expect(
                    TOKEN_RPAREN,
                    "Expected ')' after aggregate FILTER predicate.",
                )?;
                filter_predicate = Some(Box::new(predicate));
            }
            return Ok(Expr::Aggregate(AggregateFunction {
                name,
                args,
                count_star,
                filter_predicate,
                position: name_token.position,
                kind: None,
            }));
        }
        if name == "FILTER" {
            if self.current().kind == TOKEN_RPAREN {
                return Err(QueryError::syntax(
                    &self.source,
                    "FILTER requires a collection expression.",
                    name_token.position,
                    None,
                    "invalid",
                ));
            }
            let collection = self.parse_scalar_expression()?;
            self.expect_keyword(
                "AS",
                Some("Expected AS after the FILTER collection expression."),
                "invalid",
            )?;
            let binding_token =
                self.expect_identifier("Expected an element binding name after AS in FILTER.")?;
            if binding_token.text.contains('.') {
                return Err(QueryError::syntax(
                    &self.source,
                    "Collection element bindings must be simple identifiers.",
                    binding_token.position,
                    None,
                    "invalid",
                ));
            }
            self.expect_keyword(
                "WHERE",
                Some("Expected WHERE after the FILTER element binding."),
                "invalid",
            )?;
            self.collection_bindings.push(binding_token.text.clone());
            let parsed = self.parse_or();
            self.collection_bindings.pop();
            let predicate = parsed?;
            self.expect(TOKEN_RPAREN, "Expected ')' to close the FILTER expression.")?;
            return Ok(Expr::CollectionFilter(CollectionFilter {
                collection: Box::new(collection),
                binding: binding_token.text,
                predicate: Box::new(predicate),
                position: name_token.position,
                kind: None,
                resolved_type: None,
            }));
        }

        if name == "MAP" {
            if self.current().kind == TOKEN_RPAREN {
                return Err(QueryError::syntax(
                    &self.source,
                    "MAP requires a collection expression.",
                    name_token.position,
                    None,
                    "invalid",
                ));
            }
            let collection = self.parse_scalar_expression()?;
            self.expect_keyword(
                "AS",
                Some("Expected AS after the MAP collection expression."),
                "invalid",
            )?;
            let binding_token =
                self.expect_identifier("Expected an element binding name after AS in MAP.")?;
            if binding_token.text.contains('.') {
                return Err(QueryError::syntax(
                    &self.source,
                    "Collection element bindings must be simple identifiers.",
                    binding_token.position,
                    None,
                    "invalid",
                ));
            }
            self.expect_keyword(
                "SELECT",
                Some("Expected SELECT after the MAP element binding."),
                "invalid",
            )?;
            self.collection_bindings.push(binding_token.text.clone());
            let parsed = self.parse_scalar_expression();
            self.collection_bindings.pop();
            let projection = parsed?;
            self.expect(TOKEN_RPAREN, "Expected ')' to close the MAP expression.")?;
            return Ok(Expr::CollectionProjection(CollectionProjection {
                collection: Box::new(collection),
                binding: binding_token.text,
                projection: Box::new(projection),
                position: name_token.position,
                kind: None,
                resolved_type: None,
                evaluation_fusion_safe: false,
            }));
        }

        let mut args: Vec<Expr> = Vec::new();
        if self.current().kind != TOKEN_RPAREN {
            loop {
                args.push(self.parse_scalar_expression()?);
                if self.current().kind != TOKEN_COMMA {
                    break;
                }
                self.advance();
            }
        }
        self.expect(TOKEN_RPAREN, "Expected ')' after function arguments.")?;
        if matches!(name.as_str(), "LOWER" | "UPPER" | "LENGTH" | "CARDINALITY") && args.len() != 1
        {
            return Err(QueryError::syntax(
                &self.source,
                format!("{name} requires exactly one argument."),
                name_token.position,
                None,
                "invalid",
            ));
        }
        if name == "COALESCE" && args.len() < 2 {
            return Err(QueryError::syntax(
                &self.source,
                "COALESCE requires at least two arguments.",
                name_token.position,
                None,
                "invalid",
            ));
        }
        if name == "CONCAT" && args.len() < 2 {
            return Err(QueryError::syntax(
                &self.source,
                "CONCAT requires at least two arguments.",
                name_token.position,
                None,
                "invalid",
            ));
        }
        if name == "CHAR" && args.is_empty() {
            return Err(QueryError::syntax(
                &self.source,
                "CHAR requires at least one argument.",
                name_token.position,
                None,
                "invalid",
            ));
        }
        if name == "NULLIF" && args.len() != 2 {
            return Err(QueryError::syntax(
                &self.source,
                "NULLIF requires exactly two arguments.",
                name_token.position,
                None,
                "invalid",
            ));
        }
        if matches!(name.as_str(), "GREATEST" | "LEAST") && args.len() < 2 {
            return Err(QueryError::syntax(
                &self.source,
                format!("{name} requires at least two arguments."),
                name_token.position,
                None,
                "invalid",
            ));
        }
        if name == "POSITION" && !args.is_empty() {
            return Err(QueryError::syntax(
                &self.source,
                "POSITION requires no arguments.",
                name_token.position,
                None,
                "invalid",
            ));
        }
        if name == "RANDOM" && args.len() > 1 {
            return Err(QueryError::syntax(
                &self.source,
                "RANDOM accepts zero or one seed argument.",
                name_token.position,
                None,
                "invalid",
            ));
        }
        Ok(Expr::Function(ScalarFunction {
            name,
            args,
            position: name_token.position,
            kind: None,
            resolved_type: None,
        }))
    }

    /// Parse a window function call together with its mandatory OVER specification.
    ///
    /// The window specification is part of the window-function production, so a
    /// call without OVER is a syntax error rather than a semantic placement
    /// diagnostic. Future window functions join `WINDOW_FUNCTION_NAMES` and
    /// reuse this method unchanged.
    fn parse_window_function(&mut self, name_token: Token) -> Result<Expr, QueryError> {
        let name = name_token.text.to_uppercase();
        self.expect(TOKEN_LPAREN, &format!("Expected '(' after {}.", name))?;
        if self.current().kind != TOKEN_RPAREN {
            return Err(QueryError::syntax(
                &self.source,
                format!("{} requires no arguments.", name),
                self.current().position,
                None,
                "invalid",
            ));
        }
        self.expect(
            TOKEN_RPAREN,
            &format!("Expected ')' after the {} argument list.", name),
        )?;
        let over_token = match self.consume_keyword("OVER") {
            Some(token) => token,
            None => {
                return Err(QueryError::syntax(
                    &self.source,
                    format!("{} requires an OVER window specification.", name),
                    self.current().position,
                    None,
                    "missing-window-specification",
                ));
            }
        };
        let specification = self.parse_window_specification(over_token.position)?;
        Ok(Expr::Window(WindowFunction {
            name,
            specification,
            position: name_token.position,
            kind: None,
            resolved_type: None,
        }))
    }

    /// Parse `OVER ( [PARTITION BY ...] [ORDER BY ...] )`.
    ///
    /// An empty or partition-only specification parses because future window
    /// functions give those forms meaning; whether the calling window function
    /// accepts them is decided during semantic resolution.
    fn parse_window_specification(
        &mut self,
        over_position: usize,
    ) -> Result<WindowSpecification, QueryError> {
        self.expect(
            TOKEN_LPAREN,
            "Expected '(' to open the window specification.",
        )?;
        let mut partition_by: Vec<Expr> = Vec::new();
        let mut order_by: Vec<OrderTerm> = Vec::new();
        if self.consume_keyword("PARTITION").is_some() {
            self.expect_keyword(
                "BY",
                Some("Expected BY after PARTITION in the window specification."),
                "invalid",
            )?;
            loop {
                partition_by.push(self.parse_scalar_expression()?);
                if self.current().kind != TOKEN_COMMA {
                    break;
                }
                self.advance();
            }
        }
        if self.consume_keyword("ORDER").is_some() {
            self.expect_keyword(
                "BY",
                Some("Expected BY after ORDER in the window specification."),
                "invalid",
            )?;
            order_by = self.parse_order_by()?;
        }
        self.expect(
            TOKEN_RPAREN,
            "Expected ')' to close the window specification.",
        )?;
        Ok(WindowSpecification {
            partition_by,
            order_by,
            position: over_position,
            kind: None,
        })
    }

    // -----------------------------------------------------------------------
    // Relations and joins
    // -----------------------------------------------------------------------

    /// Parse one physical or logical relation source token.
    fn parse_from_source(&mut self) -> Result<String, QueryError> {
        let token = self.current();
        if token.kind == TOKEN_ATIDENT || token.kind == TOKEN_IDENT {
            self.advance();
            return Ok(token.text.clone());
        }
        if token.kind == TOKEN_QIDENT || token.kind == TOKEN_STRING {
            self.advance();
            return Ok(token.value.clone().unwrap_or_default());
        }
        Err(QueryError::syntax(
            &self.source,
            "Expected a channel/playlist identifier after FROM or JOIN. Quote full URLs.",
            token.position,
            None,
            "missing-source",
        ))
    }

    /// Parse one source with one or more logical facets and an optional alias.
    ///
    /// Multiple `OF` facets are syntactic sugar for UNION ALL branches. Keeping
    /// each returned relation single-facet preserves the established logical
    /// source, cache and provenance identity model below the parser.
    fn parse_relation_references(&mut self) -> Result<Vec<RelationReference>, QueryError> {
        let position = self.current().position;
        let mut derived: Option<DerivedRelation> = None;
        let source: Option<String>;
        if self.current().kind == TOKEN_LPAREN {
            self.advance();
            let current = self.current();
            if current.kind == TOKEN_RPAREN {
                return Err(QueryError::syntax(
                    &self.source,
                    "Derived relation query cannot be empty.",
                    current.position,
                    None,
                    "empty-query",
                ));
            }
            let query = self.parse_query_mode(false, true, false, false)?;
            self.expect(TOKEN_RPAREN, "Expected ')' after derived relation query.")?;
            derived = Some(DerivedRelation {
                query: Box::new(query),
                position,
            });
            source = None;
        } else {
            source = Some(self.parse_from_source()?);
        }
        let mut facets: Vec<(Option<String>, usize)> = vec![(None, position)];
        if self.consume_keyword("OF").is_some() {
            if derived.is_some() {
                return Err(QueryError::syntax(
                    &self.source,
                    "OF applies only to physical source relations, not derived relations.",
                    self.token_before().position,
                    None,
                    "invalid",
                ));
            }
            facets = Vec::new();
            loop {
                let facet_token = self.current();
                if facet_token.kind != TOKEN_IDENT && facet_token.kind != TOKEN_QIDENT {
                    return Err(QueryError::syntax(
                        &self.source,
                        "OF requires a collection/facet name.",
                        facet_token.position,
                        None,
                        "missing-facet",
                    ));
                }
                let facet = if facet_token.kind == TOKEN_QIDENT {
                    facet_token.value.clone().unwrap_or_default()
                } else {
                    facet_token.text.clone()
                }
                .to_lowercase();
                if facets
                    .iter()
                    .any(|(existing, _)| existing.as_deref() == Some(facet.as_str()))
                {
                    return Err(QueryError::syntax(
                        &self.source,
                        format!("Duplicate facet {} in OF list.", python_repr(&facet)),
                        facet_token.position,
                        None,
                        "invalid",
                    ));
                }
                facets.push((Some(facet), facet_token.position));
                self.advance();
                if self.current().kind != TOKEN_COMMA {
                    break;
                }
                self.advance();
            }
        }

        let mut alias = None;
        if self.consume_keyword("AS").is_some() {
            let alias_token = self.expect_identifier("Expected a relation alias after AS.")?;
            alias = Some(alias_token.text);
        }
        Ok(facets
            .into_iter()
            .enumerate()
            .map(|(index, (facet, facet_position))| RelationReference {
                source: source.clone(),
                facet,
                alias: alias.clone(),
                position: if index == 0 { position } else { facet_position },
                derived: derived.clone(),
            })
            .collect())
    }

    /// Parse one source/facet relation where multi-facet composition is not valid.
    fn parse_relation_reference(&mut self) -> Result<RelationReference, QueryError> {
        let mut relations = self.parse_relation_references()?;
        if relations.len() == 1 {
            return Ok(relations.remove(0));
        }
        if relations.len() > 1 {
            return Err(QueryError::syntax(
                &self.source,
                "Multiple OF facets are supported only for the primary FROM relation.",
                relations[1].position,
                None,
                "invalid",
            ));
        }
        // Unreachable: `parse_relation_references` always returns at least one
        // relation. Defensive only.
        Err(QueryError::syntax(
            &self.source,
            "Expected a channel/playlist identifier after FROM or JOIN. Quote full URLs.",
            self.current().position,
            None,
            "missing-source",
        ))
    }

    fn join_starts_here(&self) -> bool {
        [
            "JOIN", "INNER", "LEFT", "SEMI", "ANTI", "RIGHT", "FULL", "CROSS", "NATURAL",
        ]
        .iter()
        .any(|word| self.keyword(word))
    }

    /// Parse one supported JOIN form without assigning executable semantics.
    fn parse_join_clause(&mut self) -> Result<JoinClause, QueryError> {
        let position = self.current().position;
        for word in ["RIGHT", "FULL", "CROSS", "NATURAL"] {
            if self.consume_keyword(word).is_some() {
                return Err(QueryError::syntax(
                    &self.source,
                    "RIGHT, FULL, CROSS and NATURAL JOIN are not supported.",
                    position,
                    None,
                    "invalid",
                ));
            }
        }

        let mut kind = JoinKind::Inner;
        if self.consume_keyword("INNER").is_some() {
            kind = JoinKind::Inner;
        } else if self.consume_keyword("LEFT").is_some() {
            kind = JoinKind::Left;
            self.consume_keyword("OUTER");
        } else if self.consume_keyword("SEMI").is_some() {
            kind = JoinKind::Semi;
        } else if self.consume_keyword("ANTI").is_some() {
            kind = JoinKind::Anti;
        }
        self.expect_keyword("JOIN", Some("Expected JOIN after join kind."), "invalid")?;

        let relation = self.parse_relation_reference()?;
        self.expect_keyword(
            "ON",
            Some("JOIN requires an ON predicate."),
            "missing-join-on",
        )?;
        let current = self.current();
        if current.kind == TOKEN_EOF
            || current.kind == TOKEN_RPAREN
            || self.join_starts_here()
            || [
                "WHERE", "GROUP", "HAVING", "UNION", "ORDER", "LIMIT", "OFFSET",
            ]
            .iter()
            .any(|word| self.keyword(word))
        {
            return Err(QueryError::syntax(
                &self.source,
                "JOIN ON requires an expression.",
                current.position,
                None,
                "invalid",
            ));
        }
        let predicate = self.parse_having_or()?;
        Ok(JoinClause {
            kind,
            relation,
            predicate: Box::new(predicate),
            position,
        })
    }

    /// Parse the deterministic scalar expressions that define aggregate groups.
    fn parse_group_by(&mut self) -> Result<Vec<Expr>, QueryError> {
        let mut terms: Vec<Expr> = Vec::new();
        loop {
            terms.push(self.parse_scalar_expression()?);
            if self.current().kind != TOKEN_COMMA {
                break;
            }
            self.advance();
        }
        if terms.is_empty() {
            return Err(QueryError::syntax(
                &self.source,
                "GROUP BY requires at least one expression.",
                self.current().position,
                None,
                "invalid",
            ));
        }
        Ok(terms)
    }

    // -----------------------------------------------------------------------
    // HAVING grammar
    // -----------------------------------------------------------------------

    fn parse_having_or(&mut self) -> Result<BoolExpr, QueryError> {
        let mut node = self.parse_having_and()?;
        while self.consume_keyword("OR").is_some() {
            let right = self.parse_having_and()?;
            node = BoolExpr::Binary(Binary {
                operator: "OR".to_string(),
                left: Box::new(node),
                right: Box::new(right),
            });
        }
        Ok(node)
    }

    fn parse_having_and(&mut self) -> Result<BoolExpr, QueryError> {
        let mut node = self.parse_having_not()?;
        while self.consume_keyword("AND").is_some() {
            let right = self.parse_having_not()?;
            node = BoolExpr::Binary(Binary {
                operator: "AND".to_string(),
                left: Box::new(node),
                right: Box::new(right),
            });
        }
        Ok(node)
    }

    fn parse_having_truth_test_suffix(&mut self, node: BoolExpr) -> Result<BoolExpr, QueryError> {
        if self.consume_keyword("IS").is_none() {
            return Ok(node);
        }
        let negated = self.consume_keyword("NOT").is_some();
        for truth in ["TRUE", "FALSE", "UNKNOWN"] {
            if self.consume_keyword(truth).is_some() {
                return Ok(BoolExpr::TruthTest(TruthTest {
                    operand: Box::new(node),
                    truth: truth.to_string(),
                    negated,
                }));
            }
        }
        self.index -= if negated { 2 } else { 1 };
        Ok(node)
    }

    fn parse_having_not(&mut self) -> Result<BoolExpr, QueryError> {
        if self.consume_keyword("NOT").is_some() {
            let operand = self.parse_having_not()?;
            return Ok(BoolExpr::Unary(Unary {
                operator: "NOT".to_string(),
                operand: Box::new(operand),
            }));
        }
        if self.current().kind == TOKEN_LPAREN {
            // A leading parenthesis can wrap either a scalar expression on the
            // left of a comparison or a Boolean HAVING subtree. Try the scalar
            // interpretation first, then restore the parser position and fall
            // back to Boolean grouping if the comparison form does not parse.
            let start = self.index;
            match self.parse_having_predicate() {
                Ok(node) => return Ok(node),
                Err(_) => self.index = start,
            }
            self.advance();
            let node = self.parse_having_or()?;
            self.expect(TOKEN_RPAREN, "Expected ')' to close HAVING expression.")?;
            return self.parse_having_truth_test_suffix(node);
        }
        let node = self.parse_having_predicate()?;
        self.parse_having_truth_test_suffix(node)
    }

    /// Parse aggregate-aware HAVING comparisons without changing WHERE grammar.
    fn parse_having_predicate(&mut self) -> Result<BoolExpr, QueryError> {
        let left = self.parse_scalar_expression()?;
        if self.consume_keyword("IS").is_some() {
            let negated = self.consume_keyword("NOT").is_some();
            if self.consume_keyword("DISTINCT").is_some() {
                self.expect_keyword(
                    "FROM",
                    Some("Expected FROM after IS DISTINCT in HAVING."),
                    "invalid",
                )?;
                let operator = if negated {
                    "IS NOT DISTINCT FROM"
                } else {
                    "IS DISTINCT FROM"
                };
                let right = self.parse_scalar_expression()?;
                return Ok(BoolExpr::ScalarComparison(ScalarComparison {
                    operator: operator.to_string(),
                    left: Box::new(left),
                    right: Box::new(right),
                }));
            }
            if self.consume_keyword("NULL").is_some() {
                return Ok(BoolExpr::ScalarIsNull(ScalarIsNull {
                    expression: Box::new(left),
                    negated,
                }));
            }
            for truth in ["TRUE", "FALSE", "UNKNOWN"] {
                if self.consume_keyword(truth).is_some() {
                    return Ok(BoolExpr::TruthTest(TruthTest {
                        operand: Box::new(scalar_as_boolean(left)),
                        truth: truth.to_string(),
                        negated,
                    }));
                }
            }
            let current = self.current();
            return Err(QueryError::syntax(
                &self.source,
                "Expected NULL, TRUE, FALSE, UNKNOWN, or DISTINCT FROM after IS in HAVING.",
                current.position,
                None,
                "invalid",
            ));
        }
        if self.current().kind != TOKEN_OP {
            let current = self.current();
            return Err(QueryError::syntax(
                &self.source,
                "HAVING requires a comparison operator or IS NULL.",
                current.position,
                None,
                "invalid",
            ));
        }
        let operator_token = self.advance();
        let operator = normalise_comparison_operator(&operator_token.text);
        let right = self.parse_scalar_expression()?;
        Ok(BoolExpr::ScalarComparison(ScalarComparison {
            operator,
            left: Box::new(left),
            right: Box::new(right),
        }))
    }

    fn parse_order_by(&mut self) -> Result<Vec<OrderTerm>, QueryError> {
        let mut terms: Vec<OrderTerm> = Vec::new();
        loop {
            let position = self.current().position;
            let expression = self.parse_scalar_expression()?;
            let mut descending = false;
            if self.consume_keyword("ASC").is_some() {
                descending = false;
            } else if self.consume_keyword("DESC").is_some() {
                descending = true;
            }
            terms.push(OrderTerm {
                field: format_scalar_expression(&expression),
                descending,
                position,
                kind: None,
                expression: Some(Box::new(expression)),
            });
            if self.current().kind != TOKEN_COMMA {
                break;
            }
            self.advance();
        }
        Ok(terms)
    }

    // -----------------------------------------------------------------------
    // WHERE grammar
    // -----------------------------------------------------------------------

    fn parse_or(&mut self) -> Result<BoolExpr, QueryError> {
        let mut node = self.parse_and()?;
        while self.consume_keyword("OR").is_some() {
            let right = self.parse_and()?;
            node = BoolExpr::Binary(Binary {
                operator: "OR".to_string(),
                left: Box::new(node),
                right: Box::new(right),
            });
        }
        Ok(node)
    }

    fn parse_and(&mut self) -> Result<BoolExpr, QueryError> {
        let mut node = self.parse_not()?;
        while self.consume_keyword("AND").is_some() {
            let right = self.parse_not()?;
            node = BoolExpr::Binary(Binary {
                operator: "AND".to_string(),
                left: Box::new(node),
                right: Box::new(right),
            });
        }
        Ok(node)
    }

    fn parse_not(&mut self) -> Result<BoolExpr, QueryError> {
        if self.consume_keyword("NOT").is_some() {
            let operand = self.parse_not()?;
            return Ok(BoolExpr::Unary(Unary {
                operator: "NOT".to_string(),
                operand: Box::new(operand),
            }));
        }
        self.parse_primary()
    }

    /// Parse `ANY/ALL(collection AS binding WHERE predicate)` syntax.
    fn parse_collection_predicate(&mut self) -> Result<BoolExpr, QueryError> {
        let quantifier_token = self.advance();
        let quantifier = quantifier_token.text.to_uppercase();
        self.expect(TOKEN_LPAREN, &format!("Expected '(' after {quantifier}."))?;
        let collection = self.parse_scalar_expression()?;
        self.expect_keyword(
            "AS",
            Some(&format!(
                "Expected AS to name the {quantifier} element binding."
            )),
            "invalid",
        )?;
        let binding_token = self.expect_identifier(&format!(
            "Expected an element binding name after AS in {quantifier}."
        ))?;
        if binding_token.text.contains('.') {
            return Err(QueryError::syntax(
                &self.source,
                "Collection element bindings must be simple identifiers.",
                binding_token.position,
                None,
                "invalid",
            ));
        }
        self.expect_keyword(
            "WHERE",
            Some(&format!(
                "Expected WHERE after the {quantifier} element binding."
            )),
            "invalid",
        )?;
        self.collection_bindings.push(binding_token.text.clone());
        let parsed = self.parse_or();
        self.collection_bindings.pop();
        let predicate = parsed?;
        self.expect(
            TOKEN_RPAREN,
            &format!("Expected ')' to close the {quantifier} collection predicate."),
        )?;
        Ok(BoolExpr::CollectionPredicate(CollectionPredicate {
            quantifier,
            collection: Box::new(collection),
            binding: binding_token.text,
            predicate: Box::new(predicate),
            position: quantifier_token.position,
        }))
    }

    fn parse_truth_test_suffix(&mut self, node: BoolExpr) -> Result<BoolExpr, QueryError> {
        if self.consume_keyword("IS").is_none() {
            return Ok(node);
        }
        let negated = self.consume_keyword("NOT").is_some();
        for truth in ["TRUE", "FALSE", "UNKNOWN"] {
            if self.consume_keyword(truth).is_some() {
                return Ok(BoolExpr::TruthTest(TruthTest {
                    operand: Box::new(node),
                    truth: truth.to_string(),
                    negated,
                }));
            }
        }
        self.index -= if negated { 2 } else { 1 };
        Ok(node)
    }

    fn parse_primary(&mut self) -> Result<BoolExpr, QueryError> {
        let current = self.current();
        if current.kind == TOKEN_IDENT
            && matches!(current.text.to_uppercase().as_str(), "ANY" | "ALL")
            && self.token_at(1).kind == TOKEN_LPAREN
        {
            let predicate = self.parse_collection_predicate()?;
            return self.parse_truth_test_suffix(predicate);
        }
        if current.kind == TOKEN_LPAREN {
            // A parenthesised scalar expression may itself be the left operand of a
            // comparison, including postfix indexing. Try that form before treating
            // the parentheses as Boolean grouping.
            let start = self.index;
            match self.parse_predicate() {
                Ok(node) => return Ok(node),
                Err(_) => self.index = start,
            }
            self.advance();
            let node = self.parse_or()?;
            self.expect(TOKEN_RPAREN, "Expected ')' to close the expression.")?;
            return self.parse_truth_test_suffix(node);
        }
        let node = self.parse_predicate()?;
        self.parse_truth_test_suffix(node)
    }

    fn parse_predicate(&mut self) -> Result<BoolExpr, QueryError> {
        // Preserve the established malformed-predicate diagnostic when no left
        // operand is present.
        let current = self.current();
        if current.kind == TOKEN_EOF || current.kind == TOKEN_RPAREN {
            return Err(QueryError::syntax(
                &self.source,
                "Expected a field name.",
                current.position,
                None,
                "invalid",
            ));
        }

        let left = self.parse_scalar_expression()?;
        match left {
            Expr::Field(field) => self.parse_field_predicate(field),
            other => self.parse_scalar_predicate(other),
        }
    }

    /// Predicate continuation for a non-field scalar left operand.
    fn parse_scalar_predicate(&mut self, left: Expr) -> Result<BoolExpr, QueryError> {
        if self.consume_keyword("IS").is_some() {
            let negated = self.consume_keyword("NOT").is_some();
            if self.consume_keyword("DISTINCT").is_some() {
                self.expect_keyword("FROM", Some("Expected FROM after IS DISTINCT."), "invalid")?;
                let operator = if negated {
                    "IS NOT DISTINCT FROM"
                } else {
                    "IS DISTINCT FROM"
                };
                let right = self.parse_scalar_expression()?;
                return Ok(BoolExpr::ScalarComparison(ScalarComparison {
                    operator: operator.to_string(),
                    left: Box::new(left),
                    right: Box::new(right),
                }));
            }
            if self.consume_keyword("NULL").is_some() {
                return Ok(BoolExpr::ScalarIsNull(ScalarIsNull {
                    expression: Box::new(left),
                    negated,
                }));
            }
            for truth in ["TRUE", "FALSE", "UNKNOWN"] {
                if self.consume_keyword(truth).is_some() {
                    return Ok(BoolExpr::TruthTest(TruthTest {
                        operand: Box::new(scalar_as_boolean(left)),
                        truth: truth.to_string(),
                        negated,
                    }));
                }
            }
            let current = self.current();
            return Err(QueryError::syntax(
                &self.source,
                "Expected NULL, TRUE, FALSE, UNKNOWN, or DISTINCT FROM after IS.",
                current.position,
                None,
                "invalid",
            ));
        }
        if self.current().kind == TOKEN_OP {
            let operator_token = self.advance();
            let operator = normalise_comparison_operator(&operator_token.text);
            let right = self.parse_scalar_expression()?;
            return Ok(BoolExpr::ScalarComparison(ScalarComparison {
                operator,
                left: Box::new(left),
                right: Box::new(right),
            }));
        }
        let current = self.current();
        Err(QueryError::syntax(
            &self.source,
            "Scalar WHERE expressions must be followed by a comparison operator or IS NULL.",
            current.position,
            None,
            "invalid",
        ))
    }

    fn parse_field_predicate(&mut self, field: Field) -> Result<BoolExpr, QueryError> {
        let mut negated = self.consume_keyword("NOT").is_some();

        if self.consume_keyword("BETWEEN").is_some() {
            let lower = self.parse_literal(Some(&["AND"]), None)?;
            self.expect_keyword(
                "AND",
                Some("Expected AND after the lower bound of BETWEEN."),
                "invalid",
            )?;
            let upper = self.parse_literal(None, None)?;
            return Ok(BoolExpr::Between(Between {
                field,
                lower,
                upper,
                negated,
            }));
        }

        if self.consume_keyword("IN").is_some() {
            self.expect(TOKEN_LPAREN, "Expected '(' after IN.")?;
            let current = self.current();
            if current.kind == TOKEN_RPAREN {
                return Err(QueryError::syntax(
                    &self.source,
                    "IN requires at least one value.",
                    current.position,
                    None,
                    "invalid",
                ));
            }
            let mut values: Vec<Literal> = Vec::new();
            loop {
                values.push(self.parse_literal(Some(&[]), Some(&[TOKEN_COMMA, TOKEN_RPAREN]))?);
                if self.current().kind != TOKEN_COMMA {
                    break;
                }
                self.advance();
            }
            self.expect(TOKEN_RPAREN, "Expected ')' after IN values.")?;
            return Ok(BoolExpr::InList(InList {
                field,
                values,
                negated,
            }));
        }

        if self.consume_keyword("IS").is_some() {
            if self.consume_keyword("NOT").is_some() {
                negated = !negated;
            }
            if self.consume_keyword("DISTINCT").is_some() {
                self.expect_keyword("FROM", Some("Expected FROM after IS DISTINCT."), "invalid")?;
                let operator = if negated {
                    "IS NOT DISTINCT FROM"
                } else {
                    "IS DISTINCT FROM"
                };
                let right = self.parse_scalar_expression()?;
                return Ok(BoolExpr::ScalarComparison(ScalarComparison {
                    operator: operator.to_string(),
                    left: Box::new(Expr::Field(field)),
                    right: Box::new(right),
                }));
            }
            if self.consume_keyword("NULL").is_some() {
                return Ok(BoolExpr::IsNull(IsNull { field, negated }));
            }
            if self.consume_keyword("TRUE").is_some() {
                return Ok(truth_test_on_boolean_field(&field, "TRUE", negated));
            }
            if self.consume_keyword("FALSE").is_some() {
                return Ok(truth_test_on_boolean_field(&field, "FALSE", negated));
            }
            if self.consume_keyword("UNKNOWN").is_some() {
                return Ok(truth_test_on_boolean_field(&field, "UNKNOWN", negated));
            }
            let current = self.current();
            return Err(QueryError::syntax(
                &self.source,
                "Expected NULL, TRUE, FALSE, UNKNOWN, or DISTINCT FROM after IS.",
                current.position,
                None,
                "invalid",
            ));
        }

        if self.consume_keyword("DOES").is_some() {
            self.expect_keyword("NOT", Some("Expected NOT after DOES."), "invalid")?;
            if self.consume_keyword("CONTAIN").is_some()
                || self.consume_keyword("CONTAINS").is_some()
            {
                let value = self.parse_text_literal()?;
                return Ok(BoolExpr::TextPredicate(TextPredicate {
                    operator: "CONTAINS".to_string(),
                    field,
                    value,
                    negated: true,
                }));
            }
            if self.consume_keyword("MATCH").is_some() || self.consume_keyword("MATCHES").is_some()
            {
                let value = self.parse_regex_literal()?;
                return Ok(BoolExpr::TextPredicate(TextPredicate {
                    operator: "MATCHES".to_string(),
                    field,
                    value,
                    negated: true,
                }));
            }
            if self.consume_keyword("ILIKE").is_some() {
                let value = self.parse_like_literal()?;
                return Ok(BoolExpr::TextPredicate(TextPredicate {
                    operator: "ILIKE".to_string(),
                    field,
                    value,
                    negated: true,
                }));
            }
            if self.consume_keyword("LIKE").is_some() {
                let value = self.parse_like_literal()?;
                return Ok(BoolExpr::TextPredicate(TextPredicate {
                    operator: "LIKE".to_string(),
                    field,
                    value,
                    negated: true,
                }));
            }
            let current = self.current();
            return Err(QueryError::syntax(
                &self.source,
                "Expected CONTAIN, MATCH, LIKE, or ILIKE after DOES NOT.",
                current.position,
                None,
                "invalid",
            ));
        }

        if self.consume_keyword("CONTAINS").is_some() || self.consume_keyword("CONTAIN").is_some() {
            let value = self.parse_text_literal()?;
            return Ok(BoolExpr::TextPredicate(TextPredicate {
                operator: "CONTAINS".to_string(),
                field,
                value,
                negated,
            }));
        }
        if self.consume_keyword("MATCHES").is_some() || self.consume_keyword("MATCH").is_some() {
            let value = self.parse_regex_literal()?;
            return Ok(BoolExpr::TextPredicate(TextPredicate {
                operator: "MATCHES".to_string(),
                field,
                value,
                negated,
            }));
        }
        if self.consume_keyword("ILIKE").is_some() {
            let value = self.parse_like_literal()?;
            return Ok(BoolExpr::TextPredicate(TextPredicate {
                operator: "ILIKE".to_string(),
                field,
                value,
                negated,
            }));
        }
        if self.consume_keyword("LIKE").is_some() {
            let value = self.parse_like_literal()?;
            return Ok(BoolExpr::TextPredicate(TextPredicate {
                operator: "LIKE".to_string(),
                field,
                value,
                negated,
            }));
        }

        if negated {
            if self.at_expression_boundary() {
                return Ok(BoolExpr::Unary(Unary {
                    operator: "NOT".to_string(),
                    operand: Box::new(boolean_field_equality(&field)),
                }));
            }
            let current = self.current();
            return Err(QueryError::syntax(
                &self.source,
                "NOT must be followed by BETWEEN, IN, CONTAINS, MATCHES, LIKE, ILIKE, IS, or used with a Boolean field.",
                current.position,
                None,
                "invalid",
            ));
        }

        if let Some(operator) = self.parse_natural_operator()? {
            let literal = self.parse_literal(None, None)?;
            return Ok(BoolExpr::ScalarComparison(ScalarComparison {
                operator: operator.to_string(),
                left: Box::new(Expr::Field(field)),
                right: Box::new(Expr::Literal(literal)),
            }));
        }

        if self.current().kind == TOKEN_OP {
            let operator_token = self.advance();
            let operator = normalise_comparison_operator(&operator_token.text);
            let literal = self.parse_literal(None, None)?;
            return Ok(BoolExpr::ScalarComparison(ScalarComparison {
                operator,
                left: Box::new(Expr::Field(field)),
                right: Box::new(Expr::Literal(literal)),
            }));
        }

        if self.at_expression_boundary() {
            return Ok(boolean_field_equality(&field));
        }

        let current = self.current();
        Err(QueryError::syntax(
            &self.source,
            "Expected a comparison operator, BETWEEN, IN, IS NULL, CONTAINS, MATCHES, LIKE, or ILIKE.",
            current.position,
            None,
            "invalid",
        ))
    }

    fn parse_natural_operator(&mut self) -> Result<Option<&'static str>, QueryError> {
        const PHRASES: [(&[&str], &str); 11] = [
            (&["AT", "LEAST"], ">="),
            (&["AT", "MOST"], "<="),
            (&["GREATER", "THAN"], ">"),
            (&["MORE", "THAN"], ">"),
            (&["LESS", "THAN"], "<"),
            (&["EQUAL", "TO"], "="),
            (&["OVER"], ">"),
            (&["ABOVE"], ">"),
            (&["UNDER"], "<"),
            (&["BELOW"], "<"),
            (&["EQUALS"], "="),
        ];
        let start = self.index;
        for (words, operator) in PHRASES {
            self.index = start;
            let mut matched = true;
            for word in words {
                if self.consume_keyword(word).is_none() {
                    matched = false;
                    break;
                }
            }
            if matched {
                return Ok(Some(operator));
            }
        }
        self.index = start;
        Ok(None)
    }

    fn parse_text_literal(&mut self) -> Result<Literal, QueryError> {
        let token = self.current();
        if token.kind == TOKEN_STRING {
            self.advance();
            return Ok(Literal {
                value: LiteralValue::Text(token.value.clone().unwrap_or_default()),
                raw: token.text.clone(),
                position: token.position,
                quoted: true,
            });
        }
        if token.kind == TOKEN_IDENT
            || token.kind == TOKEN_NUMBER
            || token.kind == TOKEN_DATE
            || token.kind == TOKEN_DATETIME
            || token.kind == TOKEN_TIME
            || token.kind == TOKEN_TEMPORAL
        {
            self.advance();
            return Ok(Literal {
                value: LiteralValue::Text(token.text.clone()),
                raw: token.text.clone(),
                position: token.position,
                quoted: false,
            });
        }
        Err(QueryError::syntax(
            &self.source,
            "Expected a text value.",
            token.position,
            None,
            "invalid",
        ))
    }

    /// Parse a quoted SQL-like pattern without consuming LIKE escapes.
    fn parse_like_literal(&mut self) -> Result<Literal, QueryError> {
        let token = self.current();
        if token.kind != TOKEN_STRING {
            return Err(QueryError::syntax(
                &self.source,
                "LIKE requires a quoted text pattern.",
                token.position,
                None,
                "invalid",
            ));
        }
        self.advance();
        let raw = token.text.as_str();
        let quote = raw.chars().next().unwrap_or('\'');
        // A matched string literal always starts and ends with an ASCII quote.
        let body = &raw[1..raw.len().saturating_sub(1)];
        // Only collapse doubled SQL quote characters; backslashes belong to the
        // pattern language and are preserved verbatim.
        let mut value = String::new();
        let mut index = 0;
        while index < body.len() {
            let (character, length) = match body.get(index..).and_then(|rest| rest.chars().next()) {
                Some(character) => (character, character.len_utf8()),
                None => break,
            };
            if character == quote
                && let Some((next, next_length)) = body
                    .get(index + length..)
                    .and_then(|rest| rest.chars().next())
                    .map(|next| (next, next.len_utf8()))
                && next == quote
            {
                value.push(quote);
                index += length + next_length;
                continue;
            }
            value.push(character);
            index += length;
        }
        let literal = Literal {
            value: LiteralValue::Text(value.clone()),
            raw: token.text.clone(),
            position: token.position,
            quoted: true,
        };
        validate_like_pattern(&value, &self.source, token.position)?;
        Ok(literal)
    }

    fn parse_regex_literal(&mut self) -> Result<Literal, QueryError> {
        let literal = self.parse_text_literal()?;
        let pattern = literal_value_text(&literal);
        if let Err(error) = regex::Regex::new(&pattern) {
            return Err(QueryError::syntax(
                &self.source,
                format!("Invalid regular expression: {error}."),
                literal.position,
                None,
                "invalid",
            ));
        }
        Ok(literal)
    }

    /// Port of `parse_literal`, including the stop-keyword literal gluing that
    /// keeps clause-leading keywords out of glued values.
    fn parse_literal(
        &mut self,
        stop_keywords: Option<&[&str]>,
        stop_kinds: Option<&[&'static str]>,
    ) -> Result<Literal, QueryError> {
        let token = self.current();
        if token.kind == TOKEN_STRING {
            self.advance();
            return Ok(Literal {
                value: LiteralValue::Text(token.value.clone().unwrap_or_default()),
                raw: token.text.clone(),
                position: token.position,
                quoted: true,
            });
        }

        let keywords: &[&str] = stop_keywords.unwrap_or(&DEFAULT_STOP_KEYWORDS);
        let kinds: Vec<&'static str> = match stop_kinds {
            None => vec![TOKEN_RPAREN, TOKEN_COMMA, TOKEN_EOF],
            Some(kinds) => {
                let mut collected = kinds.to_vec();
                if !collected.contains(&TOKEN_EOF) {
                    collected.push(TOKEN_EOF);
                }
                collected
            }
        };

        let mut parts: Vec<Token> = Vec::new();
        loop {
            let current = self.current();
            if kinds.contains(&current.kind) {
                break;
            }
            if current.kind == TOKEN_IDENT
                && keywords.contains(&current.text.to_uppercase().as_str())
            {
                break;
            }
            if current.kind == TOKEN_LPAREN || current.kind == TOKEN_OP {
                break;
            }
            parts.push(self.advance());
        }
        if parts.is_empty() {
            return Err(QueryError::syntax(
                &self.source,
                "Expected a value.",
                token.position,
                None,
                "invalid",
            ));
        }

        let raw = if parts.len() == 1 {
            parts[0].text.clone()
        } else {
            parts
                .iter()
                .map(|part| part.text.as_str())
                .collect::<Vec<_>>()
                .join(" ")
        };
        let lowered = raw.to_lowercase();
        let position = parts[0].position;
        if lowered == "null" {
            return Ok(Literal {
                value: LiteralValue::Null,
                raw,
                position,
                quoted: false,
            });
        }
        if lowered == "true" {
            return Ok(Literal {
                value: LiteralValue::Bool(true),
                raw,
                position,
                quoted: false,
            });
        }
        if lowered == "false" {
            return Ok(Literal {
                value: LiteralValue::Bool(false),
                raw,
                position,
                quoted: false,
            });
        }
        Ok(Literal {
            value: LiteralValue::Text(raw.clone()),
            raw,
            position,
            quoted: false,
        })
    }

    fn at_expression_boundary(&self) -> bool {
        let current = self.current();
        if current.kind == TOKEN_EOF || current.kind == TOKEN_RPAREN {
            return true;
        }
        [
            "AND", "OR", "ORDER", "LIMIT", "OFFSET", "THEN", "WHEN", "ELSE", "END",
        ]
        .iter()
        .any(|word| self.keyword(word))
    }
}

/// Port of the module-level `parse_query` entry point.
pub fn parse_query(source: &str) -> Result<Query, QueryError> {
    Parser::new(source)?.parse_query()
}

/// Port of the module-level `parse_where` entry point; it mirrors
/// `Parser.parse_query(where_only=True)`.
pub fn parse_where(source: &str) -> Result<Query, QueryError> {
    Parser::new(source)?.parse_where()
}

/// Port of `_validate_like_pattern`.
pub fn validate_like_pattern(
    pattern: &str,
    source: &str,
    position: usize,
) -> Result<(), QueryError> {
    let mut escaped = false;
    for character in pattern.chars() {
        if escaped {
            escaped = false;
        } else if character == '\\' {
            escaped = true;
        }
    }
    if escaped {
        return Err(QueryError::syntax(
            source,
            "LIKE pattern ends with an incomplete backslash escape.",
            position,
            None,
            "invalid",
        ));
    }
    Ok(())
}
