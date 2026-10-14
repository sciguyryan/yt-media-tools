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

// The full set is deliberately explicit. Recognised options whose Python validation
// is not implemented here fail closed rather than passing unchecked values through.
const OTHER_RECOGNISED_SETTINGS: &[&str] = &[
    "resolution",
    "cookies-from-browser",
    "playlist-items",
    "wait-for-video",
    "chapter-sections",
    "time-ranges",
    "limit-rate",
    "throttled-rate",
    "headers",
    "ip-family",
    "retries",
    "fragment-retries",
    "file-access-retries",
    "extractor-retries",
    "retry-sleep",
    "extractor-args",
    "min-resolution",
    "max-resolution",
    "preferred-video-codec",
    "preferred-audio-codec",
    "preferred-hdr",
    "merge-container",
    "audio-source-codec",
    "audio-source-container",
    "audio-format",
    "audio-quality",
    "socket-timeout",
    "sponsorblock-mark",
    "sponsorblock-remove",
];

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

        let settings = serde_json::from_str(r#"{"resolution":"1080p"}"#).unwrap();
        assert_eq!(
            validate_settings(&settings),
            Err(SettingError::UnsupportedSetting("resolution".into()))
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
}
