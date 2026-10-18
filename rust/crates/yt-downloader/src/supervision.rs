//! Synchronous child-process supervision for an explicitly prepared launch.
//!
//! The supervisor owns its child, waits for termination and honours cancellation.
//! Output interpretation, download policy and CLI activation are separate work.

use std::io;
use std::process::ExitStatus;
use std::sync::mpsc::{self, Receiver, SyncSender};
use std::thread;

use crate::lifecycle::Progress;
use crate::progress_stream::read_progress_stream;
use std::time::{Duration, Instant};

use crate::lifecycle::{
    CancellationSignal, EventSink, ExecutionFailure, ExecutionLifecycle, ExecutionState,
    FailureKind, LifecycleError,
};
use crate::process::ProcessLaunch;

/// The outcome of one supervised process attempt.
#[derive(Debug)]
pub enum SupervisionError {
    /// The process could not be started; the lifecycle remains planned.
    Spawn(io::Error),
    /// Waiting for or terminating the process failed.
    Io(io::Error),
    /// The supplied lifecycle did not permit the required transition.
    Lifecycle(LifecycleError),
}

/// A bounded polling interval, allowing cancellation without a dedicated worker.
const POLL_INTERVAL: Duration = Duration::from_millis(25);

/// Run a prepared process and reconcile its exit with the lifecycle.
///
/// Cancellation before spawning transitions directly to `Cancelled`. Once
/// started, cancellation requests termination and reaps the child before
/// reporting `Cancelled`. A termination or wait error reports a failed attempt.
/// The caller retains ownership of the cancellation signal and event sink.
///
/// The launch currently inherits standard streams. In particular, the adapter
/// does not capture or interpret potentially sensitive yt-dlp output.
pub fn supervise(
    launch: &ProcessLaunch,
    lifecycle: &mut ExecutionLifecycle,
    cancellation: &impl CancellationSignal,
    sink: &mut impl EventSink,
) -> Result<ExitStatusOrCancelled, SupervisionError> {
    supervise_inner(launch, lifecycle, cancellation, sink, false, false)
}

/// Supervise a child and decode framed progress from its standard error.
///
/// Unrelated output is discarded. The reader uses a bounded, non-blocking
/// channel so a slow lifecycle consumer cannot stall the child process.
/// This entry point does not add yt-dlp progress arguments to the launch.
pub fn supervise_with_progress(
    launch: &ProcessLaunch,
    lifecycle: &mut ExecutionLifecycle,
    cancellation: &impl CancellationSignal,
    sink: &mut impl EventSink,
) -> Result<ExitStatusOrCancelled, SupervisionError> {
    supervise_inner(launch, lifecycle, cancellation, sink, true, false)
}

/// Supervise an explicitly selected yt-dlp process with structured progress.
///
/// This is an opt-in adapter boundary, not an activation of public CLI
/// downloads. The generic supervisor remains suitable for other executables.
pub fn supervise_ytdlp_with_progress(
    launch: &ProcessLaunch,
    lifecycle: &mut ExecutionLifecycle,
    cancellation: &impl CancellationSignal,
    sink: &mut impl EventSink,
) -> Result<ExitStatusOrCancelled, SupervisionError> {
    supervise_inner(launch, lifecycle, cancellation, sink, true, true)
}

const PROGRESS_QUEUE_CAPACITY: usize = 64;
/// A descendant can retain the inherited stderr pipe after the direct child exits.
/// Do not block the supervisor indefinitely waiting for that descendant to close it.
const READER_SHUTDOWN_TIMEOUT: Duration = Duration::from_millis(500);
const READER_SHUTDOWN_POLL: Duration = Duration::from_millis(10);

fn drain_progress(
    receiver: &Receiver<Progress>,
    lifecycle: &mut ExecutionLifecycle,
    sink: &mut impl EventSink,
) {
    while let Ok(progress) = receiver.try_recv() {
        let _ = lifecycle.progress(progress, sink);
    }
}

