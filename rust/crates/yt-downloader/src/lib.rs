//! A deliberately small, side-effect-free first slice of Downloader CLI parsing.
//! The Python application remains authoritative until feature parity is verified.

use std::ffi::{OsStr, OsString};

#[derive(Debug, PartialEq, Eq)]
pub struct ProfileOptions {
    pub profile: Option<OsString>,
    pub defaults: Option<OsString>,
    pub list_profiles: bool,
}

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
        && bytes.iter().all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
}

/// Parse the initial profile-related CLI subset without accessing files.
/// Other CLI options intentionally fail closed until their behaviour is ported.
pub fn parse_profile_options<I>(args: I) -> Result<ProfileOptions, ParseError>
where
    I: IntoIterator<Item = OsString>,
{
    let mut args = args.into_iter();
    let mut options = ProfileOptions {
        profile: None,
        defaults: None,
        list_profiles: false,
    };
    while let Some(arg) = args.next() {
        if arg == OsStr::new("-p") || arg == OsStr::new("--profile") || arg == OsStr::new("--parameter-profile") {
            let value = args.next().ok_or(ParseError::MissingValue("--profile"))?;
            let name = value.to_str().ok_or(ParseError::InvalidProfileName)?;
            if !valid_profile_name(name) {
                return Err(ParseError::InvalidProfileName);
            }
            options.profile = Some(value);
        } else if arg == OsStr::new("-d") || arg == OsStr::new("--defaults") {
            let value = args.next().ok_or(ParseError::MissingValue("--defaults"))?;
            options.defaults = Some(value);
        } else if arg == OsStr::new("--list-profiles") || arg == OsStr::new("--list-parameters") {
            options.list_profiles = true;
        } else {
            return Err(ParseError::UnsupportedOption);
        }
    }
    Ok(options)
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
        let options = parse(&["-p", "best", "--parameter-profile", "4k", "-d", "custom.json"]).unwrap();
        assert_eq!(options.profile, Some(OsString::from("4k")));
        assert_eq!(options.defaults, Some(OsString::from("custom.json")));
    }

    #[test]
    fn list_aliases() {
        assert!(parse(&["--list-parameters"]).unwrap().list_profiles);
        assert!(parse(&["--list-profiles"]).unwrap().list_profiles);
    }

    #[test]
    fn invalid_inputs_fail_closed() {
        assert_eq!(parse(&["--profile"]), Err(ParseError::MissingValue("--profile")));
        assert_eq!(parse(&["--defaults"]), Err(ParseError::MissingValue("--defaults")));
        assert_eq!(parse(&["-p", ".hidden"]), Err(ParseError::InvalidProfileName));
        assert_eq!(parse(&["--unknown"]), Err(ParseError::UnsupportedOption));
    }
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
        _ => (1, String::new(), "yt-download-rs: download functionality is not yet implemented; use yt-download.py\n".to_owned()),
    }
}
