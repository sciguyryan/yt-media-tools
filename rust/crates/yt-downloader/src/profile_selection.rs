//! Selection and explicit overrides for validated Downloader profiles.

use std::collections::BTreeMap;

use serde_json::{Map, Value};

use crate::profile_settings::{SettingError, ValidatedProfile, validate_settings};

/// Failures when selecting a profile or applying explicit settings.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ProfileSelectionError {
    /// The requested profile is not present in the validated document.
    UnknownProfile(String),
    /// The combined settings contain an invalid value or an unsupported combination.
    InvalidSettings(SettingError),
}

/// Effective settings selected for a download, with their origins retained.
#[derive(Debug, Clone, PartialEq)]
pub struct SelectedProfile {
    /// Validated settings after explicit overrides have been applied.
    pub settings: Map<String, Value>,
    /// Name of the selected stored profile, when one was requested.
    pub profile_name: Option<String>,
    /// Profile ancestry, from the oldest ancestor to the immediate parent.
    pub ancestry: Vec<String>,
    /// Origin of each effective setting, including explicit overrides.
    pub setting_sources: BTreeMap<String, String>,
}

/// Select a validated profile and apply explicit settings over its inherited policy.
///
/// Overrides replace settings with the same name. The combined policy is validated
/// again because an override may introduce a conflict with an inherited setting.
/// This function does not read files or interpret command-line argument syntax.
pub fn select_profile(
    profiles: &BTreeMap<String, ValidatedProfile>,
    name: Option<&str>,
    overrides: &Map<String, Value>,
) -> Result<SelectedProfile, ProfileSelectionError> {
    let selected = name
        .map(|name| {
            profiles
                .get(name)
                .ok_or_else(|| ProfileSelectionError::UnknownProfile(name.to_owned()))
        })
        .transpose()?;

    let mut settings = selected.map_or_else(Map::new, |profile| profile.settings.clone());
    let mut setting_sources =
        selected.map_or_else(BTreeMap::new, |profile| profile.setting_sources.clone());

    for (key, value) in overrides {
        settings.insert(key.clone(), value.clone());
        setting_sources.insert(key.clone(), "explicit override".to_owned());
    }

    let settings = validate_settings(&settings).map_err(ProfileSelectionError::InvalidSettings)?;

    Ok(SelectedProfile {
        settings,
        profile_name: name.map(str::to_owned),
        ancestry: selected.map_or_else(Vec::new, |profile| profile.ancestry.clone()),
        setting_sources,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::profile_pipeline::load_validated_profiles;
    use serde_json::json;

    fn profiles() -> BTreeMap<String, ValidatedProfile> {
        load_validated_profiles(
            &json!({
                "version": 3,
                "$defaults": {"playlist": true},
                "profiles": {
                    "base": {"audio-format": "mp3"},
                    "child": {"parent": "base", "audio-quality": "192K"}
                }
            })
            .to_string(),
        )
        .unwrap()
    }

    #[test]
    fn selects_inherited_policy_without_changing_its_provenance() {
        let result = select_profile(&profiles(), Some("child"), &Map::new()).unwrap();

        assert_eq!(result.settings["playlist"], true);
        assert_eq!(result.settings["audio-format"], "mp3");
        assert_eq!(result.ancestry, vec!["base"]);
        assert_eq!(result.setting_sources["audio-format"], "profile 'base'");
    }

    #[test]
    fn explicit_settings_replace_inherited_values() {
        let overrides = json!({"audio-quality": "128K", "playlist": false});
        let result =
            select_profile(&profiles(), Some("child"), overrides.as_object().unwrap()).unwrap();

        assert_eq!(result.settings["audio-quality"], "128K");
        assert_eq!(result.settings["playlist"], false);
        assert_eq!(result.setting_sources["audio-quality"], "explicit override");
        assert_eq!(result.setting_sources["playlist"], "explicit override");
        assert_eq!(result.setting_sources["audio-format"], "profile 'base'");
    }

    #[test]
    fn rejects_unknown_profiles() {
        assert_eq!(
            select_profile(&profiles(), Some("missing"), &Map::new()),
            Err(ProfileSelectionError::UnknownProfile("missing".to_owned())),
        );
    }

    #[test]
    fn rejects_conflicts_introduced_by_overrides() {
        let overrides = json!({"audio-format": null});
        let result = select_profile(&profiles(), Some("child"), overrides.as_object().unwrap());

        assert_eq!(
            result,
            Err(ProfileSelectionError::InvalidSettings(
                SettingError::InvalidValue("audio-format".to_owned())
            )),
        );
    }

    #[test]
    fn accepts_explicit_settings_without_a_stored_profile() {
        let overrides = json!({"playlist": false});
        let result = select_profile(&profiles(), None, overrides.as_object().unwrap()).unwrap();

        assert_eq!(result.settings["playlist"], false);
        assert_eq!(result.profile_name, None);
        assert!(result.ancestry.is_empty());
    }
}
