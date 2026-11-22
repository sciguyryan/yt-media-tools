//! Local execution of resolved yt-sql queries over metadata records.
//!
//! Port of `query_evaluator.py`, `query_evaluation_context.py`,
//! `query_values.py`, `collection_semantics.py` and `query_semantics.py`.
//! Python is the behavioural reference; the committed portable corpus is the
//! conformance target.
//!
//! Literal decoding note: the Python reference decodes comparison literals at
//! resolution time (`_resolve_literal`, per field kind) and scalar-expression
//! literals generically (`_generic_literal`). The Rust AST's `LiteralValue`
//! can only hold decoded text, booleans and NULL, so this evaluator performs
//! the same decoding at evaluation time: row-level field comparisons decode
//! the right-hand literal with the field's kind, while scalar expressions
//! decode literals generically. `_stable_random_identity`, arithmetic,
//! ordering and three-valued logic all follow the Python observable contract.

use crate::dates::{
    DateContext, parse_date_literal, parse_datetime_literal, timestamp_to_datetime,
};
use crate::model::{
    BoolExpr, Expr, JoinKind, Literal, LiteralValue, Query, RelationField, ScalarFunction,
    SelectTerm,
};
use crate::schema::{Record, infer_kind};
use crate::value::{Fraction, TemporalKind, Value, record_get};
use caseless::default_case_fold_str;
use chrono::{Datelike, Timelike};
use std::cell::RefCell;
use std::cmp::Ordering;
use std::collections::HashMap;
use std::time::{SystemTime, UNIX_EPOCH};

// ---------------------------------------------------------------------------
// Evaluation context (port of query_evaluation_context.py)
// ---------------------------------------------------------------------------

/// Immutable runtime state visible while evaluating one resolved expression.
#[derive(Debug, Clone)]
pub struct EvaluationContext {
    record: Record,
    collection_bindings: Vec<Value>,
    relation_records: Vec<(String, Record)>,
}

/// Read the relation-alias map embedded on a record by join execution.
fn embedded_relation_records(record: &Record) -> Vec<(String, Record)> {
    match record_get(record, "_yt_sql_relation_records") {
        Some(Value::Record(pairs)) => pairs
            .iter()
            .filter_map(|(alias, value)| match value {
                Value::Record(row) => Some((alias.clone(), row.clone())),
                _ => None,
            })
            .collect(),
        _ => Vec::new(),
    }
}

impl EvaluationContext {
    /// Build a context for one record; relation aliases come from the record's
    /// embedded `_yt_sql_relation_records` entry when present.
    pub fn new(record: Record) -> Self {
        let relation_records = embedded_relation_records(&record);
        Self {
            record,
            collection_bindings: Vec::new(),
            relation_records,
        }
    }

    /// Build a context with explicit relation-alias bindings (join execution).
    pub fn with_relation_records(record: Record, relation_records: Vec<(String, Record)>) -> Self {
        Self {
            record,
            collection_bindings: Vec::new(),
            relation_records,
        }
    }

    /// The metadata record associated with this evaluation.
    pub fn record(&self) -> &Record {
        &self.record
    }

    /// The immutable lexical collection-binding stack.
    pub fn collection_bindings(&self) -> &[Value] {
        &self.collection_bindings
    }

    /// Return a child context with one additional lexical collection binding.
    pub fn bind_collection_element(&self, element: Value) -> EvaluationContext {
        let mut bindings = self.collection_bindings.clone();
        bindings.push(element);
        EvaluationContext {
            record: self.record.clone(),
            collection_bindings: bindings,
            relation_records: self.relation_records.clone(),
        }
    }

    /// Resolve a lexical collection element by its resolver-assigned distance.
    pub fn collection_element(&self, scope_distance: usize) -> Value {
        if scope_distance >= self.collection_bindings.len() {
            return Value::Null;
        }
        let index = self.collection_bindings.len() - 1 - scope_distance;
        self.collection_bindings[index].clone()
    }

    /// Return the row bound to one resolved relation alias, if present.
    pub fn relation_record(&self, qualifier: &str) -> Option<&Record> {
        self.relation_records
            .iter()
            .find(|(alias, _)| alias == qualifier)
            .map(|(_, record)| record)
    }
}

// ---------------------------------------------------------------------------
// Scalar literal decoding (evaluation-time mirror of `_resolve_literal`)
// ---------------------------------------------------------------------------

/// The date context used for evaluation-time literal parsing.
fn default_date_context() -> DateContext {
    DateContext::new("ymd", DateContext::default_now())
}

fn normalise_spaces(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

/// Decode one temporal infinity spelling with the expected temporal family.
fn temporal_infinity_value(text: &str, kind: &str) -> Option<Value> {
    let compact: String = text
        .chars()
        .filter(|character| !character.is_whitespace())
        .collect();
    let upper = compact.to_uppercase();
    let sign = if upper == "INFINITY()" {
        1
    } else if upper == "-INFINITY()" {
        -1
    } else {
        return None;
    };
    Some(Value::Infinity {
        sign,
        kind: if kind == "datetime" {
            TemporalKind::DateTime
        } else {
            TemporalKind::Date
        },
    })
}

/// Port of `_parse_integer_literal_text`: decimal, hexadecimal, octal or binary.
fn parse_integer_literal_text(text: &str) -> Option<i64> {
    let compact: String = text
        .chars()
        .filter(|character| !character.is_whitespace())
        .collect();
    let (sign, body) = match compact.strip_prefix('-') {
        Some(rest) => (-1i64, rest),
        None => (1i64, compact.strip_prefix('+').unwrap_or(&compact)),
    };
    if is_decimal_integer(body) {
        let digits: String = body.chars().filter(|character| *character != '_').collect();
        return digits.parse::<i64>().ok().map(|value| sign * value);
    }
    let (prefix, base): (&str, u32) = if body.len() >= 2 && body.as_bytes()[0] == b'0' {
        match body.as_bytes()[1] {
            byte if byte == b'x' || byte == b'X' => (&body[..2], 16),
            byte if byte == b'o' || byte == b'O' => (&body[..2], 8),
            byte if byte == b'b' || byte == b'B' => (&body[..2], 2),
            _ => return None,
        }
    } else {
        return None;
    };
    let digits: String = body[prefix.len()..]
        .chars()
        .filter(|character| *character != '_')
        .collect();
    if digits.is_empty() {
        return None;
    }
    let valid = digits.chars().all(|character| character.is_digit(base));
    if !valid {
        return None;
    }
    i64::from_str_radix(&digits, base)
        .ok()
        .map(|value| sign * value)
}

/// `[+-]?\d+(?:_\d+)*` without the sign.
fn is_decimal_integer(text: &str) -> bool {
    let mut previous_underscore = false;
    let mut saw_digit = false;
    for character in text.chars() {
        if character.is_ascii_digit() {
            saw_digit = true;
            previous_underscore = false;
        } else if character == '_' {
            if !saw_digit || previous_underscore {
                return false;
            }
            previous_underscore = true;
        } else {
            return false;
        }
    }
    saw_digit && !previous_underscore
}

/// `[+-]?\d+(?:_\d+)*(?:\.(?:\d+(?:_\d+)*)?)` without the sign.
fn is_decimal_number(text: &str) -> bool {
    let (integer_part, fraction_part) = match text.split_once('.') {
        Some((head, tail)) => (head, Some(tail)),
        None => (text, None),
    };
    if !is_decimal_integer(integer_part) {
        return false;
    }
    match fraction_part {
        None => true,
        Some(tail) => tail.is_empty() || is_decimal_integer(tail),
    }
}

/// Port of `_parse_number_text`: decimal/base integer or decimal float.
fn parse_number_text(text: &str) -> Option<Value> {
    let compact: String = text
        .chars()
        .filter(|character| !character.is_whitespace())
        .collect();
    let has_base_prefix = compact.len() >= 2
        && compact.as_bytes()[0] == b'0'
        && matches!(
            compact.as_bytes()[1],
            b'x' | b'X' | b'o' | b'O' | b'b' | b'B'
        )
        || (compact.len() >= 3
            && (compact.starts_with('+') || compact.starts_with('-'))
            && compact.as_bytes()[1] == b'0'
            && matches!(
                compact.as_bytes()[2],
                b'x' | b'X' | b'o' | b'O' | b'b' | b'B'
            ));
    if has_base_prefix {
        return parse_integer_literal_text(&compact).map(Value::Int);
    }
    let (sign, body) = match compact.strip_prefix('-') {
        Some(rest) => (-1i64, rest),
        None => (1i64, compact.strip_prefix('+').unwrap_or(&compact)),
    };
    if is_decimal_integer(body) {
        let digits: String = body.chars().filter(|character| *character != '_').collect();
        return digits
            .parse::<i64>()
            .ok()
            .map(|value| Value::Int(sign * value));
    }
    if is_decimal_number(body) {
        let digits: String = body.chars().filter(|character| *character != '_').collect();
        return digits
            .parse::<f64>()
            .ok()
            .map(|value| Value::Float(sign as f64 * value));
    }
    None
}

/// Port of `_parse_count_text`: counts with optional k/m/b multipliers.
fn parse_count_text(text: &str) -> Option<i64> {
    let compact: String = text
        .chars()
        .filter(|character| !character.is_whitespace())
        .collect();
    let has_base_prefix = compact.len() >= 2
        && compact.as_bytes()[0] == b'0'
        && matches!(
            compact.as_bytes()[1],
            b'x' | b'X' | b'o' | b'O' | b'b' | b'B'
        )
        || (compact.len() >= 3
            && (compact.starts_with('+') || compact.starts_with('-'))
            && compact.as_bytes()[1] == b'0'
            && matches!(
                compact.as_bytes()[2],
                b'x' | b'X' | b'o' | b'O' | b'b' | b'B'
            ));
    if has_base_prefix {
        return parse_integer_literal_text(&compact);
    }
    let (sign, body) = match compact.strip_prefix('-') {
        Some(rest) => (-1i64, rest),
        None => (1i64, compact.strip_prefix('+').unwrap_or(&compact)),
    };
    let (number_part, suffix) = match body.chars().last() {
        Some(character @ ('k' | 'K' | 'm' | 'M' | 'b' | 'B')) => (
            body[..body.len() - character.len_utf8()].to_string(),
            character.to_ascii_lowercase(),
        ),
        _ => (body.to_string(), ' '),
    };
    let multiplier = match suffix {
        'k' => 1_000i64,
        'm' => 1_000_000i64,
        'b' => 1_000_000_000i64,
        _ => 1i64,
    };
    if !is_decimal_number(&number_part) {
        return None;
    }
    let digits: String = number_part
        .chars()
        .filter(|character| *character != '_')
        .collect();
    let number: f64 = digits.parse().ok()?;
    Some(sign * crate::value::python_round(number * multiplier as f64))
}

/// Port of `_parse_duration_text` (seconds, clock and unit-token forms).
fn parse_duration_text(text: &str) -> Option<i64> {
    let value = normalise_spaces(text);

    // Clock form: `\d+(:\d{1,2}){1,2}(\.\d{1,3})?`.
    if let Some(total) = parse_clock_duration(&value) {
        return Some(total);
    }
    if is_bare_number(&value) {
        // A duration needs a unit.
        return None;
    }

    let compact: String = value
        .chars()
        .filter(|character| !character.is_whitespace())
        .collect();
    let compact_is_unit_run = !compact.is_empty() && is_compact_duration_run(&compact);
    let work = if compact_is_unit_run {
        compact
    } else {
        value.clone()
    };

    let characters: Vec<char> = work.chars().collect();
    let mut total = 0.0f64;
    let mut cursor = 0usize;
    let mut matched = false;
    while cursor < characters.len() {
        if !characters[cursor].is_ascii_digit() {
            cursor += 1;
            continue;
        }
        // Gap text between matches must be blank.
        if characters[..cursor]
            .iter()
            .any(|character| !character.is_whitespace())
        {
            return None;
        }
        let (number, mut cursor_after_number) = parse_duration_number(&characters, cursor)?;
        // Optional whitespace, then the unit token: `[^\W\d_]+(?:-[^\W\d_]+)*`.
        while cursor_after_number < characters.len()
            && characters[cursor_after_number].is_whitespace()
        {
            cursor_after_number += 1;
        }
        let unit_start = cursor_after_number;
        let unit_end = scan_unit_token(&characters, unit_start);
        if unit_end == unit_start {
            return None;
        }
        let unit_text: String = characters[unit_start..unit_end].iter().collect();
        let unit = crate::units::load_default_unit_registry()
            .resolve(&unit_text)
            .ok()?;
        if unit.kind != crate::units::FIXED {
            return None;
        }
        matched = true;
        total += number * unit.amount;
        cursor = unit_end;
    }
    if !matched
        || characters[cursor.min(characters.len())..]
            .iter()
            .any(|character| !character.is_whitespace())
    {
        return None;
    }
    Some(crate::value::python_round(total))
}

fn is_bare_number(value: &str) -> bool {
    let body = value.strip_prefix('-').unwrap_or(value);
    let (head, tail) = match body.split_once('.') {
        Some((head, tail)) => (head, Some(tail)),
        None => (body, None),
    };
    !head.is_empty()
        && head.chars().all(|character| character.is_ascii_digit())
        && tail
            .map(|tail| tail.chars().all(|character| character.is_ascii_digit()))
            .unwrap_or(true)
}

/// Clock-form duration `H:MM:SS(.fff)` or `MM:SS(.fff)` in whole seconds.
fn parse_clock_duration(value: &str) -> Option<i64> {
    let (clock_body, fraction) = match value.rsplit_once('.') {
        Some((head, tail)) => {
            if tail.is_empty()
                || tail.len() > 3
                || !tail.chars().all(|c| c.is_ascii_digit())
                || !head.contains(':')
            {
                return None;
            }
            let fraction: f64 = format!("0.{tail}").parse().ok()?;
            (head.to_string(), fraction)
        }
        None => (value.to_string(), 0.0),
    };
    if !clock_body.contains(':') {
        return None;
    }
    let mut parts: Vec<u64> = Vec::new();
    for segment in clock_body.split(':') {
        if segment.is_empty() || segment.len() > 2 || !segment.chars().all(|c| c.is_ascii_digit()) {
            return None;
        }
        parts.push(segment.parse().ok()?);
    }
    if parts.len() == 2 {
        let (minutes, seconds) = (parts[0], parts[1]);
        if seconds >= 60 {
            return None;
        }
        return Some(crate::value::python_round(
            minutes as f64 * 60.0 + seconds as f64 + fraction,
        ));
    }
    if parts.len() == 3 {
        let (hours, minutes, seconds) = (parts[0], parts[1], parts[2]);
        if minutes >= 60 || seconds >= 60 {
            return None;
        }
        return Some(crate::value::python_round(
            hours as f64 * 3600.0 + minutes as f64 * 60.0 + seconds as f64 + fraction,
        ));
    }
    None
}

/// Parse `\d+(\.\d+)?` starting at `start`, returning the value and end index.
fn parse_duration_number(characters: &[char], start: usize) -> Option<(f64, usize)> {
    let mut end = start;
    while end < characters.len() && characters[end].is_ascii_digit() {
        end += 1;
    }
    if end < characters.len() && characters[end] == '.' {
        let mut fraction_end = end + 1;
        while fraction_end < characters.len() && characters[fraction_end].is_ascii_digit() {
            fraction_end += 1;
        }
        if fraction_end > end + 1 {
            end = fraction_end;
        }
    }
    if end == start {
        return None;
    }
    let text: String = characters[start..end].iter().collect();
    Some((text.parse().ok()?, end))
}

/// Scan a `[letters]+(-[letters]+)*` unit token starting at `start`.
fn scan_unit_token(characters: &[char], start: usize) -> usize {
    let is_unit_character =
        |character: char| character.is_alphanumeric() && character.to_digit(10).is_none();
    let mut end = start;
    loop {
        let run_start = end;
        while end < characters.len() && is_unit_character(characters[end]) {
            end += 1;
        }
        if end == run_start {
            return if run_start == start { start } else { end };
        }
        if end + 1 < characters.len()
            && characters[end] == '-'
            && is_unit_character(characters[end + 1])
        {
            end += 1;
            continue;
        }
        return end;
    }
}

/// `(?:\d+(?:\.\d+)?(?:h|m|s))+` case-insensitively.
fn is_compact_duration_run(compact: &str) -> bool {
    let characters: Vec<char> = compact.to_lowercase().chars().collect();
    let mut index = 0usize;
    while index < characters.len() {
        let number_start = index;
        while index < characters.len() && characters[index].is_ascii_digit() {
            index += 1;
        }
        if index == number_start {
            return false;
        }
        if index < characters.len() && characters[index] == '.' {
            index += 1;
            let fraction_start = index;
            while index < characters.len() && characters[index].is_ascii_digit() {
                index += 1;
            }
            if index == fraction_start {
                return false;
            }
        }
        if index >= characters.len() || !matches!(characters[index], 'h' | 'm' | 's') {
            return false;
        }
        index += 1;
    }
    true
}

/// Port of `_generic_literal`: quoted text, boolean words or numeric text.
fn generic_literal(text: &str, quoted: bool) -> Value {
    if quoted {
        return Value::Text(text.to_string());
    }
    let lowered = default_case_fold_str(text);
    if lowered == "true" {
        return Value::Bool(true);
    }
    if lowered == "false" {
        return Value::Bool(false);
    }
    if text
        .chars()
        .next()
        .map(|character| character.is_ascii_digit() || character == '+' || character == '-')
        .unwrap_or(false)
        && let Some(value) = parse_number_text(text)
    {
        return value;
    }
    Value::Text(text.to_string())
}

fn decode_literal_text(text: &str, quoted: bool, kind: Option<&str>) -> Value {
    match kind.unwrap_or("") {
        "duration" => parse_duration_text(text)
            .map(Value::Int)
            .unwrap_or(Value::Null),
        "count" => parse_count_text(text)
            .map(Value::Int)
            .unwrap_or(Value::Null),
        "integer" => parse_number_text(text)
            .filter(|value| matches!(value, Value::Int(_)))
            .unwrap_or(Value::Null),
        "number" => parse_number_text(text).unwrap_or(Value::Null),
        "boolean" => {
            let lowered = default_case_fold_str(text);
            if lowered == "true" {
                Value::Bool(true)
            } else if lowered == "false" {
                Value::Bool(false)
            } else {
                Value::Null
            }
        }
        "date" => {
            if let Some(infinity) = temporal_infinity_value(text, "date") {
                return infinity;
            }
            parse_date_literal_lenient(text)
                .map(Value::Date)
                .unwrap_or(Value::Null)
        }
        "datetime" => {
            if let Some(infinity) = temporal_infinity_value(text, "datetime") {
                return infinity;
            }
            parse_datetime_literal(text, &default_date_context())
                .map(Value::DateTime)
                .unwrap_or(Value::Null)
        }
        "string" => Value::Text(text.to_string()),
        _ => generic_literal(text, quoted),
    }
}

/// Parse a date literal text; the configured date order is unavailable at
/// evaluation time, so year-first then local dmy then mdy forms are tried.
fn parse_date_literal_lenient(text: &str) -> Option<chrono::NaiveDate> {
    for order in ["ymd", "dmy", "mdy"] {
        if let Ok(date) =
            parse_date_literal(text, &DateContext::new(order, DateContext::default_now()))
        {
            return Some(date);
        }
    }
    None
}

/// Decode one resolved literal into the runtime value domain.
fn decode_literal(literal: &Literal, kind: Option<&str>) -> Value {
    match &literal.value {
        LiteralValue::Null => Value::Null,
        LiteralValue::Bool(inner) => Value::Bool(*inner),
        LiteralValue::Text(text) => decode_literal_text(text, literal.quoted, kind),
        LiteralValue::Raw => decode_literal_text(&literal.raw, literal.quoted, kind),
    }
}

/// Python `str(resolved_literal_value)` for text predicates.
fn literal_text(literal: &Literal) -> String {
    match &literal.value {
        LiteralValue::Text(text) => text.clone(),
        LiteralValue::Raw => literal.raw.clone(),
        LiteralValue::Null => "None".to_string(),
        LiteralValue::Bool(true) => "True".to_string(),
        LiteralValue::Bool(false) => "False".to_string(),
    }
}

// ---------------------------------------------------------------------------
// Value helpers (port of query_values.py plus Python `==` semantics)
// ---------------------------------------------------------------------------

const CASE_INSENSITIVE_ENUM_FIELDS: [&str; 2] = ["live_status", "availability"];

/// Normalise comparison values for fields with explicit enum-like semantics.
fn comparison_values_field(field_name: &str, left: &Value, right: &Value) -> (Value, Value) {
    let folded = CASE_INSENSITIVE_ENUM_FIELDS.contains(&field_name.to_lowercase().as_str());
    if folded && let (Value::Text(a), Value::Text(b)) = (left, right) {
        return (
            Value::Text(default_case_fold_str(a)),
            Value::Text(default_case_fold_str(b)),
        );
    }
    (left.clone(), right.clone())
}

/// Python `==` for the runtime value domain (including NULL == NULL as true,
/// as Python's `None == None` does for dedup/group keys).
pub fn key_equal(left: &Value, right: &Value) -> bool {
    match (left, right) {
        (Value::Null, Value::Null) => true,
        _ if left.is_null() || right.is_null() => false,
        (Value::Array(a), Value::Array(b)) => {
            a.len() == b.len() && a.iter().zip(b.iter()).all(|(x, y)| key_equal(x, y))
        }
        (Value::Record(a), Value::Record(b)) => {
            a.len() == b.len()
                && a.iter()
                    .zip(b.iter())
                    .all(|((an, av), (bn, bv))| an == bn && key_equal(av, bv))
        }
        _ => left.equals(right),
    }
}

/// Port of `hashable_group_value`: deterministic hashable representation used
/// for relation grouping.
pub fn hashable_group_value(value: &Value) -> Value {
    match value {
        Value::Record(pairs) => Value::Array(
            pairs
                .iter()
                .map(|(key, item)| {
                    Value::Array(vec![Value::Text(key.clone()), hashable_group_value(item)])
                })
                .collect(),
        ),
        Value::Array(items) => Value::Array(items.iter().map(hashable_group_value).collect()),
        _ => value.clone(),
    }
}

fn keys_equal(left: &[Value], right: &[Value]) -> bool {
    left.len() == right.len() && left.iter().zip(right.iter()).all(|(a, b)| key_equal(a, b))
}

/// Replace an existing key's value in place, or append it (Python dict assignment).
fn record_set(record: &mut Record, key: &str, value: Value) {
    if let Some(slot) = record.iter_mut().find(|(name, _)| name == key) {
        slot.1 = value;
    } else {
        record.push((key.to_string(), value));
    }
}

// ---------------------------------------------------------------------------
// Python-style scalar arithmetic
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
enum Arith {
    Int(i64),
    Float(f64),
    Rat(i128, i128),
    Text(String),
}

fn gcd_i128(mut a: i128, mut b: i128) -> i128 {
    a = a.abs();
    b = b.abs();
    while b != 0 {
        (a, b) = (b, a % b);
    }
    a
}

/// Rebuild a fraction's exact (numerator, denominator) from its decimal text.
fn fraction_parts(value: &Value) -> Option<(i128, i128)> {
    let Value::Decimal(fraction) = value else {
        return None;
    };
    let text = fraction.decimal_string();
    let (sign, body) = match text.strip_prefix('-') {
        Some(rest) => (-1i128, rest),
        None => (1i128, text.as_str()),
    };
    let (integer_part, fraction_part) = match body.split_once('.') {
        Some((head, tail)) => (head, tail),
        None => (body, ""),
    };
    let mut digits = String::new();
    digits.push_str(integer_part);
    digits.push_str(fraction_part);
    if digits.is_empty() {
        digits.push('0');
    }
    let numerator: i128 = digits.parse().ok()?;
    let denominator = 10i128.checked_pow(fraction_part.len() as u32)?;
    Some((sign * numerator, denominator))
}

/// Exact (numerator, denominator) view of a value, as Python `Fraction(v)`.
fn value_to_fraction_parts(value: &Value) -> Option<(i128, i128)> {
    match value {
        Value::Int(inner) => Some((*inner as i128, 1)),
        Value::Bool(inner) => Some((if *inner { 1 } else { 0 }, 1)),
        Value::Decimal(_) => fraction_parts(value),
        Value::Float(inner) => exact_float_parts(*inner),
        _ => None,
    }
}

/// Exact binary-float rational parts; declines absurd magnitudes.
fn exact_float_parts(value: f64) -> Option<(i128, i128)> {
    if !value.is_finite() {
        return None;
    }
    let bits = value.to_bits();
    let negative = bits >> 63 == 1;
    let exponent_bits = ((bits >> 52) & 0x7ff) as i64;
    let mantissa_bits = bits & ((1u64 << 52) - 1);
    let (mantissa, exponent) = if exponent_bits == 0 {
        (mantissa_bits, -1074i64)
    } else {
        (mantissa_bits | (1u64 << 52), exponent_bits - 1075)
    };
    let sign = if negative { -1i128 } else { 1i128 };
    if exponent >= 0 {
        let shift = exponent as u32;
        if shift >= 127 {
            return None;
        }
        let numerator = (mantissa as i128).checked_mul(1i128 << shift)?;
        Some((sign * numerator, 1))
    } else {
        let shift = (-exponent) as u32;
        if shift >= 127 {
            return None;
        }
        Some((sign * mantissa as i128, 1i128 << shift))
    }
}

fn to_arith(value: &Value) -> Option<Arith> {
    match value {
        Value::Bool(inner) => Some(Arith::Int(if *inner { 1 } else { 0 })),
        Value::Int(inner) => Some(Arith::Int(*inner)),
        Value::Float(inner) => Some(Arith::Float(*inner)),
        Value::Decimal(_) => fraction_parts(value).map(|(n, d)| Arith::Rat(n, d)),
        Value::Text(text) => Some(Arith::Text(text.clone())),
        _ => None,
    }
}

fn arith_to_value(arith: Arith) -> Value {
    match arith {
        Arith::Int(inner) => Value::Int(inner),
        Arith::Float(inner) => Value::Float(inner),
        Arith::Rat(numerator, denominator) => Value::Decimal(Fraction::new(numerator, denominator)),
        Arith::Text(text) => Value::Text(text),
    }
}

fn floor_div_i128(a: i128, b: i128) -> i128 {
    let quotient = a / b;
    if a % b != 0 && (a < 0) != (b < 0) {
        quotient - 1
    } else {
        quotient
    }
}

/// Python float `%`: result takes the divisor's sign.
fn python_float_mod(a: f64, b: f64) -> f64 {
    let mut remainder = a % b;
    if remainder != 0.0 && (remainder < 0.0) != (b < 0.0) {
        remainder += b;
    }
    remainder
}

/// Scalar `+ - * / %` with Python's family rules.
fn scalar_binary_arith(operator: &str, left: &Value, right: &Value) -> Option<Value> {
    let a = to_arith(left)?;
    let b = to_arith(right)?;

    // Text behaviour: concatenation for `+`, repetition for `*` with integers.
    if let (Arith::Text(x), Arith::Text(y)) = (&a, &b) {
        return if operator == "+" {
            Some(Value::Text(format!("{x}{y}")))
        } else {
            None
        };
    }
    if operator == "*"
        && let (Arith::Text(text), Arith::Int(count)) | (Arith::Int(count), Arith::Text(text)) =
            (&a, &b)
    {
        let repeat = if *count > 0 { *count as usize } else { 0 };
        return Some(Value::Text(text.repeat(repeat)));
    }

    // Float participation promotes everything to binary floats.
    if matches!(a, Arith::Float(_)) || matches!(b, Arith::Float(_)) {
        let x = match a {
            Arith::Int(v) => v as f64,
            Arith::Float(v) => v,
            Arith::Rat(n, d) => n as f64 / d as f64,
            Arith::Text(_) => return None,
        };
        let y = match b {
            Arith::Int(v) => v as f64,
            Arith::Float(v) => v,
            Arith::Rat(n, d) => n as f64 / d as f64,
            Arith::Text(_) => return None,
        };
        return match operator {
            "+" => Some(Value::Float(x + y)),
            "-" => Some(Value::Float(x - y)),
            "*" => Some(Value::Float(x * y)),
            "/" => {
                if y == 0.0 {
                    None
                } else {
                    Some(Value::Float(x / y))
                }
            }
            "%" => {
                if y == 0.0 {
                    None
                } else {
                    Some(Value::Float(python_float_mod(x, y)))
                }
            }
            _ => None,
        };
    }

    // Rational participation keeps exact arithmetic.
    if matches!(a, Arith::Rat(_, _)) || matches!(b, Arith::Rat(_, _)) {
        let (xn, xd) = match a {
            Arith::Int(v) => (v as i128, 1),
            Arith::Rat(n, d) => (n, d),
            _ => return None,
        };
        let (yn, yd) = match b {
            Arith::Int(v) => (v as i128, 1),
            Arith::Rat(n, d) => (n, d),
            _ => return None,
        };
        return rational_arith(operator, xn, xd, yn, yd).map(arith_to_value);
    }

    // Integer arithmetic.
    let (x, y) = match (a, b) {
        (Arith::Int(x), Arith::Int(y)) => (x, y),
        _ => return None,
    };
    match operator {
        "+" => x.checked_add(y).map(Value::Int),
        "-" => x.checked_sub(y).map(Value::Int),
        "*" => x.checked_mul(y).map(Value::Int),
        "/" => {
            if y == 0 {
                None
            } else {
                Some(Value::Float(x as f64 / y as f64))
            }
        }
        "%" => {
            if y == 0 {
                None
            } else {
                let quotient = floor_div_i128(x as i128, y as i128);
                let remainder = x as i128 - quotient * y as i128;
                i64::try_from(remainder).ok().map(Value::Int)
            }
        }
        _ => None,
    }
}

fn rational_arith(operator: &str, xn: i128, xd: i128, yn: i128, yd: i128) -> Option<Arith> {
    match operator {
        "+" => {
            let numerator = xn.checked_mul(yd)?.checked_add(yn.checked_mul(xd)?)?;
            let denominator = xd.checked_mul(yd)?;
            Some(Arith::Rat(numerator, denominator))
        }
        "-" => {
            let numerator = xn.checked_mul(yd)?.checked_sub(yn.checked_mul(xd)?)?;
            let denominator = xd.checked_mul(yd)?;
            Some(Arith::Rat(numerator, denominator))
        }
        "*" => {
            let numerator = xn.checked_mul(yn)?;
            let denominator = xd.checked_mul(yd)?;
            Some(Arith::Rat(numerator, denominator))
        }
        "/" => {
            if yn == 0 {
                return None;
            }
            let numerator = xn.checked_mul(yd)?;
            let denominator = xd.checked_mul(yn)?;
            Some(Arith::Rat(numerator, denominator))
        }
        "%" => {
            if yn == 0 {
                return None;
            }
            // a - floor(a / b) * b
            let divided_num = xn.checked_mul(yd)?;
            let divided_den = xd.checked_mul(yn)?;
            if divided_den == 0 {
                return None;
            }
            let quotient = floor_div_i128(divided_num, divided_den);
            let numerator = xn.checked_sub(yn.checked_mul(xd)?.checked_mul(quotient)?)?;
            let denominator = xd.checked_mul(yd)?;
            Some(Arith::Rat(numerator, denominator))
        }
        _ => None,
    }
}

/// Unary `+` / `-` with Python's observable behaviour.
fn scalar_unary_arith(operator: &str, value: &Value) -> Value {
    let Some(arith) = to_arith(value) else {
        return Value::Null;
    };
    if operator == "+" {
        return arith_to_value(match arith {
            Arith::Text(_) => return Value::Null,
            other => other,
        });
    }
    match arith {
        Arith::Int(inner) => match inner.checked_neg() {
            Some(negated) => Value::Int(negated),
            None => Value::Null,
        },
        Arith::Float(inner) => Value::Float(-inner),
        Arith::Rat(numerator, denominator) => {
            Value::Decimal(Fraction::new(-numerator, denominator))
        }
        Arith::Text(_) => Value::Null,
    }
}

/// Python `sum` over the runtime value domain; `None` marks a `TypeError`.
fn sum_values(values: &[Value]) -> Option<Value> {
    let mut total = Value::Int(0);
    for value in values {
        total = scalar_binary_arith("+", &total, value)?;
    }
    Some(total)
}

/// Port of `_average_value`: exact rational AVG under the portable precision
/// contract. `None` marks a `TypeError` (non-numeric total).
fn average_value(total: &Value, count: usize) -> Option<Value> {
    let (numerator, denominator) = value_to_fraction_parts(total)?;
    let count_i = count as i128;
    let scaled_denominator = denominator.checked_mul(count_i)?;
    if scaled_denominator == 0 {
        return None;
    }
    let divisor = gcd_i128(numerator, scaled_denominator).max(1);
    let mut reduced = scaled_denominator / divisor;
    while reduced % 2 == 0 {
        reduced /= 2;
    }
    while reduced % 5 == 0 {
        reduced /= 5;
    }
    let fraction = Fraction::new(numerator, scaled_denominator);
    let fraction = if reduced != 1 {
        fraction.round_half_even(6)
    } else {
        fraction
    };
    Some(Value::Decimal(fraction))
}

/// Python `min` over non-null values; `None` marks a `TypeError`.
fn python_min(values: &[Value]) -> Option<Value> {
    let mut iter = values.iter();
    let mut best = iter.next()?.clone();
    for value in iter {
        match value.compare(&best) {
            Some(Ordering::Less) => best = value.clone(),
            Some(_) => {}
            None => return None,
        }
    }
    Some(best)
}

/// Python `max` over non-null values; `None` marks a `TypeError`.
fn python_max(values: &[Value]) -> Option<Value> {
    let mut iter = values.iter();
    let mut best = iter.next()?.clone();
    for value in iter {
        match value.compare(&best) {
            Some(Ordering::Greater) => best = value.clone(),
            Some(_) => {}
            None => return None,
        }
    }
    Some(best)
}

// ---------------------------------------------------------------------------
// BLAKE2b (RFC 7693) for the seeded RANDOM law
// ---------------------------------------------------------------------------

const BLAKE2B_IV: [u64; 8] = [
    0x6a09e667f3bcc908,
    0xbb67ae8584caa73b,
    0x3c6ef372fe94f82b,
    0xa54ff53a5f1d36f1,
    0x510e527fade682d1,
    0x9b05688c2b3e6c1f,
    0x1f83d9abfb41bd6b,
    0x5be0cd19137e2179,
];

const BLAKE2B_SIGMA: [[u8; 16]; 12] = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
    [14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3],
    [11, 8, 12, 0, 5, 2, 15, 13, 10, 14, 3, 6, 7, 1, 9, 4],
    [7, 9, 3, 1, 13, 12, 11, 14, 2, 6, 5, 10, 4, 0, 15, 8],
    [9, 0, 5, 7, 2, 4, 10, 15, 14, 1, 11, 12, 6, 8, 3, 13],
    [2, 12, 6, 10, 0, 11, 8, 3, 4, 13, 7, 5, 15, 14, 1, 9],
    [12, 5, 1, 15, 14, 13, 4, 10, 0, 7, 6, 3, 9, 2, 8, 11],
    [13, 11, 7, 14, 12, 1, 3, 9, 5, 0, 15, 4, 8, 6, 2, 10],
    [6, 15, 14, 9, 11, 3, 0, 8, 12, 2, 13, 7, 1, 4, 10, 5],
    [10, 2, 8, 4, 7, 6, 1, 5, 15, 11, 9, 14, 3, 12, 13, 0],
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
    [14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3],
];

