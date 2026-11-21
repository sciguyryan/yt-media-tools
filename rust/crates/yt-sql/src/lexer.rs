//! Hand-written port of the yt-sql lexer (`query_parser.tokenise`).
//!
//! The Python reference tokenises with a single alternation-ordered regular
//! expression (`_TOKEN_RE`). This port reproduces every alternative in the
//! same order with the same greedy semantics — including the IDENT
//! post-processing pass (ASCII fast path, XID extension scan, MISMATCH
//! fallbacks) and the MISMATCH diagnostics (unterminated quoted identifier,
//! unterminated string literal with the trailing-backslash incomplete-escape
//! check, unexpected character).
//!
//! Deliberate deviations from the Python reference (they preserve the
//! conformance outcomes of the committed corpus while avoiding a Unicode
//! table dependency beyond `unicode-ident`):
//! * `\w` (word characters) is approximated with the Rust `Alphabetic` and
//!   `Numeric` properties plus `_`; Python additionally treats some
//!   `Other_ID_Start` symbols and certain `Nl` code points slightly
//!   differently at identifier boundaries. Affected inputs still fail in the
//!   same "MISMATCH → unexpected character" paths.
//! * `\d` is approximated with ASCII digits plus the `Numeric` property; a
//!   handful of `No` category code points therefore lex as number starts
//!   instead of single-character MISMATCH tokens. Both paths are lexical
//!   failures with identical conformance outcomes.
//! * `char::is_whitespace` (plus the C0 separators Python counts) stands in
//!   for Python's `\s`.

use crate::model::{
    QueryError, TOKEN_ATIDENT, TOKEN_COMMA, TOKEN_COMMENT, TOKEN_DATE, TOKEN_DATETIME, TOKEN_DOT,
    TOKEN_EOF, TOKEN_IDENT, TOKEN_INFINITY, TOKEN_LBRACKET, TOKEN_LITERAL_WORD, TOKEN_LPAREN,
    TOKEN_MINUS, TOKEN_MISMATCH, TOKEN_NUMBER, TOKEN_OP, TOKEN_PERCENT, TOKEN_PLUS, TOKEN_QIDENT,
    TOKEN_RBRACKET, TOKEN_RPAREN, TOKEN_SLASH, TOKEN_SPACE, TOKEN_STAR, TOKEN_STRING,
    TOKEN_TEMPORAL, TOKEN_TIME, Token,
};
use unicode_ident as xid;

/// Python `str.isspace()` / regular-expression `\s`.
pub(crate) fn is_python_space(character: char) -> bool {
    matches!(
        character,
        '\t' | '\n' | '\u{000B}' | '\u{000C}' | '\r' | '\u{001C}'..='\u{001F}' | '\u{0085}'
    ) || character.is_whitespace()
}

/// Python regular-expression `\d` (approximated; see module documentation).
pub(crate) fn is_python_digit(character: char) -> bool {
    character.is_ascii_digit() || character.is_numeric()
}

/// Python regular-expression `[^\W\d_]` (approximated; see module documentation).
pub(crate) fn is_python_alpha(character: char) -> bool {
    character.is_alphabetic()
}

/// Python regular-expression `\w` (approximated; see module documentation).
fn is_python_word(character: char) -> bool {
    character == '_' || is_python_digit(character) || is_python_alpha(character)
}

/// Python `character == "_" or character.isidentifier()`.
pub(crate) fn is_xid_start(character: char) -> bool {
    character == '_' || xid::is_xid_start(character)
}

/// Python `("A" + character).isidentifier()`.
pub(crate) fn is_xid_continue(character: char) -> bool {
    xid::is_xid_continue(character)
}

/// Return the character starting at `position`, with its UTF-8 length.
fn char_at(source: &str, position: usize) -> Option<(char, usize)> {
    let rest = source.get(position..)?;
    let character = rest.chars().next()?;
    Some((character, character.len_utf8()))
}

/// Length of the character starting at `position` (defensively one when the
/// position is not a character boundary).
fn char_len_at(source: &str, position: usize) -> usize {
    source
        .get(position..)
        .and_then(|rest| rest.chars().next())
        .map_or(1, |character| character.len_utf8())
}