/// Reap the output reader before completing a lifecycle. A reader failure is
/// not a successful download, even if the child itself exited successfully.
fn finish_reader(
    reader: Option<thread::JoinHandle<io::Result<()>>>,
    receiver: &Receiver<Progress>,
    lifecycle: &mut ExecutionLifecycle,
    sink: &mut impl EventSink,
) -> Result<(), SupervisionError> {
    let outcome = if let Some(reader) = reader {
        let deadline = Instant::now() + READER_SHUTDOWN_TIMEOUT;
        while !reader.is_finished() && Instant::now() < deadline {
            drain_progress(receiver, lifecycle, sink);
            thread::sleep(READER_SHUTDOWN_POLL);
        }
        if !reader.is_finished() {
            // Dropping the handle detaches the reader. It will finish when the
            // inherited pipe eventually closes, without holding up supervision.
            drop(reader);
            drain_progress(receiver, lifecycle, sink);
            let error = io::Error::new(
                io::ErrorKind::TimedOut,
                "process progress reader did not finish after child exit",
            );
            report_io_failure(lifecycle, sink, &error);
            return Err(SupervisionError::Io(error));
        }
        Some(reader.join())
    } else {
        None
    };
    drain_progress(receiver, lifecycle, sink);
    match outcome {
        None | Some(Ok(Ok(()))) => Ok(()),
        Some(Ok(Err(error))) => {
            report_io_failure(lifecycle, sink, &error);
            Err(SupervisionError::Io(error))
        }
        Some(Err(_)) => {
            let error = io::Error::other("process progress reader terminated unexpectedly");
            report_io_failure(lifecycle, sink, &error);
            Err(SupervisionError::Io(error))
        }
    }
}

fn supervise_inner(
    launch: &ProcessLaunch,
    lifecycle: &mut ExecutionLifecycle,
    cancellation: &impl CancellationSignal,
    sink: &mut impl EventSink,
    capture_progress: bool,
    configure_ytdlp_progress: bool,
) -> Result<ExitStatusOrCancelled, SupervisionError> {
    if cancellation.is_cancelled() {
        lifecycle
            .transition(ExecutionState::Cancelled, sink)
            .map_err(SupervisionError::Lifecycle)?;
        return Ok(ExitStatusOrCancelled::Cancelled);
    }

    // Only an unstarted lifecycle may own a newly spawned process.
    if lifecycle.state() != ExecutionState::Planned {
        return Err(SupervisionError::Lifecycle(
            LifecycleError::InvalidTransition {
                from: lifecycle.state(),
                to: ExecutionState::Running,
            },
        ));
    }

    let mut command = if configure_ytdlp_progress {
        launch.ytdlp_progress_command()
    } else {
        launch.command()
    };
    if capture_progress {
        command.stderr(std::process::Stdio::piped());
    }
    let mut child = command.spawn().map_err(SupervisionError::Spawn)?;
    let (sender, receiver): (SyncSender<Progress>, Receiver<Progress>) =
        mpsc::sync_channel(PROGRESS_QUEUE_CAPACITY);
    let reader = if capture_progress {
        child.stderr.take().map(|mut stderr| {
            thread::spawn(move || {
                // Dropping observations when the queue is full is intentional:
                // progress is advisory and must never block process termination.
                read_progress_stream(&mut stderr, |progress| {
                    let _ = sender.try_send(progress);
                })
            })
        })
    } else {
        None
    };
    lifecycle
        .transition(ExecutionState::Running, sink)
        .map_err(SupervisionError::Lifecycle)?;

    loop {
        drain_progress(&receiver, lifecycle, sink);
        if cancellation.is_cancelled() {
            lifecycle
                .transition(ExecutionState::Cancelling, sink)
                .map_err(SupervisionError::Lifecycle)?;
            // A child may have exited between the previous poll and cancellation.
            // Even in that case, reap it before completing the lifecycle.
            if let Err(error) = child.kill()
                && error.kind() != io::ErrorKind::InvalidInput
            {
                let _ = child.wait();
                let _ = finish_reader(reader, &receiver, lifecycle, sink);
                report_io_failure(lifecycle, sink, &error);
                return Err(SupervisionError::Io(error));
            }
            match child.wait() {
                Ok(_) => {
                    // A failed reader is a supervision failure, even when the
                    // cancellation request successfully reaped the child.
                    finish_reader(reader, &receiver, lifecycle, sink)?;
                    lifecycle
                        .transition(ExecutionState::Cancelled, sink)
                        .map_err(SupervisionError::Lifecycle)?;
                    return Ok(ExitStatusOrCancelled::Cancelled);
                }
                Err(error) => {
                    let _ = finish_reader(reader, &receiver, lifecycle, sink);
                    report_io_failure(lifecycle, sink, &error);
                    return Err(SupervisionError::Io(error));
                }
            }
        }

        match child.try_wait() {
            Ok(Some(status)) if status.success() => {
                finish_reader(reader, &receiver, lifecycle, sink)?;
                lifecycle
                    .transition(ExecutionState::Succeeded, sink)
                    .map_err(SupervisionError::Lifecycle)?;
                return Ok(ExitStatusOrCancelled::Exited(status));
            }
            Ok(Some(status)) => {
                finish_reader(reader, &receiver, lifecycle, sink)?;
                lifecycle
                    .fail(
                        ExecutionFailure {
                            kind: FailureKind::Process,
                            message: format!("external process exited with {status}"),
                        },
                        sink,
                    )
                    .map_err(SupervisionError::Lifecycle)?;
                return Ok(ExitStatusOrCancelled::Exited(status));
            }
            Ok(None) => thread::sleep(POLL_INTERVAL),
            Err(error) => {
                let _ = child.kill();
                let _ = child.wait();
                let _ = finish_reader(reader, &receiver, lifecycle, sink);
                report_io_failure(lifecycle, sink, &error);
                return Err(SupervisionError::Io(error));
            }
        }
    }
}