#[allow(clippy::too_many_arguments)]
fn blake2b_g(v: &mut [u64; 16], a: usize, b: usize, c: usize, d: usize, x: u64, y: u64) {
    v[a] = v[a].wrapping_add(v[b]).wrapping_add(x);
    v[d] = (v[d] ^ v[a]).rotate_right(32);
    v[c] = v[c].wrapping_add(v[d]);
    v[b] = (v[b] ^ v[c]).rotate_right(24);
    v[a] = v[a].wrapping_add(v[b]).wrapping_add(y);
    v[d] = (v[d] ^ v[a]).rotate_right(16);
    v[c] = v[c].wrapping_add(v[d]);
    v[b] = (v[b] ^ v[c]).rotate_right(63);
}

fn blake2b_compress(h: &mut [u64; 8], block: &[u8; 128], counter: u128, last: bool) {
    let mut m = [0u64; 16];
    for index in 0..16 {
        let mut word = [0u8; 8];
        word.copy_from_slice(&block[index * 8..(index + 1) * 8]);
        m[index] = u64::from_le_bytes(word);
    }
    let mut v = [0u64; 16];
    v[..8].copy_from_slice(h);
    v[8..].copy_from_slice(&BLAKE2B_IV);
    v[12] ^= counter as u64;
    v[13] ^= (counter >> 64) as u64;
    if last {
        v[14] = !v[14];
    }
    for sigma in BLAKE2B_SIGMA.iter() {
        blake2b_g(
            &mut v,
            0,
            4,
            8,
            12,
            m[sigma[0] as usize],
            m[sigma[1] as usize],
        );
        blake2b_g(
            &mut v,
            1,
            5,
            9,
            13,
            m[sigma[2] as usize],
            m[sigma[3] as usize],
        );
        blake2b_g(
            &mut v,
            2,
            6,
            10,
            14,
            m[sigma[4] as usize],
            m[sigma[5] as usize],
        );
        blake2b_g(
            &mut v,
            3,
            7,
            11,
            15,
            m[sigma[6] as usize],
            m[sigma[7] as usize],
        );
        blake2b_g(
            &mut v,
            0,
            5,
            10,
            15,
            m[sigma[8] as usize],
            m[sigma[9] as usize],
        );
        blake2b_g(
            &mut v,
            1,
            6,
            11,
            12,
            m[sigma[10] as usize],
            m[sigma[11] as usize],
        );
        blake2b_g(
            &mut v,
            2,
            7,
            8,
            13,
            m[sigma[12] as usize],
            m[sigma[13] as usize],
        );
        blake2b_g(
            &mut v,
            3,
            4,
            9,
            14,
            m[sigma[14] as usize],
            m[sigma[15] as usize],
        );
    }
    for index in 0..8 {
        h[index] ^= v[index] ^ v[index + 8];
    }
}

/// One-shot BLAKE2b with a personalisation and zero-length key.
fn blake2b(data: &[u8], out_len: usize, person: &[u8]) -> Vec<u8> {
    let mut h = BLAKE2B_IV;
    // Parameter block: digest_len | (key_len=0 << 8) | (fanout=1 << 16)
    // | (depth=1 << 24) — the fanout/depth bits form the 0x0101_0000 prefix.
    h[0] ^= 0x0101_0000u64 | (out_len as u64);
    let mut person_block = [0u8; 16];
    let person_len = person.len().min(16);
    person_block[..person_len].copy_from_slice(&person[..person_len]);
    let mut lower = [0u8; 8];
    let mut upper = [0u8; 8];
    lower.copy_from_slice(&person_block[0..8]);
    upper.copy_from_slice(&person_block[8..16]);
    h[6] ^= u64::from_le_bytes(lower);
    h[7] ^= u64::from_le_bytes(upper);

    if data.is_empty() {
        let block = [0u8; 128];
        blake2b_compress(&mut h, &block, 0, true);
    } else {
        let mut offset = 0usize;
        while data.len() - offset > 128 {
            let mut block = [0u8; 128];
            block.copy_from_slice(&data[offset..offset + 128]);
            blake2b_compress(&mut h, &block, (offset + 128) as u128, false);
            offset += 128;
        }
        let mut block = [0u8; 128];
        let rest = &data[offset..];
        block[..rest.len()].copy_from_slice(rest);
        blake2b_compress(&mut h, &block, data.len() as u128, true);
    }

    let mut out = Vec::with_capacity(out_len);
    for word in h.iter() {
        out.extend_from_slice(&word.to_le_bytes());
    }
    out.truncate(out_len);
    out
}

// ---------------------------------------------------------------------------
// RANDOM evaluation
// ---------------------------------------------------------------------------

fn splitmix64(state: &mut u64) -> u64 {
    *state = state.wrapping_add(0x9E3779B97F4A7C15);
    let mut z = *state;
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D049BB133111EB);
    z ^ (z >> 31)
}

/// FNV-1a over one value's canonical byte encoding, for cache identity.
fn hash_value_bytes(value: &Value, out: &mut Vec<u8>) {
    match value {
        Value::Null => out.push(0),
        Value::Bool(inner) => {
            out.push(1);
            out.push(if *inner { 1 } else { 0 });
        }
        Value::Int(inner) => {
            out.push(2);
            out.extend_from_slice(&inner.to_le_bytes());
        }
        Value::Float(inner) => {
            out.push(3);
            out.extend_from_slice(&inner.to_bits().to_le_bytes());
        }
        Value::Text(inner) => {
            out.push(4);
            out.extend_from_slice(inner.as_bytes());
            out.push(0xff);
        }
        Value::Date(inner) => {
            out.push(5);
            out.extend_from_slice(&inner.year().to_le_bytes());
            out.extend_from_slice(&inner.ordinal().to_le_bytes());
        }
        Value::DateTime(inner) => {
            out.push(6);
            out.extend_from_slice(&inner.timestamp().to_le_bytes());
            out.extend_from_slice(&inner.nanosecond().to_le_bytes());
        }
        Value::Decimal(_) => {
            out.push(7);
            if let Value::Decimal(fraction) = value {
                out.extend_from_slice(fraction.decimal_string().as_bytes());
                out.push(0xff);
            }
        }
        Value::Infinity { sign, kind } => {
            out.push(8);
            out.extend_from_slice(&sign.to_le_bytes());
            out.push(match kind {
                TemporalKind::Date => 0,
                TemporalKind::DateTime => 1,
            });
        }
        Value::Array(items) => {
            out.push(9);
            out.extend_from_slice(&(items.len() as u64).to_le_bytes());
            for item in items {
                hash_value_bytes(item, out);
            }
        }
        Value::Record(pairs) => {
            out.push(10);
            out.extend_from_slice(&(pairs.len() as u64).to_le_bytes());
            for (name, item) in pairs {
                out.extend_from_slice(name.as_bytes());
                out.push(0xfe);
                hash_value_bytes(item, out);
            }
        }
    }
}

fn record_content_hash(record: &Record) -> u64 {
    let mut bytes = Vec::new();
    for (name, value) in record {
        bytes.extend_from_slice(name.as_bytes());
        bytes.push(0xfd);
        hash_value_bytes(value, &mut bytes);
    }
    let mut hash = 0xcbf29ce484222325u64;
    for byte in bytes {
        hash ^= byte as u64;
        hash = hash.wrapping_mul(0x100000001b3);
    }
    hash
}

thread_local! {
    /// Per-record unseeded RANDOM caches: `_yt_sql_random_cache` lives on the
    /// Python record dict; here it is keyed by the record's content identity.
    static RANDOM_CACHE: RefCell<HashMap<u64, HashMap<u64, f64>>> = RefCell::new(HashMap::new());

    static RANDOM_RUN_SEED: u64 = {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|duration| duration.as_nanos() as u64)
            .unwrap_or(0);
        let mut state = nanos;
        splitmix64(&mut state)
    };
}

/// One unseeded random draw, cached per record content and term position.
fn cached_random(record: &Record, position: u64) -> f64 {
    let content = record_content_hash(record);
    RANDOM_RUN_SEED.with(|seed| {
        let mut mixed = *seed;
        let mut draw = splitmix64(&mut mixed)
            ^ splitmix64(&mut {
                let mut state = content;
                splitmix64(&mut state)
            })
            ^ splitmix64(&mut {
                let mut state = position;
                splitmix64(&mut state)
            });
        let value = splitmix64(&mut draw);
        ((value >> 11) as f64) / ((1u64 << 53) as f64)
    })
}

/// Python `json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":"))`
/// over the runtime value domain, with `default=str` for non-JSON types.
fn python_json_dumps(value: &Value) -> String {
    let mut out = String::new();
    write_json(value, &mut out);
    out
}

fn push_json_string(text: &str, out: &mut String) {
    out.push('"');
    for character in text.chars() {
        match character {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\u{0008}' => out.push_str("\\b"),
            '\t' => out.push_str("\\t"),
            '\n' => out.push_str("\\n"),
            '\u{000c}' => out.push_str("\\f"),
            '\r' => out.push_str("\\r"),
            other if (other as u32) < 0x20 => {
                out.push_str(&format!("\\u{:04x}", other as u32));
            }
            other => out.push(other),
        }
    }
    out.push('"');
}

