//! In-memory loading and validation of Downloader profile documents.

use std::collections::BTreeMap;

use crate::profile_file::{ProfileFileError, parse_profile_structure, resolve_profile_structure};
use crate::profile_settings::{SettingError, ValidatedProfile, validate_profiles};

/// Identifies which stage rejected a profile document.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ProfilePipelineError {
    /// The document structure, reusable values or inheritance graph is invalid.
    ProfileFile(ProfileFileError),
    /// A resolved profile contains an invalid or unsupported setting.
    Setting {
        /// The profile whose effective settings failed validation.
        profile: String,
        /// The setting validation failure.
        error: SettingError,
    },
}

/// Parse, resolve and validate every profile in a JSON document.
///
/// The operation does not read files or alter process state. It validates all profiles,
/// including those not selected by a caller, so invalid stored policy cannot go unnoticed.
/// The returned map retains each profile's inheritance and setting provenance.
///
/// This is an in-memory building block. Selecting a profile and applying explicit CLI
/// overrides remain separate operations.
pub fn load_validated_profiles(
    json: &str,
) -> Result<BTreeMap<String, ValidatedProfile>, ProfilePipelineError> {
    let raw = parse_profile_structure(json).map_err(ProfilePipelineError::ProfileFile)?;
    let resolved = resolve_profile_structure(&raw).map_err(ProfilePipelineError::ProfileFile)?;

    validate_profiles(&resolved)
        .map_err(|(profile, error)| ProfilePipelineError::Setting { profile, error })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn loads_inherited_profiles_with_normalised_settings_and_sources() {
        let document = json!({
            "version": 3,
            "$defaults": {"playlist": true},
            "profiles": {
                "base": {"audio-format": "mp3"},
                "child": {"parent": "base", "audio-quality": "192K"}
            }
        });

        let profiles = load_validated_profiles(&document.to_string()).unwrap();
        let child = &profiles["child"];

        assert_eq!(child.settings["playlist"], true);
        assert_eq!(child.settings["audio-format"], "mp3");
        assert_eq!(child.settings["audio-quality"], "192K");
        assert_eq!(child.ancestry, vec!["base"]);
        assert_eq!(child.setting_sources["playlist"], "$defaults");
        assert_eq!(child.setting_sources["audio-format"], "profile 'base'");
        assert_eq!(child.setting_sources["audio-quality"], "profile 'child'");
    }

    #[test]
    fn reports_the_profile_containing_invalid_effective_policy() {
        let document = json!({
            "version": 3,
            "profiles": {
                "base": {"audio-quality": "192K"},
                "child": {"parent": "base", "audio-format": "mp3"}
            }
        });

        assert_eq!(
            load_validated_profiles(&document.to_string()),
            Err(ProfilePipelineError::Setting {
                profile: "base".to_owned(),
                error: SettingError::ConflictingSettings(
                    "audio-quality requires audio-format".to_owned(),
                ),
            }),
        );
    }

    #[test]
    fn preserves_structural_errors_without_misclassifying_them_as_settings() {
        assert_eq!(
            load_validated_profiles("not json"),
            Err(ProfilePipelineError::ProfileFile(
                ProfileFileError::InvalidJson
            )),
        );
    }
}