fn skip_spaces(source: &str, mut index: usize) -> usize {
    while let Some((character, length)) = char_at(source, index) {
        if !is_python_space(character) {
            break;
        }
        index += length;
    }
    index
}

/// `-?INFINITY\(\)`
fn match_infinity(source: &str, position: usize) -> Option<usize> {
    let body = "INFINITY()";
    let rest = source.get(position..)?;
    if rest.starts_with(body) {
        return Some(position + body.len());
    }
    if let Some(without_sign) = rest.strip_prefix('-')
        && without_sign.starts_with(body)
    {
        return Some(position + 1 + body.len());
    }
    None
}

/// `<=|>=|!=|<>|=|<|>`
fn match_op(source: &str, position: usize) -> Option<usize> {
    let bytes = source.as_bytes();
    let first = *bytes.get(position)?;
    let second = bytes.get(position + 1).copied();
    match first {
        b'<' => match second {
            Some(b'=') | Some(b'>') => Some(position + 2),
            _ => Some(position + 1),
        },
        b'>' => Some(if second == Some(b'=') {
            position + 2
        } else {
            position + 1
        }),
        b'!' => {
            if second == Some(b'=') {
                Some(position + 2)
            } else {
                None
            }
        }
        b'=' => Some(position + 1),
        _ => None,
    }
}

/// `` `(?:``|[^`])*` ``
fn match_quoted_identifier(source: &str, position: usize) -> Option<usize> {
    let mut index = position + 1;
    while index < source.len() {
        let (character, length) = char_at(source, index)?;
        if character == '`' {
            if let Some((next, next_length)) = char_at(source, index + length)
                && next == '`'
            {
                index += length + next_length;
                continue;
            }
            return Some(index + length);
        }
        index += length;
    }
    None
}

/// `'(?:''|\\.|[^'\\])*'` and `"(?:""|\\.|[^"\\])*"`.
///
/// `\\.` cannot cross a newline (Python `.` excludes `\n`), so a backslash
/// directly before a newline makes the whole alternative fail; a bare newline
/// inside the body is consumed by the negated class.
fn match_string(source: &str, position: usize) -> Option<usize> {
    let (quote, _) = char_at(source, position)?;
    let mut index = position + 1;
    while index < source.len() {
        let (character, length) = char_at(source, index)?;
        if character == quote {
            if let Some((next, next_length)) = char_at(source, index + length)
                && next == quote
            {
                index += length + next_length;
                continue;
            }
            return Some(index + length);
        }
        if character == '\\' {
            match char_at(source, index + length) {
                Some((next, next_length)) if next != '\n' => {
                    index += length + next_length;
                    continue;
                }
                _ => return None,
            }
        }
        index += length;
    }
    None
}

/// `(?:TODAY|NOW)\(\)(?:\s*[+-]\s*\d+(?:\.\d+)?\s*[^\W\d_]+(?:-[^\W\d_]+)*)?`
///
/// The optional relative part is matched atomically: any failure falls back to
/// the bare `TODAY()`/`NOW()` match, exactly like the backtracking regex.
fn match_temporal(source: &str, position: usize) -> Option<usize> {
    let rest = source.get(position..)?;
    let after_base = if rest.starts_with("TODAY()") {
        position + "TODAY()".len()
    } else if rest.starts_with("NOW()") {
        position + "NOW()".len()
    } else {
        return None;
    };

    let mut index = skip_spaces(source, after_base);
    let Some((operator, operator_length)) = char_at(source, index) else {
        return Some(after_base);
    };
    if operator != '+' && operator != '-' {
        return Some(after_base);
    }
    index += operator_length;
    index = skip_spaces(source, index);

    let digits_start = index;
    while let Some((character, length)) = char_at(source, index) {
        if !is_python_digit(character) {
            break;
        }
        index += length;
    }
    if index == digits_start {
        return Some(after_base);
    }

    if let Some(('.', length)) = char_at(source, index) {
        let mut probe = index + length;
        let fraction_start = probe;
        while let Some((character, character_length)) = char_at(source, probe) {
            if !is_python_digit(character) {
                break;
            }
            probe += character_length;
        }
        if probe > fraction_start {
            index = probe;
        }
    }

    index = skip_spaces(source, index);
    let unit_start = index;
    while let Some((character, length)) = char_at(source, index) {
        if !is_python_alpha(character) {
            break;
        }
        index += length;
    }
    if index == unit_start {
        return Some(after_base);
    }
    while let Some((character, length)) = char_at(source, index) {
        if character != '-' {
            break;
        }
        let mut probe = index + length;
        let run_start = probe;
        while let Some((run, run_length)) = char_at(source, probe) {
            if !is_python_alpha(run) {
                break;
            }
            probe += run_length;
        }
        if probe == run_start {
            break;
        }
        index = probe;
    }
    Some(index)
}