/// Python `repr(float)` / `json.dumps(float)`.
fn python_float_repr(value: f64) -> String {
    if value.is_nan() {
        return "NaN".to_string();
    }
    if value.is_infinite() {
        return if value > 0.0 { "Infinity" } else { "-Infinity" }.to_string();
    }
    if value == 0.0 {
        return if value.is_sign_negative() {
            "-0.0"
        } else {
            "0.0"
        }
        .to_string();
    }
    let negative = value < 0.0;
    let magnitude = value.abs();
    let scientific = format!("{:e}", magnitude);
    let (mantissa, exponent_text) = scientific
        .split_once('e')
        .unwrap_or((scientific.as_str(), "0"));
    let exponent: i64 = exponent_text.parse().unwrap_or(0);
    let digits: String = mantissa
        .chars()
        .filter(|character| *character != '.')
        .collect();
    let decpt = exponent + 1;
    if decpt <= -4 || decpt > 16 {
        let mut out = String::new();
        out.push_str(&digits[..1]);
        if digits.len() > 1 {
            out.push('.');
            out.push_str(&digits[1..]);
        }
        out.push('e');
        let exp = decpt - 1;
        out.push(if exp < 0 { '-' } else { '+' });
        let abs_exp = exp.abs();
        if abs_exp < 10 {
            out.push('0');
        }
        out.push_str(&abs_exp.to_string());
        if negative {
            return format!("-{out}");
        }
        return out;
    }
    let mut out = String::new();
    if decpt <= 0 {
        out.push_str("0.");
        for _ in 0..(-decpt) {
            out.push('0');
        }
        out.push_str(&digits);
    } else if decpt as usize >= digits.len() {
        out.push_str(&digits);
        for _ in 0..(decpt as usize - digits.len()) {
            out.push('0');
        }
        out.push_str(".0");
    } else {
        out.push_str(&digits[..decpt as usize]);
        out.push('.');
        out.push_str(&digits[decpt as usize..]);
    }
    if negative {
        return format!("-{out}");
    }
    out
}

fn write_json(value: &Value, out: &mut String) {
    match value {
        Value::Null => out.push_str("null"),
        Value::Bool(inner) => out.push_str(if *inner { "true" } else { "false" }),
        Value::Int(inner) => out.push_str(&inner.to_string()),
        Value::Float(inner) => out.push_str(&python_float_repr(*inner)),
        Value::Text(inner) => push_json_string(inner, out),
        Value::Date(inner) => {
            let text = format!(
                "{:04}-{:02}-{:02}",
                inner.year(),
                inner.month(),
                inner.day()
            );
            push_json_string(&text, out);
        }
        Value::DateTime(inner) => {
            // Python `str(datetime)` is `isoformat(sep=" ")`.
            let text = crate::value::datetime_isoformat(inner).replacen('T', " ", 1);
            push_json_string(&text, out);
        }
        Value::Decimal(_) => {
            if let Value::Decimal(fraction) = value {
                push_json_string(&fraction.decimal_string(), out);
            }
        }
        Value::Infinity { sign, .. } => {
            push_json_string(
                if *sign > 0 {
                    "INFINITY()"
                } else {
                    "-INFINITY()"
                },
                out,
            );
        }
        Value::Array(items) => {
            out.push('[');
            for (index, item) in items.iter().enumerate() {
                if index > 0 {
                    out.push(',');
                }
                write_json(item, out);
            }
            out.push(']');
        }
        Value::Record(pairs) => {
            let mut sorted: Vec<&(String, Value)> = pairs.iter().collect();
            sorted.sort_by(|a, b| a.0.cmp(&b.0));
            out.push('{');
            for (index, (name, item)) in sorted.iter().enumerate() {
                if index > 0 {
                    out.push(',');
                }
                push_json_string(name, out);
                out.push(':');
                write_json(item, out);
            }
            out.push('}');
        }
    }
}

/// Port of `_stable_random_identity`: stable logical identity for seeded
/// randomness, serialised exactly as Python `json.dumps`.
fn stable_random_identity(record: &Record) -> String {
    const PREFERRED_KEYS: [&str; 7] = [
        "_yt_sql_source",
        "_yt_sql_source_facet",
        "extractor",
        "extractor_key",
        "webpage_url",
        "url",
        "id",
    ];
    let mut preferred: Vec<Value> = Vec::new();
    for key in PREFERRED_KEYS {
        if let Some(value) = record_get(record, key)
            && !value.is_null()
        {
            preferred.push(Value::Array(vec![
                Value::Text(key.to_string()),
                value.clone(),
            ]));
        }
    }
    if !preferred.is_empty() {
        return python_json_dumps(&Value::Array(preferred));
    }
    let mut public: Record = record
        .iter()
        .filter(|(key, _)| !key.starts_with("_yt_sql_"))
        .cloned()
        .collect();
    public.sort_by(|a, b| a.0.cmp(&b.0));
    python_json_dumps(&Value::Record(public))
}

/// Port of `_evaluate_random`: volatile or reproducibly seeded row randomness.
fn evaluate_random(function: &ScalarFunction, record: &Record) -> Value {
    if let Some(first) = function.args.first()
        && let Expr::Literal(literal) = first
        && let Value::Int(seed) = decode_literal(literal, None)
    {
        let payload = format!("{seed}\0{}", stable_random_identity(record));
        let digest = blake2b(payload.as_bytes(), 8, b"yt-sql-rnd");
        let mut digest_bytes = [0u8; 8];
        digest_bytes.copy_from_slice(&digest);
        let integer = u64::from_be_bytes(digest_bytes) >> 11;
        return Value::Float(integer as f64 / (1u64 << 53) as f64);
    }
    // A malformed seed falls through to the volatile path; resolution
    // rejects such queries before evaluation.
    Value::Float(cached_random(record, function.position as u64))
}

// ---------------------------------------------------------------------------
// LIKE (port of `_exact_like_literal` / `_compile_like_pattern`)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq)]
enum LikeToken {
    Star,
    One,
    Lit(char),
}

/// Classify a LIKE pattern; `Some(literal)` when it is one exact string.
fn exact_like_literal(pattern: &str) -> Option<String> {
    let mut pieces = String::new();
    let mut escaped = false;
    for character in pattern.chars() {
        if escaped {
            pieces.push(character);
            escaped = false;
        } else if character == '\\' {
            escaped = true;
        } else if character == '%' || character == '_' {
            return None;
        } else {
            pieces.push(character);
        }
    }
    if escaped {
        return None;
    }
    Some(pieces)
}

fn compile_like_tokens(pattern: &str) -> Vec<LikeToken> {
    let mut tokens = Vec::new();
    let mut escaped = false;
    for character in pattern.chars() {
        if escaped {
            tokens.push(LikeToken::Lit(character));
            escaped = false;
        } else if character == '\\' {
            escaped = true;
        } else if character == '%' {
            tokens.push(LikeToken::Star);
        } else if character == '_' {
            tokens.push(LikeToken::One);
        } else {
            tokens.push(LikeToken::Lit(character));
        }
    }
    tokens
}

/// Anchored wildcard match: `%` spans any run of characters (including none
/// and newlines), `_` matches exactly one character.
fn like_match(value: &[char], tokens: &[LikeToken]) -> bool {
    let mut value_index = 0usize;
    let mut token_index = 0usize;
    let mut star: Option<(usize, usize)> = None;
    while value_index < value.len() {
        let matched = if token_index < tokens.len() {
            match tokens[token_index] {
                LikeToken::Lit(character) => value[value_index] == character,
                LikeToken::One => true,
                LikeToken::Star => false,
            }
        } else {
            false
        };
        if matched {
            value_index += 1;
            token_index += 1;
            continue;
        }
        if token_index < tokens.len() && tokens[token_index] == LikeToken::Star {
            star = Some((value_index, token_index));
            token_index += 1;
            continue;
        }
        if let Some((star_value, star_token)) = star {
            star = Some((star_value + 1, star_token));
            value_index = star_value + 1;
            token_index = star_token + 1;
            continue;
        }
        return false;
    }
    while token_index < tokens.len() && tokens[token_index] == LikeToken::Star {
        token_index += 1;
    }
    token_index == tokens.len()
}

/// Return whether one string satisfies an yt-sql LIKE pattern.
pub fn like_matches(value: &str, pattern: &str, case_insensitive: bool) -> bool {
    if !case_insensitive && let Some(literal) = exact_like_literal(pattern) {
        return value == literal;
    }
    let (value_text, pattern_text) = if case_insensitive {
        (default_case_fold_str(value), default_case_fold_str(pattern))
    } else {
        (value.to_string(), pattern.to_string())
    };
    let value_chars: Vec<char> = value_text.chars().collect();
    like_match(&value_chars, &compile_like_tokens(&pattern_text))
}

// ---------------------------------------------------------------------------
// Scalar expression evaluation
// ---------------------------------------------------------------------------

fn runtime_indexed_value(collection: &Value, index: &Value) -> Value {
    if collection.is_null() || index.is_null() {
        return Value::Null;
    }
    let index = match index {
        Value::Int(inner) if *inner >= 0 => *inner,
        _ => return Value::Null,
    };
    match collection {
        Value::Array(items) => items.get(index as usize).cloned().unwrap_or(Value::Null),
        _ => Value::Null,
    }
}

fn runtime_member_value(value: &Value, member: &str) -> Value {
    match value {
        Value::Record(pairs) => pairs
            .iter()
            .find(|(name, _)| name == member)
            .map(|(_, item)| item.clone())
            .unwrap_or(Value::Null),
        _ => Value::Null,
    }
}

/// Port of `_apply_scalar_function_values` (group/shared function body).
fn apply_scalar_function_values(name: &str, values: &[Value]) -> Value {
    let first = values.first().cloned().unwrap_or(Value::Null);
    match name {
        "LOWER" => match first {
            Value::Text(text) => Value::Text(text.to_lowercase()),
            _ => Value::Null,
        },
        "UPPER" => match first {
            Value::Text(text) => Value::Text(text.to_uppercase()),
            _ => Value::Null,
        },
        "LENGTH" => match first {
            Value::Text(text) => Value::Int(text.chars().count() as i64),
            _ => Value::Null,
        },
        "CARDINALITY" => match first {
            Value::Null => Value::Null,
            Value::Array(items) => Value::Int(items.len() as i64),
            _ => Value::Null,
        },
        "COALESCE" => values
            .iter()
            .find(|value| !value.is_null())
            .cloned()
            .unwrap_or(Value::Null),
        "CONCAT" => {
            if values.iter().any(Value::is_null) {
                return Value::Null;
            }
            if values.iter().all(|value| matches!(value, Value::Text(_))) {
                let mut text = String::new();
                for value in values {
                    if let Value::Text(part) = value {
                        text.push_str(part);
                    }
                }
                return Value::Text(text);
            }
            Value::Null
        }
        "CHAR" => {
            if values.iter().any(Value::is_null) {
                return Value::Null;
            }
            let mut text = String::new();
            for value in values {
                match coerce_char_codepoint(value) {
                    Some(codepoint) => match char::from_u32(codepoint) {
                        Some(character) => text.push(character),
                        None => return Value::Null,
                    },
                    None => return Value::Null,
                }
            }
            Value::Text(text)
        }
        "NULLIF" => {
            let first = values.first().cloned().unwrap_or(Value::Null);
            let second = values.get(1).cloned().unwrap_or(Value::Null);
            if first.is_null() {
                return Value::Null;
            }
            if second.is_null() {
                return first;
            }
            if key_equal(&first, &second) {
                Value::Null
            } else {
                first
            }
        }
        "GREATEST" => {
            if values.iter().any(Value::is_null) {
                return Value::Null;
            }
            python_max(values).unwrap_or(Value::Null)
        }
        "LEAST" => {
            if values.iter().any(Value::is_null) {
                return Value::Null;
            }
            python_min(values).unwrap_or(Value::Null)
        }
        _ => Value::Null,
    }
}

/// Port of `_coerce_char_codepoint`; `None` marks TypeError/ValueError.
pub fn coerce_char_codepoint(value: &Value) -> Option<u32> {
    let codepoint = match value {
        Value::Bool(_) => return None,
        Value::Int(inner) => *inner,
        Value::Float(inner) => {
            if *inner != inner.trunc() || !inner.is_finite() {
                return None;
            }
            *inner as i64
        }
        _ => return None,
    };
    if !(0..=0x10FFFF).contains(&codepoint) || (0xD800..=0xDFFF).contains(&codepoint) {
        return None;
    }
    Some(codepoint as u32)
}

/// Evaluate a scalar expression in an explicit runtime context.
pub fn evaluate_scalar_expression(expression: &Expr, context: &EvaluationContext) -> Value {
    evaluate_scalar(expression, context)
}

fn evaluate_scalar(expression: &Expr, context: &EvaluationContext) -> Value {
    match expression {
        Expr::Field(field) => canonical_record_value(
            context.record(),
            &CanonicalField::Field(field.clone()),
            false,
        ),
        Expr::RelationField(field) => {
            let Some(relation_record) = context.relation_record(&field.qualifier) else {
                return Value::Null;
            };
            canonical_record_value(
                relation_record,
                &CanonicalField::Named {
                    name: field.name.clone(),
                    kind: field.kind.clone(),
                },
                false,
            )
        }
        Expr::Literal(literal) => decode_literal(literal, None),
        Expr::Window(_) => {
            // Window values are established once per query body at the window
            // stage and carried by the row under their semantic identity. A
            // missing entry means a window expression escaped the
            // projection-only placement rules.
            let key = semantic_key(expression);
            let environment = record_get(context.record(), "_yt_sql_window_values");
            match environment {
                Some(Value::Record(pairs)) => pairs
                    .iter()
                    .find(|(existing, _)| existing == &key)
                    .map(|(_, value)| value.clone())
                    .unwrap_or(Value::Null),
                _ => Value::Null,
            }
        }
        Expr::CollectionElement(reference) => context.collection_element(reference.scope_distance),
        Expr::Unary(unary) => {
            let value = evaluate_scalar(&unary.operand, context);
            if value.is_null() {
                return Value::Null;
            }
            scalar_unary_arith(&unary.operator, &value)
        }
        Expr::Binary(binary) => {
            let left = evaluate_scalar(&binary.left, context);
            let right = evaluate_scalar(&binary.right, context);
            if left.is_null() || right.is_null() {
                return Value::Null;
            }
            match binary.operator.as_str() {
                "+" | "-" | "*" | "/" | "%" => {
                    scalar_binary_arith(&binary.operator, &left, &right).unwrap_or(Value::Null)
                }
                _ => Value::Null,
            }
        }
        Expr::Index(index) => {
            let collection = evaluate_scalar(&index.collection, context);
            let position = evaluate_scalar(&index.index, context);
            runtime_indexed_value(&collection, &position)
        }
        Expr::Member(member) => {
            let value = evaluate_scalar(&member.value, context);
            runtime_member_value(&value, &member.member)
        }
        Expr::Case(case) => {
            for branch in &case.whens {
                if evaluate_boolean_expression(&branch.condition, context) == Some(true) {
                    return evaluate_scalar(&branch.result, context);
                }
            }
            match &case.else_result {
                Some(else_result) => evaluate_scalar(else_result, context),
                None => Value::Null,
            }
        }
        Expr::Function(function) => {
            let values: Vec<Value> = function
                .args
                .iter()
                .map(|argument| evaluate_scalar(argument, context))
                .collect();
            match function.name.as_str() {
                "RANDOM" => evaluate_random(function, context.record()),
                "LOWER" | "UPPER" | "LENGTH" | "CARDINALITY" | "COALESCE" | "CONCAT" | "CHAR"
                | "NULLIF" | "GREATEST" | "LEAST" => {
                    apply_scalar_function_values(&function.name, &values)
                }
                _ => Value::Null,
            }
        }
        Expr::CollectionCount(count) => {
            let collection = evaluate_scalar(&count.collection, context);
            let Value::Array(items) = collection else {
                return Value::Null;
            };
            let mut total = 0i64;
            for element in items {
                if evaluate_boolean_expression(
                    &count.predicate,
                    &context.bind_collection_element(element),
                ) == Some(true)
                {
                    total += 1;
                }
            }
            Value::Int(total)
        }
        Expr::CollectionFilter(filter) => {
            let collection = evaluate_scalar(&filter.collection, context);
            let Value::Array(items) = collection else {
                return Value::Null;
            };
            Value::Array(
                items
                    .into_iter()
                    .filter(|element| {
                        evaluate_boolean_expression(
                            &filter.predicate,
                            &context.bind_collection_element(element.clone()),
                        ) == Some(true)
                    })
                    .collect(),
            )
        }
        Expr::CollectionProjection(projection) => {
            if projection.evaluation_fusion_safe
                && let Expr::CollectionFilter(source_filter) = &*projection.collection
            {
                let collection = evaluate_scalar(&source_filter.collection, context);
                let Value::Array(items) = collection else {
                    return Value::Null;
                };
                let mut projected: Vec<Value> = Vec::new();
                for element in items {
                    let element_context = context.bind_collection_element(element.clone());
                    if evaluate_boolean_expression(&source_filter.predicate, &element_context)
                        == Some(true)
                    {
                        projected.push(evaluate_scalar(&projection.projection, &element_context));
                    }
                }
                return Value::Array(projected);
            }
            let collection = evaluate_scalar(&projection.collection, context);
            let Value::Array(items) = collection else {
                return Value::Null;
            };
            Value::Array(
                items
                    .into_iter()
                    .map(|element| {
                        evaluate_scalar(
                            &projection.projection,
                            &context.bind_collection_element(element),
                        )
                    })
                    .collect(),
            )
        }
        Expr::Aggregate(_) => Value::Null,
    }
}

// ---------------------------------------------------------------------------
// Canonical record values
// ---------------------------------------------------------------------------

/// The Python overloads of `canonical_record_value`'s `field` parameter.
#[derive(Debug, Clone)]
pub enum CanonicalField {
    Field(crate::model::Field),
    RelationField(RelationField),
    OrderTerm(crate::model::OrderTerm),
    Select(SelectTerm),
    /// A plain field name plus optional declared kind.
    Named {
        name: String,
        kind: Option<String>,
    },
}

/// Identify a deferred result-position projection.
fn is_final_position(term: &SelectTerm) -> bool {
    match &term.expression {
        Some(expression) => {
            matches!(&**expression, Expr::Function(function) if function.name == "POSITION")
        }
        None => false,
    }
}

fn canonical_plain_field(record: &Record, name: &str, kind: Option<&str>) -> Value {
    let Some(value) = record_get(record, name) else {
        return Value::Null;
    };
    if value.is_null() {
        return Value::Null;
    }
    match kind {
        Some("date") => match value {
            Value::Date(_) => value.clone(),
            Value::Text(text) => match parse_date_literal(text, &default_date_context()) {
                Ok(date) => Value::Date(date),
                Err(_) => value.clone(),
            },
            _ => value.clone(),
        },
        Some("datetime") => timestamp_to_datetime(value),
        _ => value.clone(),
    }
}

/// Return a value in its canonical portable shape.
pub fn canonical_record_value(
    record: &Record,
    field: &CanonicalField,
    materialised: bool,
) -> Value {
    match field {
        CanonicalField::RelationField(relation_field) => {
            let context = EvaluationContext::new(record.clone());
            let Some(relation_record) = context.relation_record(&relation_field.qualifier) else {
                return Value::Null;
            };
            canonical_plain_field(
                relation_record,
                &relation_field.name,
                relation_field.kind.as_deref(),
            )
        }
        CanonicalField::Field(field) => {
            canonical_plain_field(record, &field.name, field.kind.as_deref())
        }
        CanonicalField::OrderTerm(term) => {
            if let Some(expression) = &term.expression {
                return evaluate_scalar(expression, &EvaluationContext::new((*record).clone()));
            }
            canonical_plain_field(record, &term.field, term.kind.as_deref())
        }
        CanonicalField::Select(term) => {
            let materialised_result = materialised
                || matches!(
                    record_get(record, "_yt_sql_aggregate_result"),
                    Some(Value::Bool(true))
                )
                || matches!(
                    record_get(record, "_yt_sql_result_row"),
                    Some(Value::Bool(true))
                );
            let aggregate_projection = term
                .expression
                .as_ref()
                .map(|expression| contains_aggregate(expression))
                .unwrap_or(false);
            let volatile_projection = term
                .expression
                .as_ref()
                .map(|expression| contains_random(expression))
                .unwrap_or(false);
            let deferred_position = is_final_position(term);
            let window_projection = matches!(term.expression.as_deref(), Some(Expr::Window(_)));
            let output_name = term.output_name().to_string();
            if record_get(record, &output_name).is_some()
                && (materialised_result
                    || aggregate_projection
                    || volatile_projection
                    || deferred_position
                    || window_projection)
            {
                return record_get(record, &output_name)
                    .cloned()
                    .unwrap_or(Value::Null);
            }
            if deferred_position {
                // POSITION() must be evaluated at the final-result stage.
                return Value::Null;
            }
            if window_projection {
                // Window functions must be evaluated at the window stage.
                return Value::Null;
            }
            if let Some(expression) = &term.expression {
                return evaluate_scalar(expression, &EvaluationContext::new((*record).clone()));
            }
            canonical_plain_field(record, &term.field, term.kind.as_deref())
        }
        CanonicalField::Named { name, kind } => {
            canonical_plain_field(record, name, kind.as_deref())
        }
    }
}

// ---------------------------------------------------------------------------
// Three-valued Boolean evaluation
// ---------------------------------------------------------------------------

/// Port of `existential_truth` (a NULL collection yields UNKNOWN at the caller).
fn existential_truth<I: Iterator<Item = Option<bool>>>(results: I) -> Option<bool> {
    let mut saw_unknown = false;
    for result in results {
        match result {
            Some(true) => return Some(true),
            Some(false) => {}
            None => saw_unknown = true,
        }
    }
    if saw_unknown { None } else { Some(false) }
}

/// Port of `universal_truth` (a NULL collection yields UNKNOWN at the caller).
fn universal_truth<I: Iterator<Item = Option<bool>>>(results: I) -> Option<bool> {
    let mut saw_unknown = false;
    for result in results {
        match result {
            Some(false) => return Some(false),
            Some(true) => {}
            None => saw_unknown = true,
        }
    }
    if saw_unknown { None } else { Some(true) }
}

/// SQL NULL-safe comparison with the observable yt-sql contract.
fn evaluate_comparison(operator: &str, left: &Value, right: &Value) -> Option<bool> {
    match operator {
        "IS DISTINCT FROM" => {
            if left.is_null() || right.is_null() {
                return Some(left.is_null() != right.is_null());
            }
            Some(!key_equal(left, right))
        }
        "IS NOT DISTINCT FROM" => {
            if left.is_null() || right.is_null() {
                return Some(left.is_null() == right.is_null());
            }
            Some(key_equal(left, right))
        }
        _ if left.is_null() || right.is_null() => None,
        "=" => Some(key_equal(left, right)),
        "!=" => Some(!key_equal(left, right)),
        "<" | "<=" | ">" | ">=" => match left.compare(right) {
            None => Some(false),
            Some(ordering) => Some(match operator {
                "<" => ordering == Ordering::Less,
                "<=" => ordering != Ordering::Greater,
                ">" => ordering == Ordering::Greater,
                ">=" => ordering != Ordering::Less,
                _ => false,
            }),
        },
        _ => None,
    }
}

