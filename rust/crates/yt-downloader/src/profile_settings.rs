//! Validation of effective Downloader profile settings.

use std::collections::BTreeMap;

use serde_json::{Map, Value};

use crate::profile_file::ResolvedProfile;

/// A setting that cannot be accepted without changing the Python Downloader's semantics.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SettingError {
    /// The setting is not recognised by the Downloader.
    UnknownSetting(String),
    /// The setting is recognised, but its validation has not yet been ported.
    UnsupportedSetting(String),
    /// The setting has an incorrect JSON type or an invalid value.
    InvalidValue(String),
    /// Two individually valid settings cannot be used together.
    ConflictingSettings(String),
}

/// Validated settings for one profile, with JSON types retained for downstream planning.
#[derive(Debug, Clone, PartialEq)]
pub struct ValidatedProfile {
    /// Effective settings after validation and normalisation.
    pub settings: Map<String, Value>,
    /// The immediate parent, when this profile inherits another profile.
    pub parent: Option<String>,
    /// Ancestors ordered from the oldest to the immediate parent.
    pub ancestry: Vec<String>,
    /// The profile or defaults block that supplied each effective setting.
    pub setting_sources: BTreeMap<String, String>,
}

const BOOLEAN_SETTINGS: &[&str] = &[
    "no-cookies",
    "reverse-playlist",
    "playlist",
    "write-subs",
    "write-auto-subs",
    "embed-subs",
    "write-thumbnail",
    "embed-thumbnail",
    "write-info-json",
    "embed-metadata",
    "embed-chapters",
    "sponsorblock",
    "audio-only",
    "audio-source-fallback",
    "live",
    "live-from-start",
    "write-live-chat",
];

const NONEMPTY_STRING_SETTINGS: &[&str] = &[
    "path",
    "output",
    "format",
    "cookies",
    "archive",
    "temp-path",
    "user-agent",
    "impersonate",
    "referer",
    "proxy",
    "source-address",
    "sub-langs",
    "sub-format",
];

const POSITIVE_INTEGER_SETTINGS: &[&str] = &[
    "min-fps",
    "max-fps",
    "preferred-fps",
    "preferred-audio-channels",
    "concurrent-fragments",
];

// Recognised settings still awaiting their Python-compatible validation rules.
const OTHER_RECOGNISED_SETTINGS: &[&str] = &[
    "cookies-from-browser",
    "playlist-items",
    "wait-for-video",
    "chapter-sections",
    "time-ranges",
    "sponsorblock-mark",
    "sponsorblock-remove",
];

/// Validate a vertical resolution, preserving the original profile representation.
///
/// The Python profile validator checks this syntax without replacing the supplied
/// string. Hard bounds, in contrast, are converted to JSON integers.
fn validate_resolution(value: &Value, bound: bool) -> Option<Value> {
    let text = if let Some(text) = value.as_str() {
        text.trim().to_ascii_lowercase()
    } else if bound {
        value.as_u64()?.to_string()
    } else {
        return None;
    };

    if !bound && text == "best" {
        return Some(value.clone());
    }

    let digits = text.strip_suffix('p').unwrap_or(&text);
    if digits.is_empty() || !digits.bytes().all(|byte| byte.is_ascii_digit()) {
        return None;
    }

    let number = digits.parse::<u64>().ok().filter(|number| *number > 0)?;
    if bound {
        Some(Value::from(number))
    } else {
        Some(value.clone())
    }
}

/// Accept a known format or container token, normalising its case as Python does.
fn validate_choice(value: &Value, choices: &[&str]) -> Option<Value> {
    let text = value.as_str()?.to_ascii_lowercase();
    choices
        .contains(&text.as_str())
        .then_some(Value::String(text))
}

/// Validate yt-dlp's numeric VBR levels and explicit bitrate notation.
fn validate_audio_quality(value: &Value) -> Option<Value> {
    if let Some(number) = value.as_u64() {
        return (number <= 10).then(|| Value::String(number.to_string()));
    }

    let text = value.as_str()?.trim();
    if text == "10" || (text.len() == 1 && text.bytes().all(|byte| byte.is_ascii_digit())) {
        return Some(Value::String(text.to_owned()));
    }

    if !text.is_ascii() {
        return None;
    }

    let (number, unit) = text.split_at(text.len().checked_sub(1)?);
    if !matches!(unit, "k" | "K" | "m" | "M") {
        return None;
    }

    let (whole, fraction) = number.split_once('.').unwrap_or((number, ""));
    if whole.is_empty()
        || whole.starts_with('0')
        || !whole.bytes().all(|byte| byte.is_ascii_digit())
        || (!fraction.is_empty() && !fraction.bytes().all(|byte| byte.is_ascii_digit()))
        || (number.contains('.') && fraction.is_empty())
    {
        return None;
    }

    Some(Value::String(text.to_ascii_uppercase()))
}