/// Consume between `min` and `max` digits, backtracking greedily until
/// `accept` accepts the following character.
fn digits_before(
    source: &str,
    position: usize,
    min: usize,
    max: usize,
    accept: impl Fn(char) -> bool,
) -> Option<usize> {
    let mut ends: Vec<usize> = Vec::new();
    let mut index = position;
    let mut count = 0;
    while count < max {
        match char_at(source, index) {
            Some((character, length)) if is_python_digit(character) => {
                index += length;
                count += 1;
                ends.push(index);
            }
            _ => break,
        }
    }
    if count < min {
        return None;
    }
    for end in ends.iter().rev() {
        match char_at(source, *end) {
            Some((character, _)) if accept(character) => return Some(*end),
            _ => continue,
        }
    }
    None
}

/// Consume exactly `count` digits.
fn fixed_digits(source: &str, position: usize, count: usize) -> Option<usize> {
    let mut index = position;
    for _ in 0..count {
        let (character, length) = char_at(source, index)?;
        if !is_python_digit(character) {
            return None;
        }
        index += length;
    }
    Some(index)
}

/// Consume between one and `max` digits greedily.
fn digits_max(source: &str, position: usize, max: usize) -> Option<usize> {
    let mut index = position;
    let mut count = 0;
    while count < max {
        match char_at(source, index) {
            Some((character, length)) if is_python_digit(character) => {
                index += length;
                count += 1;
            }
            _ => break,
        }
    }
    if count == 0 { None } else { Some(index) }
}

/// `\d{4}-\d{1,2}-\d{1,2}T\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?`
fn match_datetime(source: &str, position: usize) -> Option<usize> {
    let is_dash = |character: char| character == '-';
    let mut index = fixed_digits(source, position, 4)?;
    let (character, length) = char_at(source, index)?;
    if !is_dash(character) {
        return None;
    }
    index += length;
    index = digits_before(source, index, 1, 2, is_dash)?;
    let (character, length) = char_at(source, index)?;
    if !is_dash(character) {
        return None;
    }
    index += length;
    index = digits_before(source, index, 1, 2, |character: char| character == 'T')?;
    let (character, length) = char_at(source, index)?;
    if character != 'T' {
        return None;
    }
    index += length;
    index = digits_before(source, index, 1, 2, |character: char| character == ':')?;
    let (character, length) = char_at(source, index)?;
    if character != ':' {
        return None;
    }
    index += length;
    index = fixed_digits(source, index, 2)?;

    // Optional `(?::\d{2}(?:\.\d+)?)?` seconds group.
    if char_at(source, index).map(|(character, _)| character) == Some(':')
        && let Some(after_seconds) = fixed_digits(source, index + 1, 2)
    {
        let mut probe = after_seconds;
        if char_at(source, probe).map(|(character, _)| character) == Some('.') {
            let fraction_start = probe + 1;
            let mut end = fraction_start;
            while let Some((character, length)) = char_at(source, end) {
                if !is_python_digit(character) {
                    break;
                }
                end += length;
            }
            if end > fraction_start {
                probe = end;
            }
        }
        index = probe;
    }

    // Optional `(?:Z|[+-]\d{2}:?\d{2})?` zone group.
    if let Some((character, length)) = char_at(source, index) {
        if character == 'Z' {
            index += length;
        } else if (character == '+' || character == '-')
            && let Some(after_hours) = fixed_digits(source, index + length, 2)
        {
            let mut probe = after_hours;
            if char_at(source, probe).map(|(character, _)| character) == Some(':') {
                probe += 1;
            }
            if let Some(after_minutes) = fixed_digits(source, probe, 2) {
                index = after_minutes;
            }
        }
    }
    Some(index)
}

