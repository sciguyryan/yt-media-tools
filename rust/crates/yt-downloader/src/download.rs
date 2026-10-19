//! Explicit native download execution boundary.
//!
//! This module connects a validated execution plan to the existing supervised
//! yt-dlp progress path. It does not enable downloads in the public CLI.

use std::path::PathBuf;

use crate::lifecycle::{CancellationSignal, EventSink, ExecutionLifecycle, ExecutionState};
use crate::planning::ExecutionPlan;
use crate::process::{Executable, ProcessConfigError, ProcessLaunch};
use crate::supervision::{ExitStatusOrCancelled, SupervisionError, supervise_ytdlp_with_progress};

/// An invalid launch or an error while supervising an execution attempt.
#[derive(Debug)]
pub enum DownloadExecutionError {
    /// The executable or working directory was not valid.
    Configuration(ProcessConfigError),
    /// Starting, supervising or completing the child failed.
    Supervision(SupervisionError),
}

/// The completed lifecycle and direct child outcome for one attempt.
///
/// An unsuccessful child exit is represented as `Ok` with a `Failed` state,
/// preserving the exit status and emitted failure event for the caller.
#[derive(Debug)]
pub struct DownloadAttempt {
    /// Final lifecycle state, including cancellation and process failure.
    pub state: ExecutionState,
    /// The direct child exit or completed cancellation.
    pub outcome: ExitStatusOrCancelled,
}