/// Validate a byte rate using the same optional unit suffixes as Python.
fn validate_rate(value: &Value) -> Option<Value> {
    let text = value.as_str()?.trim();
    let digits = text.trim_end_matches(|ch: char| {
        matches!(
            ch,
            'K' | 'M' | 'G' | 'T' | 'P' | 'k' | 'm' | 'g' | 't' | 'p'
        )
    });

    if text.len() - digits.len() > 1 {
        return None;
    }

    let (whole, fraction) = digits.split_once('.').unwrap_or((digits, ""));
    if whole.is_empty()
        || !whole.bytes().all(|byte| byte.is_ascii_digit())
        || (digits.contains('.') && fraction.is_empty())
        || !fraction.bytes().all(|byte| byte.is_ascii_digit())
    {
        return None;
    }

    Some(Value::String(text.to_owned()))
}

/// Normalise retry counts to strings, including the special infinite value.
fn validate_retry(value: &Value) -> Option<Value> {
    if let Some(number) = value.as_u64() {
        return Some(Value::String(number.to_string()));
    }

    let text = value.as_str()?.trim().to_ascii_lowercase();
    if text == "infinite" || (!text.is_empty() && text.bytes().all(|byte| byte.is_ascii_digit())) {
        Some(Value::String(text))
    } else {
        None
    }
}

/// Trim a non-empty list of strings without changing its ordering.
fn validate_string_list(value: &Value) -> Option<Value> {
    let items = value.as_array()?;
    if items.is_empty() {
        return None;
    }

    let mut result = Vec::with_capacity(items.len());
    for item in items {
        let text = item.as_str()?.trim();
        if text.is_empty() {
            return None;
        }

        result.push(Value::String(text.to_owned()));
    }

    Some(Value::Array(result))
}

/// Accept a simple codec or container token, without format-expression syntax.
fn validate_codec(value: &Value) -> Option<Value> {
    let text = value.as_str()?.trim();
    let mut bytes = text.bytes();
    if !bytes.next()?.is_ascii_alphanumeric()
        || !bytes
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'+' | b'-'))
    {
        return None;
    }

    Some(Value::String(text.to_ascii_lowercase()))
}