/// `\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{4}`
fn match_date(source: &str, position: usize) -> Option<usize> {
    let is_separator = |character: char| character == '-' || character == '/' || character == '.';
    // Year-first branch.
    if let Some(after_year) = fixed_digits(source, position, 4)
        && let Some((separator, separator_length)) = char_at(source, after_year)
        && is_separator(separator)
        && let Some(after_month) =
            digits_before(source, after_year + separator_length, 1, 2, is_separator)
        && let Some((separator, separator_length)) = char_at(source, after_month)
        && is_separator(separator)
        && let Some(after_day) = digits_max(source, after_month + separator_length, 2)
    {
        return Some(after_day);
    }
    // Day-first branch.
    if let Some(after_day) = digits_before(source, position, 1, 2, is_separator)
        && let Some((separator, separator_length)) = char_at(source, after_day)
        && is_separator(separator)
        && let Some(after_month) =
            digits_before(source, after_day + separator_length, 1, 2, is_separator)
        && let Some((separator, separator_length)) = char_at(source, after_month)
        && is_separator(separator)
        && let Some(after_year) = fixed_digits(source, after_month + separator_length, 4)
    {
        return Some(after_year);
    }
    None
}

/// `\d{1,3}:\d{1,2}(?::\d{1,2})?(?:\.\d{1,3})?`
fn match_time(source: &str, position: usize) -> Option<usize> {
    let is_colon = |character: char| character == ':';
    let mut index = digits_before(source, position, 1, 3, is_colon)?;
    let (character, length) = char_at(source, index)?;
    if character != ':' {
        return None;
    }
    index += length;
    index = digits_max(source, index, 2)?;
    if char_at(source, index).map(|(character, _)| character) == Some(':')
        && let Some(after_seconds) = digits_max(source, index + 1, 2)
    {
        index = after_seconds;
    }
    if char_at(source, index).map(|(character, _)| character) == Some('.')
        && let Some(after_fraction) = digits_max(source, index + 1, 3)
    {
        index = after_fraction;
    }
    Some(index)
}

/// `(?i:TRUE|FALSE|NULL))(?![\w-])`
fn match_literal_word(source: &str, position: usize) -> Option<usize> {
    for word in ["TRUE", "FALSE", "NULL"] {
        let Some(slice) = source.get(position..position + word.len()) else {
            continue;
        };
        if !slice.eq_ignore_ascii_case(word) {
            continue;
        }
        let end = position + word.len();
        let lookahead_ok = match char_at(source, end) {
            None => true,
            Some((character, _)) => !is_python_word(character) && character != '-',
        };
        if lookahead_ok {
            return Some(end);
        }
    }
    None
}

/// `(?:0[xX][0-9A-Za-z_]*|0[oO][0-9A-Za-z_]*|0[bB][0-9A-Za-z_]*|\d[\d_]*(?:\.\d[\d_]*)?(?:[kKmMbB])?)`
fn match_number(source: &str, position: usize) -> Option<usize> {
    let rest = source.get(position..)?;
    for prefix in ["0x", "0X", "0o", "0O", "0b", "0B"] {
        if rest.starts_with(prefix) {
            let mut index = position + 2;
            while let Some((character, length)) = char_at(source, index) {
                if !(character.is_ascii_alphanumeric() || character == '_') {
                    break;
                }
                index += length;
            }
            return Some(index);
        }
    }
    let (first, first_length) = char_at(source, position)?;
    if !is_python_digit(first) {
        return None;
    }
    let mut index = position + first_length;
    while let Some((character, length)) = char_at(source, index) {
        if !(is_python_digit(character) || character == '_') {
            break;
        }
        index += length;
    }
    if let Some(('.', length)) = char_at(source, index)
        && let Some((next, next_length)) = char_at(source, index + length)
        && is_python_digit(next)
    {
        index += length + next_length;
        while let Some((character, run_length)) = char_at(source, index) {
            if !(is_python_digit(character) || character == '_') {
                break;
            }
            index += run_length;
        }
    }
    if let Some((character, length)) = char_at(source, index)
        && matches!(character, 'k' | 'K' | 'm' | 'M' | 'b' | 'B')
    {
        index += length;
    }
    Some(index)
}

