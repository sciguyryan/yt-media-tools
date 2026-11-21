//! Date and datetime literal parsing for the shared query language.
//!
//! Port of `dates.py`: the date context, TODAY()/NOW() relative expressions,
//! ISO/local/named/relative date forms, ISO datetime parsing and epoch
//! normalisation. English month names are fixed (Python's C-locale calendar).

use crate::units::load_default_unit_registry;
use crate::value::{TemporalKind, Value, epoch_to_datetime};
use chrono::{
    DateTime, Datelike, FixedOffset, NaiveDate, NaiveDateTime, NaiveTime, TimeZone, Timelike, Utc,
};

pub const DMY: &str = "dmy";
pub const MDY: &str = "mdy";
pub const YMD: &str = "ymd";

const MONTH_NAMES: [&str; 13] = [
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
];

const MONTH_ABBRS: [&str; 13] = [
    "", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

fn month_number(name: &str) -> Option<u32> {
    let lowered = name.to_lowercase();
    MONTH_NAMES
        .iter()
        .position(|month| !month.is_empty() && month.to_lowercase() == lowered)
        .or_else(|| {
            MONTH_ABBRS
                .iter()
                .position(|month| !month.is_empty() && month.to_lowercase() == lowered)
        })
        .map(|index| index as u32)
}

/// Settings used when resolving human-readable date literals.
#[derive(Debug, Clone)]
pub struct DateContext {
    pub date_order: String,
    pub now: DateTime<FixedOffset>,
}

impl DateContext {
    pub fn new(date_order: &str, now: DateTime<FixedOffset>) -> Self {
        let date_order = date_order.to_string();
        Self { date_order, now }
    }

    /// The context's fixed instant when no clock setting is declared.
    pub fn default_now() -> DateTime<FixedOffset> {
        Utc.from_utc_datetime(&NaiveDateTime::new(
            NaiveDate::from_ymd_opt(2026, 9, 1).unwrap(),
            NaiveTime::from_hms_opt(0, 0, 0).unwrap(),
        ))
        .fixed_offset()
    }

    pub fn local_now(&self) -> DateTime<FixedOffset> {
        self.now
    }

    pub fn today(&self) -> NaiveDate {
        self.now.date_naive()
    }
}

fn normalise_spaces(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn days_in_month(year: i32, month: u32) -> u32 {
    match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 => {
            if year % 4 == 0 && (year % 100 != 0 || year % 400 == 0) {
                29
            } else {
                28
            }
        }
        _ => 0,
    }
}

/// Shift a date by calendar months/years, clamping the day when needed.
/// `months` is subtracted (Python's `_calendar_shift_day` takes positive
/// months/years to subtract).
fn calendar_shift_day(value: NaiveDate, months: i64, years: i64) -> NaiveDate {
    let total = value.year() as i64 * 12 + (value.month() as i64 - 1) - months - years * 12;
    let year = total.div_euclid(12);
    let month_index = total.rem_euclid(12);
    let month = month_index + 1;
    let day = value.day().min(days_in_month(year as i32, month as u32));
    NaiveDate::from_ymd_opt(year as i32, month as u32, day)
        .expect("clamped calendar shift is valid")
}

fn calendar_shift_datetime(
    value: DateTime<FixedOffset>,
    months: i64,
    years: i64,
) -> DateTime<FixedOffset> {
    let shifted = calendar_shift_day(value.date_naive(), months, years);
    let (hour, minute, second) = (value.hour(), value.minute(), value.second());
    let time = NaiveTime::from_hms_micro_opt(hour, minute, second, value.nanosecond() / 1000)
        .expect("preserved time-of-day is valid");
    NaiveDateTime::new(shifted, time)
        .and_local_timezone(*value.offset())
        .single()
        .expect("calendar shift keeps the offset unambiguous")
}

fn make_date(raw: &str, year: i32, month: u32, day: u32) -> Result<NaiveDate, String> {
    if !(1..=12).contains(&month) {
        return Err(format!(
            "Invalid date '{raw}': month must be in 1..12, not {month}."
        ));
    }
    let last = days_in_month(year, month);
    if day < 1 || day > last {
        return Err(format!(
            "Invalid date '{raw}': day {day} must be in range 1..{last} for month {month} in year {year}."
        ));
    }
    Ok(NaiveDate::from_ymd_opt(year, month, day).expect("validated date"))
}

/// Typed positive or negative infinity used only for temporal comparisons.
pub fn parse_temporal_infinity(text: &str) -> Option<Value> {
    let compact = normalise_spaces(text).to_uppercase();
    if compact == "INFINITY()" {
        return Some(Value::Infinity {
            sign: 1,
            kind: TemporalKind::Date,
        });
    }
    if compact == "-INFINITY()" {
        return Some(Value::Infinity {
            sign: -1,
            kind: TemporalKind::Date,
        });
    }
    None
}

/// Parse a date literal under the context's date order.
pub fn parse_date_literal(text: &str, context: &DateContext) -> Result<NaiveDate, String> {
    let raw = normalise_spaces(text);
    let lowered = raw.to_lowercase();

    if let Some(expression) = temporal_expression(&raw) {
        return match parse_temporal_expression(&raw, context, "date", expression) {
            Ok(value) => match value {
                Value::Date(date) => Ok(date),
                _ => unreachable!("date context yields a date"),
            },
            Err(message) => Err(message),
        };
    }
    if lowered == "today" {
        return Ok(context.today());
    }
    if lowered == "yesterday" {
        return Ok(context.today() - chrono::Duration::days(1));
    }
    if lowered == "tomorrow" {
        return Ok(context.today() + chrono::Duration::days(1));
    }

    // Relative: "<count> <unit> ago".
    if let Some((count_text, unit_text)) = relative_date_form(&lowered) {
        let count: i64 = count_text
            .parse()
            .map_err(|_| format!("Unknown relative-date unit {unit_text:?}."))?;
        let unit = load_default_unit_registry()
            .resolve(&unit_text)
            .map_err(|_| format!("Unknown relative-date unit {unit_text:?}."))?;
        if unit.kind == crate::units::CALENDAR {
            let months_float = unit.amount * count as f64;
            if (months_float - months_float.round()).abs() > f64::EPSILON {
                return Err(format!(
                    "Calendar unit {unit_text:?} requires a whole number of months."
                ));
            }
            return Ok(calendar_shift_day(
                context.today(),
                months_float.round() as i64,
                0,
            ));
        }
        let days = unit.amount * count as f64 / 86400.0;
        if !is_integer(days) {
            return Err(format!(
                "Relative date unit {unit_text:?} must resolve to a whole number of days."
            ));
        }
        return Ok(context.today() - chrono::Duration::days(days as i64));
    }

    let segments: Vec<&str> = raw.split(['-', '/', '.']).collect();
    if segments.len() == 3 {
        let parts: Option<Vec<i64>> = segments
            .iter()
            .map(|part| part.parse::<i64>().ok())
            .collect();
        if let Some(parts) = parts {
            // Year-first and local numeric forms share the three-segment shape;
            // distinguish by segment width rather than the separator.
            let widths: Vec<usize> = segments
                .iter()
                .map(|segment| segment.chars().count())
                .collect();
            if widths == vec![4, 2, 2]
                || widths == vec![4, 1, 1]
                || widths == vec![4, 2, 1]
                || widths == vec![4, 1, 2]
            {
                return make_date(&raw, parts[0] as i32, parts[1] as u32, parts[2] as u32);
            }
            if widths == vec![1, 1, 4]
                || widths == vec![1, 2, 4]
                || widths == vec![2, 1, 4]
                || widths == vec![2, 2, 4]
            {
                let (first, second, year) = (parts[0], parts[1], parts[2]);
                return match context.date_order.as_str() {
                    DMY => make_date(&raw, year as i32, second as u32, first as u32),
                    MDY => make_date(&raw, year as i32, first as u32, second as u32),
                    _ => Err(format!(
                        "Date {raw:?} is not year-first. Use YYYY-MM-DD or choose --date-format dmy/mdy."
                    )),
                };
            }
        }
    }

    // Compact YYYYMMDD.
    if raw.len() == 8 && raw.chars().all(|character| character.is_ascii_digit()) {
        let year: i32 = raw[0..4].parse().unwrap();
        let month: u32 = raw[4..6].parse().unwrap();
        let day: u32 = raw[6..8].parse().unwrap();
        return make_date(&raw, year, month, day);
    }

    // Named month: "11 July 2026" / "3rd of June 2024" style ordinal is not
    // supported here; the Python form is day month year with an optional ordinal.
    if let Some(date) = named_month_form(&raw) {
        return date;
    }
    if let Some(date) = named_month_us_form(&raw) {
        return date;
    }

    Err(
        "Could not understand the date. Use ISO YYYY-MM-DD, YYYYMMDD, a configured local numeric date, a named date such as '1 January 2024', or a relative date such as '6 months ago'.".to_string(),
    )
}

fn is_integer(value: f64) -> bool {
    (value - value.round()).abs() < f64::EPSILON && value.abs() < 9.0e15
}

fn strip_ordinal(text: &str) -> &str {
    for suffix in ["st", "nd", "rd", "th"] {
        if let Some(stripped) = text.strip_suffix(suffix) {
            return stripped;
        }
    }
    text
}

fn named_month_form(raw: &str) -> Option<Result<NaiveDate, String>> {
    // "<day><ordinal?> <month> <year>"
    let tokens: Vec<&str> = raw.split_whitespace().collect();
    if tokens.len() != 3 {
        return None;
    }
    let day: i64 = strip_ordinal(tokens[0]).parse().ok()?;
    let month = month_number(tokens[1])?;
    let year: i64 = tokens[2].parse().ok()?;
    Some(make_date(raw, year as i32, month, day as u32))
}

fn named_month_us_form(raw: &str) -> Option<Result<NaiveDate, String>> {
    // "<month> <day><ordinal?><,> <year>"
    let without_comma = raw.trim_end_matches(',');
    let tokens: Vec<&str> = without_comma.split_whitespace().collect();
    if tokens.len() != 3 {
        return None;
    }
    let month = month_number(tokens[0])?;
    let day: i64 = strip_ordinal(tokens[1]).parse().ok()?;
    let year: i64 = tokens[2].parse().ok()?;
    Some(make_date(raw, year as i32, month, day as u32))
}

/// Split "<count> <unit> ago" when the lowered text matches the relative form.
fn relative_date_form(lowered: &str) -> Option<(String, String)> {
    let rest = lowered.strip_suffix(" ago")?;
    let (count, unit) = rest.split_once(' ')?;
    if count.is_empty()
        || unit.is_empty()
        || !count.chars().all(|character| character.is_ascii_digit())
    {
        return None;
    }
    if !unit
        .chars()
        .next()
        .map(|character| !character.is_ascii_digit() && character != '_')
        .unwrap_or(false)
    {
        return None;
    }
    Some((count.to_string(), unit.to_string()))
}

/// One recognised TODAY()/NOW() relative expression.
#[derive(Debug, Clone, Copy)]
pub struct TemporalExpression {
    pub base_is_today: bool,
    pub operator: Option<char>,
    pub count: f64,
    pub unit: &'static str,
}

/// Recognise TODAY()/NOW() with optional relative arithmetic.
fn temporal_expression(raw: &str) -> Option<TemporalExpression> {
    let (base, rest) = if let Some(rest) = raw.strip_prefix("TODAY()") {
        (true, rest.trim())
    } else {
        let rest = raw.strip_prefix("NOW()")?;
        (false, rest.trim())
    };
    if rest.is_empty() {
        return Some(TemporalExpression {
            base_is_today: base,
            operator: None,
            count: 0.0,
            unit: "",
        });
    }
    let operator = rest.chars().next().unwrap();
    if operator != '+' && operator != '-' {
        return None;
    }
    let rest = rest[1..].trim_start();
    let digit_end = rest
        .find(|character: char| !character.is_ascii_digit() && character != '.')
        .unwrap_or(rest.len());
    let count_text = &rest[..digit_end];
    if count_text.is_empty() || count_text.chars().filter(|c| *c == '.').count() > 1 {
        return None;
    }
    let count: f64 = count_text.parse().ok()?;
    let unit = rest[digit_end..].trim();
    if unit.is_empty()
        || !unit.chars().all(|character: char| {
            (!character.is_ascii_digit() && character != '_') || character == '-'
        })
    {
        return None;
    }
    // Units are sequences of letter code points and hyphens.
    if unit
        .chars()
        .any(|character| character.is_ascii_digit() || character == '_')
    {
        return None;
    }
    Some(TemporalExpression {
        base_is_today: base,
        operator: Some(operator),
        count,
        unit: "",
    })
}

/// Parse TODAY()/NOW() with optional relative arithmetic and strict result typing.
pub fn parse_temporal_expression(
    raw: &str,
    context: &DateContext,
    expected: &str,
    expression: TemporalExpression,
) -> Result<Value, String> {
    let base_is_today = expression.base_is_today;
    if expected == "date" && !base_is_today {
        return Err("NOW() produces a timestamp. Use TODAY() for date comparisons.".to_string());
    }
    if expected == "datetime" && base_is_today {
        return Err("TODAY() produces a date. Use NOW() for timestamp comparisons.".to_string());
    }

    let Some(operator) = expression.operator else {
        if base_is_today {
            return Ok(Value::Date(context.today()));
        }
        return Ok(Value::DateTime(context.local_now()));
    };

    // The unit text must be recovered from the raw expression.
    let unit_text = extract_unit_text(raw).ok_or_else(|| {
        format!(
            "Could not understand temporal expression {:?}.",
            normalise_spaces(raw)
        )
    })?;
    let unit = load_default_unit_registry()
        .resolve(&unit_text)
        .map_err(|_| format!("Unknown temporal unit {unit_text:?}."))?;
    let sign = if operator == '-' { -1i64 } else { 1 };

    if unit.kind == crate::units::CALENDAR {
        let months = unit.amount * expression.count;
        if !is_integer(months) {
            return Err(format!(
                "Calendar unit {unit_text:?} requires a whole number of months."
            ));
        }
        if expected == "date" {
            return Ok(Value::Date(calendar_shift_day(
                context.today(),
                -(months as i64) * sign,
                0,
            )));
        }
        return Ok(Value::DateTime(calendar_shift_datetime(
            context.local_now(),
            -(months as i64) * sign,
            0,
        )));
    }

    if expected == "date" {
        let days = unit.amount * expression.count / 86400.0;
        if !is_integer(days) {
            return Err(format!(
                "TODAY() date arithmetic does not support sub-day unit {unit_text:?}. Use a whole-day or calendar unit."
            ));
        }
        return Ok(Value::Date(
            context.today() + chrono::Duration::days(days as i64 * sign),
        ));
    }

    let seconds = unit.amount * expression.count * sign as f64;
    let shifted = context.local_now() + chrono::Duration::milliseconds((seconds * 1000.0) as i64);
    Ok(Value::DateTime(shifted))
}

fn extract_unit_text(raw: &str) -> Option<String> {
    // After "TODAY()/NOW()", the optional sign and the count, the unit is the
    // trailing letter run.
    let position = raw.find("()")? + 2;
    let rest = raw.get(position..)?.trim();
    let rest = rest.trim_start_matches(['+', '-']).trim_start();
    let digits_end = rest
        .find(|character: char| !character.is_ascii_digit() && character != '.')
        .unwrap_or(rest.len());
    let unit = rest[digits_end..].trim();
    if unit.is_empty() {
        None
    } else {
        Some(unit.to_string())
    }
}

/// Parse an execution-configuration clock setting: an offset-aware RFC 3339
/// timestamp. Naive timestamps are rejected.
pub fn parse_settings_clock(text: &str) -> Result<DateTime<FixedOffset>, String> {
    let (_body, offset_minutes) = split_iso_offset(text);
    offset_minutes
        .ok_or_else(|| "settings.clock must be an offset-aware RFC 3339 timestamp".to_string())
        .and_then(|_| {
            parse_datetime_literal(text, &DateContext::new("dmy", DateContext::default_now()))
        })
}

/// Parse an ISO datetime or a typed NOW() relative expression.
pub fn parse_datetime_literal(
    text: &str,
    context: &DateContext,
) -> Result<DateTime<FixedOffset>, String> {
    let raw = normalise_spaces(text);
    if let Some(expression) = temporal_expression(&raw) {
        return match parse_temporal_expression(&raw, context, "datetime", expression) {
            Ok(Value::DateTime(value)) => Ok(value),
            _ => unreachable!("datetime context yields a datetime"),
        };
    }

    let (body, offset_minutes) = split_iso_offset(&raw);
    let invalid = || {
        Err::<DateTime<FixedOffset>, String>(
            "Could not understand the timestamp. Use an ISO datetime such as 2024-01-01T18:30:00Z, or NOW() with optional relative arithmetic.".to_string(),
        )
    };
    let parts = body.split(['T', ' ']).collect::<Vec<_>>();
    if parts.len() != 2 {
        return invalid();
    }
    let date_segments: Vec<&str> = parts[0].split('-').collect();
    if date_segments.len() != 3 {
        return invalid();
    }
    let year: i32 = date_segments[0]
        .parse()
        .map_err(|_| invalid().unwrap_err())?;
    let month: u32 = date_segments[1]
        .parse()
        .map_err(|_| invalid().unwrap_err())?;
    let day: u32 = date_segments[2]
        .parse()
        .map_err(|_| invalid().unwrap_err())?;
    let date = make_date(&raw, year, month, day).map_err(|_| invalid().unwrap_err())?;

    let time_text = parts[1];
    let (clock, fraction) = match time_text.find('.') {
        Some(dot) => (&time_text[..dot], Some(&time_text[dot + 1..])),
        None => (time_text, None),
    };
    let clock_segments: Vec<&str> = clock.split(':').collect();
    if clock_segments.is_empty() || clock_segments.len() > 3 {
        return invalid();
    }
    let hour: u32 = clock_segments[0]
        .parse()
        .map_err(|_| invalid().unwrap_err())?;
    let minute: u32 = clock_segments[1]
        .parse()
        .map_err(|_| invalid().unwrap_err())?;
    let second: u32 = if clock_segments.len() > 2 {
        clock_segments[2]
            .parse()
            .map_err(|_| invalid().unwrap_err())?
    } else {
        0
    };
    if hour > 23 || minute > 59 || second > 59 {
        return invalid();
    }
    let micros = match fraction {
        Some(digits) => {
            if digits.is_empty() || !digits.chars().all(|character| character.is_ascii_digit()) {
                return invalid();
            }
            let mut micros = 0u32;
            for (index, character) in digits.chars().take(6).enumerate() {
                micros += (character as u32 - '0' as u32) * 10u32.pow(5 - index as u32);
            }
            micros
        }
        None => 0,
    };
    let time = NaiveTime::from_hms_micro_opt(hour, minute, second, micros)
        .ok_or_else(|| invalid().unwrap_err())?;
    let naive = NaiveDateTime::new(date, time);
    match offset_minutes {
        Some(minutes) => {
            let offset =
                FixedOffset::east_opt(minutes * 60).ok_or_else(|| invalid().unwrap_err())?;
            Ok(offset
                .from_local_datetime(&naive)
                .single()
                .ok_or_else(|| invalid().unwrap_err())?)
        }
        None => Ok(context
            .local_now()
            .offset()
            .from_local_datetime(&naive)
            .single()
            .ok_or_else(|| invalid().unwrap_err())?),
    }
}

fn split_iso_offset(raw: &str) -> (&str, Option<i32>) {
    if raw.ends_with('Z') || raw.ends_with('z') {
        return (&raw[..raw.len() - 1], Some(0));
    }
    // Look for a trailing +HH:MM / -HH:MM / +HHMM.
    if raw.len() > 6 {
        let candidate = &raw[raw.len() - 5..];
        let bytes = candidate.as_bytes();
        if (bytes[0] == b'+' || bytes[0] == b'-')
            && bytes[1].is_ascii_digit()
            && bytes[2].is_ascii_digit()
            && bytes[3].is_ascii_digit()
            && bytes[4].is_ascii_digit()
        {
            let hours = (bytes[1] - b'0') as i32 * 10 + (bytes[2] - b'0') as i32;
            let minutes = (bytes[3] - b'0') as i32 * 10 + (bytes[4] - b'0') as i32;
            if hours <= 23 && minutes <= 59 {
                let sign = if bytes[0] == b'+' { 1 } else { -1 };
                return (&raw[..raw.len() - 5], Some(sign * (hours * 60 + minutes)));
            }
        }
    }
    if raw.len() > 6 {
        let candidate = &raw[raw.len() - 6..];
        let bytes = candidate.as_bytes();
        if (bytes[0] == b'+' || bytes[0] == b'-')
            && bytes[1].is_ascii_digit()
            && bytes[2].is_ascii_digit()
            && bytes[3] == b':'
            && bytes[4].is_ascii_digit()
            && bytes[5].is_ascii_digit()
        {
            let hours = (bytes[1] - b'0') as i32 * 10 + (bytes[2] - b'0') as i32;
            let minutes = (bytes[4] - b'0') as i32 * 10 + (bytes[5] - b'0') as i32;
            if hours <= 23 && minutes <= 59 {
                let sign = if bytes[0] == b'+' { 1 } else { -1 };
                return (&raw[..raw.len() - 6], Some(sign * (hours * 60 + minutes)));
            }
        }
    }
    (raw, None)
}

/// Normalise numeric epoch timestamps to UTC datetimes when possible.
pub fn timestamp_to_datetime(value: &Value) -> Value {
    match value {
        Value::Bool(_) => value.clone(),
        Value::Int(seconds) => match epoch_to_datetime(*seconds) {
            Some(datetime) => Value::DateTime(datetime),
            None => value.clone(),
        },
        Value::Text(text) => match text.parse::<f64>() {
            Ok(number) => {
                if number.is_finite() {
                    match epoch_to_datetime(number as i64) {
                        Some(datetime) => Value::DateTime(datetime),
                        None => value.clone(),
                    }
                } else {
                    value.clone()
                }
            }
            Err(_) => value.clone(),
        },
        _ => value.clone(),
    }
}