/// Validate the currently supported subset of effective profile settings.
///
/// Options with more involved Python-specific validation are rejected until their
/// semantics have been ported. This avoids treating unvalidated settings as safe.
pub fn validate_settings(
    settings: &Map<String, Value>,
) -> Result<Map<String, Value>, SettingError> {
    let mut validated = Map::new();

    for (key, value) in settings {
        let normalised = if BOOLEAN_SETTINGS.contains(&key.as_str()) {
            if !value.is_boolean() {
                return Err(SettingError::InvalidValue(key.clone()));
            }

            value.clone()
        } else if NONEMPTY_STRING_SETTINGS.contains(&key.as_str()) {
            let Some(text) = value.as_str() else {
                return Err(SettingError::InvalidValue(key.clone()));
            };

            if text.trim().is_empty() {
                return Err(SettingError::InvalidValue(key.clone()));
            }

            Value::String(text.trim().to_owned())
        } else if POSITIVE_INTEGER_SETTINGS.contains(&key.as_str()) {
            if !value.as_u64().is_some_and(|number| number > 0) {
                return Err(SettingError::InvalidValue(key.clone()));
            }

            value.clone()
        } else if key == "resolution" {
            validate_resolution(value, false)
                .ok_or_else(|| SettingError::InvalidValue(key.clone()))?
        } else if matches!(key.as_str(), "min-resolution" | "max-resolution") {
            validate_resolution(value, true)
                .ok_or_else(|| SettingError::InvalidValue(key.clone()))?
        } else if key == "preferred-hdr" {
            validate_choice(value, &["sdr", "hdr", "dv"])
                .ok_or_else(|| SettingError::InvalidValue(key.clone()))?
        } else if key == "merge-container" {
            validate_choice(value, &["avi", "flv", "mkv", "mov", "mp4", "webm"])
                .ok_or_else(|| SettingError::InvalidValue(key.clone()))?
        } else if key == "audio-format" {
            validate_choice(
                value,
                &[
                    "best", "aac", "alac", "flac", "m4a", "mp3", "opus", "vorbis", "wav",
                ],
            )
            .ok_or_else(|| SettingError::InvalidValue(key.clone()))?
        } else if key == "audio-quality" {
            validate_audio_quality(value).ok_or_else(|| SettingError::InvalidValue(key.clone()))?
        } else if matches!(key.as_str(), "limit-rate" | "throttled-rate") {
            validate_rate(value).ok_or_else(|| SettingError::InvalidValue(key.clone()))?
        } else if matches!(
            key.as_str(),
            "retries" | "fragment-retries" | "file-access-retries" | "extractor-retries"
        ) {
            validate_retry(value).ok_or_else(|| SettingError::InvalidValue(key.clone()))?
        } else if matches!(key.as_str(), "retry-sleep" | "extractor-args" | "headers") {
            let items = validate_string_list(value)
                .ok_or_else(|| SettingError::InvalidValue(key.clone()))?;

            if key == "headers"
                && items.as_array().is_some_and(|entries| {
                    entries.iter().any(|entry| {
                        let (field, content) = entry
                            .as_str()
                            .unwrap_or_default()
                            .split_once(':')
                            .unwrap_or(("", ""));
                        field.trim().is_empty() || content.trim().is_empty()
                    })
                })
            {
                return Err(SettingError::InvalidValue(key.clone()));
            }

            items
        } else if matches!(
            key.as_str(),
            "preferred-video-codec"
                | "preferred-audio-codec"
                | "audio-source-codec"
                | "audio-source-container"
        ) {
            validate_codec(value).ok_or_else(|| SettingError::InvalidValue(key.clone()))?
        } else if key == "ip-family" {
            validate_choice(value, &["ipv4", "ipv6"])
                .ok_or_else(|| SettingError::InvalidValue(key.clone()))?
        } else if key == "socket-timeout" {
            let number = value
                .as_f64()
                .filter(|number| number.is_finite() && *number > 0.0)
                .ok_or_else(|| SettingError::InvalidValue(key.clone()))?;

            Value::from(number)
        } else if OTHER_RECOGNISED_SETTINGS.contains(&key.as_str()) {
            return Err(SettingError::UnsupportedSetting(key.clone()));
        } else {
            return Err(SettingError::UnknownSetting(key.clone()));
        };

        validated.insert(key.clone(), normalised);
    }

    if ["cookies", "no-cookies"]
        .iter()
        .filter(|key| validated.contains_key(**key))
        .count()
        > 1
    {
        return Err(SettingError::ConflictingSettings(
            "cookies and no-cookies".to_owned(),
        ));
    }

    if (validated.get("live-from-start") == Some(&Value::Bool(true))
        || validated.get("write-live-chat") == Some(&Value::Bool(true)))
        && validated.get("live") != Some(&Value::Bool(true))
    {
        return Err(SettingError::ConflictingSettings(
            "live=true is required".to_owned(),
        ));
    }

    Ok(validated)
}