/// `[^\W\d][\w-]*(?:\.[^\W\d][\w-]*)*`
fn match_ident_regex(source: &str, position: usize) -> Option<usize> {
    let (first, first_length) = char_at(source, position)?;
    if !is_python_word(first) || is_python_digit(first) {
        return None;
    }
    let mut index = position + first_length;
    while let Some((character, length)) = char_at(source, index) {
        if !(is_python_word(character) || character == '-') {
            break;
        }
        index += length;
    }
    while let Some((dot, dot_length)) = char_at(source, index) {
        if dot != '.' {
            break;
        }
        let Some((start, start_length)) = char_at(source, index + dot_length) else {
            break;
        };
        if !is_python_word(start) || is_python_digit(start) {
            break;
        }
        index += dot_length + start_length;
        while let Some((character, length)) = char_at(source, index) {
            if !(is_python_word(character) || character == '-') {
                break;
            }
            index += length;
        }
    }
    Some(index)
}

/// Return the end of an XID-style yt-sql identifier, retaining the
/// established hyphen extension. Mirrors `_scan_identifier`.
pub(crate) fn scan_identifier(source: &str, position: usize) -> Option<usize> {
    let (first, first_length) = char_at(source, position)?;
    if !is_xid_start(first) {
        return None;
    }
    let mut index = position + first_length;
    while let Some((character, length)) = char_at(source, index) {
        if !(is_xid_continue(character) || character == '-') {
            break;
        }
        index += length;
    }
    while let Some((dot, dot_length)) = char_at(source, index) {
        if dot != '.' {
            break;
        }
        let component_start = index + dot_length;
        let Some((start, start_length)) = char_at(source, component_start) else {
            break;
        };
        if !is_xid_start(start) {
            break;
        }
        index = component_start + start_length;
        while let Some((character, length)) = char_at(source, index) {
            if !(is_xid_continue(character) || character == '-') {
                break;
            }
            index += length;
        }
    }
    Some(index)
}

/// Match one `_TOKEN_RE` alternative at `position`, in declaration order.
fn match_token(source: &str, position: usize) -> Option<(&'static str, usize)> {
    let (character, length) = char_at(source, position)?;
    // SPACE
    if is_python_space(character) {
        let mut end = position + length;
        while let Some((next, next_length)) = char_at(source, end) {
            if !is_python_space(next) {
                break;
            }
            end += next_length;
        }
        return Some((TOKEN_SPACE, end));
    }
    // COMMENT
    if character == '#' {
        let mut end = position + length;
        while let Some((next, next_length)) = char_at(source, end) {
            if next == '\r' || next == '\n' {
                break;
            }
            end += next_length;
        }
        return Some((TOKEN_COMMENT, end));
    }
    // INFINITY
    if let Some(end) = match_infinity(source, position) {
        return Some((TOKEN_INFINITY, end));
    }
    // OP
    if let Some(end) = match_op(source, position) {
        return Some((TOKEN_OP, end));
    }
    if character == '(' {
        return Some((TOKEN_LPAREN, position + length));
    }
    if character == '[' {
        return Some((TOKEN_LBRACKET, position + length));
    }
    if character == ']' {
        return Some((TOKEN_RBRACKET, position + length));
    }
    if character == '.' {
        return Some((TOKEN_DOT, position + length));
    }
    // ATIDENT
    if character == '@' {
        let mut end = position + length;
        while let Some(next) = source.as_bytes().get(end) {
            if !(next.is_ascii_alphanumeric() || *next == b'_' || *next == b'.' || *next == b'-') {
                break;
            }
            end += 1;
        }
        if end > position + length {
            return Some((TOKEN_ATIDENT, end));
        }
        // `@` alone falls through to the MISMATCH alternative.
    }
    if character == ')' {
        return Some((TOKEN_RPAREN, position + length));
    }
    // QIDENT
    if character == '`'
        && let Some(end) = match_quoted_identifier(source, position)
    {
        return Some((TOKEN_QIDENT, end));
    }
    // STRING
    if (character == '\'' || character == '"')
        && let Some(end) = match_string(source, position)
    {
        return Some((TOKEN_STRING, end));
    }
    // TEMPORAL
    if let Some(end) = match_temporal(source, position) {
        return Some((TOKEN_TEMPORAL, end));
    }
    // DATETIME / DATE / TIME
    if is_python_digit(character) {
        if let Some(end) = match_datetime(source, position) {
            return Some((TOKEN_DATETIME, end));
        }
        if let Some(end) = match_date(source, position) {
            return Some((TOKEN_DATE, end));
        }
        if let Some(end) = match_time(source, position) {
            return Some((TOKEN_TIME, end));
        }
    }
    // LITERAL_WORD
    if let Some(end) = match_literal_word(source, position) {
        return Some((TOKEN_LITERAL_WORD, end));
    }
    // NUMBER
    if let Some(end) = match_number(source, position) {
        return Some((TOKEN_NUMBER, end));
    }
    // IDENT
    if let Some(end) = match_ident_regex(source, position) {
        return Some((TOKEN_IDENT, end));
    }
    if character == ',' {
        return Some((TOKEN_COMMA, position + length));
    }
    if character == '*' {
        return Some((TOKEN_STAR, position + length));
    }
    if character == '+' {
        return Some((TOKEN_PLUS, position + length));
    }
    if character == '-' {
        return Some((TOKEN_MINUS, position + length));
    }
    if character == '/' {
        return Some((TOKEN_SLASH, position + length));
    }
    if character == '%' {
        return Some((TOKEN_PERCENT, position + length));
    }
    // MISMATCH
    Some((TOKEN_MISMATCH, position + length))
}

