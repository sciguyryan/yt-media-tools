//! Runtime scalar values for yt-sql evaluation.
//!
//! The value domain mirrors the Python reference implementation: NULL, booleans,
//! integers, binary floats, exact text, civil dates, offset-aware timestamps,
//! exact rationals (AVG), ordered arrays and insertion-ordered records. Ordering,
//! equality and arithmetic follow the Python observable contract, including
//! three-valued NULL propagation and cross-family behaviour.

use chrono::{DateTime, Datelike, FixedOffset, NaiveDate, NaiveDateTime, TimeZone, Timelike};
use serde_json::{Map, Value as Json};
use std::cmp::Ordering;

/// One exact rational used by the AVG precision contract.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Fraction {
    numerator: i128,
    denominator: i128,
}

fn gcd(mut a: i128, mut b: i128) -> i128 {
    a = a.abs();
    b = b.abs();
    while b != 0 {
        (a, b) = (b, a % b);
    }
    a
}

impl Fraction {
    pub fn new(numerator: i128, denominator: i128) -> Self {
        assert!(denominator != 0, "fraction denominator must be non-zero");
        let sign = if denominator < 0 { -1 } else { 1 };
        let (numerator, denominator) = (sign * numerator, sign * denominator);
        let divisor = gcd(numerator, denominator).max(1);
        Self {
            numerator: numerator / divisor,
            denominator: denominator / divisor,
        }
    }

    pub fn from_int(value: i128) -> Self {
        Self::new(value, 1)
    }

    pub fn divide(numerator: i128, denominator: i128) -> Self {
        Self::new(numerator, denominator)
    }

    pub fn is_negative(&self) -> bool {
        self.numerator < 0
    }

    /// Divide by a positive count, as AVG does over an integer total.
    pub fn over_count(total: i128, count: usize) -> Self {
        Self::new(total, count as i128)
    }

    /// Round to `places` fractional digits, half to even.
    pub fn round_half_even(&self, places: u32) -> Self {
        let scale = 10i128.pow(places);
        let scaled = self.numerator * scale;
        let (quotient, remainder) = div_rem(scaled, self.denominator);
        let double = remainder * 2;
        let rounded = match double.cmp(&self.denominator) {
            Ordering::Greater => quotient + 1,
            Ordering::Less => quotient,
            Ordering::Equal => {
                if quotient % 2 == 0 {
                    quotient
                } else {
                    quotient + 1
                }
            }
        };
        Self::new(rounded, scale)
    }

    /// Exact finite decimal text for this fraction; the caller must ensure the
    /// fraction terminates in decimal (or has been rounded already).
    pub fn decimal_string(&self) -> String {
        let sign = if self.numerator < 0 { "-" } else { "" };
        let (quotient, mut remainder) = div_rem(self.numerator.abs(), self.denominator);
        let mut digits = String::new();
        while remainder != 0 {
            remainder *= 10;
            let (digit, rest) = div_rem(remainder, self.denominator);
            digits.push(char::from(b'0' + digit as u8));
            remainder = rest;
        }
        if digits.is_empty() {
            format!("{sign}{quotient}")
        } else {
            format!("{sign}{quotient}.{digits}")
        }
    }
}

fn div_rem(a: i128, b: i128) -> (i128, i128) {
    (a / b, a % b)
}

/// Which temporal family an infinity sentinel belongs to.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TemporalKind {
    Date,
    DateTime,
}

/// One runtime value.
#[derive(Debug, Clone)]
pub enum Value {
    Null,
    Bool(bool),
    Int(i64),
    Float(f64),
    Text(String),
    Date(NaiveDate),
    DateTime(DateTime<FixedOffset>),
    Decimal(Fraction),
    Array(Vec<Value>),
    /// Insertion-ordered structured record (provider metadata).
    Record(Vec<(String, Value)>),
    /// Typed positive or negative temporal infinity sentinel.
    Infinity {
        sign: i32,
        kind: TemporalKind,
    },
}

