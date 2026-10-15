//! Placeholder for the native Downloader implementation.

pub mod profile_file;
pub mod profile_pipeline;
pub mod profile_selection;
pub mod profile_settings;
pub mod profile_store;

use std::ffi::OsString;

/// Profile-related arguments recognised by the native CLI.
#[derive(Debug, PartialEq, Eq)]
pub struct ProfileOptions {
    /// Last selected profile name, if supplied.
    pub profile: Option<OsString>,
    /// Last defaults selection, if supplied.
    pub defaults: Option<OsString>,
    /// Whether the caller requested a listing of available profiles.
    pub list_profiles: bool,
}

/// Errors returned while parsing profile-related CLI arguments.
#[derive(Debug, PartialEq, Eq)]
pub enum ParseError {
    MissingValue(&'static str),
    InvalidProfileName,
    UnsupportedOption,
}

pub fn valid_profile_name(name: &str) -> bool {
    let bytes = name.as_bytes();
    !bytes.is_empty()
        && bytes[0].is_ascii_alphanumeric()
        && bytes
            .iter()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
}

/// Parse the initial profile-related CLI subset without accessing files.
/// Other CLI options intentionally fail closed until their behaviour is ported.
pub fn parse_profile_options<I>(args: I) -> Result<ProfileOptions, ParseError>
where
    I: IntoIterator<Item = OsString>,
{
    use clap::{Arg, ArgAction, Command};

    // Clap handles tokenisation and aliases. The Python-specific profile name
    // restriction remains a separate validation step.
    let command = Command::new("yt-download-rs")
        .disable_help_flag(true)
        .disable_version_flag(true)
        .arg(
            Arg::new("profile")
                .short('p')
                .long("profile")
                .visible_alias("parameter-profile")
                .num_args(1)
                .action(ArgAction::Append),
        )
        .arg(
            Arg::new("defaults")
                .short('d')
                .long("defaults")
                .num_args(1)
                .action(ArgAction::Append),
        )
        .arg(
            Arg::new("list-profiles")
                .long("list-profiles")
                .visible_alias("list-parameters")
                .action(ArgAction::SetTrue),
        );

    let arguments: Vec<OsString> = args.into_iter().collect();
    // Clap reports a missing trailing value as InvalidValue in some releases.
    // Keep the option identity before asking Clap to parse the arguments.
    if let Some(last) = arguments.last() {
        let missing = match last.to_str() {
            Some("-p" | "--profile" | "--parameter-profile") => Some("--profile"),
            Some("-d" | "--defaults") => Some("--defaults"),
            _ => None,
        };
        if let Some(option) = missing {
            return Err(ParseError::MissingValue(option));
        }
    }

    let input = std::iter::once(OsString::from("yt-download-rs")).chain(arguments);
    let matches = command.try_get_matches_from(input).map_err(|error| {
        use clap::error::ErrorKind;
        match error.kind() {
            ErrorKind::InvalidValue | ErrorKind::ValueValidation => ParseError::InvalidProfileName,
            _ => ParseError::UnsupportedOption,
        }
    })?;

    let profile = matches
        .get_many::<String>("profile")
        .and_then(|mut values| values.next_back())
        .map(OsString::from);
    if let Some(ref name) = profile
        && !name.to_str().is_some_and(valid_profile_name)
    {
        return Err(ParseError::InvalidProfileName);
    }

    let defaults = matches
        .get_many::<String>("defaults")
        .and_then(|mut values| values.next_back())
        .map(OsString::from);

    Ok(ProfileOptions {
        profile,
        defaults,
        list_profiles: matches.get_flag("list-profiles"),
    })
}

/// Separate the first supported download-setting overrides from profile options.
///
/// Python argparse honours the last occurrence of the mutually exclusive
/// boolean flags. Other settings remain unsupported until their exact CLI
/// syntax and precedence have been reviewed.
pub fn extract_cli_overrides(
    args: &[OsString],
) -> (Vec<OsString>, serde_json::Map<String, serde_json::Value>) {
    let mut remaining = Vec::new();
    let mut overrides = serde_json::Map::new();

    for argument in args {
        match argument.to_str() {
            Some("--playlist") => {
                overrides.insert("playlist".to_owned(), serde_json::Value::Bool(true));
            }
            Some("--no-playlist") => {
                overrides.insert("playlist".to_owned(), serde_json::Value::Bool(false));
            }
            Some("--audio-only") => {
                overrides.insert("audio-only".to_owned(), serde_json::Value::Bool(true));
            }
            Some("--no-audio-only") => {
                overrides.insert("audio-only".to_owned(), serde_json::Value::Bool(false));
            }
            Some("--embed-metadata") => {
                overrides.insert("embed-metadata".to_owned(), serde_json::Value::Bool(true));
            }
            Some("--no-embed-metadata") => {
                overrides.insert("embed-metadata".to_owned(), serde_json::Value::Bool(false));
            }
            Some("--embed-chapters") => {
                overrides.insert("embed-chapters".to_owned(), serde_json::Value::Bool(true));
            }
            Some("--no-embed-chapters") => {
                overrides.insert("embed-chapters".to_owned(), serde_json::Value::Bool(false));
            }
            _ => remaining.push(argument.clone()),
        }
    }

    (remaining, overrides)
}

/// The current experimental CLI responses, kept pure for deterministic testing.
/// The executable prints these responses and uses their exit status.
pub fn experimental_cli(args: &[OsString]) -> (u8, String, String) {
    match args {
        [arg] if arg == "--version" => (0, format!("yt-download-rs {}\n", env!("CARGO_PKG_VERSION")), String::new()),
        [arg] if arg == "--help" || arg == "-h" => (
            0,
            "yt-download-rs (experimental)\n\nUSAGE:\n    yt-download-rs [--help | --version]\n\nThe native downloader is under development. Use yt-download.py for downloads.\n".to_owned(),
            String::new(),
        ),
        _ => {
            // A positional download target is recognised but cannot be handled
            // until native download execution is implemented.
            if args.len() == 1 && args[0].to_str().is_some_and(|arg| !arg.starts_with('-')) {
                return (
                    1,
                    String::new(),
                    "yt-download-rs: download functionality is not yet implemented; use yt-download.py\n".to_owned(),
                );
            }

            let (profile_arguments, overrides) = extract_cli_overrides(args);
            let options = match parse_profile_options(profile_arguments) {
                Ok(options) => options,
                Err(_) => return (1, String::new(), "yt-download-rs: unsupported or invalid arguments\n".to_owned()),
            };

            let executable_dir = match std::env::current_exe()
                .ok()
                .and_then(|path| path.parent().map(std::path::Path::to_path_buf))
            {
                Some(path) => path,
                None => return (1, String::new(), "yt-download-rs: cannot determine executable directory\n".to_owned()),
            };

            if options.list_profiles && !overrides.is_empty() {
                return (
                    1,
                    String::new(),
                    "yt-download-rs: download-setting overrides cannot be combined with profile listing\n".to_owned(),
                );
            }

            if options.list_profiles {
                return match profile_store::render_from_cli_store(&options, &executable_dir) {
                    Ok(output) => (0, output, String::new()),
                    Err(error) => {
                        let (path, _) = profile_store::resolve_defaults_path(&options, &executable_dir);
                        let diagnostic = profile_store::describe_store_error(&error, &path);
                        (1, String::new(), format!("yt-download-rs: {diagnostic}\n"))
                    },
                };
            }

            // Apply explicitly supplied download settings over the stored profile
            // before reporting that native download execution is unavailable.
            match profile_store::select_from_cli_store(
                &options,
                &executable_dir,
                &overrides,
            ) {
                Ok(_) => (
                    1,
                    String::new(),
                    "yt-download-rs: download functionality is not yet implemented; use yt-download.py\n".to_owned(),
                ),
                Err(error) => {
                    let (path, _) = profile_store::resolve_defaults_path(&options, &executable_dir);
                    let diagnostic = profile_store::describe_store_error(&error, &path);
                    (1, String::new(), format!("yt-download-rs: {diagnostic}\n"))
                },
            }
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse(args: &[&str]) -> Result<ProfileOptions, ParseError> {
        parse_profile_options(args.iter().map(OsString::from))
    }

    #[test]
    fn accepted_names_match_the_python_pattern() {
        for name in ["a", "4k", "a.b", "A_b-c", "9"] {
            assert!(valid_profile_name(name), "{name}");
        }
        for name in ["", ".hidden", "-bad", "a/b", "a b", "é", "x\\ny"] {
            assert!(!valid_profile_name(name), "{name:?}");
        }
    }

    #[test]
    fn profile_aliases_and_last_value_win() {
        let options = parse(&[
            "-p",
            "best",
            "--parameter-profile",
            "4k",
            "-d",
            "custom.json",
        ])
        .unwrap();
        assert_eq!(options.profile, Some(OsString::from("4k")));
        assert_eq!(options.defaults, Some(OsString::from("custom.json")));
    }

    #[test]
    fn list_aliases() {
        assert!(parse(&["--list-parameters"]).unwrap().list_profiles);
        assert!(parse(&["--list-profiles"]).unwrap().list_profiles);
    }

    #[test]
    fn embedding_overrides_follow_last_explicit_flag() {
        let args = [
            OsString::from("--no-embed-metadata"),
            OsString::from("--embed-metadata"),
            OsString::from("--embed-chapters"),
            OsString::from("--no-embed-chapters"),
            OsString::from("--profile"),
            OsString::from("example"),
        ];
        let (remaining, overrides) = extract_cli_overrides(&args);

        assert_eq!(overrides["embed-metadata"], true);
        assert_eq!(overrides["embed-chapters"], false);
        assert_eq!(
            remaining,
            [OsString::from("--profile"), OsString::from("example")],
        );
    }

    #[test]
    fn omitted_embedding_flags_do_not_override_profile_values() {
        let (_, overrides) = extract_cli_overrides(&[OsString::from("--no-playlist")]);

        assert!(!overrides.contains_key("embed-metadata"));
        assert!(!overrides.contains_key("embed-chapters"));
    }

    #[test]
    fn embedding_flags_cannot_be_combined_with_profile_listing() {
        let (status, stdout, stderr) = experimental_cli(&[
            OsString::from("--list-profiles"),
            OsString::from("--embed-metadata"),
        ]);

        assert_eq!(status, 1);
        assert!(stdout.is_empty());
        assert!(stderr.contains("cannot be combined"));
        assert!(stderr.ends_with('\n'));
    }

    #[test]
    fn embedding_overrides_preserve_unavailable_download_boundary() {
        let (status, stdout, stderr) = experimental_cli(&[
            OsString::from("--no-embed-metadata"),
            OsString::from("--embed-chapters"),
        ]);

        assert_eq!(status, 1);
        assert!(stdout.is_empty());
        assert!(stderr.contains("not yet implemented"));
    }

    #[test]
    fn audio_only_overrides_follow_last_explicit_flag() {
        let args = [
            OsString::from("--audio-only"),
            OsString::from("--no-audio-only"),
            OsString::from("--audio-only"),
            OsString::from("--profile"),
            OsString::from("example"),
        ];
        let (remaining, overrides) = extract_cli_overrides(&args);

        assert_eq!(overrides["audio-only"], true);
        assert_eq!(
            remaining,
            [OsString::from("--profile"), OsString::from("example")],
        );
    }

    #[test]
    fn audio_only_is_not_overridden_when_unspecified() {
        let (remaining, overrides) =
            extract_cli_overrides(&[OsString::from("--profile"), OsString::from("example")]);

        assert_eq!(remaining.len(), 2);
        assert!(!overrides.contains_key("audio-only"));
    }

    #[test]
    fn executable_rejects_audio_only_override_during_listing() {
        let (status, stdout, stderr) = experimental_cli(&[
            OsString::from("--list-profiles"),
            OsString::from("--audio-only"),
        ]);

        assert_eq!(status, 1);
        assert!(stdout.is_empty());
        assert!(stderr.contains("cannot be combined"));
    }

    #[test]
    fn executable_accepts_audio_only_override_without_download_execution() {
        let (status, stdout, stderr) = experimental_cli(&[OsString::from("--no-audio-only")]);

        assert_eq!(status, 1);
        assert!(stdout.is_empty());
        assert!(stderr.contains("not yet implemented"));
    }

    #[test]
    fn playlist_overrides_follow_last_explicit_flag() {
        let args = [
            OsString::from("--playlist"),
            OsString::from("--no-playlist"),
            OsString::from("--playlist"),
            OsString::from("--profile"),
            OsString::from("example"),
        ];
        let (remaining, overrides) = extract_cli_overrides(&args);

        assert_eq!(overrides["playlist"], true);
        assert_eq!(
            remaining,
            [OsString::from("--profile"), OsString::from("example")],
        );
    }

    #[test]
    fn playlist_override_is_not_inferred_when_omitted() {
        let (remaining, overrides) =
            extract_cli_overrides(&[OsString::from("--profile"), OsString::from("example")]);

        assert_eq!(remaining.len(), 2);
        assert!(overrides.is_empty());
    }

    #[test]
    fn executable_rejects_listing_with_playlist_override() {
        let (status, stdout, stderr) = experimental_cli(&[
            OsString::from("--list-profiles"),
            OsString::from("--no-playlist"),
        ]);

        assert_eq!(status, 1);
        assert!(stdout.is_empty());
        assert!(stderr.contains("cannot be combined"));
    }

    #[test]
    fn executable_accepts_playlist_override_without_enabling_downloads() {
        let (status, stdout, stderr) = experimental_cli(&[OsString::from("--no-playlist")]);

        assert_eq!(status, 1);
        assert!(stdout.is_empty());
        assert!(stderr.contains("not yet implemented"));
    }

    #[test]
    fn executable_lists_absent_implicit_profiles() {
        // The binary's implicit defaults file is environment-dependent, so
        // test a missing explicit file instead for a deterministic failure.
        let path = std::env::temp_dir().join(format!(
            "yt-download-rs-missing-list-{}-{}.json",
            std::process::id(),
            "not-created",
        ));
        let args = [
            OsString::from("--list-profiles"),
            OsString::from("--defaults"),
            path.into_os_string(),
        ];
        let (status, stdout, stderr) = experimental_cli(&args);

        assert_eq!(status, 1);
        assert!(stdout.is_empty());
        assert!(stderr.contains("defaults file not found:"));
    }

    #[test]
    fn executable_reports_missing_explicit_defaults_before_download_boundary() {
        let path = std::env::temp_dir().join(format!(
            "yt-download-rs-selection-missing-{}-never-created.json",
            std::process::id(),
        ));
        let args = [
            OsString::from("--profile"),
            OsString::from("missing"),
            OsString::from("--defaults"),
            path.into_os_string(),
        ];

        let (status, stdout, stderr) = experimental_cli(&args);

        assert_eq!(status, 1);
        assert!(stdout.is_empty());
        assert!(stderr.contains("defaults file not found:"));
        assert!(!stderr.contains("not yet implemented"));
    }

    #[test]
    fn store_selection_rejects_unknown_profile_without_implicit_fallback() {
        let options =
            parse_profile_options([OsString::from("--profile"), OsString::from("missing")])
                .unwrap();
        let directory = std::env::temp_dir().join(format!(
            "yt-download-rs-selection-absent-{}",
            std::process::id(),
        ));

        let result =
            profile_store::select_from_cli_store(&options, &directory, &serde_json::Map::new());

        assert!(matches!(
            result,
            Err(profile_store::ProfileStoreError::Selection(
                profile_selection::ProfileSelectionError::UnknownProfile(name)
            )) if name == "missing"
        ));
    }

    #[test]
    fn positional_download_target_fails_as_unimplemented() {
        let (status, stdout, stderr) =
            experimental_cli(&[OsString::from("https://example.invalid/video")]);

        assert_eq!(status, 1);
        assert!(stdout.is_empty());
        assert!(stderr.contains("not yet implemented"));
    }

    #[test]
    fn executable_does_not_claim_download_support() {
        let (status, stdout, stderr) = experimental_cli(&[]);

        assert_eq!(status, 1);
        assert!(stdout.is_empty());
        assert!(stderr.contains("not yet implemented"));
    }

    #[test]
    fn invalid_inputs_fail_closed() {
        assert_eq!(
            parse(&["--profile"]),
            Err(ParseError::MissingValue("--profile"))
        );
        assert_eq!(
            parse(&["--defaults"]),
            Err(ParseError::MissingValue("--defaults"))
        );
        assert_eq!(parse(&["-p"]), Err(ParseError::MissingValue("--profile")));
        assert_eq!(
            parse(&["--parameter-profile"]),
            Err(ParseError::MissingValue("--profile"))
        );
        assert_eq!(parse(&["-d"]), Err(ParseError::MissingValue("--defaults")));
        assert_eq!(
            parse(&["-p", ".hidden"]),
            Err(ParseError::InvalidProfileName)
        );
        assert_eq!(parse(&["--unknown"]), Err(ParseError::UnsupportedOption));
    }
}