/// Decode one quoted string without reinterpreting already-decoded escapes.
/// Port of `_unescape_string`.
pub(crate) fn unescape_string(text: &str) -> String {
    let quote = text.chars().next().unwrap_or('\'');
    // A matched string literal always starts and ends with an ASCII quote.
    let body = &text[1..text.len().saturating_sub(1)];
    let mut result = String::new();
    let mut index = 0;
    while index < body.len() {
        let (character, length) = char_at(body, index).unwrap_or(('\\', 1));
        if character == quote {
            if let Some((next, next_length)) = char_at(body, index + length)
                && next == quote
            {
                result.push(quote);
                index += length + next_length;
                continue;
            }
            result.push(character);
            index += length;
            continue;
        }
        if character == '\\' {
            if let Some((escaped, escaped_length)) = char_at(body, index + length) {
                match escaped {
                    'n' => result.push('\n'),
                    't' => result.push('\t'),
                    '\\' => result.push('\\'),
                    other if other == quote => result.push(other),
                    other => {
                        result.push('\\');
                        result.push(other);
                    }
                }
                index += length + escaped_length;
                continue;
            }
            result.push(character);
            index += length;
            continue;
        }
        result.push(character);
        index += length;
    }
    result
}

/// Python `isprintable()`: only space is printable among separators, and
/// control/format/private-use code points escape. Unassigned code points are
/// conservatively treated as printable (a documented approximation).
fn is_python_printable(character: char) -> bool {
    if character == ' ' {
        return true;
    }
    if character.is_control() {
        return false;
    }
    if matches!(
        character,
        '\u{00AD}'
            | '\u{061C}'
            | '\u{180E}'
            | '\u{200B}'..='\u{200F}'
            | '\u{202A}'..='\u{202E}'
            | '\u{2060}'..='\u{2064}'
            | '\u{2066}'..='\u{206F}'
            | '\u{FEFF}'
            | '\u{FFF9}'..='\u{FFFB}'
            | '\u{00A0}'
            | '\u{1680}'
            | '\u{2000}'..='\u{200A}'
            | '\u{2028}'
            | '\u{2029}'
            | '\u{202F}'
            | '\u{205F}'
            | '\u{3000}'
    ) {
        return false;
    }
    if matches!(
        character,
        '\u{E000}'..='\u{F8FF}' | '\u{F0000}'..='\u{FFFFD}' | '\u{100000}'..='\u{10FFFD}'
    ) {
        return false;
    }
    true
}