fn report_io_failure(
    lifecycle: &mut ExecutionLifecycle,
    sink: &mut impl EventSink,
    error: &io::Error,
) {
    let _ = lifecycle.fail(
        ExecutionFailure {
            kind: FailureKind::Io,
            message: format!("external process supervision failed: {error}"),
        },
        sink,
    );
}

/// A child exit status or a completed cancellation request.
#[derive(Debug)]
pub enum ExitStatusOrCancelled {
    /// The process exited; inspect `success()` to determine its outcome.
    Exited(ExitStatus),
    /// Cancellation was honoured and the child has been reaped, or never started.
    Cancelled,
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::lifecycle::{CancellationToken, ExecutionEvent};
    use crate::planning::ExecutionPlan;
    use crate::process::Executable;
    use crate::targets::TargetSource;

    #[derive(Default)]
    struct Events(Vec<ExecutionEvent>);
    impl EventSink for Events {
        fn emit(&mut self, event: ExecutionEvent) {
            self.0.push(event);
        }
    }

    fn fixture() -> (ProcessLaunch, ExecutionLifecycle) {
        let plan = ExecutionPlan {
            arguments: vec![],
            source: TargetSource::Direct(vec!["fixture".into()]),
        };
        // This executable need not exist for the pre-cancellation test.
        let launch = ProcessLaunch::new(
            Executable::new("nonexistent-test-executable").unwrap(),
            ".",
            &plan,
        )
        .unwrap();
        (launch, ExecutionLifecycle::new(plan))
    }

