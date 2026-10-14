//! File loading and profile selection for Downloader defaults documents.

use std::collections::BTreeMap;
use std::fs;
use std::io;
use std::path::Path;

use serde_json::{Map, Value};

use crate::profile_pipeline::{ProfilePipelineError, load_validated_profiles};
use crate::profile_selection::{ProfileSelectionError, SelectedProfile, select_profile};
use crate::profile_settings::ValidatedProfile;

/// Errors encountered while loading or selecting stored Downloader policy.
#[derive(Debug)]
pub enum ProfileStoreError {
    /// An explicitly named defaults file does not exist.
    MissingFile,
    /// Reading the defaults file failed for a reason other than its absence.
    Read(io::Error),
    /// The stored JSON document or one of its profiles is invalid.
    InvalidDocument(ProfilePipelineError),
    /// The requested profile or the combined policy is invalid.
    Selection(ProfileSelectionError),
}

/// Read and validate a defaults document, allowing an absent implicit file.
///
/// The caller resolves the default path. An explicitly supplied path must exist;
/// an absent implicit file produces an empty collection. Other I/O errors are
/// reported rather than treated as missing configuration.
pub fn load_profiles_from_path(
    path: &Path,
    explicit: bool,
) -> Result<BTreeMap<String, ValidatedProfile>, ProfileStoreError> {
    let content = match fs::read_to_string(path) {
        Ok(content) => content,
        Err(error) if error.kind() == io::ErrorKind::NotFound => {
            if explicit {
                return Err(ProfileStoreError::MissingFile);
            }

            return Ok(BTreeMap::new());
        }
        Err(error) => return Err(ProfileStoreError::Read(error)),
    };

    // Python's utf-8-sig reader accepts a UTF-8 BOM at the start of the file.
    let content = content.strip_prefix('\u{feff}').unwrap_or(&content);

    load_validated_profiles(content).map_err(ProfileStoreError::InvalidDocument)
}

/// Select a requested profile, or the conventional `default` profile if present.
///
/// Explicit settings take precedence over the selected profile. If there is no
/// named selection and no stored `default` profile, only the overrides apply.
pub fn select_stored_profile(
    profiles: &BTreeMap<String, ValidatedProfile>,
    requested_name: Option<&str>,
    overrides: &Map<String, Value>,
) -> Result<SelectedProfile, ProfileStoreError> {
    let name = requested_name.or_else(|| profiles.contains_key("default").then_some("default"));

    select_profile(profiles, name, overrides).map_err(ProfileStoreError::Selection)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::sync::atomic::{AtomicUsize, Ordering};

    static NEXT_FILE: AtomicUsize = AtomicUsize::new(0);

    /// Keep each test's temporary file distinct without introducing a test dependency.
    fn temporary_file() -> std::path::PathBuf {
        let id = NEXT_FILE.fetch_add(1, Ordering::Relaxed);
        std::env::temp_dir().join(format!(
            "yt-downloader-profile-{}-{id}.json",
            std::process::id()
        ))
    }

    #[test]
    fn missing_implicit_file_is_allowed_but_explicit_file_is_not() {
        let path = temporary_file();
        assert!(load_profiles_from_path(&path, false).unwrap().is_empty());
        assert!(matches!(
            load_profiles_from_path(&path, true),
            Err(ProfileStoreError::MissingFile)
        ));
    }

    #[test]
    fn loads_utf8_bom_and_selects_default_profile() {
        let path = temporary_file();
        let document = json!({
            "version": 3,
            "profiles": {
                "default": {"playlist": true},
                "other": {"playlist": false}
            }
        });
        fs::write(&path, format!("\u{feff}{document}")).unwrap();
        let profiles = load_profiles_from_path(&path, true).unwrap();
        fs::remove_file(&path).unwrap();

        let selected = select_stored_profile(&profiles, None, &Map::new()).unwrap();
        assert_eq!(selected.profile_name.as_deref(), Some("default"));
        assert_eq!(selected.settings["playlist"], true);

        let selected = select_stored_profile(&profiles, Some("other"), &Map::new()).unwrap();
        assert_eq!(selected.settings["playlist"], false);
    }

    #[test]
    fn rejects_invalid_stored_json() {
        let path = temporary_file();
        fs::write(&path, "not json").unwrap();
        let result = load_profiles_from_path(&path, true);
        fs::remove_file(&path).unwrap();

        assert!(matches!(result, Err(ProfileStoreError::InvalidDocument(_))));
    }

    #[test]
    fn missing_default_profile_keeps_explicit_settings() {
        let overrides = json!({"playlist": false});
        let selected =
            select_stored_profile(&BTreeMap::new(), None, overrides.as_object().unwrap()).unwrap();

        assert_eq!(selected.profile_name, None);
        assert_eq!(selected.settings["playlist"], false);
    }
}