/// The shared AND/OR truth table with short-circuit reachability.
fn and_or_truth(operator: &str, left: Option<bool>, right: Option<bool>) -> Option<bool> {
    match operator {
        "AND" => {
            if left == Some(false) {
                return Some(false);
            }
            if right == Some(false) {
                return Some(false);
            }
            if left.is_none() || right.is_none() {
                return None;
            }
            Some(true)
        }
        "OR" => {
            if left == Some(true) {
                return Some(true);
            }
            if right == Some(true) {
                return Some(true);
            }
            if left.is_none() || right.is_none() {
                return None;
            }
            Some(false)
        }
        _ => None,
    }
}

/// Recover the compared field (name and kind) for a row-level `Binary`
/// comparison. The parser encodes the field as a bare unquoted text literal;
/// its kind is inferred the same way the schema infers it.
fn binary_comparison_field(binary: &crate::model::Binary) -> Option<(String, Option<String>)> {
    let BoolExpr::Literal(literal) = &*binary.left else {
        return None;
    };
    if literal.quoted {
        return None;
    }
    let text = match &literal.value {
        LiteralValue::Text(text) => text.clone(),
        LiteralValue::Raw => literal.raw.clone(),
        _ => return None,
    };
    let kind = infer_kind(&text, &[]);
    Some((text, Some(kind)))
}

/// Evaluate a Boolean expression using SQL-like three-valued logic.
pub fn evaluate(node: &BoolExpr, record: &EvaluationContext) -> Option<bool> {
    evaluate_boolean_expression(node, record)
}

/// Evaluate an optional resolved predicate; a missing predicate is TRUE.
fn evaluate_predicate(predicate: Option<&BoolExpr>, context: &EvaluationContext) -> Option<bool> {
    match predicate {
        None => Some(true),
        Some(node) => evaluate_boolean_expression(node, context),
    }
}

fn evaluate_boolean_expression(node: &BoolExpr, context: &EvaluationContext) -> Option<bool> {
    match node {
        BoolExpr::Literal(literal) => match &literal.value {
            LiteralValue::Null => None,
            LiteralValue::Bool(inner) => Some(*inner),
            _ => None,
        },
        BoolExpr::Unary(unary) => {
            evaluate_boolean_expression(&unary.operand, context).map(|value| !value)
        }
        BoolExpr::Binary(binary) if binary.operator == "AND" || binary.operator == "OR" => {
            let left = evaluate_boolean_expression(&binary.left, context);
            if left == Some(false) && binary.operator == "AND" {
                return Some(false);
            }
            if left == Some(true) && binary.operator == "OR" {
                return Some(true);
            }
            let right = evaluate_boolean_expression(&binary.right, context);
            and_or_truth(&binary.operator, left, right)
        }
        BoolExpr::CollectionPredicate(predicate) => {
            let collection = evaluate_scalar(&predicate.collection, context);
            if collection.is_null() {
                // A NULL collection yields UNKNOWN for either quantifier.
                return None;
            }
            let Value::Array(items) = collection else {
                return None;
            };
            let results = items.into_iter().map(|element| {
                evaluate_boolean_expression(
                    &predicate.predicate,
                    &context.bind_collection_element(element),
                )
            });
            if predicate.quantifier == "ANY" {
                existential_truth(results)
            } else if predicate.quantifier == "ALL" {
                universal_truth(results)
            } else {
                None
            }
        }
        BoolExpr::TruthTest(truth) => {
            let value = evaluate_boolean_expression(&truth.operand, context);
            let result = match truth.truth.as_str() {
                "TRUE" => value == Some(true),
                "FALSE" => value == Some(false),
                "UNKNOWN" => value.is_none(),
                _ => return None,
            };
            Some(if truth.negated { !result } else { result })
        }
        BoolExpr::ScalarIsNull(is_null) => {
            let result = evaluate_scalar(&is_null.expression, context).is_null();
            Some(if is_null.negated { !result } else { result })
        }
        BoolExpr::ScalarComparison(comparison) => {
            let left = evaluate_scalar(&comparison.left, context);
            // Row-level field-vs-literal comparisons decode the literal with
            // the field's kind and apply enum-value folding, mirroring the
            // Python row-level `Binary` path.
            if let (Expr::Field(field), Expr::Literal(literal)) =
                (&*comparison.left, &*comparison.right)
                && matches!(
                    comparison.operator.as_str(),
                    "=" | "!=" | "<" | "<=" | ">" | ">="
                )
            {
                let right = decode_literal(literal, field.kind.as_deref());
                if left.is_null() || right.is_null() {
                    return None;
                }
                let (folded_left, folded_right) =
                    comparison_values_field(&field.name, &left, &right);
                return evaluate_comparison(&comparison.operator, &folded_left, &folded_right);
            }
            let right = evaluate_scalar(&comparison.right, context);
            evaluate_comparison(&comparison.operator, &left, &right)
        }
        BoolExpr::Binary(binary) => {
            // Row-level comparison against a literal.
            let (name, kind) = binary_comparison_field(binary)?;
            let left = canonical_record_value(
                context.record(),
                &CanonicalField::Named {
                    name: name.clone(),
                    kind: kind.clone(),
                },
                false,
            );
            let right = match &*binary.right {
                BoolExpr::Literal(literal) => decode_literal(literal, kind.as_deref()),
                _ => Value::Null,
            };
            if left.is_null() || right.is_null() {
                return None;
            }
            let (folded_left, folded_right) = comparison_values_field(&name, &left, &right);
            evaluate_comparison(&binary.operator, &folded_left, &folded_right)
        }
        BoolExpr::Between(between) => {
            let value = canonical_record_value(
                context.record(),
                &CanonicalField::Field(between.field.clone()),
                false,
            );
            if value.is_null() {
                return None;
            }
            let kind = between.field.kind.as_deref();
            let lower = decode_literal(&between.lower, kind);
            let upper = decode_literal(&between.upper, kind);
            let mut result = true;
            match lower.compare(&value) {
                Some(Ordering::Less | Ordering::Equal) => {}
                _ => result = false,
            }
            if result {
                match value.compare(&upper) {
                    Some(Ordering::Less | Ordering::Equal) => {}
                    _ => result = false,
                }
            }
            Some(if between.negated { !result } else { result })
        }
        BoolExpr::InList(in_list) => {
            let value = canonical_record_value(
                context.record(),
                &CanonicalField::Field(in_list.field.clone()),
                false,
            );
            if value.is_null() {
                return None;
            }
            let mut result = false;
            for item in &in_list.values {
                let decoded = decode_literal(item, in_list.field.kind.as_deref());
                let (folded_left, folded_right) =
                    comparison_values_field(&in_list.field.name, &value, &decoded);
                if key_equal(&folded_left, &folded_right) {
                    result = true;
                    break;
                }
            }
            Some(if in_list.negated { !result } else { result })
        }
        BoolExpr::IsNull(is_null) => {
            let result = canonical_record_value(
                context.record(),
                &CanonicalField::Field(is_null.field.clone()),
                false,
            )
            .is_null();
            Some(if is_null.negated { !result } else { result })
        }
        BoolExpr::TextPredicate(text) => {
            let value = canonical_record_value(
                context.record(),
                &CanonicalField::Field(text.field.clone()),
                false,
            );
            if value.is_null() {
                return None;
            }
            let Value::Text(value_text) = value else {
                return Some(false);
            };
            let needle = literal_text(&text.value);
            let result = match text.operator.as_str() {
                "CONTAINS" => {
                    default_case_fold_str(&value_text).contains(&default_case_fold_str(&needle))
                }
                "MATCHES" => regex::Regex::new(&needle)
                    .map(|expression| expression.is_match(&value_text))
                    .unwrap_or(false),
                "LIKE" | "ILIKE" => like_matches(&value_text, &needle, text.operator == "ILIKE"),
                _ => return None,
            };
            Some(if text.negated { !result } else { result })
        }
    }
}

// ---------------------------------------------------------------------------
// Aggregate group evaluation
// ---------------------------------------------------------------------------

/// Evaluate one resolved SELECT/HAVING/ORDER expression over a group.
fn evaluate_group_expression(expression: &Expr, group: &[Record]) -> Value {
    if let Expr::Aggregate(aggregate) = expression {
        let mut rows: Vec<Record> = group.to_vec();
        if let Some(predicate) = &aggregate.filter_predicate {
            rows.retain(|row| {
                evaluate_boolean_expression(predicate, &EvaluationContext::new(row.clone()))
                    == Some(true)
            });
        }
        if aggregate.count_star {
            return Value::Int(rows.len() as i64);
        }
        let Some(argument) = aggregate.args.first() else {
            return Value::Null;
        };
        let non_null: Vec<Value> = rows
            .iter()
            .map(|row| evaluate_scalar(argument, &EvaluationContext::new(row.clone())))
            .filter(|value| !value.is_null())
            .collect();
        return match aggregate.name.as_str() {
            "COUNT" => Value::Int(non_null.len() as i64),
            _ if non_null.is_empty() => Value::Null,
            "SUM" => sum_values(&non_null).unwrap_or(Value::Null),
            "AVG" => sum_values(&non_null)
                .and_then(|total| average_value(&total, non_null.len()))
                .unwrap_or(Value::Null),
            "MIN" => python_min(&non_null).unwrap_or(Value::Null),
            "MAX" => python_max(&non_null).unwrap_or(Value::Null),
            _ => Value::Null,
        };
    }
    let representative: Record = group.first().cloned().unwrap_or_default();
    match expression {
        Expr::Field(_) | Expr::RelationField(_) | Expr::Literal(_) => {
            evaluate_scalar(expression, &EvaluationContext::new(representative))
        }
        Expr::Unary(unary) => {
            let value = evaluate_group_expression(&unary.operand, group);
            if value.is_null() {
                return Value::Null;
            }
            scalar_unary_arith(&unary.operator, &value)
        }
        Expr::Binary(binary) => {
            let left = evaluate_group_expression(&binary.left, group);
            let right = evaluate_group_expression(&binary.right, group);
            if left.is_null() || right.is_null() {
                return Value::Null;
            }
            match binary.operator.as_str() {
                "+" | "-" | "*" | "/" | "%" => {
                    scalar_binary_arith(&binary.operator, &left, &right).unwrap_or(Value::Null)
                }
                _ => Value::Null,
            }
        }
        Expr::Function(function) => {
            if function.name == "RANDOM" {
                return evaluate_random(function, &representative);
            }
            let values: Vec<Value> = function
                .args
                .iter()
                .map(|argument| evaluate_group_expression(argument, group))
                .collect();
            apply_scalar_function_values(&function.name, &values)
        }
        Expr::Case(case) => {
            for branch in &case.whens {
                if evaluate_boolean_expression(
                    &branch.condition,
                    &EvaluationContext::new(representative.clone()),
                ) == Some(true)
                {
                    return evaluate_group_expression(&branch.result, group);
                }
            }
            match &case.else_result {
                Some(else_result) => evaluate_group_expression(else_result, group),
                None => Value::Null,
            }
        }
        _ => Value::Null,
    }
}

/// Evaluate one HAVING node over an aggregate group.
fn evaluate_having_opt(predicate: Option<&BoolExpr>, group: &[Record]) -> Option<bool> {
    match predicate {
        None => Some(true),
        Some(node) => evaluate_having(node, group),
    }
}

fn evaluate_having(node: &BoolExpr, group: &[Record]) -> Option<bool> {
    match node {
        BoolExpr::Literal(literal) => match &literal.value {
            LiteralValue::Null => None,
            LiteralValue::Bool(inner) => Some(*inner),
            _ => None,
        },
        BoolExpr::Unary(unary) => evaluate_having(&unary.operand, group).map(|value| !value),
        BoolExpr::Binary(binary) if binary.operator == "AND" || binary.operator == "OR" => {
            let left = evaluate_having(&binary.left, group);
            if left == Some(false) && binary.operator == "AND" {
                return Some(false);
            }
            if left == Some(true) && binary.operator == "OR" {
                return Some(true);
            }
            let right = evaluate_having(&binary.right, group);
            and_or_truth(&binary.operator, left, right)
        }
        BoolExpr::TruthTest(truth) => {
            let value = evaluate_having(&truth.operand, group);
            let result = match truth.truth.as_str() {
                "TRUE" => value == Some(true),
                "FALSE" => value == Some(false),
                "UNKNOWN" => value.is_none(),
                _ => return None,
            };
            Some(if truth.negated { !result } else { result })
        }
        BoolExpr::ScalarIsNull(is_null) => {
            let result = evaluate_group_expression(&is_null.expression, group).is_null();
            Some(if is_null.negated { !result } else { result })
        }
        BoolExpr::ScalarComparison(comparison) => {
            let left = evaluate_group_expression(&comparison.left, group);
            let right = evaluate_group_expression(&comparison.right, group);
            evaluate_comparison(&comparison.operator, &left, &right)
        }
        _ => None,
    }
}

// ---------------------------------------------------------------------------
// Ordering, slicing and dedup helpers
// ---------------------------------------------------------------------------

/// Sort one ORDER BY term, retaining NULL-last placement in either direction.
fn order_items<T>(
    items: Vec<T>,
    term: &crate::model::OrderTerm,
    value_of: impl Fn(&T) -> Value,
) -> Result<Vec<T>, String> {
    let mut present: Vec<(T, Value)> = Vec::new();
    let mut missing: Vec<T> = Vec::new();
    for item in items {
        let value = value_of(&item);
        if value.is_null() {
            missing.push(item);
        } else {
            present.push((item, value));
        }
    }
    let mut failed = false;
    present.sort_by(|a, b| {
        if failed {
            return Ordering::Equal;
        }
        let comparison = if term.descending {
            b.1.compare(&a.1)
        } else {
            a.1.compare(&b.1)
        };
        match comparison {
            Some(ordering) => ordering,
            None => {
                failed = true;
                Ordering::Equal
            }
        }
    });
    if failed {
        return Err("ORDER BY contains values that cannot be compared".to_string());
    }
    let mut ordered: Vec<T> = present.into_iter().map(|(item, _)| item).collect();
    ordered.extend(missing);
    Ok(ordered)
}

/// Python slice `rows[offset:]` including negative-offset behaviour.
fn slice_offset(mut rows: Vec<Record>, offset: i64) -> Vec<Record> {
    if offset == 0 {
        return rows;
    }
    let start = if offset < 0 {
        (rows.len() as i64 + offset).max(0) as usize
    } else {
        (offset as usize).min(rows.len())
    };
    rows = rows.into_iter().skip(start).collect();
    rows
}

/// Python slice `rows[:limit]` including negative-limit behaviour.
fn slice_limit(mut rows: Vec<Record>, limit: i64) -> Vec<Record> {
    if limit >= 0 {
        rows.truncate(limit as usize);
    } else {
        let keep = (rows.len() as i64 + limit).max(0) as usize;
        rows.truncate(keep);
    }
    rows
}

/// Attach deferred projections after deduplication and ordering, then slice.
fn slice_final_result(rows: Vec<Record>, query: &Query) -> Vec<Record> {
    let mut rows = slice_offset(rows, query.offset);
    if let Some(limit) = query.limit {
        rows = slice_limit(rows, limit);
    }
    let names: Vec<String> = query
        .select
        .iter()
        .filter(|term| is_final_position(term))
        .map(|term| term.output_name().to_string())
        .collect();
    if names.is_empty() {
        return rows;
    }
    let start = query.offset + 1;
    rows.into_iter()
        .enumerate()
        .map(|(index, row)| {
            let mut row = row;
            for name in &names {
                record_set(&mut row, name, Value::Int(start + index as i64));
            }
            row
        })
        .collect()
}

/// Dedup rows by the SELECT projection values, preserving first occurrence.
fn dedup_by_select_terms(rows: Vec<Record>, query: &Query) -> Vec<Record> {
    let mut seen: Vec<Vec<Value>> = Vec::new();
    let mut unique: Vec<Record> = Vec::new();
    for row in rows {
        let mut key: Vec<Value> = Vec::new();
        for term in &query.select {
            if is_final_position(term) {
                continue;
            }
            key.push(
                record_get(&row, term.output_name())
                    .cloned()
                    .unwrap_or(Value::Null),
            );
        }
        if seen.iter().any(|existing| keys_equal(existing, &key)) {
            continue;
        }
        seen.push(key);
        unique.push(row);
    }
    unique
}

/// Port of `_union_row_key` (values keyed by output name, missing means NULL).
fn union_row_key(row: &Record, output_names: &[String]) -> Vec<Value> {
    output_names
        .iter()
        .map(|name| record_get(row, name).cloned().unwrap_or(Value::Null))
        .collect()
}

// ---------------------------------------------------------------------------
// Query semantics (port of query_semantics.py)
// ---------------------------------------------------------------------------

/// Whether a scalar expression subtree contains a window function.
pub fn contains_window(expression: &Expr) -> bool {
    match expression {
        Expr::Window(_) => true,
        Expr::Field(_) | Expr::RelationField(_) | Expr::Literal(_) | Expr::CollectionElement(_) => {
            false
        }
        Expr::Unary(unary) => contains_window(&unary.operand),
        Expr::Binary(binary) => contains_window(&binary.left) || contains_window(&binary.right),
        Expr::Index(index) => contains_window(&index.collection) || contains_window(&index.index),
        Expr::Member(member) => contains_window(&member.value),
        Expr::Function(function) => function.args.iter().any(contains_window),
        Expr::Aggregate(aggregate) => {
            aggregate.args.iter().any(contains_window)
                || aggregate
                    .filter_predicate
                    .as_deref()
                    .map(having_contains_window)
                    .unwrap_or(false)
        }
        Expr::Case(case) => {
            case.whens.iter().any(|branch| {
                bool_contains_window(&branch.condition) || contains_window(&branch.result)
            }) || case
                .else_result
                .as_deref()
                .map(contains_window)
                .unwrap_or(false)
        }
        Expr::CollectionCount(count) => {
            contains_window(&count.collection) || having_contains_window(&count.predicate)
        }
        Expr::CollectionFilter(filter) => {
            contains_window(&filter.collection) || having_contains_window(&filter.predicate)
        }
        Expr::CollectionProjection(projection) => {
            contains_window(&projection.collection) || contains_window(&projection.projection)
        }
    }
}

fn having_contains_window(node: &BoolExpr) -> bool {
    match node {
        BoolExpr::Unary(unary) => having_contains_window(&unary.operand),
        BoolExpr::Binary(binary) if binary.operator == "AND" || binary.operator == "OR" => {
            having_contains_window(&binary.left) || having_contains_window(&binary.right)
        }
        BoolExpr::ScalarComparison(comparison) => {
            contains_window(&comparison.left) || contains_window(&comparison.right)
        }
        BoolExpr::ScalarIsNull(is_null) => contains_window(&is_null.expression),
        BoolExpr::TruthTest(truth) => having_contains_window(&truth.operand),
        _ => false,
    }
}

fn bool_contains_window(node: &BoolExpr) -> bool {
    match node {
        BoolExpr::Unary(unary) => having_contains_window(&unary.operand),
        BoolExpr::Binary(binary) => {
            having_contains_window(&binary.left) || having_contains_window(&binary.right)
        }
        BoolExpr::ScalarComparison(comparison) => {
            contains_window(&comparison.left) || contains_window(&comparison.right)
        }
        BoolExpr::ScalarIsNull(is_null) => contains_window(&is_null.expression),
        _ => false,
    }
}

/// Whether a scalar expression contains an aggregate function.
pub fn contains_aggregate(expression: &Expr) -> bool {
    match expression {
        Expr::Aggregate(_) => true,
        Expr::CollectionElement(_) | Expr::Field(_) | Expr::RelationField(_) | Expr::Literal(_) => {
            false
        }
        Expr::CollectionCount(count) => {
            contains_aggregate(&count.collection) || having_contains_aggregate(&count.predicate)
        }
        Expr::CollectionFilter(filter) => {
            contains_aggregate(&filter.collection) || having_contains_aggregate(&filter.predicate)
        }
        Expr::CollectionProjection(projection) => {
            contains_aggregate(&projection.collection) || contains_aggregate(&projection.projection)
        }
        Expr::Unary(unary) => contains_aggregate(&unary.operand),
        Expr::Binary(binary) => {
            contains_aggregate(&binary.left) || contains_aggregate(&binary.right)
        }
        Expr::Index(index) => {
            contains_aggregate(&index.collection) || contains_aggregate(&index.index)
        }
        Expr::Member(member) => contains_aggregate(&member.value),
        Expr::Function(function) => function.args.iter().any(contains_aggregate),
        Expr::Window(window) => {
            window
                .specification
                .partition_by
                .iter()
                .any(contains_aggregate)
                || window
                    .specification
                    .order_by
                    .iter()
                    .filter_map(|term| term.expression.as_deref())
                    .any(contains_aggregate)
        }
        Expr::Case(case) => {
            case.whens
                .iter()
                .any(|branch| contains_aggregate(&branch.result))
                || case
                    .else_result
                    .as_ref()
                    .map(|else_result| contains_aggregate(else_result))
                    .unwrap_or(false)
        }
    }
}

/// Whether a HAVING-side Boolean node contains an aggregate.
fn having_contains_aggregate(node: &BoolExpr) -> bool {
    match node {
        BoolExpr::Unary(unary) => having_contains_aggregate(&unary.operand),
        BoolExpr::Binary(binary) if binary.operator == "AND" || binary.operator == "OR" => {
            having_contains_aggregate(&binary.left) || having_contains_aggregate(&binary.right)
        }
        BoolExpr::ScalarComparison(comparison) => {
            contains_aggregate(&comparison.left) || contains_aggregate(&comparison.right)
        }
        BoolExpr::ScalarIsNull(is_null) => contains_aggregate(&is_null.expression),
        _ => false,
    }
}

/// Port of `_having_contains_aggregate` over an optional HAVING predicate.
fn having_contains_aggregate_opt(node: Option<&BoolExpr>) -> bool {
    node.map(having_contains_aggregate).unwrap_or(false)
}

