//! Resolve the source of download targets without starting yt-dlp.
//!
//! Resolution follows the Python Downloader's precedence and ambiguity rules.
//! Collection manifests are deliberately not interpreted here: they require
//! the separate collection interchange contract.

use std::path::{Path, PathBuf};

/// A validated source of targets for a future execution plan.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TargetSource {
    /// An existing file passed to yt-dlp with `--batch-file`.
    BatchFile(PathBuf),
    /// Targets read by yt-dlp from standard input.
    Stdin,
    /// Positional targets preserved in their original order.
    Direct(Vec<String>),
}

impl TargetSource {
    /// Append the target-specific arguments to an existing yt-dlp argument vector.
    pub fn append_arguments(&self, arguments: &mut Vec<String>) {
        match self {
            Self::BatchFile(path) => {
                arguments.push("--batch-file".to_owned());
                arguments.push(path.to_string_lossy().into_owned());
            }
            Self::Stdin => {
                arguments.push("--batch-file".to_owned());
                arguments.push("-".to_owned());
            }
            Self::Direct(targets) => {
                arguments.push("--".to_owned());
                arguments.extend(targets.iter().cloned());
            }
        }
    }
}

/// Inputs to target resolution, independent of CLI parsing and profile loading.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TargetRequest {
    /// Positional target arguments, without normalisation or deduplication.
    pub targets: Vec<String>,
    /// Explicit batch file, if supplied.
    pub input_file: Option<PathBuf>,
    /// Explicit collection manifest, if supplied.
    pub collection_file: Option<PathBuf>,
    /// Default batch file used when no target source is specified.
    pub default_input_file: PathBuf,
}

/// Target-resolution failures which must not be silently converted to direct URLs.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TargetError {
    /// A collection manifest needs its dedicated parser.
    CollectionRequiresResolver,
    /// An explicit input source conflicts with positional targets.
    ConflictingSources(&'static str),
    /// The standard-input marker cannot accompany other targets.
    MixedStdin,
    /// A batch file does not exist or is not a regular file.
    MissingInputFile(PathBuf),
}

/// Resolve a request using the Python Downloader's source precedence.
///
/// The filesystem is inspected only to distinguish an existing single-target
/// file from a direct target and to validate batch-file sources. This function
/// does not read target contents or launch any process.
pub fn resolve_targets(request: &TargetRequest) -> Result<TargetSource, TargetError> {
    if request.collection_file.is_some() {
        if request.input_file.is_some() || !request.targets.is_empty() {
            return Err(TargetError::ConflictingSources("--collection-file"));
        }
        return Err(TargetError::CollectionRequiresResolver);
    }

    if let Some(path) = &request.input_file {
        if !request.targets.is_empty() {
            return Err(TargetError::ConflictingSources("--input-file"));
        }
        return batch_file(path);
    }

    if request.targets.is_empty() {
        return batch_file(&request.default_input_file);
    }

    if request.targets.iter().any(|target| target == "-") {
        return if request.targets.len() == 1 {
            Ok(TargetSource::Stdin)
        } else {
            Err(TargetError::MixedStdin)
        };
    }

    if request.targets.len() == 1 {
        let path = expand_home(Path::new(&request.targets[0]));
        if path.is_file() {
            return batch_file(&path);
        }
    }

    Ok(TargetSource::Direct(request.targets.clone()))
}

fn batch_file(path: &Path) -> Result<TargetSource, TargetError> {
    let expanded = expand_home(path);
    if !expanded.is_file() {
        return Err(TargetError::MissingInputFile(expanded));
    }
    Ok(TargetSource::BatchFile(expanded))
}

fn expand_home(path: &Path) -> PathBuf {
    let text = path.to_string_lossy();
    if text == "~" {
        return home::home_dir().unwrap_or_else(|| path.to_path_buf());
    }
    if let Some(suffix) = text.strip_prefix("~/") {
        return home::home_dir().map_or_else(|| path.to_path_buf(), |home| home.join(suffix));
    }
    path.to_path_buf()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn request(targets: &[&str]) -> TargetRequest {
        TargetRequest {
            targets: targets.iter().map(|value| (*value).to_owned()).collect(),
            input_file: None,
            collection_file: None,
            default_input_file: PathBuf::from("/nonexistent-yt-downloader-default-batch"),
        }
    }

    #[test]
    fn direct_targets_preserve_order_duplicates_and_dash_prefixes() {
        let source = resolve_targets(&request(&["url:b", "url:a", "url:b", "--unusual"])).unwrap();
        let mut args = vec!["yt-dlp-option".to_owned()];
        source.append_arguments(&mut args);
        assert_eq!(
            args,
            [
                "yt-dlp-option",
                "--",
                "url:b",
                "url:a",
                "url:b",
                "--unusual"
            ]
        );
    }

    #[test]
    fn stdin_is_exclusive() {
        assert_eq!(resolve_targets(&request(&["-"])), Ok(TargetSource::Stdin));
        assert_eq!(
            resolve_targets(&request(&["-", "other"])),
            Err(TargetError::MixedStdin)
        );
        let mut args = Vec::new();
        TargetSource::Stdin.append_arguments(&mut args);
        assert_eq!(args, ["--batch-file", "-"]);
    }

    #[test]
    fn explicit_sources_reject_positional_targets() {
        let mut value = request(&["video"]);
        value.input_file = Some(PathBuf::from("anything"));
        assert_eq!(
            resolve_targets(&value),
            Err(TargetError::ConflictingSources("--input-file"))
        );
        value.collection_file = Some(PathBuf::from("collection.json"));
        assert_eq!(
            resolve_targets(&value),
            Err(TargetError::ConflictingSources("--collection-file"))
        );
    }

    #[test]
    fn collections_require_a_dedicated_resolver() {
        let mut value = request(&[]);
        value.collection_file = Some(PathBuf::from("collection.json"));
        assert_eq!(
            resolve_targets(&value),
            Err(TargetError::CollectionRequiresResolver)
        );
    }

    #[test]
    fn missing_batch_files_are_rejected() {
        assert!(matches!(
            resolve_targets(&request(&[])),
            Err(TargetError::MissingInputFile(_))
        ));
    }

    #[test]
    fn single_existing_file_is_a_batch_source() {
        let path = std::env::current_exe().unwrap();
        let mut value = request(&[path.to_str().unwrap()]);
        assert_eq!(
            resolve_targets(&value),
            Ok(TargetSource::BatchFile(path.clone()))
        );
        value.targets.clear();
        value.input_file = Some(path.clone());
        assert_eq!(resolve_targets(&value), Ok(TargetSource::BatchFile(path)));
    }

    #[test]
    fn nonexistent_single_path_is_a_direct_target() {
        assert_eq!(
            resolve_targets(&request(&["nonexistent-video-target"])),
            Ok(TargetSource::Direct(vec![
                "nonexistent-video-target".to_owned()
            ]))
        );
    }
}