/// A record value lookup that preserves the "missing means NULL" contract.
pub fn record_get<'a>(record: &'a [(String, Value)], key: &str) -> Option<&'a Value> {
    record
        .iter()
        .find(|(name, _)| name == key)
        .map(|(_, value)| value)
}

impl Value {
    pub fn is_null(&self) -> bool {
        matches!(self, Value::Null)
    }

    /// Numeric view used by comparisons, treating booleans as integers.
    fn numeric(&self) -> Option<f64> {
        match self {
            Value::Bool(value) => Some(if *value { 1.0 } else { 0.0 }),
            Value::Int(value) => Some(*value as f64),
            Value::Float(value) => Some(*value),
            _ => None,
        }
    }

    fn numeric_exact(&self) -> Option<(i64, Option<f64>)> {
        match self {
            Value::Bool(value) => Some((if *value { 1 } else { 0 }, None)),
            Value::Int(value) => Some((*value, None)),
            Value::Float(value) => Some((0, Some(*value))),
            _ => None,
        }
    }

    /// Python-style equality: numeric families compare across representations,
    /// other families only compare within their own kind, and everything else
    /// is simply unequal rather than an error.
    pub fn equals(&self, other: &Value) -> bool {
        match (self, other) {
            (Value::Null, _) | (_, Value::Null) => false,
            (Value::Bool(a), Value::Bool(b)) => a == b,
            _ if self.numeric_exact().is_some() && other.numeric_exact().is_some() => {
                match (self.numeric_exact(), other.numeric_exact()) {
                    (Some((a, None)), Some((b, None))) => a == b,
                    (Some((a, None)), Some((_, Some(b)))) => (a as f64) == b,
                    (Some((_, Some(a))), Some((b, None))) => a == (b as f64),
                    (Some((_, Some(a))), Some((_, Some(b)))) => a == b,
                    _ => false,
                }
            }
            (Value::Text(a), Value::Text(b)) => a == b,
            (Value::Date(a), Value::Date(b)) => a == b,
            (Value::DateTime(a), Value::DateTime(b)) => a == b,
            (Value::Decimal(_), _) | (_, Value::Decimal(_)) => {
                // Exact rationals compare against the numeric family.
                match (self.as_fraction(), other.as_fraction()) {
                    (Some(a), Some(b)) => a == b,
                    _ => false,
                }
            }
            (Value::Array(a), Value::Array(b)) => {
                a.len() == b.len() && a.iter().zip(b.iter()).all(|(x, y)| x.equals(y))
            }
            (Value::Record(a), Value::Record(b)) => {
                a.len() == b.len()
                    && a.iter()
                        .zip(b.iter())
                        .all(|((an, av), (bn, bv))| an == bn && av.equals(bv))
            }
            (Value::Infinity { sign: a, kind: ak }, Value::Infinity { sign: b, kind: bk }) => {
                a == b && ak == bk
            }
            _ => false,
        }
    }

    fn as_fraction(&self) -> Option<Fraction> {
        match self {
            Value::Decimal(value) => Some(value.clone()),
            Value::Int(value) => Some(Fraction::from_int(*value as i128)),
            Value::Bool(value) => Some(Fraction::from_int(if *value { 1 } else { 0 })),
            _ => None,
        }
    }

