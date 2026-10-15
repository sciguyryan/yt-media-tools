//! File loading and profile selection for Downloader defaults documents.

use serde_json::{Map, Value};
use std::collections::BTreeMap;
use std::ffi::OsStr;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use unicode_casefold::UnicodeCaseFold;

use crate::ProfileOptions;
use crate::profile_file::ProfileFileError;
use crate::profile_pipeline::{ProfilePipelineError, load_validated_profiles};
use crate::profile_selection::{ProfileSelectionError, SelectedProfile, select_profile};
use crate::profile_settings::{SettingError, ValidatedProfile};

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

/// Format a stored-profile failure for a user-facing diagnostic.
///
/// The resolved path is supplied by the caller because file loading and error
/// classification deliberately remain independent of CLI presentation.
pub fn describe_store_error(error: &ProfileStoreError, path: &Path) -> String {
    let location = path.display();

    match error {
        ProfileStoreError::MissingFile => {
            format!("defaults file not found: {location}")
        }
        ProfileStoreError::Read(cause) => {
            format!("cannot read defaults file {location}: {cause}")
        }
        ProfileStoreError::InvalidDocument(cause) => {
            format!(
                "invalid defaults file {location}: {}",
                describe_pipeline_error(cause)
            )
        }
        ProfileStoreError::ListingRequested => {
            "profile selection cannot handle a listing request".to_owned()
        }
        ProfileStoreError::InvalidProfileNameEncoding => {
            "profile name must be valid UTF-8".to_owned()
        }
        ProfileStoreError::Selection(cause) => match cause {
            ProfileSelectionError::UnknownProfile(name) => {
                format!("unknown profile: {name}")
            }
            ProfileSelectionError::InvalidSettings(setting_error) => {
                format!(
                    "invalid effective profile settings: {}",
                    describe_setting_error(setting_error)
                )
            }
            ProfileSelectionError::InvalidProfileNameEncoding => {
                "profile name must be valid UTF-8".to_owned()
            }
            ProfileSelectionError::DefaultsFileNotLoaded => {
                "defaults file must be loaded before selecting a profile".to_owned()
            }
            ProfileSelectionError::ListingRequested => {
                "profile listing cannot be used to select download policy".to_owned()
            }
        },
    }
}

/// Describe a document failure while preserving the stage and affected profile.
fn describe_pipeline_error(error: &ProfilePipelineError) -> String {
    match error {
        ProfilePipelineError::ProfileFile(cause) => describe_profile_file_error(cause),
        ProfilePipelineError::Setting { profile, error } => {
            format!("profile '{profile}': {}", describe_setting_error(error))
        }
    }
}

/// Describe structural, inheritance and reusable-value failures.
fn describe_profile_file_error(error: &ProfileFileError) -> String {
    match error {
        ProfileFileError::InvalidJson => "invalid JSON".to_owned(),
        ProfileFileError::InvalidRoot => "root must be a JSON object".to_owned(),
        ProfileFileError::InvalidVersion => {
            "unsupported or missing profile format version".to_owned()
        }
        ProfileFileError::UnknownRootKey(key) => format!("unknown root key: {key}"),
        ProfileFileError::InvalidValues => "'values' must be a JSON object".to_owned(),
        ProfileFileError::InvalidProfiles => "'profiles' must be a JSON object".to_owned(),
        ProfileFileError::InvalidDefaults => "'$defaults' must be a JSON object".to_owned(),
        ProfileFileError::InvalidProfileName(name) => format!("invalid profile name: {name}"),
        ProfileFileError::InvalidProfile(name) => {
            format!("profile '{name}' must be a JSON object")
        }
        ProfileFileError::InvalidParent(name) => {
            format!("invalid parent declaration in profile '{name}'")
        }
        ProfileFileError::MissingParent(name) => format!("unknown parent profile: {name}"),
        ProfileFileError::InheritanceCycle(chain) => {
            format!("profile inheritance cycle: {}", chain.join(" -> "))
        }
        ProfileFileError::InvalidValueReference(reference) => {
            format!("invalid value reference: {reference}")
        }
        ProfileFileError::UnknownValueReference(reference) => {
            format!("unknown value reference: {reference}")
        }
        ProfileFileError::ValueReferenceCycle(chain) => {
            format!("value reference cycle: {}", chain.join(" -> "))
        }
    }
}