    #[cfg(unix)]
    #[test]
    fn supervised_stderr_progress_precedes_success() {
        let plan = ExecutionPlan { arguments: vec![
            "-c".into(),
            "printf 'unrelated\\nYT_MEDIA_TOOLS_PROGRESS:3,10\\nYT_MEDIA_TOOLS_PROGRESS:10,10\\n' >&2".into(),
        ], source: TargetSource::Direct(vec!["fixture".into()]) };
        let launch = ProcessLaunch::new(Executable::new("/bin/sh").unwrap(), ".", &plan).unwrap();
        let mut lifecycle = ExecutionLifecycle::new(plan);
        let mut events = Events::default();
        let cancellation = CancellationToken::default();
        let result = supervise_with_progress(&launch, &mut lifecycle, &cancellation, &mut events);
        assert!(matches!(result, Ok(ExitStatusOrCancelled::Exited(status)) if status.success()));
        assert_eq!(lifecycle.state(), ExecutionState::Succeeded);
        assert!(events.0.contains(&ExecutionEvent::Progress(Progress {
            completed_bytes: 3,
            total_bytes: Some(10)
        })));
        assert!(events.0.contains(&ExecutionEvent::Progress(Progress {
            completed_bytes: 10,
            total_bytes: Some(10)
        })));
        assert!(matches!(
            events.0.last(),
            Some(ExecutionEvent::StateChanged(ExecutionState::Succeeded))
        ));
    }

    #[cfg(unix)]
    #[test]
    fn failed_child_delivers_progress_before_failure() {
        let plan = ExecutionPlan {
            arguments: vec![
                "-c".into(),
                "printf 'YT_MEDIA_TOOLS_PROGRESS:4,10\\n' >&2; exit 7".into(),
            ],
            source: TargetSource::Direct(vec!["fixture".into()]),
        };
        let launch = ProcessLaunch::new(Executable::new("/bin/sh").unwrap(), ".", &plan).unwrap();
        let mut lifecycle = ExecutionLifecycle::new(plan);
        let mut events = Events::default();
        let cancellation = CancellationToken::default();
        let result = supervise_with_progress(&launch, &mut lifecycle, &cancellation, &mut events);
        assert!(matches!(result, Ok(ExitStatusOrCancelled::Exited(status)) if !status.success()));
        assert_eq!(lifecycle.state(), ExecutionState::Failed);
        let progress_index = events
            .0
            .iter()
            .position(|event| {
                matches!(
                    event,
                    ExecutionEvent::Progress(Progress {
                        completed_bytes: 4,
                        total_bytes: Some(10)
                    })
                )
            })
            .unwrap();
        let terminal_index = events
            .0
            .iter()
            .position(|event| matches!(event, ExecutionEvent::StateChanged(ExecutionState::Failed)))
            .unwrap();
        assert!(progress_index < terminal_index);
    }

    #[test]
    fn pre_cancelled_attempt_does_not_spawn() {
        let (launch, mut lifecycle) = fixture();
        let cancellation = CancellationToken::default();
        cancellation.cancel();
        let mut events = Events::default();
        assert!(matches!(
            supervise(&launch, &mut lifecycle, &cancellation, &mut events),
            Ok(ExitStatusOrCancelled::Cancelled)
        ));
        assert_eq!(lifecycle.state(), ExecutionState::Cancelled);
        assert_eq!(
            events.0,
            vec![ExecutionEvent::StateChanged(ExecutionState::Cancelled)]
        );
    }

    #[test]
    fn spawn_failure_does_not_claim_running() {
        let (launch, mut lifecycle) = fixture();
        let cancellation = CancellationToken::default();
        let mut events = Events::default();
        assert!(matches!(
            supervise(&launch, &mut lifecycle, &cancellation, &mut events),
            Err(SupervisionError::Spawn(_))
        ));
        assert_eq!(lifecycle.state(), ExecutionState::Planned);
        assert!(events.0.is_empty());
    }

    #[test]
    fn an_existing_lifecycle_cannot_spawn_twice() {
        let (launch, mut lifecycle) = fixture();
        let cancellation = CancellationToken::default();
        let mut events = Events::default();
        lifecycle
            .transition(ExecutionState::Running, &mut events)
            .unwrap();
        assert!(matches!(
            supervise(&launch, &mut lifecycle, &cancellation, &mut events),
            Err(SupervisionError::Lifecycle(_))
        ));
    }
}

#[cfg(test)]
mod reader_completion_tests {
    use super::*;
    use crate::lifecycle::{ExecutionEvent, ExecutionState};
    use crate::planning::ExecutionPlan;
    use crate::targets::TargetSource;