/// Execute an already validated plan using explicitly selected yt-dlp.
///
/// This opt-in library entry point does not parse CLI arguments, resolve a
/// default executable, reinterpret targets or activate the public download CLI.
/// The caller owns the event sink and cancellation signal. Standard output is
/// inherited, while structured progress is decoded from standard error.
pub fn execute_download(
    plan: ExecutionPlan,
    executable: Executable,
    working_directory: impl Into<PathBuf>,
    cancellation: &impl CancellationSignal,
    sink: &mut impl EventSink,
) -> Result<DownloadAttempt, DownloadExecutionError> {
    let launch = ProcessLaunch::new(executable, working_directory, &plan)
        .map_err(DownloadExecutionError::Configuration)?;
    let mut lifecycle = ExecutionLifecycle::new(plan);
    let outcome = supervise_ytdlp_with_progress(&launch, &mut lifecycle, cancellation, sink)
        .map_err(DownloadExecutionError::Supervision)?;
    Ok(DownloadAttempt {
        state: lifecycle.state(),
        outcome,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::lifecycle::{CancellationToken, ExecutionEvent};
    use crate::targets::TargetSource;

    #[derive(Default)]
    struct Events(Vec<ExecutionEvent>);
    impl EventSink for Events {
        fn emit(&mut self, event: ExecutionEvent) {
            self.0.push(event);
        }
    }

    fn plan() -> ExecutionPlan {
        ExecutionPlan {
            arguments: vec!["--".into(), "literal-target".into()],
            source: TargetSource::Direct(vec!["literal-target".into()]),
        }
    }

    #[test]
    fn invalid_working_directory_fails_before_any_lifecycle_event() {
        let mut events = Events::default();
        let result = execute_download(
            plan(),
            Executable::new("yt-dlp").unwrap(),
            "",
            &CancellationToken::default(),
            &mut events,
        );
        assert!(matches!(
            result,
            Err(DownloadExecutionError::Configuration(
                ProcessConfigError::EmptyWorkingDirectory
            ))
        ));
        assert!(events.0.is_empty());
    }

    #[test]
    fn cancellation_before_spawn_does_not_require_an_installed_executable() {
        let cancellation = CancellationToken::default();
        cancellation.cancel();
        let mut events = Events::default();
        let attempt = execute_download(
            plan(),
            Executable::new("nonexistent-yt-dlp-fixture").unwrap(),
            ".",
            &cancellation,
            &mut events,
        )
        .unwrap();
        assert_eq!(attempt.state, ExecutionState::Cancelled);
        assert!(matches!(attempt.outcome, ExitStatusOrCancelled::Cancelled));
        assert_eq!(
            events.0.last(),
            Some(&ExecutionEvent::StateChanged(ExecutionState::Cancelled))
        );
    }

    #[cfg(unix)]
    #[test]
    fn successful_process_reports_terminal_success() {
        let mut events = Events::default();
        let attempt = execute_download(
            plan(),
            Executable::new("/bin/true").unwrap(),
            ".",
            &CancellationToken::default(),
            &mut events,
        )
        .unwrap();
        assert_eq!(attempt.state, ExecutionState::Succeeded);
        assert!(
            matches!(attempt.outcome, ExitStatusOrCancelled::Exited(status) if status.success())
        );
        assert_eq!(
            events.0.last(),
            Some(&ExecutionEvent::StateChanged(ExecutionState::Succeeded))
        );
    }

    #[cfg(unix)]
    #[test]
    fn unsuccessful_process_retains_exit_status_and_failed_lifecycle() {
        let mut events = Events::default();
        let attempt = execute_download(
            plan(),
            Executable::new("/bin/false").unwrap(),
            ".",
            &CancellationToken::default(),
            &mut events,
        )
        .unwrap();
        assert_eq!(attempt.state, ExecutionState::Failed);
        assert!(
            matches!(attempt.outcome, ExitStatusOrCancelled::Exited(status) if !status.success())
        );
        assert!(
            events
                .0
                .iter()
                .any(|event| matches!(event, ExecutionEvent::Failure(_)))
        );
        assert_eq!(
            events.0.last(),
            Some(&ExecutionEvent::StateChanged(ExecutionState::Failed))
        );
    }
    /// A sink that requests cancellation only after observing real progress.
    #[cfg(unix)]
    struct CancelOnProgress<'a> {
        events: Vec<ExecutionEvent>,
        cancellation: &'a CancellationToken,
    }

    #[cfg(unix)]
    impl EventSink for CancelOnProgress<'_> {
        fn emit(&mut self, event: ExecutionEvent) {
            if matches!(event, ExecutionEvent::Progress(_)) {
                self.cancellation.cancel();
            }
            self.events.push(event);
        }
    }

    #[cfg(unix)]
    fn shell_plan(script: &str) -> ExecutionPlan {
        ExecutionPlan {
            arguments: vec![
                "-c".into(),
                script.into(),
                "fixture".into(),
                "--".into(),
                "literal-target".into(),
            ],
            source: TargetSource::Direct(vec!["literal-target".into()]),
        }
    }

    #[cfg(unix)]
    #[test]
    fn explicit_adapter_forwards_progress_before_terminal_success() {
        let mut events = Events::default();
        let plan = shell_plan(
            "printf 'YT_MEDIA_TOOLS_PROGRESS:4,10\\nYT_MEDIA_TOOLS_PROGRESS:10,10\\n' >&2",
        );
        let attempt = execute_download(
            plan,
            Executable::new("/bin/sh").unwrap(),
            ".",
            &CancellationToken::default(),
            &mut events,
        )
        .unwrap();
        assert_eq!(attempt.state, ExecutionState::Succeeded);
        assert!(
            matches!(attempt.outcome, ExitStatusOrCancelled::Exited(status) if status.success())
        );
        let first = events.0.iter().position(|event| matches!(event, ExecutionEvent::Progress(progress) if progress.completed_bytes == 4 && progress.total_bytes == Some(10))).expect("first progress observation");
        let second = events.0.iter().position(|event| matches!(event, ExecutionEvent::Progress(progress) if progress.completed_bytes == 10 && progress.total_bytes == Some(10))).expect("final progress observation");
        let terminal = events
            .0
            .iter()
            .position(|event| *event == ExecutionEvent::StateChanged(ExecutionState::Succeeded))
            .expect("terminal success");
        assert!(first < second && second < terminal);
    }

    #[cfg(unix)]
    #[test]
    fn explicit_adapter_cancels_running_child_after_progress() {
        let cancellation = CancellationToken::default();
        let mut sink = CancelOnProgress {
            events: Vec::new(),
            cancellation: &cancellation,
        };
        let plan = shell_plan("printf 'YT_MEDIA_TOOLS_PROGRESS:1,10\\n' >&2; exec sleep 5");
        let attempt = execute_download(
            plan,
            Executable::new("/bin/sh").unwrap(),
            ".",
            &cancellation,
            &mut sink,
        )
        .unwrap();
        assert_eq!(attempt.state, ExecutionState::Cancelled);
        assert!(matches!(attempt.outcome, ExitStatusOrCancelled::Cancelled));
        let progress = sink.events.iter().position(|event| matches!(event, ExecutionEvent::Progress(value) if value.completed_bytes == 1)).expect("progress before cancellation");
        let cancelling = sink
            .events
            .iter()
            .position(|event| *event == ExecutionEvent::StateChanged(ExecutionState::Cancelling))
            .expect("cancelling state");
        let terminal = sink
            .events
            .iter()
            .position(|event| *event == ExecutionEvent::StateChanged(ExecutionState::Cancelled))
            .expect("cancelled state");
        assert!(progress < cancelling && cancelling < terminal);
        assert_eq!(
            sink.events.last(),
            Some(&ExecutionEvent::StateChanged(ExecutionState::Cancelled))
        );
    }

    /// Check that progress instrumentation never consumes or rearranges literal
    /// download targets, including option-looking and duplicate values.
    #[cfg(unix)]
    #[test]
    fn explicit_adapter_preserves_literal_target_arguments() {
        let script = r#"
            test "$1" = "--newline" || exit 21
            test "$2" = "--progress-template" || exit 22
            case "$3" in
                download:YT_MEDIA_TOOLS_PROGRESS:*) ;;
                *) exit 23 ;;
            esac
            test "$4" = "--" || exit 24
            test "$5" = "--unusual" || exit 25
            test "$6" = "repeat" || exit 26
            test "$7" = "repeat" || exit 27
            test "$#" -eq 7 || exit 28
            printf 'YT_MEDIA_TOOLS_PROGRESS:1,1\n' >&2
        "#;
        let plan = ExecutionPlan {
            arguments: vec![
                "-c".into(),
                script.into(),
                "fixture".into(),
                "--".into(),
                "--unusual".into(),
                "repeat".into(),
                "repeat".into(),
            ],
            source: TargetSource::Direct(vec![
                "--unusual".into(),
                "repeat".into(),
                "repeat".into(),
            ]),
        };
        let mut events = Events::default();
        let attempt = execute_download(
            plan,
            Executable::new("/bin/sh").unwrap(),
            ".",
            &CancellationToken::default(),
            &mut events,
        )
        .unwrap();
        assert_eq!(attempt.state, ExecutionState::Succeeded);
        assert!(events.0.iter().any(
            |event| matches!(event, ExecutionEvent::Progress(value) if value.completed_bytes == 1)
        ));
    }

    /// Verify that a batch file reaches the child as a path, not expanded targets.
    #[cfg(unix)]
    #[test]
    fn explicit_adapter_preserves_batch_file_source() {
        let batch_path = std::env::current_dir().unwrap().join("Cargo.toml");
        assert!(batch_path.is_file());
        let script = r#"
            test "$1" = "--batch-file" || exit 31
            test -f "$2" || exit 32
            test "$3" = "--newline" || exit 33
            test "$4" = "--progress-template" || exit 34
            case "$5" in
                download:YT_MEDIA_TOOLS_PROGRESS:*) ;;
                *) exit 35 ;;
            esac
            test "$#" -eq 5 || exit 36
            printf 'YT_MEDIA_TOOLS_PROGRESS:2,2\n' >&2
        "#;
        let plan = ExecutionPlan {
            arguments: vec![
                "-c".into(),
                script.into(),
                "fixture".into(),
                "--batch-file".into(),
                batch_path.to_string_lossy().into_owned(),
            ],
            source: TargetSource::BatchFile(batch_path),
        };
        let mut events = Events::default();
        let attempt = execute_download(
            plan,
            Executable::new("/bin/sh").unwrap(),
            ".",
            &CancellationToken::default(),
            &mut events,
        )
        .unwrap();
        assert_eq!(attempt.state, ExecutionState::Succeeded);
        assert!(events.0.iter().any(
            |event| matches!(event, ExecutionEvent::Progress(value) if value.completed_bytes == 2)
        ));
    }

    /// The standard-input marker is forwarded as a batch source. The fixture
    /// deliberately does not read stdin, which is inherited from the caller.
    #[cfg(unix)]
    #[test]
    fn explicit_adapter_preserves_standard_input_source() {
        let script = r#"
            test "$1" = "--batch-file" || exit 41
            test "$2" = "-" || exit 42
            test "$3" = "--newline" || exit 43
            test "$4" = "--progress-template" || exit 44
            case "$5" in
                download:YT_MEDIA_TOOLS_PROGRESS:*) ;;
                *) exit 45 ;;
            esac
            test "$#" -eq 5 || exit 46
            printf 'YT_MEDIA_TOOLS_PROGRESS:1,1\n' >&2
        "#;
        let plan = ExecutionPlan {
            arguments: vec![
                "-c".into(),
                script.into(),
                "fixture".into(),
                "--batch-file".into(),
                "-".into(),
            ],
            source: TargetSource::Stdin,
        };
        let mut events = Events::default();
        let attempt = execute_download(
            plan,
            Executable::new("/bin/sh").unwrap(),
            ".",
            &CancellationToken::default(),
            &mut events,
        )
        .unwrap();
        assert_eq!(attempt.state, ExecutionState::Succeeded);
        assert!(events.0.iter().any(
            |event| matches!(event, ExecutionEvent::Progress(value) if value.completed_bytes == 1)
        ));
    }

    /// A failed child must not discard progress already delivered to callers.
    #[cfg(unix)]
    #[test]
    fn explicit_adapter_preserves_progress_before_terminal_failure() {
        let script = r"printf 'ordinary diagnostic\n' >&2; printf 'YT_MEDIA_TOOLS_PROGRESS:3,9\n' >&2; exit 17";
        let mut events = Events::default();
        let attempt = execute_download(
            shell_plan(script),
            Executable::new("/bin/sh").unwrap(),
            ".",
            &CancellationToken::default(),
            &mut events,
        )
        .unwrap();
        assert_eq!(attempt.state, ExecutionState::Failed);
        assert!(
            matches!(attempt.outcome, ExitStatusOrCancelled::Exited(status) if status.code() == Some(17))
        );
        let progress = events.0.iter().position(|event| matches!(event, ExecutionEvent::Progress(value) if value.completed_bytes == 3 && value.total_bytes == Some(9))).expect("progress before failure");
        let failure = events
            .0
            .iter()
            .position(|event| matches!(event, ExecutionEvent::Failure(_)))
            .expect("failure event");
        let terminal = events
            .0
            .iter()
            .position(|event| *event == ExecutionEvent::StateChanged(ExecutionState::Failed))
            .expect("terminal failure");
        assert!(progress < failure && failure < terminal);
        assert_eq!(
            events.0.last(),
            Some(&ExecutionEvent::StateChanged(ExecutionState::Failed))
        );
    }
}