/// Describe an effective-setting failure without exposing Rust enum syntax.
fn describe_setting_error(error: &SettingError) -> String {
    match error {
        SettingError::UnknownSetting(name) => format!("unknown setting: {name}"),
        SettingError::UnsupportedSetting(name) => {
            format!("setting not yet supported by the Rust Downloader: {name}")
        }
        SettingError::InvalidValue(name) => format!("invalid value for setting: {name}"),
        SettingError::ConflictingSettings(reason) => {
            format!("conflicting settings: {reason}")
        }
    }
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

/// A successful full-file validation result, independent of CLI presentation.
///
/// The caller supplies whether the path was explicitly requested. Validation
/// always requires a real file, unlike implicit profile selection, which may
/// legitimately proceed without a defaults file.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ConfigValidation {
    /// Number of validated profiles in the file.
    pub profile_count: usize,
    /// Profile names in deterministic order.
    pub profiles: Vec<String>,
}

/// Validate a complete defaults document without selecting or downloading.
///
/// Unlike normal implicit defaults loading, a missing file is an error here,
/// matching the Python validation command's required-file semantics.
pub fn validate_config_path(path: &Path) -> Result<ConfigValidation, ProfileStoreError> {
    let profiles = load_profiles_from_path(path, true)?;
    Ok(ConfigValidation {
        profile_count: profiles.len(),
        profiles: profiles.keys().cloned().collect(),
    })
}