/// Whether a scalar expression contains a volatile or seeded RANDOM call.
pub fn contains_random(expression: &Expr) -> bool {
    match expression {
        Expr::Field(_) | Expr::RelationField(_) | Expr::Literal(_) | Expr::CollectionElement(_) => {
            false
        }
        Expr::Unary(unary) => contains_random(&unary.operand),
        Expr::Binary(binary) => contains_random(&binary.left) || contains_random(&binary.right),
        Expr::Index(index) => contains_random(&index.collection) || contains_random(&index.index),
        Expr::Member(member) => contains_random(&member.value),
        Expr::Case(case) => {
            case.whens.iter().any(|branch| {
                bool_contains_random(&branch.condition) || contains_random(&branch.result)
            }) || case
                .else_result
                .as_ref()
                .map(|else_result| contains_random(else_result))
                .unwrap_or(false)
        }
        Expr::Function(function) => {
            function.name == "RANDOM" || function.args.iter().any(contains_random)
        }
        Expr::Aggregate(aggregate) => {
            aggregate.args.iter().any(contains_random)
                || aggregate
                    .filter_predicate
                    .as_ref()
                    .map(|predicate| bool_contains_random(predicate))
                    .unwrap_or(false)
        }
        Expr::Window(window) => {
            window
                .specification
                .partition_by
                .iter()
                .any(contains_random)
                || window
                    .specification
                    .order_by
                    .iter()
                    .filter_map(|term| term.expression.as_deref())
                    .any(contains_random)
        }
        Expr::CollectionCount(count) => {
            contains_random(&count.collection) || bool_contains_random(&count.predicate)
        }
        Expr::CollectionFilter(filter) => {
            contains_random(&filter.collection) || bool_contains_random(&filter.predicate)
        }
        Expr::CollectionProjection(projection) => {
            contains_random(&projection.collection) || contains_random(&projection.projection)
        }
    }
}

fn bool_contains_random(node: &BoolExpr) -> bool {
    match node {
        BoolExpr::Literal(_)
        | BoolExpr::Between(_)
        | BoolExpr::InList(_)
        | BoolExpr::IsNull(_)
        | BoolExpr::TextPredicate(_) => false,
        BoolExpr::Unary(unary) => bool_contains_random(&unary.operand),
        BoolExpr::Binary(binary) => {
            bool_contains_random(&binary.left) || bool_contains_random(&binary.right)
        }
        BoolExpr::TruthTest(truth) => bool_contains_random(&truth.operand),
        BoolExpr::CollectionPredicate(predicate) => {
            contains_random(&predicate.collection) || bool_contains_random(&predicate.predicate)
        }
        BoolExpr::ScalarIsNull(is_null) => contains_random(&is_null.expression),
        BoolExpr::ScalarComparison(comparison) => {
            contains_random(&comparison.left) || contains_random(&comparison.right)
        }
    }
}

/// Structural semantic identity that ignores non-semantic source positions.
///
/// This is the Rust counterpart of the Python reference's `semantic_key`,
/// rendered as a deterministic string so it can key the per-row window value
/// environment. Window expressions carry their full specification so that two
/// structurally identical projections share one numbering.
pub fn semantic_key(expression: &Expr) -> String {
    match expression {
        Expr::Field(field) => format!("field:{}|{:?}", field.name, field.kind),
        Expr::RelationField(field) => {
            format!(
                "relation-field:{}:{}|{:?}",
                field.qualifier, field.name, field.kind
            )
        }
        Expr::Literal(literal) => {
            let decoded = decode_literal(literal, None);
            let text = match &decoded {
                Value::Null => "null".to_string(),
                Value::Bool(value) => format!("bool:{}", value),
                Value::Int(value) => format!("int:{}", value),
                Value::Float(value) => format!("float:{}", value),
                Value::Text(value) => format!("text:{}|{}", value, literal.quoted),
                other => format!("other:{:?}", other),
            };
            format!("literal:{}", text)
        }
        Expr::Unary(unary) => {
            format!(
                "scalar-unary:{}|{}|{:?}",
                unary.operator,
                semantic_key(&unary.operand),
                unary.kind
            )
        }
        Expr::Binary(binary) => format!(
            "scalar-binary:{}|{}|{}|{:?}",
            binary.operator,
            semantic_key(&binary.left),
            semantic_key(&binary.right),
            binary.kind
        ),
        Expr::Index(index) => format!(
            "scalar-index:{}|{}|{:?}",
            semantic_key(&index.collection),
            semantic_key(&index.index),
            index.kind
        ),
        Expr::Member(member) => {
            format!(
                "scalar-member:{}|{}|{:?}",
                semantic_key(&member.value),
                member.member,
                member.kind
            )
        }
        Expr::Case(case) => {
            let branches = case
                .whens
                .iter()
                .map(|branch| {
                    format!(
                        "{}=>{}",
                        bool_semantic_key(&branch.condition),
                        semantic_key(&branch.result)
                    )
                })
                .collect::<Vec<_>>()
                .join(",");
            let else_key = case
                .else_result
                .as_ref()
                .map(|else_result| semantic_key(else_result))
                .unwrap_or_else(|| "none".to_string());
            format!("scalar-case:{}|else:{}|{:?}", branches, else_key, case.kind)
        }
        Expr::Function(function) => {
            let args = function
                .args
                .iter()
                .map(semantic_key)
                .collect::<Vec<_>>()
                .join(",");
            format!(
                "scalar-function:{}|{}|{:?}",
                function.name, args, function.kind
            )
        }
        Expr::Aggregate(aggregate) => {
            let args = aggregate
                .args
                .iter()
                .map(semantic_key)
                .collect::<Vec<_>>()
                .join(",");
            let filter = aggregate
                .filter_predicate
                .as_deref()
                .map(bool_semantic_key)
                .unwrap_or_else(|| "none".to_string());
            format!(
                "aggregate:{}|{}|star:{}|{}|{:?}",
                aggregate.name, args, aggregate.count_star, filter, aggregate.kind
            )
        }
        Expr::Window(window) => format!(
            "window-function:{}|{}|{:?}",
            window.name,
            window_specification_key(&window.specification),
            window.kind
        ),
        Expr::CollectionElement(reference) => {
            format!(
                "collection-element:{}|{}",
                reference.binding, reference.scope_distance
            )
        }
        Expr::CollectionCount(count) => format!(
            "collection-count:{}|{}|{}|{:?}",
            semantic_key(&count.collection),
            count.binding,
            bool_semantic_key(&count.predicate),
            count.kind
        ),
        Expr::CollectionFilter(filter) => format!(
            "collection-filter:{}|{}|{}|{:?}",
            semantic_key(&filter.collection),
            filter.binding,
            bool_semantic_key(&filter.predicate),
            filter.kind
        ),
        Expr::CollectionProjection(projection) => format!(
            "collection-projection:{}|{}|{}|{:?}",
            semantic_key(&projection.collection),
            projection.binding,
            semantic_key(&projection.projection),
            projection.kind
        ),
    }
}

fn window_specification_key(specification: &crate::model::WindowSpecification) -> String {
    let partition = specification
        .partition_by
        .iter()
        .map(semantic_key)
        .collect::<Vec<_>>()
        .join(",");
    let order = specification
        .order_by
        .iter()
        .map(|term| {
            let expression = term
                .expression
                .as_deref()
                .map(semantic_key)
                .unwrap_or_else(|| term.field.clone());
            format!(
                "order:{}|{}|{:?}|{:?}",
                term.field, term.descending, term.kind, expression
            )
        })
        .collect::<Vec<_>>()
        .join(",");
    format!(
        "specification:{}|{}|{:?}",
        partition, order, specification.kind
    )
}

fn field_semantic_key(field: &crate::model::Field) -> String {
    format!("field:{}|{:?}", field.name, field.kind)
}

fn bool_semantic_key(node: &BoolExpr) -> String {
    match node {
        BoolExpr::Literal(literal) => format!("bool-literal:{:?}", literal),
        BoolExpr::Unary(unary) => format!(
            "bool-unary:{}|{}",
            unary.operator,
            bool_semantic_key(&unary.operand)
        ),
        BoolExpr::Binary(binary) => format!(
            "bool-binary:{}|{}|{}",
            binary.operator,
            bool_semantic_key(&binary.left),
            bool_semantic_key(&binary.right)
        ),
        BoolExpr::Between(between) => format!(
            "between:{}|{:?}|{:?}|{}",
            field_semantic_key(&between.field),
            decode_literal(&between.lower, None),
            decode_literal(&between.upper, None),
            between.negated
        ),
        BoolExpr::InList(in_list) => {
            let values = in_list
                .values
                .iter()
                .map(|literal| format!("{:?}", decode_literal(literal, None)))
                .collect::<Vec<_>>()
                .join(",");
            format!(
                "in:{}|{}|{}",
                field_semantic_key(&in_list.field),
                values,
                in_list.negated
            )
        }
        BoolExpr::IsNull(is_null) => {
            format!(
                "is-null:{}|{}",
                field_semantic_key(&is_null.field),
                is_null.negated
            )
        }
        BoolExpr::TextPredicate(predicate) => format!(
            "text:{}|{}|{:?}|{}|{}",
            predicate.operator,
            field_semantic_key(&predicate.field),
            decode_literal(&predicate.value, None),
            predicate.value.quoted,
            predicate.negated
        ),
        BoolExpr::TruthTest(truth) => format!(
            "truth-test:{}|{}|{}",
            bool_semantic_key(&truth.operand),
            truth.truth,
            truth.negated
        ),
        BoolExpr::CollectionPredicate(predicate) => format!(
            "collection-predicate:{}|{}|{}|{}",
            predicate.quantifier,
            semantic_key(&predicate.collection),
            predicate.binding,
            bool_semantic_key(&predicate.predicate)
        ),
        BoolExpr::ScalarIsNull(is_null) => {
            format!(
                "scalar-is-null:{}|{}",
                semantic_key(&is_null.expression),
                is_null.negated
            )
        }
        BoolExpr::ScalarComparison(comparison) => format!(
            "scalar-comparison:{}|{}|{}",
            comparison.operator,
            semantic_key(&comparison.left),
            semantic_key(&comparison.right)
        ),
    }
}

/// Port of `_aggregate_query`: whether a query evaluates over aggregate groups.
pub fn is_aggregate_query(query: &Query) -> bool {
    aggregate_query(query)
}

/// The `_aggregate_query` port under the Python reference's name.
pub fn aggregate_query(query: &Query) -> bool {
    !query.group_by.is_empty()
        || query.select.iter().any(|term| {
            term.expression
                .as_ref()
                .map(|expression| contains_aggregate(expression))
                .unwrap_or(false)
        })
        || query.order_by.iter().any(|term| {
            term.expression
                .as_ref()
                .map(|expression| contains_aggregate(expression))
                .unwrap_or(false)
        })
        || having_contains_aggregate_opt(query.having.as_deref())
}

/// Port of `query_physical_source_requests`: reachable physical source/facet
/// requests in deterministic first-use order.
pub fn query_physical_source_requests(query: &Query) -> Vec<(String, Option<String>)> {
    let mut state = PhysicalRequestState {
        cte_map: query
            .ctes
            .iter()
            .map(|cte| (cte.name.clone(), &*cte.query))
            .collect(),
        seen_ctes: Vec::new(),
        seen: Vec::new(),
        result: Vec::new(),
    };
    state.visit(query);
    state.result
}

struct PhysicalRequestState<'a> {
    cte_map: HashMap<String, &'a Query>,
    seen_ctes: Vec<String>,
    seen: Vec<(String, Option<String>)>,
    result: Vec<(String, Option<String>)>,
}

impl<'a> PhysicalRequestState<'a> {
    fn visit_relation(&mut self, source_name: &str, facet: Option<&str>) {
        if let Some(cte_query) = self.cte_map.get(source_name).copied() {
            // A facet over a CTE is rejected by the resolver; evaluation simply
            // visits the CTE body.
            if !self.seen_ctes.iter().any(|name| name == source_name) {
                self.seen_ctes.push(source_name.to_string());
                self.visit(cte_query);
            }
            return;
        }
        let key = (source_name.to_string(), facet.map(str::to_string));
        if !self.seen.contains(&key) {
            self.seen.push(key.clone());
            self.result.push(key);
        }
    }

    fn visit(&mut self, candidate: &'a Query) {
        if let Some(left) = &candidate.left_query {
            self.visit(left);
        }
        if let Some(source) = &candidate.from_source {
            self.visit_relation(source, candidate.from_facet.as_deref());
        } else if let Some(relation) = &candidate.from_relation
            && let Some(derived) = &relation.derived
        {
            self.visit(&derived.query);
        }
        for join in &candidate.joins {
            if let Some(source) = &join.relation.source {
                self.visit_relation(source, join.relation.facet.as_deref());
            } else if let Some(derived) = &join.relation.derived {
                self.visit(&derived.query);
            }
        }
        for operation in &candidate.set_operations {
            self.visit(&operation.query);
        }
    }
}

/// Port of `query_physical_sources`: physical source references in
/// deterministic first-use order.
pub fn query_physical_sources(query: &Query) -> Vec<String> {
    let mut seen: Vec<String> = Vec::new();
    let mut result: Vec<String> = Vec::new();
    for (source_name, _) in query_physical_source_requests(query) {
        if seen.iter().any(|name| name == &source_name) {
            continue;
        }
        seen.push(source_name.clone());
        result.push(source_name);
    }
    result
}

// ---------------------------------------------------------------------------
// Query execution
// ---------------------------------------------------------------------------

/// Materialise one physical, CTE or derived relation operand.
fn materialise_relation_reference(
    records: &[Record],
    relation: Option<&crate::model::RelationReference>,
    relations: &HashMap<String, Vec<Record>>,
    physical_requests: &[(String, Option<String>)],
    relational_optimisation: bool,
) -> Result<Vec<Record>, String> {
    if let Some(relation) = relation
        && let Some(derived) = &relation.derived
    {
        let nested = &derived.query;
        let nested_rows = apply_composed_query(
            records,
            nested,
            relations,
            physical_requests,
            relational_optimisation,
        )?;
        if !nested.set_operations.is_empty() {
            return Ok(nested_rows);
        }
        return Ok(project_result_rows(&nested_rows, nested));
    }
    let source = relation.and_then(|relation| relation.source.clone());
    let facet = relation.and_then(|relation| relation.facet.clone());
    Ok(records_for_source(
        records,
        source.as_deref(),
        facet.as_deref(),
        relations,
        physical_requests,
    ))
}

/// Port of `_records_for_source`.
fn records_for_source(
    records: &[Record],
    source_name: Option<&str>,
    source_facet: Option<&str>,
    relations: &HashMap<String, Vec<Record>>,
    physical_requests: &[(String, Option<String>)],
) -> Vec<Record> {
    if let Some(name) = source_name
        && let Some(rows) = relations.get(name)
    {
        return rows.clone();
    }
    if source_name.is_none() || physical_requests.len() <= 1 {
        return records.to_vec();
    }
    records
        .iter()
        .filter(|record| {
            record_key_matches(record, "_yt_sql_source", source_name)
                && record_key_matches(record, "_yt_sql_source_facet", source_facet)
        })
        .cloned()
        .collect()
}

/// Python `record.get(key) == expected`, where an explicit NULL matches NULL.
fn record_key_matches(record: &Record, key: &str, expected: Option<&str>) -> bool {
    let actual = record_get(record, key)
        .filter(|value| !value.is_null())
        .and_then(|value| match value {
            Value::Text(text) => Some(text.as_str()),
            _ => None,
        });
    match (actual, expected) {
        (None, None) => true,
        (Some(actual), Some(expected)) => actual == expected,
        _ => false,
    }
}

/// Return left/right fields for a safely hashable equality JOIN key.
fn equality_join_key_fields(query: &Query) -> Option<Vec<(RelationField, RelationField)>> {
    let join = query.joins.first()?;
    let left_alias = query.from_alias.as_deref().unwrap_or("");
    let right_alias = join.relation.alias.as_deref().unwrap_or("");
    let fields = collect_join_key_fields(&join.predicate, left_alias, right_alias)?;
    if fields.is_empty() {
        return None;
    }
    Some(fields)
}

fn collect_join_key_fields(
    node: &BoolExpr,
    left_alias: &str,
    right_alias: &str,
) -> Option<Vec<(RelationField, RelationField)>> {
    match node {
        BoolExpr::Binary(binary) if binary.operator == "AND" => {
            let mut left = collect_join_key_fields(&binary.left, left_alias, right_alias)?;
            let right = collect_join_key_fields(&binary.right, left_alias, right_alias)?;
            left.extend(right);
            Some(left)
        }
        BoolExpr::ScalarComparison(comparison) if comparison.operator == "=" => {
            let (Expr::RelationField(left), Expr::RelationField(right)) =
                (&*comparison.left, &*comparison.right)
            else {
                return None;
            };
            if left.qualifier == left_alias && right.qualifier == right_alias {
                return Some(vec![(left.clone(), right.clone())]);
            }
            if right.qualifier == left_alias && left.qualifier == right_alias {
                return Some(vec![(right.clone(), left.clone())]);
            }
            None
        }
        _ => None,
    }
}

#[derive(Debug, Clone)]
enum JoinKey {
    Null,
    Unhashable,
    Key(Value),
}

/// Port of `_join_key`.
fn join_key(record: &Record, fields: &[RelationField]) -> JoinKey {
    let mut values: Vec<Value> = Vec::new();
    for field in fields {
        let value = canonical_record_value(
            record,
            &CanonicalField::Named {
                name: field.name.clone(),
                kind: field.kind.clone(),
            },
            false,
        );
        if value.is_null() {
            return JoinKey::Null;
        }
        values.push(value);
    }
    let key = if values.len() == 1 {
        values.into_iter().next().unwrap_or(Value::Null)
    } else {
        Value::Array(values)
    };
    let unhashable = match &key {
        Value::Array(items) => items
            .iter()
            .any(|item| matches!(item, Value::Array(_) | Value::Record(_))),
        Value::Record(_) => true,
        _ => false,
    };
    if unhashable {
        return JoinKey::Unhashable;
    }
    JoinKey::Key(key)
}

/// Build a stable right-side equality index, or decline unsafe values.
fn hash_join_index(
    right_records: &[Record],
    right_fields: &[RelationField],
) -> Option<Vec<(Value, Vec<usize>)>> {
    let mut index: Vec<(Value, Vec<usize>)> = Vec::new();
    for (record_index, record) in right_records.iter().enumerate() {
        let key = join_key(record, right_fields);
        match key {
            JoinKey::Null => continue,
            JoinKey::Unhashable => return None,
            JoinKey::Key(key) => {
                match index
                    .iter_mut()
                    .find(|(existing, _)| key_equal(existing, &key))
                {
                    Some((_, rows)) => rows.push(record_index),
                    None => index.push((key, vec![record_index])),
                }
            }
        }
    }
    Some(index)
}

/// `Some(rows)` for the indexed candidates, `Some(empty)` for NULL keys and
/// `None` when an unhashable left value invalidates the fast path.
fn hash_join_matches(
    left_record: &Record,
    left_fields: &[RelationField],
    index: &[(Value, Vec<usize>)],
    right_records: &[Record],
) -> Option<Vec<Record>> {
    let key = join_key(left_record, left_fields);
    match key {
        JoinKey::Null => Some(Vec::new()),
        JoinKey::Unhashable => None,
        JoinKey::Key(key) => Some(
            index
                .iter()
                .find(|(existing, _)| key_equal(existing, &key))
                .map(|(_, rows)| {
                    rows.iter()
                        .map(|index| right_records[*index].clone())
                        .collect()
                })
                .unwrap_or_default(),
        ),
    }
}

/// Apply one SEMI or ANTI join, with a proof-limited membership fast path.
fn apply_existence_join(
    records: &[Record],
    query: &Query,
    relations: &HashMap<String, Vec<Record>>,
    physical_requests: &[(String, Option<String>)],
    relational_optimisation: bool,
) -> Result<Vec<Record>, String> {
    let join = &query.joins[0];
    let left_records = if query.from_relation.is_some() {
        materialise_relation_reference(
            records,
            query.from_relation.as_ref(),
            relations,
            physical_requests,
            relational_optimisation,
        )?
    } else {
        records_for_source(
            records,
            query.from_source.as_deref(),
            query.from_facet.as_deref(),
            relations,
            physical_requests,
        )
    };
    let right_records = materialise_relation_reference(
        records,
        Some(&join.relation),
        relations,
        physical_requests,
        relational_optimisation,
    )?;

    let equality_fields = if relational_optimisation {
        equality_join_key_fields(query)
    } else {
        None
    };
    if left_records.is_empty() {
        return Ok(Vec::new());
    }
    if right_records.is_empty() {
        if join.kind == JoinKind::Semi {
            return Ok(Vec::new());
        }
        if join.kind == JoinKind::Anti {
            return Ok(left_records);
        }
    }

    if let Some(fields) = &equality_fields {
        let left_fields: Vec<RelationField> = fields.iter().map(|(left, _)| left.clone()).collect();
        let right_fields: Vec<RelationField> =
            fields.iter().map(|(_, right)| right.clone()).collect();
        if let Some(index) = hash_join_index(&right_records, &right_fields) {
            let mut selected: Vec<Record> = Vec::new();
            let mut declined = false;
            for left_record in &left_records {
                match hash_join_matches(left_record, &left_fields, &index, &right_records) {
                    None => {
                        declined = true;
                        break;
                    }
                    Some(matches) => {
                        let matched = !matches.is_empty();
                        if (join.kind == JoinKind::Semi && matched)
                            || (join.kind == JoinKind::Anti && !matched)
                        {
                            selected.push(left_record.clone());
                        }
                    }
                }
            }
            if !declined {
                return Ok(selected);
            }
        }
    }

    // Reference execution route.
    let left_alias = query.from_alias.clone().unwrap_or_default();
    let right_alias = join.relation.alias.clone().unwrap_or_default();
    let mut selected: Vec<Record> = Vec::new();
    for left_record in &left_records {
        let mut matched = false;
        for right_record in &right_records {
            let context = EvaluationContext::with_relation_records(
                left_record.clone(),
                vec![
                    (left_alias.clone(), left_record.clone()),
                    (right_alias.clone(), right_record.clone()),
                ],
            );
            if evaluate_predicate(Some(&join.predicate), &context) == Some(true) {
                matched = true;
                break;
            }
        }
        if (join.kind == JoinKind::Semi && matched) || (join.kind == JoinKind::Anti && !matched) {
            selected.push(left_record.clone());
        }
    }
    Ok(selected)
}

