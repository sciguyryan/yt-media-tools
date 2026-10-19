//! Bounded yt-dlp metadata decoding without acquisition side effects.
//!
//! This module recognises a deliberately small stable subset of the JSON
//! returned by `--dump-single-json`. It does not infer download policy from
//! metadata, and it never retains arbitrary provider fields or raw output.

use serde_json::Value;

/// Maximum metadata document accepted by the native adapter (8 MiB).
pub const MAX_METADATA_BYTES: usize = 8 * 1024 * 1024;

/// A minimal, validated media identity for subsequent acquisition planning.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MediaMetadata {
    /// Extractor-defined media identifier.
    pub id: String,
    /// Optional human-readable title.
    pub title: Option<String>,
    /// Duration in whole seconds, when known.
    pub duration_seconds: Option<u64>,
    /// Extractor name when supplied.
    pub extractor: Option<String>,
}

/// Failure categories do not contain raw metadata or sensitive URLs.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MetadataError {
    /// The input exceeds the configured resource boundary.
    TooLarge,
    /// The output is not one valid JSON document.
    InvalidJson,
    /// The result is not a single video-like metadata record.
    UnsupportedRecord,
    /// A required identity is absent or malformed.
    InvalidIdentity,
    /// A recognised optional field has an invalid type or value.
    InvalidField,
}

/// Decode one complete metadata document without retaining unknown fields.
///
/// Playlist and collection results are rejected rather than silently
/// selecting the first entry or claiming single-item equivalence.
pub fn decode_metadata(bytes: &[u8]) -> Result<MediaMetadata, MetadataError> {
    if bytes.len() > MAX_METADATA_BYTES {
        return Err(MetadataError::TooLarge);
    }
    let value: Value = serde_json::from_slice(bytes).map_err(|_| MetadataError::InvalidJson)?;
    let object = value.as_object().ok_or(MetadataError::UnsupportedRecord)?;
    if object.contains_key("entries")
        || object
            .get("_type")
            .and_then(Value::as_str)
            .is_some_and(|kind| kind != "video")
    {
        return Err(MetadataError::UnsupportedRecord);
    }
    let id = object
        .get("id")
        .and_then(Value::as_str)
        .filter(|id| !id.trim().is_empty() && id.len() <= 4096)
        .ok_or(MetadataError::InvalidIdentity)?;
    let title = optional_text(object.get("title"))?;
    let extractor = optional_text(object.get("extractor"))?;
    let duration_seconds = match object.get("duration") {
        None | Some(Value::Null) => None,
        Some(value) => {
            let duration = value.as_u64().ok_or(MetadataError::InvalidField)?;
            Some(duration)
        }
    };
    Ok(MediaMetadata {
        id: id.to_owned(),
        title,
        duration_seconds,
        extractor,
    })
}