/// Render successful validation using the Python machine-output field names.
///
/// Version identifiers are explicit inputs: the Rust crate version must not be
/// mistaken for the authoritative Python Downloader contract version.
pub fn config_validation_json(
    validation: &ConfigValidation,
    path: &Path,
    schema_version: u64,
    contract_version: u64,
    downloader_version: &str,
) -> Value {
    serde_json::json!({
        "kind": "yt-download-config-validation",
        "schema_version": schema_version,
        "contract_version": contract_version,
        "downloader_version": downloader_version,
        "path": path.to_string_lossy(),
        "valid": true,
        "profile_count": validation.profile_count,
        "profiles": validation.profiles,
    })
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

/// Names and effective settings available for profile-listing presentation.
#[derive(Debug, Clone, PartialEq)]
pub struct ListedProfile {
    /// Stored profile name.
    pub name: String,
    /// Effective validated settings, including inherited values.
    pub settings: Map<String, Value>,
    /// Parent profile, if this profile inherits another.
    pub parent: Option<String>,
}

/// Return profiles in deterministic name order without selecting download policy.
///
/// Listing operates on the same validated profiles as ordinary selection, so
/// inherited values have already been resolved and checked.
pub fn list_stored_profiles(profiles: &BTreeMap<String, ValidatedProfile>) -> Vec<ListedProfile> {
    profiles
        .iter()
        .map(|(name, profile)| ListedProfile {
            name: name.clone(),
            settings: profile.settings.clone(),
            parent: profile.parent.clone(),
        })
        .collect()
}

/// Render a validated profile hierarchy without loading files or selecting media.
///
/// The caller supplies whether the document declares `$defaults`; this is a
/// property of the original document, not of the resolved profile settings.
/// Unknown focus names are rejected instead of silently showing an empty tree.
pub fn render_profile_tree(
    profiles: &[ListedProfile],
    has_defaults: bool,
    focus: Option<&str>,
    ascii_only: bool,
) -> Result<String, String> {
    use std::collections::BTreeMap;

    let mut parents = BTreeMap::new();
    let mut children: BTreeMap<Option<String>, Vec<String>> = BTreeMap::new();
    for profile in profiles {
        parents.insert(profile.name.clone(), profile.parent.clone());
        children
            .entry(profile.parent.clone())
            .or_default()
            .push(profile.name.clone());
    }

    for names in children.values_mut() {
        names.sort_by_key(|name| name.case_fold().collect::<String>());
    }

    let (tee, elbow, pipe, space) = if ascii_only {
        ("|-- ", "`-- ", "|   ", "    ")
    } else {
        ("├── ", "└── ", "│   ", "    ")
    };

    if let Some(name) = focus {
        if !parents.contains_key(name) {
            return Err(format!("unknown profile: {name}"));
        }

        let mut chain = vec![name.to_owned()];
        let mut current = name;
        for _ in 0..parents.len() {
            let Some(Some(parent)) = parents.get(current) else {
                break;
            };
            chain.push(parent.clone());
            current = parent;
        }
        chain.reverse();
        if has_defaults {
            chain.insert(0, "$defaults".to_owned());
        }

        let mut lines = vec![chain[0].clone()];
        for (depth, item) in chain.iter().skip(1).enumerate() {
            lines.push(format!("{}{elbow}{item}", space.repeat(depth)));
        }
        return Ok(lines.join("\n"));
    }

    fn emit(
        parent: &str,
        prefix: &str,
        children: &BTreeMap<Option<String>, Vec<String>>,
        lines: &mut Vec<String>,
        connectors: (&str, &str, &str, &str),
    ) {
        let (tee, elbow, pipe, space) = connectors;
        if let Some(kids) = children.get(&Some(parent.to_owned())) {
            for (index, child) in kids.iter().enumerate() {
                let last = index + 1 == kids.len();
                lines.push(format!("{prefix}{}{child}", if last { elbow } else { tee }));
                emit(
                    child,
                    &format!("{prefix}{}", if last { space } else { pipe }),
                    children,
                    lines,
                    connectors,
                );
            }
        }
    }

    let roots = children.get(&None).map(Vec::as_slice).unwrap_or(&[]);
    let mut lines = Vec::new();
    if has_defaults {
        lines.push("$defaults".to_owned());
    }

    for (index, root) in roots.iter().enumerate() {
        let last = index + 1 == roots.len();
        if has_defaults {
            lines.push(format!("{}{root}", if last { elbow } else { tee }));
            emit(
                root,
                if last { space } else { pipe },
                &children,
                &mut lines,
                (tee, elbow, pipe, space),
            );
        } else {
            if index > 0 {
                lines.push(String::new());
            }
            lines.push(root.clone());
            emit(root, "", &children, &mut lines, (tee, elbow, pipe, space));
        }
    }
    Ok(lines.join("\n"))
}

/// Load the same validated profile model used by listing, and render its tree.
///
/// A missing implicit defaults file follows the Python inspection convention.
pub fn render_tree_from_path(
    path: &Path,
    explicit: bool,
    focus: Option<&str>,
    ascii_only: bool,
) -> Result<String, ProfileStoreError> {
    if !explicit && !path.exists() {
        return Ok(format!(
            "No profiles are available in {}.\n",
            path.display()
        ));
    }

    let profiles = load_profiles_from_path(path, true)?;
    let document = fs::read_to_string(path).map_err(ProfileStoreError::Read)?;
    let document = document.strip_prefix('\u{feff}').unwrap_or(&document);
    let root: Value = serde_json::from_str(document).map_err(|_| {
        ProfileStoreError::InvalidDocument(ProfilePipelineError::ProfileFile(
            ProfileFileError::InvalidJson,
        ))
    })?;
    let has_defaults =
        root.get("version").and_then(Value::as_u64) == Some(3) && root.get("$defaults").is_some();
    let listed = list_stored_profiles(&profiles);
    let rendered =
        render_profile_tree(&listed, has_defaults, focus, ascii_only).map_err(|name| {
            ProfileStoreError::Selection(ProfileSelectionError::UnknownProfile(
                name.strip_prefix("unknown profile: ")
                    .unwrap_or(&name)
                    .to_owned(),
            ))
        })?;
    Ok(format!("{rendered}\n"))
}

/// Render the human-readable profile list used by the Python Downloader.
///
/// The stored names are presented without their resolved settings. Sorting is
/// case-insensitive using Unicode case folding, matching Python's sorting key.
pub fn render_profile_listing(path: &Path, profiles: &[ListedProfile]) -> String {
    if profiles.is_empty() {
        return format!("No profiles are available in {}.\n", path.display());
    }

    let mut names: Vec<&str> = profiles
        .iter()
        .map(|profile| profile.name.as_str())
        .collect();
    // Python orders profile names by Unicode casefolded spelling.
    // Stable sorting preserves the input order for equivalent folded names.
    names.sort_by_key(|name| name.case_fold().collect::<String>());

    let mut output = format!("Available profiles in {}:\n\n", path.display());

    for name in names {
        output.push_str("  ");
        output.push_str(name);
        output.push('\n');
    }

    output
}

/// Load and render a listing using the same path as profile selection.
///
/// A missing implicit defaults file produces the Python Downloader's empty
/// listing message. Explicitly missing files remain errors.
pub fn render_from_cli_store(
    options: &ProfileOptions,
    executable_dir: &Path,
) -> Result<String, ProfileStoreError> {
    let (path, _) = resolve_defaults_path(options, executable_dir);
    let profiles = list_from_cli_store(options, executable_dir)?;

    Ok(render_profile_listing(&path, &profiles))
}

/// Load a defaults document for a CLI listing request.
///
/// The listing path does not select a profile or apply download overrides.
/// An absent implicit defaults file yields an empty list, while a missing
/// explicitly named file remains an error.
pub fn list_from_cli_store(
    options: &ProfileOptions,
    executable_dir: &Path,
) -> Result<Vec<ListedProfile>, ProfileStoreError> {
    if !options.list_profiles {
        return Err(ProfileStoreError::ListingRequested);
    }

    let (path, explicit) = resolve_defaults_path(options, executable_dir);
    let profiles = load_profiles_from_path(&path, explicit)?;

    Ok(list_stored_profiles(&profiles))
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
    #[test]
    fn profile_tree_matches_python_hierarchy_layout() {
        let profiles = vec![
            ListedProfile {
                name: "root".to_owned(),
                settings: Map::new(),
                parent: None,
            },
            ListedProfile {
                name: "child".to_owned(),
                settings: Map::new(),
                parent: Some("root".to_owned()),
            },
        ];
        assert_eq!(
            render_profile_tree(&profiles, true, None, false).unwrap(),
            "$defaults\n└── root\n    └── child"
        );
        assert_eq!(
            render_profile_tree(&profiles, true, Some("child"), true).unwrap(),
            "$defaults\n`-- root\n    `-- child"
        );
        assert_eq!(
            render_profile_tree(&profiles, false, None, true).unwrap(),
            "root\n`-- child"
        );
        assert_eq!(
            render_profile_tree(&profiles, false, Some("child"), false).unwrap(),
            "root\n└── child"
        );
        assert!(render_profile_tree(&profiles, false, Some("missing"), false).is_err());
    }

    #[test]
    fn validation_json_preserves_the_python_field_contract() {
        let result = ConfigValidation {
            profile_count: 2,
            profiles: vec!["default".to_owned(), "music".to_owned()],
        };
        let payload = config_validation_json(
            &result,
            Path::new("/tmp/example.json"),
            3,
            2,
            "test-version",
        );
        assert_eq!(payload["kind"], "yt-download-config-validation");
        assert_eq!(payload["schema_version"], 3);
        assert_eq!(payload["contract_version"], 2);
        assert_eq!(payload["downloader_version"], "test-version");
        assert_eq!(payload["path"], "/tmp/example.json");
        assert_eq!(payload["valid"], true);
        assert_eq!(payload["profile_count"], 2);
        assert_eq!(payload["profiles"], serde_json::json!(["default", "music"]));
    }

    #[test]
    fn config_validation_requires_an_existing_file() {
        let path = std::env::temp_dir().join(format!(
            "yt-downloader-absent-validation-{}-{}.json",
            std::process::id(),
            "nonexistent"
        ));
        let error = validate_config_path(&path).unwrap_err();
        assert!(matches!(error, ProfileStoreError::MissingFile));
    }

    #[test]
    fn config_validation_rejects_invalid_json() {
        let path = std::env::temp_dir().join(format!(
            "yt-downloader-invalid-validation-{}.json",
            std::process::id()
        ));
        std::fs::write(&path, "{invalid").unwrap();
        let result = validate_config_path(&path);
        let _ = std::fs::remove_file(&path);
        assert!(matches!(result, Err(ProfileStoreError::InvalidDocument(_))));
    }

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
    fn renders_python_style_profile_names_without_settings() {
        let profiles = [
            ListedProfile {
                name: "zeta".to_owned(),
                settings: Map::new(),
                parent: None,
            },
            ListedProfile {
                name: "Alpha".to_owned(),
                settings: Map::new(),
                parent: None,
            },
            ListedProfile {
                name: "beta".to_owned(),
                settings: Map::new(),
                parent: None,
            },
        ];

        assert_eq!(
            render_profile_listing(Path::new("defaults.json"), &profiles),
            "Available profiles in defaults.json:\n\n  Alpha\n  beta\n  zeta\n",
        );
    }

    #[test]
    fn sorts_non_ascii_names_by_unicode_lowercase() {
        let profiles = [
            ListedProfile {
                name: "zeta".to_owned(),
                settings: Map::new(),
                parent: None,
            },
            ListedProfile {
                name: "Éclair".to_owned(),
                settings: Map::new(),
                parent: None,
            },
            ListedProfile {
                name: "étude".to_owned(),
                settings: Map::new(),
                parent: None,
            },
            ListedProfile {
                name: "Alpha".to_owned(),
                settings: Map::new(),
                parent: None,
            },
        ];

        assert_eq!(
            render_profile_listing(Path::new("defaults.json"), &profiles),
            "Available profiles in defaults.json:\n\n  Alpha\n  zeta\n  Éclair\n  étude\n",
        );
    }

    #[test]
    fn preserves_original_spelling_when_lowercase_keys_match() {
        let profiles = [
            ListedProfile {
                name: "beta".to_owned(),
                settings: Map::new(),
                parent: None,
            },
            ListedProfile {
                name: "Beta".to_owned(),
                settings: Map::new(),
                parent: None,
            },
        ];

        assert_eq!(
            render_profile_listing(Path::new("defaults.json"), &profiles),
            "Available profiles in defaults.json:\n\n  beta\n  Beta\n",
        );
    }

    #[test]
    fn casefolds_sharp_s_and_ascii_equivalents() {
        let profiles = [
            ListedProfile {
                name: "zulu".to_owned(),
                settings: Map::new(),
                parent: None,
            },
            ListedProfile {
                name: "Straße".to_owned(),
                settings: Map::new(),
                parent: None,
            },
            ListedProfile {
                name: "strasse".to_owned(),
                settings: Map::new(),
                parent: None,
            },
            ListedProfile {
                name: "alpha".to_owned(),
                settings: Map::new(),
                parent: None,
            },
        ];

        assert_eq!(
            render_profile_listing(Path::new("defaults.json"), &profiles),
            "Available profiles in defaults.json:\\n\\n  alpha\\n  Straße\\n  strasse\\n  zulu\\n"
                .replace("\\n", "\n"),
        );
    }

    #[test]
    fn casefolds_greek_final_sigma_with_standard_sigma() {
        let profiles = [
            ListedProfile {
                name: "ος".to_owned(),
                settings: Map::new(),
                parent: None,
            },
            ListedProfile {
                name: "οσ".to_owned(),
                settings: Map::new(),
                parent: None,
            },
        ];

        assert_eq!(
            render_profile_listing(Path::new("defaults.json"), &profiles),
            "Available profiles in defaults.json:\\n\\n  ος\\n  οσ\\n".replace("\\n", "\n"),
        );
    }

    #[test]
    fn renders_python_style_empty_listing() {
        assert_eq!(
            render_profile_listing(Path::new("/example/defaults.json"), &[]),
            "No profiles are available in /example/defaults.json.\n",
        );
    }

    #[test]
    fn listing_presentation_rejects_non_listing_requests() {
        let options = crate::parse_profile_options(Vec::<std::ffi::OsString>::new()).unwrap();

        assert!(matches!(
            render_from_cli_store(&options, Path::new("/example")),
            Err(ProfileStoreError::ListingRequested),
        ));
    }

    #[test]
    fn listing_is_sorted_and_includes_inherited_effective_settings() {
        let document = json!({
            "version": 3,
            "profiles": {
                "zeta": {"parent": "alpha", "audio-quality": "128K"},
                "alpha": {"audio-format": "mp3"}
            }
        });
        let profiles = load_validated_profiles(&document.to_string()).unwrap();

        let listed = list_stored_profiles(&profiles);

        assert_eq!(
            listed
                .iter()
                .map(|profile| profile.name.as_str())
                .collect::<Vec<_>>(),
            vec!["alpha", "zeta"]
        );
        assert_eq!(listed[1].parent.as_deref(), Some("alpha"));
        assert_eq!(listed[1].settings["audio-format"], "mp3");
    }

    #[test]
    fn listing_an_absent_implicit_file_returns_no_profiles() {
        let directory = std::env::temp_dir().join(format!(
            "yt-downloader-list-absent-{}-{}",
            std::process::id(),
            NEXT_FILE.fetch_add(1, Ordering::Relaxed),
        ));
        let options = crate::parse_profile_options(
            ["--list-profiles"]
                .into_iter()
                .map(std::ffi::OsString::from),
        )
        .unwrap();

        assert!(
            list_from_cli_store(&options, &directory)
                .unwrap()
                .is_empty()
        );
    }

    #[test]
    fn listing_rejects_missing_explicit_defaults_file() {
        let path = temporary_file();
        let options = crate::parse_profile_options([
            std::ffi::OsString::from("--list-parameters"),
            std::ffi::OsString::from("--defaults"),
            path.into_os_string(),
        ])
        .unwrap();

        assert!(matches!(
            list_from_cli_store(&options, Path::new("/unused")),
            Err(ProfileStoreError::MissingFile)
        ));
    }

    #[test]
    fn describes_unknown_profile_without_debug_syntax() {
        let error = ProfileStoreError::Selection(ProfileSelectionError::UnknownProfile(
            "missing".to_owned(),
        ));

        assert_eq!(
            describe_store_error(&error, Path::new("defaults.json")),
            "unknown profile: missing",
        );
    }

    #[test]
    fn describes_invalid_effective_settings() {
        let error = ProfileStoreError::Selection(ProfileSelectionError::InvalidSettings(
            SettingError::ConflictingSettings("audio-quality requires audio-format".to_owned()),
        ));

        assert_eq!(
            describe_store_error(&error, Path::new("defaults.json")),
            "invalid effective profile settings: conflicting settings: audio-quality requires audio-format",
        );
    }

    #[test]
    fn describes_structural_document_errors_without_debug_syntax() {
        let error = ProfileStoreError::InvalidDocument(ProfilePipelineError::ProfileFile(
            ProfileFileError::UnknownRootKey("unexpected".to_owned()),
        ));

        assert_eq!(
            describe_store_error(&error, Path::new("custom.json")),
            "invalid defaults file custom.json: unknown root key: unexpected",
        );
    }

    #[test]
    fn describes_inheritance_cycles_with_the_full_chain() {
        let error = ProfileStoreError::InvalidDocument(ProfilePipelineError::ProfileFile(
            ProfileFileError::InheritanceCycle(vec![
                "first".to_owned(),
                "second".to_owned(),
                "first".to_owned(),
            ]),
        ));

        assert_eq!(
            describe_store_error(&error, Path::new("defaults.json")),
            "invalid defaults file defaults.json: profile inheritance cycle: first -> second -> first",
        );
    }

    #[test]
    fn describes_profile_validation_failures_with_the_profile_name() {
        let error = ProfileStoreError::InvalidDocument(ProfilePipelineError::Setting {
            profile: "child".to_owned(),
            error: SettingError::InvalidValue("audio-quality".to_owned()),
        });

        assert_eq!(
            describe_store_error(&error, Path::new("defaults.json")),
            "invalid defaults file defaults.json: profile 'child': invalid value for setting: audio-quality",
        );
    }

    #[test]
    fn explicit_profile_overrides_automatic_default_even_with_cli_settings() {
        let profiles = load_validated_profiles(
            &json!({
                "version": 3,
                "$defaults": {"playlist": true},
                "profiles": {
                    "default": {"audio-format": "mp3"},
                    "other": {"audio-format": "opus"}
                }
            })
            .to_string(),
        )
        .unwrap();
        let overrides = json!({"playlist": false});

        let selected =
            select_stored_profile(&profiles, Some("other"), overrides.as_object().unwrap())
                .unwrap();

        assert_eq!(selected.profile_name.as_deref(), Some("other"));
        assert_eq!(selected.settings["audio-format"], "opus");
        assert_eq!(selected.settings["playlist"], false);
        assert_eq!(selected.setting_sources["playlist"], "explicit override");
    }

    #[test]
    fn absent_default_does_not_select_an_arbitrary_stored_profile() {
        let profiles = load_validated_profiles(
            &json!({
                "version": 3,
                "profiles": {"other": {"playlist": true}}
            })
            .to_string(),
        )
        .unwrap();
        let overrides = json!({"playlist": false});

        let selected =
            select_stored_profile(&profiles, None, overrides.as_object().unwrap()).unwrap();

        assert_eq!(selected.profile_name, None);
        assert_eq!(selected.settings["playlist"], false);
        assert_eq!(selected.setting_sources["playlist"], "explicit override");
    }

    #[test]
    fn explicitly_requested_missing_profile_never_falls_back_to_default() {
        let profiles = load_validated_profiles(
            &json!({
                "version": 3,
                "profiles": {"default": {"playlist": true}}
            })
            .to_string(),
        )
        .unwrap();

        assert!(matches!(
            select_stored_profile(&profiles, Some("missing"), &Map::new()),
            Err(ProfileStoreError::Selection(ProfileSelectionError::UnknownProfile(name)))
                if name == "missing"
        ));
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
    fn diagnostics_identify_missing_explicit_file() {
        let path = Path::new("custom/defaults.json");
        assert_eq!(
            describe_store_error(&ProfileStoreError::MissingFile, path),
            "defaults file not found: custom/defaults.json",
        );
    }

    #[test]
    fn diagnostics_distinguish_invalid_documents_and_read_failures() {
        let path = Path::new("defaults.json");
        let invalid = ProfileStoreError::InvalidDocument(ProfilePipelineError::ProfileFile(
            crate::profile_file::ProfileFileError::InvalidJson,
        ));
        assert!(
            describe_store_error(&invalid, path).contains("invalid defaults file defaults.json")
        );

        let unreadable = ProfileStoreError::Read(io::Error::from(io::ErrorKind::PermissionDenied));
        assert!(
            describe_store_error(&unreadable, path)
                .contains("cannot read defaults file defaults.json")
        );
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