/// Validate every resolved profile while retaining its inheritance provenance.
pub fn validate_profiles(
    profiles: &BTreeMap<String, ResolvedProfile>,
) -> Result<BTreeMap<String, ValidatedProfile>, (String, SettingError)> {
    let mut validated = BTreeMap::new();

    for (name, profile) in profiles {
        let settings =
            validate_settings(&profile.settings).map_err(|error| (name.clone(), error))?;

        validated.insert(
            name.clone(),
            ValidatedProfile {
                settings,
                parent: profile.parent.clone(),
                ancestry: profile.ancestry.clone(),
                setting_sources: profile.setting_sources.clone(),
            },
        );
    }

    Ok(validated)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::profile_file::{parse_profile_structure, resolve_profile_structure};

    #[test]
    fn normalises_strings_and_preserves_json_types() {
        let settings =
            serde_json::from_str(r#"{"path":" /tmp/videos ","playlist":true,"min-fps":24}"#)
                .unwrap();
        let validated = validate_settings(&settings).unwrap();

        assert_eq!(validated["path"], "/tmp/videos");
        assert_eq!(validated["playlist"], true);
        assert_eq!(validated["min-fps"], 24);
    }

    #[test]
    fn rejects_invalid_types_and_unported_options() {
        for json in [r#"{"playlist":1}"#, r#"{"path":"  "}"#, r#"{"min-fps":0}"#] {
            let settings = serde_json::from_str(json).unwrap();
            assert!(matches!(
                validate_settings(&settings),
                Err(SettingError::InvalidValue(_))
            ));
        }

        let settings = serde_json::from_str(r#"{"cookies-from-browser":"firefox"}"#).unwrap();
        assert_eq!(
            validate_settings(&settings),
            Err(SettingError::UnsupportedSetting(
                "cookies-from-browser".into()
            ))
        );

        let settings = serde_json::from_str(r#"{"unrecognised":true}"#).unwrap();
        assert_eq!(
            validate_settings(&settings),
            Err(SettingError::UnknownSetting("unrecognised".into()))
        );
    }

    #[test]
    fn validates_inherited_settings_and_retains_sources() {
        let raw = parse_profile_structure(r#"{"version":3,"$defaults":{"playlist":true},"profiles":{"base":{"path":" /tmp "},"child":{"parent":"base","output":"file.%(ext)s"}}}"#).unwrap();
        let resolved = resolve_profile_structure(&raw).unwrap();
        let validated = validate_profiles(&resolved).unwrap();

        assert_eq!(validated["child"].settings["path"], "/tmp");
        assert_eq!(validated["child"].setting_sources["path"], "profile 'base'");
        assert_eq!(validated["child"].ancestry, ["base"]);
    }

    #[test]
    fn rejects_conflicting_live_and_cookie_settings() {
        for json in [
            r#"{"cookies":"file.txt","no-cookies":false}"#,
            r#"{"live-from-start":true}"#,
        ] {
            let settings = serde_json::from_str(json).unwrap();
            assert!(matches!(
                validate_settings(&settings),
                Err(SettingError::ConflictingSettings(_))
            ));
        }
    }
    #[test]
    fn validates_resolution_and_audio_families() {
        let settings = serde_json::from_str(r#"{"resolution":" 1080P ","min-resolution":"720p","max-resolution":2160,"preferred-hdr":"HDR","merge-container":"MKV","audio-format":"MP3","audio-quality":"192k"}"#).unwrap();
        let validated = validate_settings(&settings).unwrap();

        assert_eq!(validated["resolution"], " 1080P ");
        assert_eq!(validated["min-resolution"], 720);
        assert_eq!(validated["max-resolution"], 2160);
        assert_eq!(validated["preferred-hdr"], "hdr");
        assert_eq!(validated["merge-container"], "mkv");
        assert_eq!(validated["audio-format"], "mp3");
        assert_eq!(validated["audio-quality"], "192K");
    }

    #[test]
    fn validates_network_retry_and_codec_settings() {
        let settings = serde_json::from_str(r#"{"limit-rate":" 12m ","throttled-rate":"500K","retries":3,"fragment-retries":" INFINITE ","retry-sleep":[" fragment:exp=1:20 "],"headers":[" Accept: text/plain "],"ip-family":"IPV6","socket-timeout":1.5,"preferred-video-codec":" AV01 ","audio-source-container":" M4A "}"#).unwrap();
        let validated = validate_settings(&settings).unwrap();

        assert_eq!(validated["limit-rate"], "12m");
        assert_eq!(validated["retries"], "3");
        assert_eq!(validated["fragment-retries"], "infinite");
        assert_eq!(
            validated["retry-sleep"],
            serde_json::json!(["fragment:exp=1:20"])
        );
        assert_eq!(validated["ip-family"], "ipv6");
        assert_eq!(validated["socket-timeout"], 1.5);
        assert_eq!(validated["preferred-video-codec"], "av01");
        assert_eq!(validated["audio-source-container"], "m4a");
    }

    #[test]
    fn rejects_invalid_network_retry_and_codec_settings() {
        for json in [
            r#"{"limit-rate":"2MB"}"#,
            r#"{"limit-rate":"1."}"#,
            r#"{"retries":-1}"#,
            r#"{"retries":true}"#,
            r#"{"fragment-retries":"never"}"#,
            r#"{"retry-sleep":[]}"#,
            r#"{"extractor-args":[" "]}"#,
            r#"{"headers":["invalid"]}"#,
            r#"{"headers":["x: "]}"#,
            r#"{"socket-timeout":0}"#,
            r#"{"socket-timeout":"5"}"#,
            r#"{"ip-family":"auto"}"#,
            r#"{"preferred-audio-codec":"aac/mp3"}"#,
        ] {
            let settings = serde_json::from_str(json).unwrap();
            assert!(
                matches!(
                    validate_settings(&settings),
                    Err(SettingError::InvalidValue(_))
                ),
                "{json}"
            );
        }
    }

    #[test]
    fn rejects_invalid_resolution_and_audio_values() {
        for json in [
            r#"{"resolution":"0p"}"#,
            r#"{"min-resolution":true}"#,
            r#"{"max-resolution":"1.5p"}"#,
            r#"{"preferred-hdr":"dolby"}"#,
            r#"{"merge-container":"exe"}"#,
            r#"{"audio-format":"aac+mp3"}"#,
            r#"{"audio-quality":11}"#,
            r#"{"audio-quality":"0128K"}"#,
            r#"{"audio-quality":"1.K"}"#,
        ] {
            let settings = serde_json::from_str(json).unwrap();
            assert!(
                matches!(
                    validate_settings(&settings),
                    Err(SettingError::InvalidValue(_))
                ),
                "{json}"
            );
        }
    }
}