/// Apply one INNER or LEFT JOIN while preserving explicit relation ownership.
fn apply_row_producing_join(
    records: &[Record],
    query: &Query,
    relations: &HashMap<String, Vec<Record>>,
    physical_requests: &[(String, Option<String>)],
    relational_optimisation: bool,
) -> Result<Vec<Record>, String> {
    let join = &query.joins[0];
    let left_records = if query.from_relation.is_some() {
        materialise_relation_reference(
            records,
            query.from_relation.as_ref(),
            relations,
            physical_requests,
            relational_optimisation,
        )?
    } else {
        records_for_source(
            records,
            query.from_source.as_deref(),
            query.from_facet.as_deref(),
            relations,
            physical_requests,
        )
    };
    let right_records = materialise_relation_reference(
        records,
        Some(&join.relation),
        relations,
        physical_requests,
        relational_optimisation,
    )?;
    let left_alias = query.from_alias.clone().unwrap_or_default();
    let right_alias = join.relation.alias.clone().unwrap_or_default();

    let equality_fields = if relational_optimisation {
        equality_join_key_fields(query)
    } else {
        None
    };
    if left_records.is_empty() {
        return Ok(Vec::new());
    }
    if join.kind == JoinKind::Inner && right_records.is_empty() {
        return Ok(Vec::new());
    }
    let mut index: Option<Vec<(Value, Vec<usize>)>> = None;
    let mut left_fields: Option<Vec<RelationField>> = None;
    if let Some(fields) = &equality_fields {
        left_fields = Some(fields.iter().map(|(left, _)| left.clone()).collect());
        let right_fields: Vec<RelationField> =
            fields.iter().map(|(_, right)| right.clone()).collect();
        index = hash_join_index(&right_records, &right_fields);
    }

    let mut joined: Vec<Record> = Vec::new();
    for left_record in &left_records {
        // The equality fast path narrows the candidate rows; one unhashable
        // left value invalidates the fast path for this row only, and
        // reference evaluation over all right rows retains exact semantics.
        let mut candidates: Vec<Record> = right_records.clone();
        if let (Some(index), Some(left_fields)) = (&index, &left_fields)
            && let Some(indexed) =
                hash_join_matches(left_record, left_fields, index, &right_records)
        {
            candidates = indexed;
        }
        let mut matched = false;
        for right_record in &candidates {
            let context = EvaluationContext::with_relation_records(
                left_record.clone(),
                vec![
                    (left_alias.clone(), left_record.clone()),
                    (right_alias.clone(), right_record.clone()),
                ],
            );
            if evaluate_predicate(Some(&join.predicate), &context) != Some(true) {
                continue;
            }
            matched = true;
            let mut row = left_record.clone();
            record_set(
                &mut row,
                "_yt_sql_relation_records",
                Value::Record(vec![
                    (left_alias.clone(), Value::Record(left_record.clone())),
                    (right_alias.clone(), Value::Record(right_record.clone())),
                ]),
            );
            joined.push(row);
        }
        if join.kind == JoinKind::Left && !matched {
            let mut row = left_record.clone();
            record_set(
                &mut row,
                "_yt_sql_relation_records",
                Value::Record(vec![
                    (left_alias.clone(), Value::Record(left_record.clone())),
                    (right_alias.clone(), Value::Record(Vec::new())),
                ]),
            );
            joined.push(row);
        }
    }
    Ok(joined)
}

/// Project execution rows into result rows carrying the result-row marker.
fn project_result_rows(records: &[Record], query: &Query) -> Vec<Record> {
    if is_aggregate_query(query) {
        records
            .iter()
            .map(|record| {
                let mut row: Record = query
                    .select
                    .iter()
                    .map(|term| {
                        (
                            term.output_name().to_string(),
                            record_get(record, term.output_name())
                                .cloned()
                                .unwrap_or(Value::Null),
                        )
                    })
                    .collect();
                row.push(("_yt_sql_result_row".to_string(), Value::Bool(true)));
                row
            })
            .collect()
    } else {
        records
            .iter()
            .map(|record| {
                let mut row: Record = query
                    .select
                    .iter()
                    .map(|term| {
                        (
                            term.output_name().to_string(),
                            canonical_record_value(
                                record,
                                &CanonicalField::Select(term.clone()),
                                false,
                            ),
                        )
                    })
                    .collect();
                row.push(("_yt_sql_result_row".to_string(), Value::Bool(true)));
                row
            })
            .collect()
    }
}

/// Port of `_apply_aggregate_query`.
/// Establish window projections over the filtered input relation.
///
/// Window numbering is computed once per query body over its complete filtered
/// input, before final ordering, deduplication and slicing. Each materialised
/// row carries standalone window values under their output names and a
/// semantic-key environment for ordering expressions that reference them.
fn apply_window_values(rows: Vec<Record>, select: &[SelectTerm]) -> Result<Vec<Record>, String> {
    let window_terms: Vec<&SelectTerm> = select
        .iter()
        .filter(|term| matches!(term.expression.as_deref(), Some(Expr::Window(_))))
        .collect();
    if window_terms.is_empty() {
        return Ok(rows);
    }
    let mut environments: Vec<Vec<(String, Value)>> = vec![Vec::new(); rows.len()];
    for term in &window_terms {
        let Some(Expr::Window(expression)) = term.expression.as_deref() else {
            continue;
        };
        let numbers = window_numbers(&rows, expression)?;
        let key = semantic_key(term.expression.as_deref().expect("window expression"));
        for (environment, number) in environments.iter_mut().zip(numbers) {
            environment.retain(|(existing, _)| existing != &key);
            environment.push((key.clone(), Value::Int(number)));
        }
    }
    let mut materialised = Vec::with_capacity(rows.len());
    for (record, environment) in rows.into_iter().zip(environments) {
        let mut row = record;
        for term in &window_terms {
            let key = semantic_key(term.expression.as_deref().expect("window expression"));
            let number = environment
                .iter()
                .find(|(existing, _)| existing == &key)
                .map(|(_, value)| value.clone())
                .unwrap_or(Value::Null);
            record_set(&mut row, term.output_name(), number);
        }
        record_set(
            &mut row,
            "_yt_sql_window_values",
            Value::Record(environment),
        );
        materialised.push(row);
    }
    Ok(materialised)
}

/// Number rows one-based within each partition, in window order.
///
/// Rows whose complete window-ordering keys compare equal keep encounter order
/// through the stable sort, but that relative numbering is not a language
/// guarantee: yt-sql does not add an implicit tie-breaker.
fn window_numbers(
    rows: &[Record],
    expression: &crate::model::WindowFunction,
) -> Result<Vec<i64>, String> {
    let specification = &expression.specification;
    let mut partitions: Vec<(Vec<Value>, Vec<usize>)> = Vec::new();
    for (index, record) in rows.iter().enumerate() {
        let mut key: Vec<Value> = Vec::with_capacity(specification.partition_by.len());
        for item in &specification.partition_by {
            let value = evaluate_scalar(item, &EvaluationContext::new(record.clone()));
            key.push(hashable_group_value(&value));
        }
        match partitions
            .iter_mut()
            .find(|(existing, _)| keys_equal(existing, &key))
        {
            Some((_, members)) => members.push(index),
            None => partitions.push((key, vec![index])),
        }
    }
    let mut numbers = vec![0i64; rows.len()];
    for (_, members) in &partitions {
        let mut ordered = members.clone();
        for term in specification.order_by.iter().rev() {
            let term = term.clone();
            ordered = order_items(ordered, &term, |index| {
                canonical_record_value(
                    &rows[*index],
                    &CanonicalField::OrderTerm(term.clone()),
                    false,
                )
            })?;
        }
        for (position, index) in ordered.into_iter().enumerate() {
            numbers[index] = position as i64 + 1;
        }
    }
    Ok(numbers)
}

fn apply_aggregate_query(records: &[Record], query: &Query) -> Result<Vec<Record>, String> {
    let filtered: Vec<Record> = records
        .iter()
        .filter(|record| {
            evaluate_predicate(
                query.predicate.as_deref(),
                &EvaluationContext::new((*record).clone()),
            ) == Some(true)
        })
        .cloned()
        .collect();

    let mut grouped: Vec<(Vec<Value>, Vec<Record>)> = Vec::new();
    if !query.group_by.is_empty() {
        for record in &filtered {
            let context = EvaluationContext::new(record.clone());
            let key: Vec<Value> = query
                .group_by
                .iter()
                .map(|expression| hashable_group_value(&evaluate_scalar(expression, &context)))
                .collect();
            match grouped
                .iter_mut()
                .find(|(existing, _)| keys_equal(existing, &key))
            {
                Some((_, rows)) => rows.push(record.clone()),
                None => grouped.push((key, vec![record.clone()])),
            }
        }
    } else {
        grouped = vec![(Vec::new(), filtered.clone())];
    }

    let mut surviving: Vec<Vec<Record>> = grouped
        .into_iter()
        .filter(|(_, group)| evaluate_having_opt(query.having.as_deref(), group) == Some(true))
        .map(|(_, group)| group)
        .collect();

    for term in query.order_by.iter().rev() {
        let term = term.clone();
        surviving = order_items(surviving, &term, |group| match &term.expression {
            Some(expression) => evaluate_group_expression(expression, group),
            None => Value::Null,
        })?;
    }

    let mut rows: Vec<Record> = Vec::new();
    for group in &surviving {
        let mut row: Record = vec![("_yt_sql_aggregate_result".to_string(), Value::Bool(true))];
        for term in &query.select {
            let value = if let Some(expression) = &term.expression {
                if is_final_position(term) {
                    Value::Null
                } else {
                    evaluate_group_expression(expression, group)
                }
            } else if !group.is_empty() {
                canonical_record_value(&group[0], &CanonicalField::Select(term.clone()), false)
            } else {
                Value::Null
            };
            row.push((term.output_name().to_string(), value));
        }
        rows.push(row);
    }

    if query.distinct {
        rows = dedup_by_select_terms(rows, query);
    }
    Ok(slice_final_result(rows, query))
}

/// Port of `_apply_query_body`.
fn apply_query_body(records: &[Record], query: &Query) -> Result<Vec<Record>, String> {
    if is_aggregate_query(query) {
        return apply_aggregate_query(records, query);
    }
    let mut result: Vec<Record> = records
        .iter()
        .filter(|record| {
            evaluate_predicate(
                query.predicate.as_deref(),
                &EvaluationContext::new((*record).clone()),
            ) == Some(true)
        })
        .cloned()
        .collect();

    // Window values are established over the complete filtered input relation
    // before ordering, deduplication and slicing can observe them.
    result = apply_window_values(result, &query.select)?;

    // Sort from the last term backwards so each ORDER BY direction remains
    // independent; the stable sort retains encounter order for ties.
    for term in query.order_by.iter().rev() {
        let term = term.clone();
        result = order_items(result, &term, |record| {
            canonical_record_value(record, &CanonicalField::OrderTerm(term.clone()), false)
        })?;
    }

    if query.distinct {
        result = dedup_by_select_terms(result, query);
    }

    let mut result = slice_final_result(result, query);

    let random_terms: Vec<SelectTerm> = query
        .select
        .iter()
        .filter(|term| {
            term.expression
                .as_ref()
                .map(|expression| contains_random(expression))
                .unwrap_or(false)
        })
        .cloned()
        .collect();
    if !random_terms.is_empty() {
        let mut materialised: Vec<Record> = Vec::new();
        for record in result {
            let mut row = record.clone();
            for term in &random_terms {
                let value =
                    canonical_record_value(&record, &CanonicalField::Select(term.clone()), false);
                record_set(&mut row, term.output_name(), value);
            }
            materialised.push(row);
        }
        result = materialised;
    }
    Ok(result)
}

/// Clone a query with the composed-execution `replace(...)` updates applied:
/// set_operations, order_by, limit, offset, ctes and the limit/offset literals
/// are reset; `distinct` is controlled by the caller, everything else is kept.
fn body_without_tail(query: &Query, keep_distinct: bool, keep_left_query: bool) -> Query {
    let mut body = query.clone();
    body.set_operations = Vec::new();
    body.order_by = Vec::new();
    body.limit = None;
    body.offset = 0;
    body.ctes = Vec::new();
    body.limit_literal = None;
    body.offset_literal = None;
    if !keep_distinct {
        body.distinct = false;
    }
    if !keep_left_query {
        body.left_query = None;
    }
    body
}

/// Port of `_apply_composed_query`.
fn apply_composed_query(
    records: &[Record],
    query: &Query,
    relations: &HashMap<String, Vec<Record>>,
    physical_requests: &[(String, Option<String>)],
    relational_optimisation: bool,
) -> Result<Vec<Record>, String> {
    if query.set_operations.is_empty()
        && let Some(left_query) = &query.left_query
    {
        let mut rows = apply_composed_query(
            records,
            left_query,
            relations,
            physical_requests,
            relational_optimisation,
        )?;
        for term in query.order_by.iter().rev() {
            let term = term.clone();
            rows = order_items(rows, &term, |row| {
                canonical_record_value(row, &CanonicalField::OrderTerm(term.clone()), false)
            })?;
        }
        rows = slice_offset(rows, query.offset);
        if let Some(limit) = query.limit {
            rows = slice_limit(rows, limit);
        }
        return Ok(rows);
    }

    if query.set_operations.is_empty() {
        let input_records = if !query.joins.is_empty() {
            if matches!(query.joins[0].kind, JoinKind::Inner | JoinKind::Left) {
                apply_row_producing_join(
                    records,
                    query,
                    relations,
                    physical_requests,
                    relational_optimisation,
                )?
            } else {
                apply_existence_join(
                    records,
                    query,
                    relations,
                    physical_requests,
                    relational_optimisation,
                )?
            }
        } else if query.from_relation.is_some() {
            materialise_relation_reference(
                records,
                query.from_relation.as_ref(),
                relations,
                physical_requests,
                relational_optimisation,
            )?
        } else {
            records_for_source(
                records,
                query.from_source.as_deref(),
                query.from_facet.as_deref(),
                relations,
                physical_requests,
            )
        };
        return apply_query_body(&input_records, query);
    }

    let pure_facet_expansion = query
        .set_operations
        .iter()
        .all(|operation| operation.facet_expansion);
    if pure_facet_expansion {
        // Multi-facet OF is one logical source relation expanded across facets.
        let mut bodies: Vec<Query> = vec![body_without_tail(query, false, true)];
        bodies.extend(
            query
                .set_operations
                .iter()
                .map(|operation| body_without_tail(&operation.query, false, true)),
        );
        let mut rows: Vec<Record> = Vec::new();
        for body in &bodies {
            rows.extend(apply_composed_query(
                records,
                body,
                relations,
                physical_requests,
                relational_optimisation,
            )?);
        }
        for term in query.order_by.iter().rev() {
            let term = term.clone();
            rows = order_items(rows, &term, |row| {
                canonical_record_value(row, &CanonicalField::OrderTerm(term.clone()), false)
            })?;
        }
        if query.distinct {
            rows = dedup_by_select_terms(rows, query);
        }
        let rows = slice_final_result(rows, query);
        return Ok(project_result_rows(
            &rows,
            &body_without_tail(query, false, true),
        ));
    }

    let mut rows: Vec<Record>;
    if let Some(left_query) = &query.left_query {
        let left_rows = apply_composed_query(
            records,
            left_query,
            relations,
            physical_requests,
            relational_optimisation,
        )?;
        rows = if !left_query.set_operations.is_empty() || left_query.left_query.is_some() {
            left_rows
        } else {
            project_result_rows(&left_rows, left_query)
        };
    } else {
        let left_body = body_without_tail(query, true, true);
        let left_rows = apply_composed_query(
            records,
            &left_body,
            relations,
            physical_requests,
            relational_optimisation,
        )?;
        rows = project_result_rows(&left_rows, &left_body);
    }
    let output_names: Vec<String> = query
        .select
        .iter()
        .map(|term| term.output_name().to_string())
        .collect();

    for operation in &query.set_operations {
        let branch = &operation.query;
        let (branch_names, branch_rows) = if operation.grouped
            || !branch.set_operations.is_empty()
            || branch.left_query.is_some()
        {
            let branch_result = apply_composed_query(
                records,
                branch,
                relations,
                physical_requests,
                relational_optimisation,
            )?;
            let rows = if !branch.set_operations.is_empty() || branch.left_query.is_some() {
                branch_result
            } else {
                project_result_rows(&branch_result, branch)
            };
            (
                branch
                    .select
                    .iter()
                    .map(|term| term.output_name().to_string())
                    .collect::<Vec<_>>(),
                rows,
            )
        } else {
            let branch_body = body_without_tail(branch, true, true);
            let branch_result = apply_composed_query(
                records,
                &branch_body,
                relations,
                physical_requests,
                relational_optimisation,
            )?;
            let rows = project_result_rows(&branch_result, &branch_body);
            (
                branch
                    .select
                    .iter()
                    .map(|term| term.output_name().to_string())
                    .collect::<Vec<_>>(),
                rows,
            )
        };
        let remapped: Vec<Record> = branch_rows
            .into_iter()
            .map(|row| {
                let mut remapped_row: Record = Vec::new();
                for (target, source) in output_names.iter().zip(branch_names.iter()) {
                    remapped_row.push((
                        target.clone(),
                        record_get(&row, source).cloned().unwrap_or(Value::Null),
                    ));
                }
                remapped_row.push(("_yt_sql_result_row".to_string(), Value::Bool(true)));
                remapped_row
            })
            .collect();
        rows.extend(remapped);
        if !operation.all {
            let mut seen: Vec<Vec<Value>> = Vec::new();
            let mut unique: Vec<Record> = Vec::new();
            for row in rows {
                let key = union_row_key(&row, &output_names);
                if seen.iter().any(|existing| keys_equal(existing, &key)) {
                    continue;
                }
                seen.push(key);
                unique.push(row);
            }
            rows = unique;
        }
    }

    // Global ORDER BY, OFFSET and LIMIT apply to the already materialised
    // logical result relation.
    for term in query.order_by.iter().rev() {
        let term = term.clone();
        rows = order_items(rows, &term, |row| {
            canonical_record_value(row, &CanonicalField::OrderTerm(term.clone()), false)
        })?;
    }
    rows = slice_offset(rows, query.offset);
    if let Some(limit) = query.limit {
        rows = slice_limit(rows, limit);
    }
    Ok(rows)
}

const EXECUTION_ONLY_KEYS: [&str; 4] = [
    "_yt_sql_result_row",
    "_yt_sql_aggregate_result",
    "_yt_sql_random_cache",
    "_yt_sql_window_values",
];