fn optional_text(value: Option<&Value>) -> Result<Option<String>, MetadataError> {
    match value {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(text)) if text.len() <= 4096 => Ok(Some(text.clone())),
        _ => Err(MetadataError::InvalidField),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn decodes_known_fields_without_retaining_provider_payloads() {
        let record = decode_metadata(br#"{"id":"abc","title":"Example","duration":42,"extractor":"youtube","webpage_url":"https://secret.example/"}"#).unwrap();
        assert_eq!(
            record,
            MediaMetadata {
                id: "abc".into(),
                title: Some("Example".into()),
                duration_seconds: Some(42),
                extractor: Some("youtube".into())
            }
        );
    }

    #[test]
    fn accepts_missing_optional_values() {
        let record = decode_metadata(br#"{"id":"abc","title":null,"duration":null}"#).unwrap();
        assert_eq!(record.duration_seconds, None);
        assert_eq!(record.title, None);
    }

    #[test]
    fn rejects_collection_and_malformed_records() {
        assert_eq!(
            decode_metadata(br#"{"_type":"playlist","id":"p","entries":[]}"#),
            Err(MetadataError::UnsupportedRecord)
        );
        assert_eq!(
            decode_metadata(br#"{"id":" "}"#),
            Err(MetadataError::InvalidIdentity)
        );
        assert_eq!(
            decode_metadata(br#"{"id":"x","duration":-1}"#),
            Err(MetadataError::InvalidField)
        );
        assert_eq!(
            decode_metadata(br#"{"id":"x","title":12}"#),
            Err(MetadataError::InvalidField)
        );
        assert_eq!(
            decode_metadata(b"not json"),
            Err(MetadataError::InvalidJson)
        );
    }

    #[test]
    fn enforces_bounded_document_size() {
        assert_eq!(
            decode_metadata(&vec![b' '; MAX_METADATA_BYTES + 1]),
            Err(MetadataError::TooLarge)
        );
    }
}

/// Errors from an explicitly requested yt-dlp metadata acquisition.
#[derive(Debug)]
pub enum AcquisitionError {
    /// The selected executable or child process could not be used.
    Io(std::io::Error),
    /// yt-dlp reported an unsuccessful exit without exposing its raw output.
    ProcessFailed,
    /// The process returned metadata that failed the bounded contract.
    Metadata(MetadataError),
    /// The caller supplied an empty target or working directory.
    InvalidConfiguration,
    /// The child or its output pipe exceeded the acquisition deadline.
    TimedOut,
    /// The output reader stopped without returning a result.
    ReaderFailed,
}

/// Default wall-clock limit for a single metadata acquisition.
pub const DEFAULT_ACQUISITION_DEADLINE: std::time::Duration = std::time::Duration::from_secs(30);

/// Acquire one record with the default deadline.
pub fn acquire_metadata(
    executable: &std::path::Path,
    working_directory: &std::path::Path,
    target: &str,
) -> Result<MediaMetadata, AcquisitionError> {
    acquire_metadata_with_deadline(
        executable,
        working_directory,
        target,
        DEFAULT_ACQUISITION_DEADLINE,
    )
}

/// Acquire one metadata record within a caller-specified wall-clock deadline.
///
/// Output is read on a dedicated thread so a stalled child or inherited pipe
/// cannot indefinitely block the calling thread. On timeout the direct child
/// is killed and reaped. A descendant retaining stdout can keep the detached
/// reader alive; process-group cleanup is outside this API's current contract.
/// No raw standard error, provider output or target is included in errors.
pub fn acquire_metadata_with_deadline(
    executable: &std::path::Path,
    working_directory: &std::path::Path,
    target: &str,
    deadline: std::time::Duration,
) -> Result<MediaMetadata, AcquisitionError> {
    use std::io::Read;
    use std::process::{Command, Stdio};
    use std::sync::mpsc;

    if executable.as_os_str().is_empty()
        || working_directory.as_os_str().is_empty()
        || target.trim().is_empty()
        || target.contains('\0')
        || deadline.is_zero()
    {
        return Err(AcquisitionError::InvalidConfiguration);
    }
    let mut child = Command::new(executable)
        .current_dir(working_directory)
        .args([
            "--ignore-config",
            "--no-playlist",
            "--dump-single-json",
            "--",
            target,
        ])
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(AcquisitionError::Io)?;

    let stdout = child.stdout.take().expect("stdout was explicitly piped");
    let (sender, receiver) = mpsc::sync_channel(1);
    let reader = std::thread::spawn(move || {
        let mut output = Vec::new();
        let result = stdout
            .take(MAX_METADATA_BYTES as u64 + 1)
            .read_to_end(&mut output);
        let _ = sender.send(result.map(|_| output));
    });
    let started = std::time::Instant::now();
    let output = match receiver.recv_timeout(deadline) {
        Ok(Ok(output)) => output,
        Ok(Err(error)) => {
            let _ = child.kill();
            let _ = child.wait();
            let _ = reader.join();
            return Err(AcquisitionError::Io(error));
        }
        Err(mpsc::RecvTimeoutError::Timeout) => {
            let _ = child.kill();
            let _ = child.wait();
            // The reader might hold a pipe inherited by a descendant.
            // Detach rather than wait indefinitely for its completion.
            return Err(AcquisitionError::TimedOut);
        }
        Err(mpsc::RecvTimeoutError::Disconnected) => {
            let _ = child.kill();
            let _ = child.wait();
            let _ = reader.join();
            return Err(AcquisitionError::ReaderFailed);
        }
    };
    let _ = reader.join();
    if output.len() > MAX_METADATA_BYTES {
        let _ = child.kill();
        let _ = child.wait();
        return Err(AcquisitionError::Metadata(MetadataError::TooLarge));
    }
    // Waiting for process exit must share the same deadline as output capture.
    loop {
        match child.try_wait() {
            Ok(Some(status)) => {
                if !status.success() {
                    return Err(AcquisitionError::ProcessFailed);
                }
                return decode_metadata(&output).map_err(AcquisitionError::Metadata);
            }
            Ok(None) if started.elapsed() >= deadline => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(AcquisitionError::TimedOut);
            }
            Ok(None) => std::thread::sleep(
                std::time::Duration::from_millis(10)
                    .min(deadline.saturating_sub(started.elapsed())),
            ),
            Err(error) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(AcquisitionError::Io(error));
            }
        }
    }
}

#[cfg(all(test, unix))]
mod acquisition_tests {
    use super::*;
    use std::path::Path;

    #[test]
    fn acquires_one_record_from_an_explicit_executable() {
        let result = acquire_metadata(
            Path::new("/bin/sh"),
            Path::new("."),
            "printf '{\"id\":\"sample\",\"duration\":3}'",
        );
        // A shell is not given a script flag: the target remains an inert
        // positional argument and must never be interpreted as shell code.
        assert!(matches!(result, Err(AcquisitionError::ProcessFailed)));
    }

    #[test]
    fn rejects_invalid_configuration_before_spawning() {
        assert!(matches!(
            acquire_metadata(Path::new(""), Path::new("."), "sample"),
            Err(AcquisitionError::InvalidConfiguration)
        ));
        assert!(matches!(
            acquire_metadata(Path::new("/bin/sh"), Path::new("."), "\0"),
            Err(AcquisitionError::InvalidConfiguration)
        ));
    }
}

#[cfg(all(test, unix))]
mod acquisition_deadline_tests {
    use super::*;
    use std::path::Path;
    use std::time::{Duration, Instant};

    #[test]
    fn rejects_zero_deadline() {
        assert!(matches!(
            acquire_metadata_with_deadline(
                Path::new("/bin/sh"),
                Path::new("."),
                "target",
                Duration::ZERO
            ),
            Err(AcquisitionError::InvalidConfiguration)
        ));
    }

    #[test]
    fn bounds_stalled_process_and_reaps_direct_child() {
        // /bin/sleep ignores the extra yt-dlp arguments and remains alive.
        // /bin/sh without -c exits immediately, so use a temporary executable
        // script instead to model a non-terminating acquisition.
        use std::os::unix::fs::PermissionsExt;
        let dir = std::env::temp_dir().join(format!(
            "yt-metadata-deadline-{}-{:?}",
            std::process::id(),
            std::thread::current().id()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        let script = dir.join("mock-ytdlp");
        std::fs::write(&script, "#!/bin/sh\nsleep 3\n").unwrap();
        std::fs::set_permissions(&script, std::fs::Permissions::from_mode(0o700)).unwrap();
        let start = Instant::now();
        let result =
            acquire_metadata_with_deadline(&script, &dir, "target", Duration::from_millis(100));
        assert!(matches!(result, Err(AcquisitionError::TimedOut)));
        assert!(start.elapsed() < Duration::from_secs(2));
        std::fs::remove_file(script).unwrap();
        std::fs::remove_dir(dir).unwrap();
    }
}

/// Regression coverage for the controlled acquisition boundary. The mock
/// executables exercise the real argument vector, exit status and output cap.
#[cfg(all(test, unix))]
mod acquisition_compatibility_tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;
    use std::path::PathBuf;
    use std::sync::atomic::{AtomicU64, Ordering};
    use std::time::Duration;

    static NEXT_FIXTURE: AtomicU64 = AtomicU64::new(0);

    struct MockExecutable {
        directory: PathBuf,
        executable: PathBuf,
    }

    impl MockExecutable {
        fn new(script_body: &str) -> Self {
            let serial = NEXT_FIXTURE.fetch_add(1, Ordering::Relaxed);
            let directory = std::env::temp_dir().join(format!(
                "yt-metadata-compat-{}-{serial}",
                std::process::id()
            ));
            std::fs::create_dir(&directory).unwrap();
            let executable = directory.join("mock-ytdlp");
            std::fs::write(&executable, format!("#!/bin/sh\n{script_body}\n")).unwrap();
            std::fs::set_permissions(&executable, std::fs::Permissions::from_mode(0o700)).unwrap();
            Self {
                directory,
                executable,
            }
        }

        fn acquire(&self, target: &str) -> Result<MediaMetadata, AcquisitionError> {
            acquire_metadata_with_deadline(
                &self.executable,
                &self.directory,
                target,
                Duration::from_secs(2),
            )
        }
    }

    impl Drop for MockExecutable {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.directory);
        }
    }

    #[test]
    fn passes_literal_target_and_isolated_ytdlp_options() {
        let mock = MockExecutable::new(
            r#"[ "$#" -eq 5 ] || exit 40
[ "$1" = '--ignore-config' ] || exit 41
[ "$2" = '--no-playlist' ] || exit 42
[ "$3" = '--dump-single-json' ] || exit 43
[ "$4" = '--' ] || exit 44
[ "$5" = 'https://example.invalid/watch?v=a;echo injected' ] || exit 45
printf '{"id":"safe","title":"Test","duration":9}'"#,
        );
        let record = mock
            .acquire("https://example.invalid/watch?v=a;echo injected")
            .unwrap();
        assert_eq!(record.id, "safe");
        assert_eq!(record.duration_seconds, Some(9));
    }

    #[test]
    fn distinguishes_process_failure_from_invalid_json_without_stderr_leakage() {
        let failed = MockExecutable::new(
            "printf 'sensitive diagnostic' >&2; printf '{\"id\":\"ok\"}'; exit 7",
        );
        assert!(matches!(
            failed.acquire("target"),
            Err(AcquisitionError::ProcessFailed)
        ));
        let malformed = MockExecutable::new("printf 'not-json'");
        assert!(matches!(
            malformed.acquire("target"),
            Err(AcquisitionError::Metadata(MetadataError::InvalidJson))
        ));
    }

    #[test]
    fn bounds_waiting_for_exit_after_complete_metadata_output() {
        // The child has closed stdout but remains alive. A successful JSON
        // read must not bypass the overall process-exit deadline.
        let mock = MockExecutable::new("printf '{\"id\":\"ready\"}'; exec 1>&-; sleep 3");
        let started = std::time::Instant::now();
        let result = acquire_metadata_with_deadline(
            &mock.executable,
            &mock.directory,
            "target",
            Duration::from_millis(100),
        );
        assert!(matches!(result, Err(AcquisitionError::TimedOut)));
        assert!(started.elapsed() < Duration::from_secs(2));
    }

    #[test]
    fn bounds_inherited_stdout_pipe_after_direct_child_exits() {
        // A descendant can retain the stdout pipe after its parent exits.
        // The acquisition call must return without joining that reader.
        let mock = MockExecutable::new("sleep 2 & printf '{\"id\":\"ready\"}'");
        let started = std::time::Instant::now();
        let result = acquire_metadata_with_deadline(
            &mock.executable,
            &mock.directory,
            "target",
            Duration::from_millis(100),
        );
        assert!(matches!(result, Err(AcquisitionError::TimedOut)));
        assert!(started.elapsed() < Duration::from_secs(2));
    }

    #[test]
    fn rejects_collections_and_excessive_output() {
        let collection =
            MockExecutable::new(r#"printf '{"_type":"playlist","id":"p","entries":[]}'"#);
        assert!(matches!(
            collection.acquire("target"),
            Err(AcquisitionError::Metadata(MetadataError::UnsupportedRecord))
        ));
        // Use a prepared payload rather than generating 8 MiB through a
        // shell pipeline under the fixture's short default deadline.
        let oversized = MockExecutable::new("cat oversized.json");
        std::fs::write(
            oversized.directory.join("oversized.json"),
            vec![b' '; MAX_METADATA_BYTES + 1],
        )
        .unwrap();
        assert!(matches!(
            acquire_metadata_with_deadline(
                &oversized.executable,
                &oversized.directory,
                "target",
                Duration::from_secs(10),
            ),
            Err(AcquisitionError::Metadata(MetadataError::TooLarge))
        ));
    }
}
