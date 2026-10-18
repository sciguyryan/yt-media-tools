//! Synchronous child-process supervision for an explicitly prepared launch.
//!
//! The supervisor owns its child, waits for termination and honours cancellation.
//! Output interpretation, download policy and CLI activation are separate work.

use std::io;
use std::process::ExitStatus;
use std::thread;
use std::time::Duration;

use crate::lifecycle::{CancellationSignal, EventSink, ExecutionFailure, ExecutionLifecycle, ExecutionState, FailureKind, LifecycleError};
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
    if cancellation.is_cancelled() {
        lifecycle.transition(ExecutionState::Cancelled, sink).map_err(SupervisionError::Lifecycle)?;
        return Ok(ExitStatusOrCancelled::Cancelled);
    }

    // Only an unstarted lifecycle may own a newly spawned process.
    if lifecycle.state() != ExecutionState::Planned {
        return Err(SupervisionError::Lifecycle(LifecycleError::InvalidTransition {
            from: lifecycle.state(),
            to: ExecutionState::Running,
        }));
    }

    let mut child = launch.command().spawn().map_err(SupervisionError::Spawn)?;
    lifecycle.transition(ExecutionState::Running, sink).map_err(SupervisionError::Lifecycle)?;

    loop {
        if cancellation.is_cancelled() {
            lifecycle.transition(ExecutionState::Cancelling, sink).map_err(SupervisionError::Lifecycle)?;
            // A child may have exited between the previous poll and cancellation.
            // Even in that case, reap it before completing the lifecycle.
            if let Err(error) = child.kill() {
                if error.kind() != io::ErrorKind::InvalidInput {
                    let _ = child.wait();
                    report_io_failure(lifecycle, sink, &error);
                    return Err(SupervisionError::Io(error));
                }
            }
            match child.wait() {
                Ok(_) => {
                    lifecycle.transition(ExecutionState::Cancelled, sink).map_err(SupervisionError::Lifecycle)?;
                    return Ok(ExitStatusOrCancelled::Cancelled);
                }
                Err(error) => {
                    report_io_failure(lifecycle, sink, &error);
                    return Err(SupervisionError::Io(error));
                }
            }
        }

        match child.try_wait() {
            Ok(Some(status)) if status.success() => {
                lifecycle.transition(ExecutionState::Succeeded, sink).map_err(SupervisionError::Lifecycle)?;
                return Ok(ExitStatusOrCancelled::Exited(status));
            }
            Ok(Some(status)) => {
                lifecycle.fail(ExecutionFailure {
                    kind: FailureKind::Process,
                    message: format!("external process exited with {status}"),
                }, sink).map_err(SupervisionError::Lifecycle)?;
                return Ok(ExitStatusOrCancelled::Exited(status));
            }
            Ok(None) => thread::sleep(POLL_INTERVAL),
            Err(error) => {
                let _ = child.kill();
                let _ = child.wait();
                report_io_failure(lifecycle, sink, &error);
                return Err(SupervisionError::Io(error));
            }
        }
    }
}

fn report_io_failure(lifecycle: &mut ExecutionLifecycle, sink: &mut impl EventSink, error: &io::Error) {
    let _ = lifecycle.fail(ExecutionFailure {
        kind: FailureKind::Io,
        message: format!("external process supervision failed: {error}"),
    }, sink);
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
        fn emit(&mut self, event: ExecutionEvent) { self.0.push(event); }
    }

    fn fixture() -> (ProcessLaunch, ExecutionLifecycle) {
        let plan = ExecutionPlan {
            arguments: vec![],
            source: TargetSource::Direct(vec!["fixture".into()]),
        };
        // This executable need not exist for the pre-cancellation test.
        let launch = ProcessLaunch::new(Executable::new("nonexistent-test-executable").unwrap(), ".", &plan).unwrap();
        (launch, ExecutionLifecycle::new(plan))
    }

    #[test]
    fn pre_cancelled_attempt_does_not_spawn() {
        let (launch, mut lifecycle) = fixture();
        let cancellation = CancellationToken::default();
        cancellation.cancel();
        let mut events = Events::default();
        assert!(matches!(supervise(&launch, &mut lifecycle, &cancellation, &mut events), Ok(ExitStatusOrCancelled::Cancelled)));
        assert_eq!(lifecycle.state(), ExecutionState::Cancelled);
        assert_eq!(events.0, vec![ExecutionEvent::StateChanged(ExecutionState::Cancelled)]);
    }

    #[test]
    fn spawn_failure_does_not_claim_running() {
        let (launch, mut lifecycle) = fixture();
        let cancellation = CancellationToken::default();
        let mut events = Events::default();
        assert!(matches!(supervise(&launch, &mut lifecycle, &cancellation, &mut events), Err(SupervisionError::Spawn(_))));
        assert_eq!(lifecycle.state(), ExecutionState::Planned);
        assert!(events.0.is_empty());
    }

    #[test]
    fn an_existing_lifecycle_cannot_spawn_twice() {
        let (launch, mut lifecycle) = fixture();
        let cancellation = CancellationToken::default();
        let mut events = Events::default();
        lifecycle.transition(ExecutionState::Running, &mut events).unwrap();
        assert!(matches!(supervise(&launch, &mut lifecycle, &cancellation, &mut events), Err(SupervisionError::Lifecycle(_))));
    }
}