/// Apply a resolved query, materialising CTEs and set-composed relations.
pub fn apply_query(
    records: &[Record],
    query: &Query,
    relational_optimisation: bool,
) -> Result<Vec<Record>, String> {
    // Python drops any record-level RANDOM cache before a run; the evaluator
    // keeps that cache keyed by record content in thread-local state.
    RANDOM_CACHE.with(|cache| cache.borrow_mut().clear());

    let physical_requests = query_physical_source_requests(query);
    let result = if query.ctes.is_empty() {
        apply_composed_query(
            records,
            query,
            &HashMap::new(),
            &physical_requests,
            relational_optimisation,
        )?
    } else {
        let mut relations: HashMap<String, Vec<Record>> = HashMap::new();
        for cte in &query.ctes {
            let cte_result = apply_composed_query(
                records,
                &cte.query,
                &relations,
                &physical_requests,
                relational_optimisation,
            )?;
            let stored = if cte.query.set_operations.is_empty() {
                project_result_rows(&cte_result, &cte.query)
            } else {
                cte_result
            };
            relations.insert(cte.name.clone(), stored);
        }
        let mut body = query.clone();
        body.ctes = Vec::new();
        apply_composed_query(
            records,
            &body,
            &relations,
            &physical_requests,
            relational_optimisation,
        )?
    };

    // Result-row markers are an internal execution detail used while
    // materialising CTEs and set operations; they never escape this API.
    Ok(result
        .into_iter()
        .map(|row| {
            row.into_iter()
                .filter(|(key, _)| !EXECUTION_ONLY_KEYS.contains(&key.as_str()))
                .collect()
        })
        .collect())
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{Binary, Field, Literal, OrderTerm, Query, SelectTerm};

    fn text_value(text: &str) -> Value {
        Value::Text(text.to_string())
    }

    fn field_literal(name: &str) -> Literal {
        Literal {
            value: LiteralValue::Text(name.to_string()),
            raw: name.to_string(),
            position: 0,
            quoted: false,
        }
    }

    #[test]
    fn blake2b_personalisation_matches_hashlib() {
        // Reference digests from Python hashlib.blake2b(..., digest_size=8,
        // person=b"yt-sql-rnd").
        let digest = blake2b(b"1\x00test", 8, b"yt-sql-rnd");
        let mut bytes = [0u8; 8];
        bytes.copy_from_slice(&digest);
        assert_eq!(hex(&bytes), "e83fcea2d9d29cbb");

        let digest = blake2b(b"abc", 8, b"yt-sql-rnd");
        let mut bytes = [0u8; 8];
        bytes.copy_from_slice(&digest);
        assert_eq!(hex(&bytes), "5cf7e8e84d9c8b8e");

        let digest = blake2b(b"", 8, b"yt-sql-rnd");
        let mut bytes = [0u8; 8];
        bytes.copy_from_slice(&digest);
        assert_eq!(hex(&bytes), "ec1c6199b3aa9fee");

        let mut payload = b"7\x00".to_vec();
        let filler = [b'x'; 200];
        payload.extend_from_slice(&filler);
        let digest = blake2b(&payload, 8, b"yt-sql-rnd");
        let mut bytes = [0u8; 8];
        bytes.copy_from_slice(&digest);
        assert_eq!(hex(&bytes), "3dd94838736276a0");
    }

    fn hex(bytes: &[u8]) -> String {
        bytes.iter().map(|byte| format!("{byte:02x}")).collect()
    }

    #[test]
    fn seeded_random_matches_corpus_case() {
        // random_seeded_value: SELECT RANDOM(7) AS result ... WHERE id='vid001'.
        let mut record: Record = vec![
            ("availability".to_string(), text_value("public")),
            ("id".to_string(), text_value("vid001")),
            (
                "webpage_url".to_string(),
                text_value("https://fixture.invalid/watch/vid001"),
            ),
        ];
        record.push(("_yt_sql_source".to_string(), text_value("@yt_sql_fixture")));
        record.push(("_yt_sql_source_facet".to_string(), Value::Null));

        assert_eq!(
            stable_random_identity(&record),
            "[[\"_yt_sql_source\",\"@yt_sql_fixture\"],[\"webpage_url\",\"https://fixture.invalid/watch/vid001\"],[\"id\",\"vid001\"]]"
        );

        let function = ScalarFunction {
            name: "RANDOM".to_string(),
            args: vec![Expr::Literal(Literal {
                value: LiteralValue::Text("7".to_string()),
                raw: "7".to_string(),
                position: 0,
                quoted: false,
            })],
            position: 0,
            kind: None,
            resolved_type: None,
        };
        let value = evaluate_random(&function, &record);
        let Value::Float(random) = value else {
            panic!("expected a float");
        };
        // Python: 0.09132582776249675848845299697131849825382232666015625
        let expected: f64 = "0.09132582776249675848845299697131849825382232666015625"
            .parse()
            .unwrap();
        assert_eq!(random.to_bits(), expected.to_bits());
    }

    #[test]
    fn like_matches_semantics() {
        assert!(like_matches("hello", "hello", false));
        assert!(like_matches("hello", "h%", false));
        assert!(like_matches("hello", "%", false));
        assert!(like_matches("hello", "h_llo", false));
        assert!(like_matches("a\nb", "a%b", false));
        assert!(like_matches("100%", "100\\%", false));
        assert!(!like_matches("100x", "100\\%", false));
        assert!(like_matches("Hello", "hello", true));
        assert!(!like_matches("Hello", "hello", false));
        assert!(!like_matches("", "_", false));
        assert!(like_matches("", "%", false));
    }

    #[test]
    fn float_repr_matches_python() {
        assert_eq!(python_float_repr(1.0), "1.0");
        assert_eq!(python_float_repr(0.1), "0.1");
        assert_eq!(python_float_repr(1e15), "1000000000000000.0");
        assert_eq!(python_float_repr(1e16), "1e+16");
        assert_eq!(python_float_repr(0.0001), "0.0001");
        assert_eq!(python_float_repr(0.00001), "1e-05");
        assert_eq!(python_float_repr(-2.5), "-2.5");
        assert_eq!(python_float_repr(-0.0), "-0.0");
    }

    #[test]
    fn json_dumps_matches_python() {
        let record: Record = vec![
            ("b".to_string(), Value::Int(2)),
            ("a".to_string(), text_value("x\"y")),
        ];
        assert_eq!(
            python_json_dumps(&Value::Record(record)),
            "{\"a\":\"x\\\"y\",\"b\":2}"
        );
        assert_eq!(
            python_json_dumps(&Value::Array(vec![Value::Bool(true), Value::Null])),
            "[true,null]"
        );
    }

    #[test]
    fn like_matches_differential_battery() {
        // (value, pattern, case_insensitive, expected) — expected produced by
        // the Python reference `like_matches` on this battery.
        let cases: &[(&str, &str, bool, bool)] = &[
            ("", "", false, true),
            ("", "", true, true),
            ("", "%", false, true),
            ("", "%", true, true),
            ("", "_", false, false),
            ("", "_", true, false),
            ("", "a", false, false),
            ("", "a", true, false),
            ("", "a_", false, false),
            ("", "a_", true, false),
            ("", "_a", false, false),
            ("", "_a", true, false),
            ("", "%a%", false, false),
            ("", "%a%", true, false),
            ("", "a%c", false, false),
            ("", "a%c", true, false),
            ("", "\\_", false, false),
            ("", "\\_", true, false),
            ("", "\\%", false, false),
            ("", "\\%", true, false),
            ("", "\\\\", false, false),
            ("", "\\\\", true, false),
            ("", "a\\", false, false),
            ("", "a\\", true, false),
            ("", "%%", false, true),
            ("", "%%", true, true),
            ("", "__", false, false),
            ("", "__", true, false),
            ("", "_%_", false, false),
            ("", "_%_", true, false),
            ("", "É%", false, false),
            ("", "É%", true, false),
            ("", "%é", false, false),
            ("", "%é", true, false),
            ("", "a\\a", false, false),
            ("", "a\\a", true, false),
            ("", "100\\%", false, false),
            ("", "100\\%", true, false),
            ("a", "", false, false),
            ("a", "", true, false),
            ("a", "%", false, true),
            ("a", "%", true, true),
            ("a", "_", false, true),
            ("a", "_", true, true),
            ("a", "a", false, true),
            ("a", "a", true, true),
            ("a", "a_", false, false),
            ("a", "a_", true, false),
            ("a", "_a", false, false),
            ("a", "_a", true, false),
            ("a", "%a%", false, true),
            ("a", "%a%", true, true),
            ("a", "a%c", false, false),
            ("a", "a%c", true, false),
            ("a", "\\_", false, false),
            ("a", "\\_", true, false),
            ("a", "\\%", false, false),
            ("a", "\\%", true, false),
            ("a", "\\\\", false, false),
            ("a", "\\\\", true, false),
            ("a", "a\\", false, true),
            ("a", "a\\", true, true),
            ("a", "%%", false, true),
            ("a", "%%", true, true),
            ("a", "__", false, false),
            ("a", "__", true, false),
            ("a", "_%_", false, false),
            ("a", "_%_", true, false),
            ("a", "É%", false, false),
            ("a", "É%", true, false),
            ("a", "%é", false, false),
            ("a", "%é", true, false),
            ("a", "a\\a", false, false),
            ("a", "a\\a", true, false),
            ("a", "100\\%", false, false),
            ("a", "100\\%", true, false),
            ("ab", "", false, false),
            ("ab", "", true, false),
            ("ab", "%", false, true),
            ("ab", "%", true, true),
            ("ab", "_", false, false),
            ("ab", "_", true, false),
            ("ab", "a", false, false),
            ("ab", "a", true, false),
            ("ab", "a_", false, true),
            ("ab", "a_", true, true),
            ("ab", "_a", false, false),
            ("ab", "_a", true, false),
            ("ab", "%a%", false, true),
            ("ab", "%a%", true, true),
            ("ab", "a%c", false, false),
            ("ab", "a%c", true, false),
            ("ab", "\\_", false, false),
            ("ab", "\\_", true, false),
            ("ab", "\\%", false, false),
            ("ab", "\\%", true, false),
            ("ab", "\\\\", false, false),
            ("ab", "\\\\", true, false),
            ("ab", "a\\", false, false),
            ("ab", "a\\", true, false),
            ("ab", "%%", false, true),
            ("ab", "%%", true, true),
            ("ab", "__", false, true),
            ("ab", "__", true, true),
            ("ab", "_%_", false, true),
            ("ab", "_%_", true, true),
            ("ab", "É%", false, false),
            ("ab", "É%", true, false),
            ("ab", "%é", false, false),
            ("ab", "%é", true, false),
            ("ab", "a\\a", false, false),
            ("ab", "a\\a", true, false),
            ("ab", "100\\%", false, false),
            ("ab", "100\\%", true, false),
            ("abc", "", false, false),
            ("abc", "", true, false),
            ("abc", "%", false, true),
            ("abc", "%", true, true),
            ("abc", "_", false, false),
            ("abc", "_", true, false),
            ("abc", "a", false, false),
            ("abc", "a", true, false),
            ("abc", "a_", false, false),
            ("abc", "a_", true, false),
            ("abc", "_a", false, false),
            ("abc", "_a", true, false),
            ("abc", "%a%", false, true),
            ("abc", "%a%", true, true),
            ("abc", "a%c", false, true),
            ("abc", "a%c", true, true),
            ("abc", "\\_", false, false),
            ("abc", "\\_", true, false),
            ("abc", "\\%", false, false),
            ("abc", "\\%", true, false),
            ("abc", "\\\\", false, false),
            ("abc", "\\\\", true, false),
            ("abc", "a\\", false, false),
            ("abc", "a\\", true, false),
            ("abc", "%%", false, true),
            ("abc", "%%", true, true),
            ("abc", "__", false, false),
            ("abc", "__", true, false),
            ("abc", "_%_", false, true),
            ("abc", "_%_", true, true),
            ("abc", "É%", false, false),
            ("abc", "É%", true, false),
            ("abc", "%é", false, false),
            ("abc", "%é", true, false),
            ("abc", "a\\a", false, false),
            ("abc", "a\\a", true, false),
            ("abc", "100\\%", false, false),
            ("abc", "100\\%", true, false),
            ("a\nb", "", false, false),
            ("a\nb", "", true, false),
            ("a\nb", "%", false, true),
            ("a\nb", "%", true, true),
            ("a\nb", "_", false, false),
            ("a\nb", "_", true, false),
            ("a\nb", "a", false, false),
            ("a\nb", "a", true, false),
            ("a\nb", "a_", false, false),
            ("a\nb", "a_", true, false),
            ("a\nb", "_a", false, false),
            ("a\nb", "_a", true, false),
            ("a\nb", "%a%", false, true),
            ("a\nb", "%a%", true, true),
            ("a\nb", "a%c", false, false),
            ("a\nb", "a%c", true, false),
            ("a\nb", "\\_", false, false),
            ("a\nb", "\\_", true, false),
            ("a\nb", "\\%", false, false),
            ("a\nb", "\\%", true, false),
            ("a\nb", "\\\\", false, false),
            ("a\nb", "\\\\", true, false),
            ("a\nb", "a\\", false, false),
            ("a\nb", "a\\", true, false),
            ("a\nb", "%%", false, true),
            ("a\nb", "%%", true, true),
            ("a\nb", "__", false, false),
            ("a\nb", "__", true, false),
            ("a\nb", "_%_", false, true),
            ("a\nb", "_%_", true, true),
            ("a\nb", "É%", false, false),
            ("a\nb", "É%", true, false),
            ("a\nb", "%é", false, false),
            ("a\nb", "%é", true, false),
            ("a\nb", "a\\a", false, false),
            ("a\nb", "a\\a", true, false),
            ("a\nb", "100\\%", false, false),
            ("a\nb", "100\\%", true, false),
            ("Écé", "", false, false),
            ("Écé", "", true, false),
            ("Écé", "%", false, true),
            ("Écé", "%", true, true),
            ("Écé", "_", false, false),
            ("Écé", "_", true, false),
            ("Écé", "a", false, false),
            ("Écé", "a", true, false),
            ("Écé", "a_", false, false),
            ("Écé", "a_", true, false),
            ("Écé", "_a", false, false),
            ("Écé", "_a", true, false),
            ("Écé", "%a%", false, false),
            ("Écé", "%a%", true, false),
            ("Écé", "a%c", false, false),
            ("Écé", "a%c", true, false),
            ("Écé", "\\_", false, false),
            ("Écé", "\\_", true, false),
            ("Écé", "\\%", false, false),
            ("Écé", "\\%", true, false),
            ("Écé", "\\\\", false, false),
            ("Écé", "\\\\", true, false),
            ("Écé", "a\\", false, false),
            ("Écé", "a\\", true, false),
            ("Écé", "%%", false, true),
            ("Écé", "%%", true, true),
            ("Écé", "__", false, false),
            ("Écé", "__", true, false),
            ("Écé", "_%_", false, true),
            ("Écé", "_%_", true, true),
            ("Écé", "É%", false, true),
            ("Écé", "É%", true, true),
            ("Écé", "%é", false, true),
            ("Écé", "%é", true, true),
            ("Écé", "a\\a", false, false),
            ("Écé", "a\\a", true, false),
            ("Écé", "100\\%", false, false),
            ("Écé", "100\\%", true, false),
            ("aaa", "", false, false),
            ("aaa", "", true, false),
            ("aaa", "%", false, true),
            ("aaa", "%", true, true),
            ("aaa", "_", false, false),
            ("aaa", "_", true, false),
            ("aaa", "a", false, false),
            ("aaa", "a", true, false),
            ("aaa", "a_", false, false),
            ("aaa", "a_", true, false),
            ("aaa", "_a", false, false),
            ("aaa", "_a", true, false),
            ("aaa", "%a%", false, true),
            ("aaa", "%a%", true, true),
            ("aaa", "a%c", false, false),
            ("aaa", "a%c", true, false),
            ("aaa", "\\_", false, false),
            ("aaa", "\\_", true, false),
            ("aaa", "\\%", false, false),
            ("aaa", "\\%", true, false),
            ("aaa", "\\\\", false, false),
            ("aaa", "\\\\", true, false),
            ("aaa", "a\\", false, false),
            ("aaa", "a\\", true, false),
            ("aaa", "%%", false, true),
            ("aaa", "%%", true, true),
            ("aaa", "__", false, false),
            ("aaa", "__", true, false),
            ("aaa", "_%_", false, true),
            ("aaa", "_%_", true, true),
            ("aaa", "É%", false, false),
            ("aaa", "É%", true, false),
            ("aaa", "%é", false, false),
            ("aaa", "%é", true, false),
            ("aaa", "a\\a", false, false),
            ("aaa", "a\\a", true, false),
            ("aaa", "100\\%", false, false),
            ("aaa", "100\\%", true, false),
            ("\\a", "", false, false),
            ("\\a", "", true, false),
            ("\\a", "%", false, true),
            ("\\a", "%", true, true),
            ("\\a", "_", false, false),
            ("\\a", "_", true, false),
            ("\\a", "a", false, false),
            ("\\a", "a", true, false),
            ("\\a", "a_", false, false),
            ("\\a", "a_", true, false),
            ("\\a", "_a", false, true),
            ("\\a", "_a", true, true),
            ("\\a", "%a%", false, true),
            ("\\a", "%a%", true, true),
            ("\\a", "a%c", false, false),
            ("\\a", "a%c", true, false),
            ("\\a", "\\_", false, false),
            ("\\a", "\\_", true, false),
            ("\\a", "\\%", false, false),
            ("\\a", "\\%", true, false),
            ("\\a", "\\\\", false, false),
            ("\\a", "\\\\", true, false),
            ("\\a", "a\\", false, false),
            ("\\a", "a\\", true, false),
            ("\\a", "%%", false, true),
            ("\\a", "%%", true, true),
            ("\\a", "__", false, true),
            ("\\a", "__", true, true),
            ("\\a", "_%_", false, true),
            ("\\a", "_%_", true, true),
            ("\\a", "É%", false, false),
            ("\\a", "É%", true, false),
            ("\\a", "%é", false, false),
            ("\\a", "%é", true, false),
            ("\\a", "a\\a", false, false),
            ("\\a", "a\\a", true, false),
            ("\\a", "100\\%", false, false),
            ("\\a", "100\\%", true, false),
            ("a%b", "", false, false),
            ("a%b", "", true, false),
            ("a%b", "%", false, true),
            ("a%b", "%", true, true),
            ("a%b", "_", false, false),
            ("a%b", "_", true, false),
            ("a%b", "a", false, false),
            ("a%b", "a", true, false),
            ("a%b", "a_", false, false),
            ("a%b", "a_", true, false),
            ("a%b", "_a", false, false),
            ("a%b", "_a", true, false),
            ("a%b", "%a%", false, true),
            ("a%b", "%a%", true, true),
            ("a%b", "a%c", false, false),
            ("a%b", "a%c", true, false),
            ("a%b", "\\_", false, false),
            ("a%b", "\\_", true, false),
            ("a%b", "\\%", false, false),
            ("a%b", "\\%", true, false),
            ("a%b", "\\\\", false, false),
            ("a%b", "\\\\", true, false),
            ("a%b", "a\\", false, false),
            ("a%b", "a\\", true, false),
            ("a%b", "%%", false, true),
            ("a%b", "%%", true, true),
            ("a%b", "__", false, false),
            ("a%b", "__", true, false),
            ("a%b", "_%_", false, true),
            ("a%b", "_%_", true, true),
            ("a%b", "É%", false, false),
            ("a%b", "É%", true, false),
            ("a%b", "%é", false, false),
            ("a%b", "%é", true, false),
            ("a%b", "a\\a", false, false),
            ("a%b", "a\\a", true, false),
            ("a%b", "100\\%", false, false),
            ("a%b", "100\\%", true, false),
            ("100%", "", false, false),
            ("100%", "", true, false),
            ("100%", "%", false, true),
            ("100%", "%", true, true),
            ("100%", "_", false, false),
            ("100%", "_", true, false),
            ("100%", "a", false, false),
            ("100%", "a", true, false),
            ("100%", "a_", false, false),
            ("100%", "a_", true, false),
            ("100%", "_a", false, false),
            ("100%", "_a", true, false),
            ("100%", "%a%", false, false),
            ("100%", "%a%", true, false),
            ("100%", "a%c", false, false),
            ("100%", "a%c", true, false),
            ("100%", "\\_", false, false),
            ("100%", "\\_", true, false),
            ("100%", "\\%", false, false),
            ("100%", "\\%", true, false),
            ("100%", "\\\\", false, false),
            ("100%", "\\\\", true, false),
            ("100%", "a\\", false, false),
            ("100%", "a\\", true, false),
            ("100%", "%%", false, true),
            ("100%", "%%", true, true),
            ("100%", "__", false, false),
            ("100%", "__", true, false),
            ("100%", "_%_", false, true),
            ("100%", "_%_", true, true),
            ("100%", "É%", false, false),
            ("100%", "É%", true, false),
            ("100%", "%é", false, false),
            ("100%", "%é", true, false),
            ("100%", "a\\a", false, false),
            ("100%", "a\\a", true, false),
            ("100%", "100\\%", false, true),
            ("100%", "100\\%", true, true),
            ("x_y", "", false, false),
            ("x_y", "", true, false),
            ("x_y", "%", false, true),
            ("x_y", "%", true, true),
            ("x_y", "_", false, false),
            ("x_y", "_", true, false),
            ("x_y", "a", false, false),
            ("x_y", "a", true, false),
            ("x_y", "a_", false, false),
            ("x_y", "a_", true, false),
            ("x_y", "_a", false, false),
            ("x_y", "_a", true, false),
            ("x_y", "%a%", false, false),
            ("x_y", "%a%", true, false),
            ("x_y", "a%c", false, false),
            ("x_y", "a%c", true, false),
            ("x_y", "\\_", false, false),
            ("x_y", "\\_", true, false),
            ("x_y", "\\%", false, false),
            ("x_y", "\\%", true, false),
            ("x_y", "\\\\", false, false),
            ("x_y", "\\\\", true, false),
            ("x_y", "a\\", false, false),
            ("x_y", "a\\", true, false),
            ("x_y", "%%", false, true),
            ("x_y", "%%", true, true),
            ("x_y", "__", false, false),
            ("x_y", "__", true, false),
            ("x_y", "_%_", false, true),
            ("x_y", "_%_", true, true),
            ("x_y", "É%", false, false),
            ("x_y", "É%", true, false),
            ("x_y", "%é", false, false),
            ("x_y", "%é", true, false),
            ("x_y", "a\\a", false, false),
            ("x_y", "a\\a", true, false),
            ("x_y", "100\\%", false, false),
            ("x_y", "100\\%", true, false),
            ("AB", "", false, false),
            ("AB", "", true, false),
            ("AB", "%", false, true),
            ("AB", "%", true, true),
            ("AB", "_", false, false),
            ("AB", "_", true, false),
            ("AB", "a", false, false),
            ("AB", "a", true, false),
            ("AB", "a_", false, false),
            ("AB", "a_", true, true),
            ("AB", "_a", false, false),
            ("AB", "_a", true, false),
            ("AB", "%a%", false, false),
            ("AB", "%a%", true, true),
            ("AB", "a%c", false, false),
            ("AB", "a%c", true, false),
            ("AB", "\\_", false, false),
            ("AB", "\\_", true, false),
            ("AB", "\\%", false, false),
            ("AB", "\\%", true, false),
            ("AB", "\\\\", false, false),
            ("AB", "\\\\", true, false),
            ("AB", "a\\", false, false),
            ("AB", "a\\", true, false),
            ("AB", "%%", false, true),
            ("AB", "%%", true, true),
            ("AB", "__", false, true),
            ("AB", "__", true, true),
            ("AB", "_%_", false, true),
            ("AB", "_%_", true, true),
            ("AB", "É%", false, false),
            ("AB", "É%", true, false),
            ("AB", "%é", false, false),
            ("AB", "%é", true, false),
            ("AB", "a\\a", false, false),
            ("AB", "a\\a", true, false),
            ("AB", "100\\%", false, false),
            ("AB", "100\\%", true, false),
            ("éÉ", "", false, false),
            ("éÉ", "", true, false),
            ("éÉ", "%", false, true),
            ("éÉ", "%", true, true),
            ("éÉ", "_", false, false),
            ("éÉ", "_", true, false),
            ("éÉ", "a", false, false),
            ("éÉ", "a", true, false),
            ("éÉ", "a_", false, false),
            ("éÉ", "a_", true, false),
            ("éÉ", "_a", false, false),
            ("éÉ", "_a", true, false),
            ("éÉ", "%a%", false, false),
            ("éÉ", "%a%", true, false),
            ("éÉ", "a%c", false, false),
            ("éÉ", "a%c", true, false),
            ("éÉ", "\\_", false, false),
            ("éÉ", "\\_", true, false),
            ("éÉ", "\\%", false, false),
            ("éÉ", "\\%", true, false),
            ("éÉ", "\\\\", false, false),
            ("éÉ", "\\\\", true, false),
            ("éÉ", "a\\", false, false),
            ("éÉ", "a\\", true, false),
            ("éÉ", "%%", false, true),
            ("éÉ", "%%", true, true),
            ("éÉ", "__", false, true),
            ("éÉ", "__", true, true),
            ("éÉ", "_%_", false, true),
            ("éÉ", "_%_", true, true),
            ("éÉ", "É%", false, false),
            ("éÉ", "É%", true, true),
            ("éÉ", "%é", false, false),
            ("éÉ", "%é", true, true),
            ("éÉ", "a\\a", false, false),
            ("éÉ", "a\\a", true, false),
            ("éÉ", "100\\%", false, false),
            ("éÉ", "100\\%", true, false),
        ];
        for (value, pattern, case_insensitive, expected) in cases {
            assert_eq!(
                like_matches(value, pattern, *case_insensitive),
                *expected,
                "value={value:?} pattern={pattern:?} ci={case_insensitive}"
            );
        }
    }

    #[test]
    fn float_repr_differential_battery() {
        // (python_literal, python_repr) pairs produced by the Python reference.
        let cases: &[(&str, &str)] = &[
            ("0.0", "0.0"),
            ("-0.0", "-0.0"),
            ("1.0", "1.0"),
            ("-1.0", "-1.0"),
            ("0.1", "0.1"),
            ("0.5", "0.5"),
            ("1000000000000000.0", "1000000000000000.0"),
            ("1e+16", "1e+16"),
            ("1e+17", "1e+17"),
            ("1.5e-05", "1.5e-05"),
            ("0.0001", "0.0001"),
            ("1e-05", "1e-05"),
            ("123.456", "123.456"),
            ("0.3333333333333333", "0.3333333333333333"),
            ("9007199254740992.0", "9007199254740992.0"),
            ("5e-324", "5e-324"),
            ("1.7976931348623157e+308", "1.7976931348623157e+308"),
            ("3.0", "3.0"),
            ("12.25", "12.25"),
            ("-0.125", "-0.125"),
            ("-3.5233447033367526e+17", "-3.5233447033367526e+17"),
            ("-0.6983016521509962", "-0.6983016521509962"),
            ("3.031149846687232e-10", "3.031149846687232e-10"),
            ("6.425485839826166e+17", "6.425485839826166e+17"),
            ("-0.8117399161206349", "-0.8117399161206349"),
            ("9777560.257249864", "9777560.257249864"),
            ("-5.7060363832867654e+17", "-5.7060363832867654e+17"),
            ("-0.8281055326216566", "-0.8281055326216566"),
            ("0.0004083712415730073", "0.0004083712415730073"),
            ("-8.185739733122698e+17", "-8.185739733122698e+17"),
            ("-0.15096162171497207", "-0.15096162171497207"),
            ("2.4642113586426915e-08", "2.4642113586426915e-08"),
            ("8.94899401414975e+17", "8.94899401414975e+17"),
            ("0.2612518314634742", "0.2612518314634742"),
            ("6.786977225686509e-11", "6.786977225686509e-11"),
            ("1.5420589723499725e+17", "1.5420589723499725e+17"),
            ("-0.20663905069843969", "-0.20663905069843969"),
            ("2.8412763075697005e-11", "2.8412763075697005e-11"),
            ("1.1332979587418522e+17", "1.1332979587418522e+17"),
            ("-0.7336503671167898", "-0.7336503671167898"),
            ("225023560.5770203", "225023560.5770203"),
            ("-7.644155238432632e+17", "-7.644155238432632e+17"),
            ("-0.38303635179613127", "-0.38303635179613127"),
            ("6.226549981079341e-06", "6.226549981079341e-06"),
            ("-7.938885751128173e+17", "-7.938885751128173e+17"),
            ("0.1424087828235845", "0.1424087828235845"),
            ("6.998741134522241e-10", "6.998741134522241e-10"),
            ("9.548893141911565e+16", "9.548893141911565e+16"),
            ("-0.8744220500533537", "-0.8744220500533537"),
            ("3.6377667215718176e-06", "3.6377667215718176e-06"),
            ("-7171009773016448.0", "-7171009773016448.0"),
            ("0.06344049316037137", "0.06344049316037137"),
            ("407491.71997713734", "407491.71997713734"),
            ("1.7112372701527757e+17", "1.7112372701527757e+17"),
            ("-0.09363124725844929", "-0.09363124725844929"),
            ("2.287040686521014e-06", "2.287040686521014e-06"),
            ("3.979888674591424e+17", "3.979888674591424e+17"),
            ("-0.5118069785556942", "-0.5118069785556942"),
            ("77097845.30024911", "77097845.30024911"),
            ("-9767280889488896.0", "-9767280889488896.0"),
            ("-0.3130486200832534", "-0.3130486200832534"),
            ("61687301414.84827", "61687301414.84827"),
            ("9.603496949851643e+17", "9.603496949851643e+17"),
            ("-0.7638684434900758", "-0.7638684434900758"),
            ("3.3449825742818176", "3.3449825742818176"),
            ("-6.960309306789905e+17", "-6.960309306789905e+17"),
            ("-0.022073799048388798", "-0.022073799048388798"),
            ("1.8257301788515253e-11", "1.8257301788515253e-11"),
            ("5.291417324256261e+17", "5.291417324256261e+17"),
            ("0.14605188055476792", "0.14605188055476792"),
            ("0.8754778118308882", "0.8754778118308882"),
            ("-3.1975527561760896e+17", "-3.1975527561760896e+17"),
            ("-0.29964322456166337", "-0.29964322456166337"),
            ("130200.31753885781", "130200.31753885781"),
            ("-8.624741011862789e+17", "-8.624741011862789e+17"),
            ("-0.8128080078261928", "-0.8128080078261928"),
            ("6.285013564119994e-11", "6.285013564119994e-11"),
            ("-8.786611448055606e+17", "-8.786611448055606e+17"),
            ("0.4029840426088478", "0.4029840426088478"),
            ("84820.4732206506", "84820.4732206506"),
            ("-4.3080893581170157e+17", "-4.3080893581170157e+17"),
            ("-0.22841711510657836", "-0.22841711510657836"),
            ("2.432544409690993e-12", "2.432544409690993e-12"),
            ("8.812971332921874e+17", "8.812971332921874e+17"),
            ("-0.28907178091930796", "-0.28907178091930796"),
            ("5124764.569818486", "5124764.569818486"),
            ("-8.820911613373792e+17", "-8.820911613373792e+17"),
            ("0.5364659769450415", "0.5364659769450415"),
            ("0.00025261762113024263", "0.00025261762113024263"),
            ("-2.042046429075346e+17", "-2.042046429075346e+17"),
            ("0.8336324523601228", "0.8336324523601228"),
            ("9.470113735770453e-07", "9.470113735770453e-07"),
            ("-1.0162519810133811e+17", "-1.0162519810133811e+17"),
            ("0.0988798182880748", "0.0988798182880748"),
            ("28946.72122483548", "28946.72122483548"),
            ("7.279689393970304e+17", "7.279689393970304e+17"),
            ("-0.4431578709722057", "-0.4431578709722057"),
            ("13.289488550774355", "13.289488550774355"),
            ("3.654461187749033e+17", "3.654461187749033e+17"),
            ("-0.23911739948792454", "-0.23911739948792454"),
            ("2.1490408862818234e-10", "2.1490408862818234e-10"),
            ("-6.475645430192594e+17", "-6.475645430192594e+17"),
            ("-0.5360862663609285", "-0.5360862663609285"),
            ("978682.4691269705", "978682.4691269705"),
            ("6.621871231365727e+17", "6.621871231365727e+17"),
            ("-0.6353142520376054", "-0.6353142520376054"),
            ("6.721752222221796e-08", "6.721752222221796e-08"),
            ("-1.6210699774934413e+17", "-1.6210699774934413e+17"),
            ("-0.26149285421054924", "-0.26149285421054924"),
            ("3.375656746067953e-08", "3.375656746067953e-08"),
            ("3.809873142719557e+17", "3.809873142719557e+17"),
            ("0.030982866141556764", "0.030982866141556764"),
            ("3.594862934022255e-11", "3.594862934022255e-11"),
            ("-8.67125555942505e+16", "-8.67125555942505e+16"),
            ("0.7419590023155433", "0.7419590023155433"),
            ("2044160093.9922109", "2044160093.9922109"),
            ("-2.1524218621746266e+17", "-2.1524218621746266e+17"),
            ("-0.20204233535945404", "-0.20204233535945404"),
            ("212.0439679187441", "212.0439679187441"),
            ("-8.755043567626248e+17", "-8.755043567626248e+17"),
            ("-0.8653047683139503", "-0.8653047683139503"),
            ("1.990920881711621e-07", "1.990920881711621e-07"),
            ("-7.801433899990671e+17", "-7.801433899990671e+17"),
            ("0.20145452100896244", "0.20145452100896244"),
            ("439717024.0074649", "439717024.0074649"),
            ("-6.97470135441144e+17", "-6.97470135441144e+17"),
            ("-0.797071263954807", "-0.797071263954807"),
            ("2.6456103808200786e-12", "2.6456103808200786e-12"),
            ("-8.593688476930205e+17", "-8.593688476930205e+17"),
            ("-0.5840946344424935", "-0.5840946344424935"),
            ("0.00146964594455641", "0.00146964594455641"),
            ("9.109360478429427e+17", "9.109360478429427e+17"),
            ("0.20455837792401654", "0.20455837792401654"),
            ("7.06540738391517e-09", "7.06540738391517e-09"),
            ("6.978738529692298e+17", "6.978738529692298e+17"),
            ("0.9862054434094278", "0.9862054434094278"),
            ("977250.7262561733", "977250.7262561733"),
            ("-3.762953715639612e+17", "-3.762953715639612e+17"),
            ("-0.7117650195630252", "-0.7117650195630252"),
            ("0.005856827503456491", "0.005856827503456491"),
            ("-4.275611298001754e+16", "-4.275611298001754e+16"),
            ("0.3841135376906186", "0.3841135376906186"),
            ("3.151455804213388e-05", "3.151455804213388e-05"),
            ("9.019711457494042e+17", "9.019711457494042e+17"),
            ("0.05651479008424953", "0.05651479008424953"),
            ("78706638.7602703", "78706638.7602703"),
            ("8.282915655827891e+17", "8.282915655827891e+17"),
            ("0.5162859190718745", "0.5162859190718745"),
            ("5.552353157592564e-10", "5.552353157592564e-10"),
            ("3.923935718156037e+17", "3.923935718156037e+17"),
            ("-0.4777696055412761", "-0.4777696055412761"),
            ("6.994243464683129e-07", "6.994243464683129e-07"),
            ("-2.8860766035410906e+17", "-2.8860766035410906e+17"),
            ("-0.5544144878895225", "-0.5544144878895225"),
            ("9085988.59738186", "9085988.59738186"),
            ("-3.4067000990447526e+17", "-3.4067000990447526e+17"),
            ("-0.5539166537936298", "-0.5539166537936298"),
            ("1.238267893636467e-05", "1.238267893636467e-05"),
            ("6.121571695713349e+17", "6.121571695713349e+17"),
            ("0.6366658866507464", "0.6366658866507464"),
            ("0.00036126612323032916", "0.00036126612323032916"),
            ("-6.001640332097006e+17", "-6.001640332097006e+17"),
            ("-0.014436314172110887", "-0.014436314172110887"),
            ("5.318754065050025e-12", "5.318754065050025e-12"),
            ("5.802282732638497e+17", "5.802282732638497e+17"),
            ("-0.05551987500228939", "-0.05551987500228939"),
            ("26614358725.142456", "26614358725.142456"),
            ("9.130301526826757e+17", "9.130301526826757e+17"),
            ("-0.1055446444665531", "-0.1055446444665531"),
            ("14.992339220419877", "14.992339220419877"),
            ("9.100012626426662e+17", "9.100012626426662e+17"),
            ("-0.27072822927626783", "-0.27072822927626783"),
            ("0.00010764761865050658", "0.00010764761865050658"),
            ("-5.984003548761958e+16", "-5.984003548761958e+16"),
            ("-0.32452504032293916", "-0.32452504032293916"),
            ("132670729470.08795", "132670729470.08795"),
            ("6.808710545585797e+17", "6.808710545585797e+17"),
            ("-0.04105314747692357", "-0.04105314747692357"),
            ("6.081331920260648e-10", "6.081331920260648e-10"),
            ("6.69297615596438e+17", "6.69297615596438e+17"),
            ("-0.7601927383277247", "-0.7601927383277247"),
            ("1.1857169916380115e-05", "1.1857169916380115e-05"),
            ("-4.393451081199949e+16", "-4.393451081199949e+16"),
            ("-0.6429565633248528", "-0.6429565633248528"),
            ("3.1565417240811056", "3.1565417240811056"),
            ("-8.265002846595116e+17", "-8.265002846595116e+17"),
            ("0.8923306907960367", "0.8923306907960367"),
            ("378444.0445149941", "378444.0445149941"),
            ("-1.97226364264597e+17", "-1.97226364264597e+17"),
            ("0.8935940129297859", "0.8935940129297859"),
            ("1.3824437439617448e-06", "1.3824437439617448e-06"),
            ("9.862247128343337e+17", "9.862247128343337e+17"),
            ("-0.944902298582335", "-0.944902298582335"),
            ("309755.8004095785", "309755.8004095785"),
            ("6.130039640643922e+17", "6.130039640643922e+17"),
            ("-0.7076513825122517", "-0.7076513825122517"),
            ("866659.0515302363", "866659.0515302363"),
            ("3.1453658547203994e+17", "3.1453658547203994e+17"),
            ("-0.29918497568499425", "-0.29918497568499425"),
            ("3.2702687024282166e-08", "3.2702687024282166e-08"),
        ];
        for (literal, expected) in cases {
            let value: f64 = literal.parse().unwrap();
            assert_eq!(python_float_repr(value), *expected, "literal={}", literal);
        }
    }

    #[test]
    fn json_dumps_differential_battery() {
        // (value, json.dumps(..., ensure_ascii=False, sort_keys=True,
        // separators=(",", ":"), default=str)) pairs from the Python reference.
        let cases: &[(Value, &str)] = &[
            (Value::Null, "null"),
            (Value::Bool(true), "true"),
            (Value::Bool(false), "false"),
            (Value::Int(0), "0"),
            (Value::Int(42), "42"),
            (Value::Int(-7), "-7"),
            (Value::Float(0.5), "0.5"),
            (Value::Float(1e+16), "1e+16"),
            (Value::Text("plain".into()), "\"plain\""),
            (Value::Text("q\"uo\\te".into()), "\"q\\\"uo\\\\te\""),
            (Value::Text("line\nbreak".into()), "\"line\\nbreak\""),
            (Value::Text("éÉ".into()), "\"éÉ\""),
            (
                Value::Array(vec![
                    Value::Int(1),
                    Value::Text("two".into()),
                    Value::Null,
                    Value::Bool(true),
                ]),
                "[1,\"two\",null,true]",
            ),
            (Value::Array(vec![]), "[]"),
            (Value::Record(vec![]), "{}"),
            (
                Value::Record(vec![
                    ("b".into(), Value::Int(2)),
                    (
                        "a".into(),
                        Value::Array(vec![
                            Value::Int(1),
                            Value::Record(vec![("c".into(), Value::Null)]),
                        ]),
                    ),
                ]),
                "{\"a\":[1,{\"c\":null}],\"b\":2}",
            ),
            (
                Value::Array(vec![Value::Array(vec![
                    Value::Array(vec![
                        Value::Text("_yt_sql_source".into()),
                        Value::Text("@yt_sql_fixture".into()),
                    ]),
                    Value::Array(vec![
                        Value::Text("webpage_url".into()),
                        Value::Text("https://x/y".into()),
                    ]),
                    Value::Array(vec![Value::Text("id".into()), Value::Text("vid001".into())]),
                ])]),
                "[[[\"_yt_sql_source\",\"@yt_sql_fixture\"],[\"webpage_url\",\"https://x/y\"],[\"id\",\"vid001\"]]]",
            ),
            (
                Value::Record(vec![(
                    "k".into(),
                    Value::Array(vec![
                        Value::Float(1.5),
                        Value::Float(-0.0),
                        Value::Float(1e+16),
                    ]),
                )]),
                "{\"k\":[1.5,-0.0,1e+16]}",
            ),
        ];
        for (value, expected) in cases {
            assert_eq!(&python_json_dumps(value), expected);
        }
    }

    #[test]
    fn average_value_differential_battery() {
        // (total, count, str(_average_value(total, count))) from the Python
        // reference; AVG emits exact quotients or 6-digit half-even rounding.
        let cases: &[(Value, usize, &str)] = &[
            (Value::Int(0), 1, "0"),
            (Value::Int(7), 2, "3.5"),
            (Value::Int(1), 3, "0.333333"),
            (Value::Int(10), 4, "2.5"),
            (Value::Int(3), 6, "0.5"),
            (Value::Int(5), 6, "0.833333"),
            (Value::Int(1), 7, "0.142857"),
            (Value::Int(-1), 3, "-0.333333"),
            (Value::Int(15), 3, "5"),
            (Value::Int(100), 8, "12.5"),
            (Value::Int(6), 3, "2"),
            (Value::Int(9), 4, "2.25"),
            (Value::Int(2), 3, "0.666667"),
            (Value::Int(-7), 2, "-3.5"),
            (Value::Int(1), 1, "1"),
            (Value::Int(255), 6, "42.5"),
            (Value::Int(4), 3, "1.333333"),
            (Value::Float(2.5), 2, "1.25"),
            (Value::Float(0.5), 3, "0.166667"),
            (Value::Float(1.5), 7, "0.214286"),
            (Value::Float(-2.5), 2, "-1.25"),
            (Value::Float(10.0), 4, "2.5"),
        ];
        for (total, count, expected) in cases {
            let Value::Decimal(fraction) = average_value(total, *count).unwrap() else {
                panic!("expected a decimal average");
            };
            assert_eq!(
                &fraction.decimal_string(),
                expected,
                "total={:?} count={}",
                total,
                count
            );
        }
    }

    #[test]
    fn sum_and_min_max_semantics() {
        // Python sum over booleans and mixed numeric families.
        assert!(matches!(
            sum_values(&[Value::Bool(true), Value::Int(2), Value::Float(0.5)]),
            Some(Value::Float(_))
        ));
        assert!(sum_values(&[Value::Text("a".into()), Value::Text("b".into())]).is_none());
        assert!(matches!(
            python_min(&[Value::Text("b".into()), Value::Text("a".into())]),
            Some(Value::Text(text)) if text == "a"
        ));
        // Incomparable families make min/max fail (Python TypeError).
        assert!(python_max(&[Value::Int(1), Value::Text("a".into())]).is_none());
        // NaN never equals itself in Python min/max ordering checks... the first
        // element is kept without comparisons, so single-element input returns.
        assert!(matches!(python_min(&[Value::Int(7)]), Some(Value::Int(7))));
    }

    #[test]
    fn apply_query_filters_projects_and_orders() {
        let records: Vec<Record> = vec![
            vec![
                ("id".to_string(), text_value("a")),
                ("view_count".to_string(), Value::Int(30)),
            ],
            vec![
                ("id".to_string(), text_value("b")),
                ("view_count".to_string(), Value::Int(10)),
            ],
            vec![
                ("id".to_string(), text_value("c")),
                ("view_count".to_string(), Value::Int(20)),
            ],
        ];

        let query = Query {
            from_source: Some("@fixture".to_string()),
            select: vec![
                SelectTerm {
                    field: "id".to_string(),
                    alias: None,
                    position: 0,
                    kind: Some("string".to_string()),
                    expression: None,
                },
                SelectTerm {
                    field: "view_count".to_string(),
                    alias: Some("views".to_string()),
                    position: 1,
                    kind: Some("count".to_string()),
                    expression: None,
                },
            ],
            predicate: Some(Box::new(BoolExpr::Binary(Binary {
                operator: ">".to_string(),
                left: Box::new(BoolExpr::Literal(field_literal("view_count"))),
                right: Box::new(BoolExpr::Literal(Literal {
                    value: LiteralValue::Text("10".to_string()),
                    raw: "10".to_string(),
                    position: 0,
                    quoted: false,
                })),
            }))),
            order_by: vec![OrderTerm {
                field: "view_count".to_string(),
                descending: true,
                position: 0,
                kind: Some("count".to_string()),
                expression: None,
            }],
            ..Query::default()
        };

        let result = apply_query(&records, &query, true).unwrap();
        assert_eq!(result.len(), 2);
        // Simple queries return the (filtered, ordered) source records; the
        // SELECT projection happens at CTE/set-operation boundaries.
        assert!(matches!(record_get(&result[0], "id"), Some(Value::Text(text)) if text == "a"));
        assert!(matches!(
            record_get(&result[0], "view_count"),
            Some(Value::Int(30))
        ));
        assert!(matches!(record_get(&result[1], "id"), Some(Value::Text(text)) if text == "c"));
        assert!(matches!(
            record_get(&result[1], "view_count"),
            Some(Value::Int(20))
        ));
        assert!(
            result
                .iter()
                .all(|row| record_get(row, "_yt_sql_result_row").is_none())
        );
    }

    #[test]
    fn apply_query_count_star_grouping() {
        let records: Vec<Record> = (0..4)
            .map(|index| {
                vec![
                    ("id".to_string(), Value::Int(index)),
                    ("fixture_group".to_string(), Value::Int(index % 2)),
                ]
            })
            .collect();
        let query = Query {
            from_source: Some("@fixture".to_string()),
            select: vec![
                SelectTerm {
                    field: "fixture_group".to_string(),
                    alias: None,
                    position: 0,
                    kind: Some("count".to_string()),
                    expression: None,
                },
                SelectTerm {
                    field: "n".to_string(),
                    alias: None,
                    position: 1,
                    kind: Some("count".to_string()),
                    expression: Some(Box::new(Expr::Aggregate(crate::model::AggregateFunction {
                        name: "COUNT".to_string(),
                        args: Vec::new(),
                        count_star: true,
                        filter_predicate: None,
                        position: 0,
                        kind: None,
                    }))),
                },
                SelectTerm {
                    field: "avg_view".to_string(),
                    alias: None,
                    position: 2,
                    kind: None,
                    expression: Some(Box::new(Expr::Aggregate(crate::model::AggregateFunction {
                        name: "AVG".to_string(),
                        args: vec![Expr::Field(Field {
                            name: "id".to_string(),
                            position: 0,
                            kind: Some("count".to_string()),
                        })],
                        count_star: false,
                        filter_predicate: None,
                        position: 0,
                        kind: None,
                    }))),
                },
            ],
            group_by: vec![Expr::Field(Field {
                name: "fixture_group".to_string(),
                position: 0,
                kind: Some("count".to_string()),
            })],
            ..Query::default()
        };

        let result = apply_query(&records, &query, true).unwrap();
        assert_eq!(result.len(), 2);
        // Group 0: ids 0 and 2 → COUNT 2, AVG = 1 exactly.
        let groups: Vec<i64> = result
            .iter()
            .filter_map(|row| match record_get(row, "fixture_group") {
                Some(Value::Int(value)) => Some(*value),
                _ => None,
            })
            .collect();
        assert!(groups.contains(&0) && groups.contains(&1));
        for row in &result {
            assert!(matches!(record_get(row, "n"), Some(Value::Int(2))));
            let Value::Decimal(fraction) = record_get(row, "avg_view").unwrap() else {
                panic!("expected decimal AVG");
            };
            let expected = if matches!(record_get(row, "fixture_group"), Some(Value::Int(0))) {
                "1"
            } else {
                "2"
            };
            assert_eq!(fraction.decimal_string(), expected);
        }
    }

    #[test]
    fn three_valued_logic_short_circuit() {
        let context = EvaluationContext::new(Vec::new());
        let null_node = BoolExpr::Literal(Literal {
            value: LiteralValue::Null,
            raw: "NULL".to_string(),
            position: 0,
            quoted: false,
        });
        let true_node = BoolExpr::Literal(Literal {
            value: LiteralValue::Bool(true),
            raw: "TRUE".to_string(),
            position: 0,
            quoted: false,
        });
        let false_node = BoolExpr::Literal(Literal {
            value: LiteralValue::Bool(false),
            raw: "FALSE".to_string(),
            position: 0,
            quoted: false,
        });
        let both = |a: &BoolExpr, b: &BoolExpr| {
            evaluate(
                &BoolExpr::Binary(Binary {
                    operator: "AND".to_string(),
                    left: Box::new(a.clone()),
                    right: Box::new(b.clone()),
                }),
                &context,
            )
        };
        assert_eq!(both(&false_node, &null_node), Some(false));
        assert_eq!(both(&null_node, &false_node), Some(false));
        assert_eq!(both(&null_node, &true_node), None);
        assert_eq!(both(&true_node, &null_node), None);
        let either = |a: &BoolExpr, b: &BoolExpr| {
            evaluate(
                &BoolExpr::Binary(Binary {
                    operator: "OR".to_string(),
                    left: Box::new(a.clone()),
                    right: Box::new(b.clone()),
                }),
                &context,
            )
        };
        assert_eq!(either(&true_node, &null_node), Some(true));
        assert_eq!(either(&null_node, &true_node), Some(true));
        assert_eq!(either(&null_node, &false_node), None);
    }
}
