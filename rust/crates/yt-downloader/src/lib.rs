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

            let options = match parse_profile_options(args.iter().cloned()) {
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

            // Validate stored policy before reporting unavailable download execution.
            // CLI setting overrides are not yet connected.
            match profile_store::select_from_cli_store(
                &options,
                &executable_dir,
                &serde_json::Map::new(),
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