fn escape_codepoint(character: char) -> String {
    let code = character as u32;
    if code < 0x100 {
        format!("\\x{code:02x}")
    } else if code < 0x10000 {
        format!("\\u{code:04x}")
    } else {
        format!("\\U{code:08x}")
    }
}

/// Python `repr()` of a string, used by diagnostic messages.
pub(crate) fn python_repr(text: &str) -> String {
    let has_single = text.contains('\'');
    let has_double = text.contains('"');
    let (quote, quoted_self): (char, &str) = if has_single && !has_double {
        ('"', "\"")
    } else {
        ('\'', "\\'")
    };
    let mut out = String::new();
    out.push(quote);
    for character in text.chars() {
        match character {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            quoted if quoted == quote => out.push_str(quoted_self),
            printable if !is_python_printable(printable) => {
                out.push_str(&escape_codepoint(printable))
            }
            other => out.push(other),
        }
    }
    out.push(quote);
    out
}

/// Tokenise `source` exactly like the Python reference.
pub fn tokenise(source: &str) -> Result<Vec<Token>, QueryError> {
    let mut tokens: Vec<Token> = Vec::new();
    let mut position = 0;
    while position < source.len() {
        let Some((mut kind, mut end)) = match_token(source, position) else {
            return Err(QueryError::lexical(
                source,
                "Could not tokenise query.",
                position,
                Some((position + 1).min(source.len())),
                "invalid",
            ));
        };
        let mut text = source[position..end].to_string();
        if kind == TOKEN_IDENT || kind == TOKEN_MISMATCH {
            // ASCII identifier matches are already complete unless a following
            // non-ASCII code point could extend the identifier under XID rules.
            let ascii_fast = kind == TOKEN_IDENT
                && text.is_ascii()
                && (end == source.len()
                    || source.as_bytes().get(end).is_some_and(|byte| *byte < 0x80));
            let identifier_end = if ascii_fast {
                Some(end)
            } else {
                scan_identifier(source, position)
            };
            match identifier_end {
                Some(new_end) => {
                    kind = TOKEN_IDENT;
                    text = source[position..new_end].to_string();
                    end = new_end;
                }
                None if kind == TOKEN_IDENT => {
                    kind = TOKEN_MISMATCH;
                    text = source[position..position + char_len_at(source, position)].to_string();
                    end = position + text.len();
                }
                None => {}
            }
        }
        if kind == TOKEN_SPACE || kind == TOKEN_COMMENT {
            position = end;
            continue;
        }
        if kind == TOKEN_MISMATCH {
            if text == "`" {
                return Err(QueryError::lexical(
                    source,
                    "Unterminated quoted identifier.",
                    position,
                    Some(source.len()),
                    "invalid",
                ));
            }
            if text == "'" || text == "\"" {
                let remainder = &source[position + 1..];
                let trailing_backslashes =
                    remainder.chars().rev().take_while(|c| *c == '\\').count();
                if trailing_backslashes % 2 == 1 {
                    return Err(QueryError::lexical(
                        source,
                        "Incomplete escape sequence at end of string literal.",
                        source.len() - 1,
                        None,
                        "invalid",
                    ));
                }
                return Err(QueryError::lexical(
                    source,
                    "Unterminated string literal.",
                    position,
                    Some(source.len()),
                    "unterminated-string",
                ));
            }
            return Err(QueryError::lexical(
                source,
                format!("Unexpected character {}.", python_repr(&text)),
                position,
                Some(end),
                "invalid",
            ));
        }
        let value = if kind == TOKEN_STRING {
            Some(unescape_string(&text))
        } else if kind == TOKEN_QIDENT {
            let decoded = text[1..text.len() - 1].replace("``", "`");
            if decoded.is_empty() {
                return Err(QueryError::lexical(
                    source,
                    "Quoted identifier cannot be empty.",
                    position,
                    Some(end),
                    "invalid",
                ));
            }
            Some(decoded)
        } else {
            Some(text.clone())
        };
        tokens.push(Token {
            kind,
            text,
            position,
            value,
            end_position: end,
        });
        position = end;
    }
    tokens.push(Token {
        kind: TOKEN_EOF,
        text: String::new(),
        position: source.len(),
        value: None,
        end_position: source.len(),
    });
    Ok(tokens)
}
