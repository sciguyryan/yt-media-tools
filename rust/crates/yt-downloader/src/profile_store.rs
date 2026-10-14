//! File loading and profile selection for Downloader defaults documents.

use std::collections::BTreeMap;
use std::ffi::OsStr;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

use serde_json::{Map, Value};

use crate::ProfileOptions;
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
    /// A listing request must be handled separately from effective-policy selection.
    ListingRequested,
    /// The supplied profile name cannot be represented as UTF-8.
    InvalidProfileNameEncoding,
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

/// Expand a leading home-directory marker for an explicitly supplied path.
///
/// Python's `Path.expanduser()` recognises `~` and `~/...` (or `~\...` on
/// Windows). Named-user expansion is not attempted here: it requires a separate
/// platform account lookup and must not be approximated with the current home.
fn expand_current_user(path: &Path, home: Option<&Path>) -> PathBuf {
    let mut components = path.components();
    let first = components.next();
    let Some(home) = home else {
        return path.to_path_buf();
    };

    if first.is_some_and(|component| component.as_os_str() == OsStr::new("~")) {
        return home.join(components.as_path());
    }

    path.to_path_buf()
}

/// Return the current user's home directory using platform-aware resolution.
fn home_directory() -> Option<PathBuf> {
    home::home_dir()
}

/// Resolve the defaults file relative to the caller's executable directory.
///
/// Explicit paths expand a leading current-user home marker. Other relative
/// paths remain relative to the working directory. The implicit file lives beside the
/// executable rather than in the working directory.
pub fn resolve_defaults_path(options: &ProfileOptions, executable_dir: &Path) -> (PathBuf, bool) {
    match &options.defaults {
        Some(path) => (
            expand_current_user(Path::new(path), home_directory().as_deref()),
            true,
        ),
        None => (executable_dir.join("defaults.json"), false),
    }
}

/// Load stored profiles and select the effective policy for parsed CLI options.
///
/// The caller provides the executable directory and already interpreted explicit
/// overrides. Listing requests have a separate result path and are rejected here
/// rather than accidentally selecting a download policy.
pub fn select_from_cli_store(
    options: &ProfileOptions,
    executable_dir: &Path,
    overrides: &Map<String, Value>,
) -> Result<SelectedProfile, ProfileStoreError> {
    if options.list_profiles {
        return Err(ProfileStoreError::ListingRequested);
    }

    let requested_name = options
        .profile
        .as_ref()
        .map(|name| {
            name.to_str()
                .ok_or(ProfileStoreError::InvalidProfileNameEncoding)
        })
        .transpose()?;

    let (path, explicit) = resolve_defaults_path(options, executable_dir);
    let profiles = load_profiles_from_path(&path, explicit)?;

    select_stored_profile(&profiles, requested_name, overrides)
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
    fn expands_current_user_home_without_changing_other_relative_paths() {
        let home = Path::new("/example/home");
        assert_eq!(
            expand_current_user(Path::new("~/profiles/defaults.json"), Some(home)),
            home.join("profiles/defaults.json"),
        );
        assert_eq!(expand_current_user(Path::new("~"), Some(home)), home,);
        assert_eq!(
            expand_current_user(Path::new("profiles/defaults.json"), Some(home)),
            PathBuf::from("profiles/defaults.json"),
        );
        assert_eq!(
            expand_current_user(Path::new("~other/defaults.json"), Some(home)),
            PathBuf::from("~other/defaults.json"),
        );
        assert_eq!(
            expand_current_user(Path::new("~/profiles/defaults.json"), None),
            PathBuf::from("~/profiles/defaults.json"),
        );
    }

    #[test]
    fn implicit_path_is_executable_local_and_explicit_path_is_preserved() {
        let options = crate::parse_profile_options(Vec::<std::ffi::OsString>::new()).unwrap();
        assert_eq!(
            resolve_defaults_path(&options, Path::new("/opt/downloader")),
            (PathBuf::from("/opt/downloader/defaults.json"), false),
        );

        let options = crate::parse_profile_options(
            ["--defaults", "config/profiles.json"]
                .into_iter()
                .map(std::ffi::OsString::from),
        )
        .unwrap();
        assert_eq!(
            resolve_defaults_path(&options, Path::new("/opt/downloader")),
            (PathBuf::from("config/profiles.json"), true),
        );
    }

    #[test]
    fn cli_store_selects_default_or_explicit_profile_and_applies_overrides() {
        let directory = std::env::temp_dir().join(format!(
            "yt-downloader-store-{}-{}",
            std::process::id(),
            NEXT_FILE.fetch_add(1, Ordering::Relaxed),
        ));
        fs::create_dir(&directory).unwrap();
        let file = directory.join("defaults.json");
        fs::write(
            &file,
            json!({
                "version": 3,
                "profiles": {
                    "default": {"playlist": true},
                    "other": {"playlist": false}
                }
            })
            .to_string(),
        )
        .unwrap();

        let options = crate::parse_profile_options(Vec::<std::ffi::OsString>::new()).unwrap();
        let overrides = json!({"playlist": false});
        let selected =
            select_from_cli_store(&options, &directory, overrides.as_object().unwrap()).unwrap();
        assert_eq!(selected.profile_name.as_deref(), Some("default"));
        assert_eq!(selected.settings["playlist"], false);
        assert_eq!(selected.setting_sources["playlist"], "explicit override");

        let options = crate::parse_profile_options(
            ["--profile", "other"]
                .into_iter()
                .map(std::ffi::OsString::from),
        )
        .unwrap();
        let selected = select_from_cli_store(&options, &directory, &Map::new()).unwrap();
        assert_eq!(selected.profile_name.as_deref(), Some("other"));
        assert_eq!(selected.settings["playlist"], false);

        fs::remove_file(&file).unwrap();
        fs::remove_dir(&directory).unwrap();
    }

    #[test]
    fn cli_store_distinguishes_missing_implicit_and_explicit_files() {
        let directory = std::env::temp_dir().join(format!(
            "yt-downloader-absent-{}-{}",
            std::process::id(),
            NEXT_FILE.fetch_add(1, Ordering::Relaxed),
        ));
        let options = crate::parse_profile_options(Vec::<std::ffi::OsString>::new()).unwrap();
        let selected = select_from_cli_store(&options, &directory, &Map::new()).unwrap();
        assert_eq!(selected.profile_name, None);

        let missing = directory.join("not-found.json");
        let options = crate::parse_profile_options([
            std::ffi::OsString::from("--defaults"),
            missing.into_os_string(),
        ])
        .unwrap();
        assert!(matches!(
            select_from_cli_store(&options, &directory, &Map::new()),
            Err(ProfileStoreError::MissingFile)
        ));
    }

    #[test]
    fn cli_store_rejects_listing_without_loading_a_file() {
        let options = crate::parse_profile_options(
            ["--list-profiles"]
                .into_iter()
                .map(std::ffi::OsString::from),
        )
        .unwrap();
        assert!(matches!(
            select_from_cli_store(&options, Path::new("/unused"), &Map::new()),
            Err(ProfileStoreError::ListingRequested)
        ));
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