    /// Python-style ordering: `None` marks incomparable values (a `TypeError`).
    /// Numeric families intercompare; other families only order within their
    /// own kind.
    pub fn compare(&self, other: &Value) -> Option<Ordering> {
        match (self, other) {
            _ if self.numeric().is_some() && other.numeric().is_some() => {
                self.numeric().partial_cmp(&other.numeric())
            }
            (Value::Text(a), Value::Text(b)) => Some(a.cmp(b)),
            (Value::Date(a), Value::Date(b)) => Some(a.cmp(b)),
            (Value::DateTime(a), Value::DateTime(b)) => Some(a.cmp(b)),
            (Value::Date(_), Value::DateTime(_)) | (Value::DateTime(_), Value::Date(_)) => None,
            (Value::Decimal(_), _) | (_, Value::Decimal(_)) => {
                match (self.as_fraction(), other.as_fraction()) {
                    (Some(a), Some(b)) => {
                        // Compare a/b and c/d via cross multiplication.
                        Some((a.numerator * b.denominator).cmp(&(b.numerator * a.denominator)))
                    }
                    _ => None,
                }
            }
            (Value::Infinity { sign: a, kind: ak }, Value::Infinity { sign: b, kind: bk }) => {
                if ak == bk { Some(a.cmp(b)) } else { None }
            }
            (Value::Infinity { sign, kind }, Value::DateTime(_) | Value::Date(_)) => {
                if *kind == TemporalKind::DateTime && matches!(other, Value::DateTime(_))
                    || *kind == TemporalKind::Date && matches!(other, Value::Date(_))
                {
                    Some(if *sign < 0 {
                        Ordering::Less
                    } else {
                        Ordering::Greater
                    })
                } else {
                    None
                }
            }
            (Value::DateTime(_) | Value::Date(_), Value::Infinity { sign, kind }) => {
                if *kind == TemporalKind::DateTime && matches!(self, Value::DateTime(_))
                    || *kind == TemporalKind::Date && matches!(self, Value::Date(_))
                {
                    Some(if *sign < 0 {
                        Ordering::Greater
                    } else {
                        Ordering::Less
                    })
                } else {
                    None
                }
            }
            (Value::Array(a), Value::Array(b)) => {
                // Element-wise Python list comparison semantics.
                for (x, y) in a.iter().zip(b.iter()) {
                    match x.compare(y)? {
                        Ordering::Equal => continue,
                        unequal => return Some(unequal),
                    }
                }
                Some(a.len().cmp(&b.len()))
            }
            _ => None,
        }
    }

    /// Ordering key for ORDER BY over one homogeneous term.
    pub fn sort_cmp(&self, other: &Value) -> Option<Ordering> {
        self.compare(other)
    }
}

/// Python's `round` on a float value: half to even.
pub fn python_round(value: f64) -> i64 {
    let rounded = value.round();
    // Rust's f64::round is half-away-from-zero; adjust exact halves.
    let floor = value.floor();
    let ceil = value.ceil();

    if (value - floor).abs() == 0.5 {
        let f = floor as i64;
        let c = ceil as i64;
        if f % 2 == 0 { f } else { c }
    } else {
        rounded as i64
    }
}

/// Exact decimal text for a binary float, matching `Decimal.from_float`.
pub fn float_to_exact_decimal(value: f64) -> String {
    assert!(value.is_finite(), "non-finite float result");
    let bits = value.to_bits();
    let sign = if bits >> 63 == 1 { "-" } else { "" };
    let exponent_bits = ((bits >> 52) & 0x7ff) as i64;
    let mantissa_bits = bits & ((1u64 << 52) - 1);
    let (mantissa, exponent) = if exponent_bits == 0 {
        (mantissa_bits, -1074i64)
    } else {
        (mantissa_bits | (1u64 << 52), exponent_bits - 1075)
    };
    // value = sign * mantissa * 2^exponent
    let mut digits = mantissa.to_string();
    let mut decimal_exponent = exponent;
    if exponent < 0 {
        // Multiply the digit string by 5^(-exponent) to keep an integer value,
        // then place the decimal point at -exponent digits from the right.
        let fives = (-exponent) as u32;
        for _ in 0..fives {
            digits = multiply_small(&digits, 5);
        }
        // Decimal.from_float renders the shortest exact decimal: strip the
        // trailing zeros the ×5ᵏ multiplication introduced, keeping the
        // implied decimal point aligned with the remaining digit count.
        while decimal_exponent < 0 && digits.ends_with('0') {
            digits.pop();
            decimal_exponent += 1;
        }
        digits = trim_leading_zeros(&digits);
        let point = digits.len() as i64 + decimal_exponent;
        return place_decimal(sign, &digits, point);
    }
    while decimal_exponent > 0 {
        digits = multiply_small(&digits, 2);
        decimal_exponent -= 1;
    }
    let digits = trim_leading_zeros(&digits);
    place_decimal(sign, &digits, digits.len() as i64)
}

