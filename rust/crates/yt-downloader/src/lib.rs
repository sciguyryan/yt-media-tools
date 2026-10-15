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
        let setting = match argument.to_str() {
            Some("--playlist") => Some(("playlist", true)),
            Some("--no-playlist") => Some(("playlist", false)),
            Some("--audio-only") => Some(("audio-only", true)),
            Some("--no-audio-only") => Some(("audio-only", false)),
            Some("--embed-metadata") => Some(("embed-metadata", true)),
            Some("--no-embed-metadata") => Some(("embed-metadata", false)),
            Some("--embed-chapters") => Some(("embed-chapters", true)),
            Some("--no-embed-chapters") => Some(("embed-chapters", false)),
            Some("--embed-thumbnail") => Some(("embed-thumbnail", true)),
            Some("--no-embed-thumbnail") => Some(("embed-thumbnail", false)),
            _ => None,
        };

        if let Some((name, enabled)) = setting {
            overrides.insert(name.to_owned(), serde_json::Value::Bool(enabled));
        } else {
            remaining.push(argument.clone());
        }
    }

    (remaining, overrides)
}

/// Extract value-taking audio conversion options without consuming unrelated arguments.
///
/// A missing value is reported before Clap parses profile arguments. Explicit
/// audio conversion settings take precedence over the stored profile values.
pub fn extract_audio_overrides(
    args: &[OsString],
) -> Result<(Vec<OsString>, serde_json::Map<String, serde_json::Value>), ParseError> {
    let mut remaining = Vec::new();
    let mut overrides = serde_json::Map::new();
    let mut arguments = args.iter();

    while let Some(argument) = arguments.next() {
        let text = argument.to_str();
        let (name, inline_value) = match text {
            Some("--audio-format") => (Some("audio-format"), None),
            Some("--audio-quality") => (Some("audio-quality"), None),
            Some(value) if value.starts_with("--audio-format=") => {
                (Some("audio-format"), value.strip_prefix("--audio-format="))
            }
            Some(value) if value.starts_with("--audio-quality=") => (
                Some("audio-quality"),
                value.strip_prefix("--audio-quality="),
            ),
            _ => (None, None),
        };

        if let Some(name) = name {
            let option = if name == "audio-format" {
                "--audio-format"
            } else {
                "--audio-quality"
            };
            let value = match inline_value {
                Some(value) => value,
                None => {
                    let next = arguments.next().ok_or(ParseError::MissingValue(option))?;
                    next.to_str().ok_or(ParseError::UnsupportedOption)?
                }
            };

            if value.is_empty() || value.starts_with('-') {
                return Err(ParseError::MissingValue(option));
            }

            overrides.insert(name.to_owned(), serde_json::Value::String(value.to_owned()));
        } else {
            remaining.push(argument.clone());
        }
    }

    Ok((remaining, overrides))
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

            let (value_arguments, mut overrides) = match extract_audio_overrides(args) {
                Ok(result) => result,
                Err(error) => return (
                    1,
                    String::new(),
                    match error {
                        ParseError::MissingValue(option) => {
                            format!("yt-download-rs: missing value for {option}\n")
                        }
                        ParseError::InvalidProfileName => {
                            "yt-download-rs: invalid profile name\n".to_owned()
                        }
                        ParseError::UnsupportedOption => {
                            "yt-download-rs: unsupported or invalid arguments\n".to_owned()
                        }
                    },
                ),
            };
            let (profile_arguments, boolean_overrides) = extract_cli_overrides(&value_arguments);
            overrides.extend(boolean_overrides);
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
    fn thumbnail_overrides_are_independent_of_metadata_and_chapters() {
        let (remaining, overrides) = extract_cli_overrides(&[
            OsString::from("--embed-metadata"),
            OsString::from("--no-embed-thumbnail"),
            OsString::from("--embed-chapters"),
            OsString::from("--embed-thumbnail"),
        ]);

        assert!(remaining.is_empty());
        assert_eq!(overrides["embed-metadata"], true);
        assert_eq!(overrides["embed-chapters"], true);
        assert_eq!(overrides["embed-thumbnail"], true);
    }

    #[test]
    fn thumbnail_override_is_not_inferred_from_other_embedding_flags() {
        let (_, overrides) = extract_cli_overrides(&[
            OsString::from("--embed-metadata"),
            OsString::from("--no-embed-chapters"),
        ]);

        assert!(!overrides.contains_key("embed-thumbnail"));
    }

    #[test]
    fn thumbnail_override_cannot_be_combined_with_profile_listing() {
        let (status, stdout, stderr) = experimental_cli(&[
            OsString::from("--list-profiles"),
            OsString::from("--no-embed-thumbnail"),
        ]);

        assert_eq!(status, 1);
        assert!(stdout.is_empty());
        assert!(stderr.contains("cannot be combined"));
    }

    #[test]
    fn missing_audio_values_have_human_readable_diagnostics() {
        for (args, expected) in [
            (
                vec![OsString::from("--audio-format")],
                "yt-download-rs: missing value for --audio-format\n",
            ),
            (
                vec![
                    OsString::from("--audio-quality"),
                    OsString::from("--profile"),
                    OsString::from("example"),
                ],
                "yt-download-rs: missing value for --audio-quality\n",
            ),
        ] {
            let (status, stdout, stderr) = experimental_cli(&args);
            assert_eq!(status, 1);
            assert!(stdout.is_empty());
            assert_eq!(stderr, expected);
        }
    }

    #[test]
    fn invalid_audio_format_is_rejected_by_effective_policy_validation() {
        let (_, overrides) = extract_audio_overrides(&[
            OsString::from("--audio-format"),
            OsString::from("not-a-format"),
        ])
        .unwrap();

        let result = profile_store::select_stored_profile(
            &std::collections::BTreeMap::new(),
            None,
            &overrides,
        );

        assert!(matches!(
            result,
            Err(profile_store::ProfileStoreError::Selection(
                profile_selection::ProfileSelectionError::InvalidSettings(
                    profile_settings::SettingError::InvalidValue(name)
                )
            )) if name == "audio-format"
        ));
    }

    #[test]
    fn invalid_audio_quality_is_rejected_by_effective_policy_validation() {
        let (_, overrides) =
            extract_audio_overrides(&[OsString::from("--audio-quality=not-a-quality")]).unwrap();

        let result = profile_store::select_stored_profile(
            &std::collections::BTreeMap::new(),
            None,
            &overrides,
        );

        assert!(matches!(
            result,
            Err(profile_store::ProfileStoreError::Selection(
                profile_selection::ProfileSelectionError::InvalidSettings(
                    profile_settings::SettingError::InvalidValue(name)
                )
            )) if name == "audio-quality"
        ));
    }

    #[test]
    fn invalid_audio_values_have_exact_executable_diagnostics() {
        for (args, setting) in [
            (
                vec![OsString::from("--audio-format=not-a-format")],
                "audio-format",
            ),
            (
                vec![
                    OsString::from("--audio-quality"),
                    OsString::from("not-a-quality"),
                ],
                "audio-quality",
            ),
        ] {
            let (status, stdout, stderr) = experimental_cli(&args);

            assert_eq!(status, 1);
            assert!(stdout.is_empty());
            assert_eq!(
                stderr,
                format!(
                    "yt-download-rs: invalid effective profile settings: invalid value for setting: {setting}\n"
                ),
            );
        }
    }

    #[test]
    fn audio_option_boundaries_do_not_swallow_other_supported_flags() {
        for (option, following) in [
            ("--audio-format", "--no-playlist"),
            ("--audio-quality", "--embed-metadata"),
            ("--audio-format", "--profile=music"),
        ] {
            assert_eq!(
                extract_audio_overrides(&[OsString::from(option), OsString::from(following)]),
                Err(ParseError::MissingValue(option)),
            );
        }
    }

    #[test]
    fn audio_value_overrides_are_rejected_during_profile_listing() {
        let (status, stdout, stderr) = experimental_cli(&[
            OsString::from("--list-profiles"),
            OsString::from("--audio-format=flac"),
        ]);

        assert_eq!(status, 1);
        assert!(stdout.is_empty());
        assert_eq!(
            stderr,
            "yt-download-rs: download-setting overrides cannot be combined with profile listing\n",
        );
    }

    #[test]
    fn audio_equals_syntax_and_separate_values_share_precedence() {
        let (remaining, overrides) = extract_audio_overrides(&[
            OsString::from("--audio-format=mp3"),
            OsString::from("--audio-quality"),
            OsString::from("192K"),
            OsString::from("--audio-format"),
            OsString::from("flac"),
            OsString::from("--audio-quality=0"),
            OsString::from("--profile"),
            OsString::from("music"),
        ])
        .unwrap();

        assert_eq!(overrides["audio-format"], "flac");
        assert_eq!(overrides["audio-quality"], "0");
        assert_eq!(
            remaining,
            [OsString::from("--profile"), OsString::from("music")]
        );
    }

    #[test]
    fn audio_empty_inline_values_are_rejected() {
        for (argument, option) in [
            ("--audio-format=", "--audio-format"),
            ("--audio-quality=", "--audio-quality"),
        ] {
            assert_eq!(
                extract_audio_overrides(&[OsString::from(argument)]),
                Err(ParseError::MissingValue(option)),
            );
        }
    }

    #[test]
    fn audio_equals_values_do_not_swallow_unrelated_options() {
        let (remaining, overrides) = extract_audio_overrides(&[
            OsString::from("--audio-format=opus"),
            OsString::from("--unknown"),
        ])
        .unwrap();

        assert_eq!(overrides["audio-format"], "opus");
        assert_eq!(remaining, [OsString::from("--unknown")]);
    }

    #[test]
    fn audio_value_overrides_preserve_last_explicit_value() {
        let args = [
            OsString::from("--audio-format"),
            OsString::from("mp3"),
            OsString::from("--audio-quality"),
            OsString::from("192K"),
            OsString::from("--audio-format"),
            OsString::from("flac"),
            OsString::from("--profile"),
            OsString::from("example"),
        ];
        let (remaining, overrides) = extract_audio_overrides(&args).unwrap();

        assert_eq!(overrides["audio-format"], "flac");
        assert_eq!(overrides["audio-quality"], "192K");
        assert_eq!(
            remaining,
            [OsString::from("--profile"), OsString::from("example")]
        );
    }

    #[test]
    fn missing_audio_values_do_not_consume_following_flags() {
        assert_eq!(
            extract_audio_overrides(&[OsString::from("--audio-format")]),
            Err(ParseError::MissingValue("--audio-format")),
        );
        assert_eq!(
            extract_audio_overrides(&[
                OsString::from("--audio-quality"),
                OsString::from("--profile"),
                OsString::from("example"),
            ]),
            Err(ParseError::MissingValue("--audio-quality")),
        );
    }

    #[test]
    fn unknown_options_remain_for_profile_argument_rejection() {
        let (remaining, overrides) = extract_audio_overrides(&[
            OsString::from("--audio-format"),
            OsString::from("opus"),
            OsString::from("--unknown"),
        ])
        .unwrap();

        assert_eq!(overrides["audio-format"], "opus");
        assert_eq!(remaining, [OsString::from("--unknown")]);
    }

    #[test]
    fn every_boolean_override_pair_preserves_explicit_false() {
        for (enabled, disabled, name) in [
            ("--playlist", "--no-playlist", "playlist"),
            ("--audio-only", "--no-audio-only", "audio-only"),
            ("--embed-metadata", "--no-embed-metadata", "embed-metadata"),
            ("--embed-chapters", "--no-embed-chapters", "embed-chapters"),
            (
                "--embed-thumbnail",
                "--no-embed-thumbnail",
                "embed-thumbnail",
            ),
        ] {
            let (remaining, overrides) =
                extract_cli_overrides(&[OsString::from(enabled), OsString::from(disabled)]);

            assert!(remaining.is_empty());
            assert_eq!(overrides.len(), 1);
            assert_eq!(overrides[name], false, "{name}");

            let (_, reversed) =
                extract_cli_overrides(&[OsString::from(disabled), OsString::from(enabled)]);
            assert_eq!(reversed[name], true, "{name}");
        }
    }

    #[test]
    fn unsupported_options_are_not_silently_consumed() {
        let args = [
            OsString::from("--embed-thumbnail"),
            OsString::from("--no-embed-metadata"),
            OsString::from("--unknown"),
        ];
        let (remaining, overrides) = extract_cli_overrides(&args);

        assert_eq!(remaining, [OsString::from("--unknown")],);
        assert_eq!(overrides["embed-thumbnail"], true);
        assert_eq!(overrides["embed-metadata"], false);
        assert_eq!(
            parse_profile_options(remaining),
            Err(ParseError::UnsupportedOption),
        );
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