    #[derive(Default)]
    struct Events(Vec<ExecutionEvent>);
    impl EventSink for Events {
        fn emit(&mut self, event: ExecutionEvent) {
            self.0.push(event);
        }
    }

    fn lifecycle() -> ExecutionLifecycle {
        let mut lifecycle = ExecutionLifecycle::new(ExecutionPlan {
            arguments: vec![],
            source: TargetSource::Direct(vec!["fixture".into()]),
        });
        lifecycle
            .transition(ExecutionState::Running, &mut Events::default())
            .unwrap();
        lifecycle
    }

    #[test]
    fn reader_io_error_prevents_success_and_reports_failure() {
        let (sender, receiver) = mpsc::sync_channel(2);
        sender
            .send(Progress {
                completed_bytes: 2,
                total_bytes: Some(10),
            })
            .unwrap();
        let reader = thread::spawn(|| Err(io::Error::other("test read failure")));
        let mut lifecycle = lifecycle();
        let mut events = Events::default();
        assert!(matches!(
            finish_reader(Some(reader), &receiver, &mut lifecycle, &mut events),
            Err(SupervisionError::Io(_))
        ));
        assert_eq!(lifecycle.state(), ExecutionState::Failed);
        assert!(matches!(
            events.0.first(),
            Some(ExecutionEvent::Progress(_))
        ));
        assert!(matches!(
            events.0.last(),
            Some(ExecutionEvent::StateChanged(ExecutionState::Failed))
        ));
    }

    #[test]
    fn cancelling_lifecycle_can_report_reader_failure() {
        let (sender, receiver) = mpsc::sync_channel(2);
        sender
            .send(Progress {
                completed_bytes: 2,
                total_bytes: Some(10),
            })
            .unwrap();
        let reader = thread::spawn(|| Err(io::Error::other("test read failure")));
        let mut lifecycle = lifecycle();
        let mut events = Events::default();
        lifecycle
            .transition(ExecutionState::Cancelling, &mut events)
            .unwrap();
        assert!(matches!(
            finish_reader(Some(reader), &receiver, &mut lifecycle, &mut events),
            Err(SupervisionError::Io(_))
        ));
        assert_eq!(lifecycle.state(), ExecutionState::Failed);
        assert!(matches!(
            events.0.last(),
            Some(ExecutionEvent::StateChanged(ExecutionState::Failed))
        ));
        assert!(
            !events
                .0
                .contains(&ExecutionEvent::StateChanged(ExecutionState::Cancelled))
        );
    }

    #[test]
    fn inherited_pipe_does_not_block_terminal_lifecycle_indefinitely() {
        let (_sender, receiver) = mpsc::sync_channel(2);
        let reader = thread::spawn(|| {
            thread::sleep(Duration::from_secs(2));
            Ok(())
        });
        let mut lifecycle = lifecycle();
        let mut events = Events::default();
        let start = Instant::now();
        assert!(
            matches!(finish_reader(Some(reader), &receiver, &mut lifecycle, &mut events), Err(SupervisionError::Io(error)) if error.kind() == io::ErrorKind::TimedOut)
        );
        assert!(start.elapsed() < Duration::from_millis(1500));
        assert_eq!(lifecycle.state(), ExecutionState::Failed);
        assert!(matches!(
            events.0.last(),
            Some(ExecutionEvent::StateChanged(ExecutionState::Failed))
        ));
    }

    #[test]
    fn panicked_reader_reports_failure_without_exposing_payload() {
        let (_sender, receiver) = mpsc::sync_channel(2);
        let reader = thread::spawn(|| -> io::Result<()> { panic!("fixture panic") });
        let mut lifecycle = lifecycle();
        let mut events = Events::default();
        assert!(matches!(
            finish_reader(Some(reader), &receiver, &mut lifecycle, &mut events),
            Err(SupervisionError::Io(_))
        ));
        assert_eq!(lifecycle.state(), ExecutionState::Failed);
    }
}