fn trim_leading_zeros(digits: &str) -> String {
    let trimmed = digits.trim_start_matches('0');
    if trimmed.is_empty() {
        "0".to_string()
    } else {
        trimmed.to_string()
    }
}

fn multiply_small(digits: &str, factor: u32) -> String {
    let mut carry = 0u64;
    let mut out = String::new();
    for character in digits.chars().rev() {
        let digit = character as u64 - '0' as u64;
        let product = digit * factor as u64 + carry;
        out.push(char::from(b'0' + (product % 10) as u8));
        carry = product / 10;
    }
    while carry > 0 {
        out.push(char::from(b'0' + (carry % 10) as u8));
        carry /= 10;
    }
    out.chars().rev().collect()
}

fn place_decimal(sign: &str, digits: &str, point: i64) -> String {
    let len = digits.len() as i64;
    if point >= len {
        let zeros = "0".repeat((point - len) as usize);
        format!("{sign}{digits}{zeros}")
    } else if point <= 0 {
        let zeros = "0".repeat((-point) as usize);
        format!("{sign}0.{zeros}{digits}")
    } else {
        let split = point as usize;
        format!("{sign}{}.{}", &digits[..split], &digits[split..])
    }
}

/// Python `datetime.isoformat()` for an offset-aware UTC timestamp.
pub fn datetime_isoformat(value: &DateTime<FixedOffset>) -> String {
    let base = format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}",
        value.year(),
        value.month(),
        value.day(),
        value.hour(),
        value.minute(),
        value.second()
    );
    let micros = value.nanosecond() / 1000;
    let suffix = if micros == 0 {
        "+00:00".to_string()
    } else {
        format!(".{micros:06}+00:00")
    };
    format!("{base}{suffix}")
}

/// Convert an epoch-seconds value to a UTC timestamp, as `timestamp_to_datetime`.
pub fn epoch_to_datetime(seconds: i64) -> Option<DateTime<FixedOffset>> {
    use chrono::Offset as _;
    let utc = chrono::Utc.fix().timestamp_opt(seconds, 0).single()?;
    Some(utc)
}

/// Build a UTC timestamp from naive fields (all offsets collapse to UTC here).
pub fn utc_datetime(
    date: NaiveDate,
    hour: u32,
    minute: u32,
    second: u32,
    micros: u32,
) -> Option<DateTime<FixedOffset>> {
    NaiveDateTime::new(
        date,
        chrono::NaiveTime::from_hms_micro_opt(hour, minute, second, micros)?,
    )
    .and_local_timezone(FixedOffset::east_opt(0).unwrap())
    .single()
}

/// Serialise one value into the portable typed-value JSON shape.
pub fn to_typed_json(value: &Value) -> Result<Json, String> {
    let object = |kind: &str, raw: Json| -> Json {
        let mut map = Map::new();
        map.insert("type".to_string(), Json::String(kind.to_string()));
        map.insert("value".to_string(), raw);
        Json::Object(map)
    };
    match value {
        Value::Null => Ok(Json::Null),
        Value::Bool(inner) => Ok(Json::Bool(*inner)),
        Value::Text(inner) => Ok(Json::String(inner.clone())),
        Value::Int(inner) => Ok(object("integer", Json::String(inner.to_string()))),
        Value::Float(inner) => {
            if !inner.is_finite() {
                return Err("non-finite floating-point result".to_string());
            }
            Ok(object(
                "decimal",
                Json::String(float_to_exact_decimal(*inner)),
            ))
        }
        Value::Decimal(inner) => Ok(object("decimal", Json::String(inner.decimal_string()))),
        Value::DateTime(inner) => Ok(object("timestamp", Json::String(datetime_isoformat(inner)))),
        Value::Array(items) => {
            let converted: Result<Vec<Json>, String> = items.iter().map(to_typed_json).collect();
            Ok(object("array", Json::Array(converted?)))
        }
        Value::Date(_) | Value::Record(_) | Value::Infinity { .. } => {
            Err("unsupported result value type".to_string())
        }
    }
}
