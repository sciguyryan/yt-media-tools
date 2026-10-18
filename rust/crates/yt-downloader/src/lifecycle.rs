//! Side-effect-free execution lifecycle contracts for future yt-dlp integration.
//!
//! A lifecycle records transitions and emits structured events. It does not
//! spawn processes, acquire metadata, or alter the filesystem.

use std::sync::atomic::{AtomicBool, Ordering};

use crate::planning::ExecutionPlan;

/// Distinct states of one planned execution attempt.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExecutionState {
    /// A plan has been accepted but execution has not started.
    Planned,
    /// An execution adapter has begun work.
    Running,
    /// Cancellation was requested and the adapter must stop safely.
    Cancelling,
    /// Execution completed successfully.
    Succeeded,
    /// Execution ended with a reported failure.
    Failed,
    /// Execution ended after a cancellation request.
    Cancelled,
}

impl ExecutionState {
    /// Whether no further transitions are permitted.
    pub fn is_terminal(self) -> bool {
        matches!(self, Self::Succeeded | Self::Failed | Self::Cancelled)
    }
}

/// An execution failure category, independent of a process implementation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FailureKind {
    /// An external executable could not be started.
    Spawn,
    /// The external executable exited unsuccessfully.
    Process,
    /// External output could not be interpreted safely.
    Protocol,
    /// An input or output operation failed.
    Io,
    /// An internal execution invariant was violated.
    Internal,
}

/// Structured information about an unsuccessful execution.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExecutionFailure {
    /// Stable failure classification for callers and tests.
    pub kind: FailureKind,
    /// A human-readable diagnostic, without credentials or sensitive arguments.
    pub message: String,
}

/// A progress observation supplied by an execution adapter.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Progress {
    /// Bytes reported as completed by the adapter.
    pub completed_bytes: u64,
    /// Expected total, if the external tool provides a trustworthy value.
    pub total_bytes: Option<u64>,
}

/// Observable lifecycle events in emission order.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ExecutionEvent {
    /// A state transition has occurred.
    StateChanged(ExecutionState),
    /// A progress observation was received while running.
    Progress(Progress),
    /// A failed execution has an associated diagnostic.
    Failure(ExecutionFailure),
}

/// Receives execution events without prescribing storage or presentation.
pub trait EventSink {
    /// Handle a single structured event.
    fn emit(&mut self, event: ExecutionEvent);
}

/// A cancellation signal that adapters can poll without global state.
pub trait CancellationSignal {
    /// Whether cancellation has been requested.
    fn is_cancelled(&self) -> bool;
}

/// Thread-safe cancellation signal for future process adapters.
#[derive(Debug, Default)]
pub struct CancellationToken(AtomicBool);

impl CancellationToken {
    /// Request cancellation. Repeated requests are idempotent.
    pub fn cancel(&self) {
        self.0.store(true, Ordering::Release);
    }
}

impl CancellationSignal for CancellationToken {
    fn is_cancelled(&self) -> bool {
        self.0.load(Ordering::Acquire)
    }
}

/// Errors in lifecycle bookkeeping, not external execution failures.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LifecycleError {
    /// The requested transition is not valid from the current state.
    InvalidTransition {
        from: ExecutionState,
        to: ExecutionState,
    },
    /// Progress exceeds the stated total.
    InvalidProgress,
}

/// Tracks a single plan's lifecycle without performing its execution.
#[derive(Debug, Clone)]
pub struct ExecutionLifecycle {
    /// The immutable execution plan represented by this lifecycle.
    pub plan: ExecutionPlan,
    state: ExecutionState,
}

impl ExecutionLifecycle {
    /// Create a lifecycle in the planned state.
    pub fn new(plan: ExecutionPlan) -> Self {
        Self {
            plan,
            state: ExecutionState::Planned,
        }
    }

    /// Return the current execution state.
    pub fn state(&self) -> ExecutionState {
        self.state
    }

    /// Apply an allowed transition and emit it exactly once.
    pub fn transition(
        &mut self,
        next: ExecutionState,
        sink: &mut impl EventSink,
    ) -> Result<(), LifecycleError> {
        let allowed = matches!(
            (self.state, next),
            (ExecutionState::Planned, ExecutionState::Running)
                | (ExecutionState::Planned, ExecutionState::Cancelled)
                | (ExecutionState::Running, ExecutionState::Cancelling)
                | (ExecutionState::Running, ExecutionState::Succeeded)
                | (ExecutionState::Running, ExecutionState::Failed)
                | (ExecutionState::Cancelling, ExecutionState::Cancelled)
                | (ExecutionState::Cancelling, ExecutionState::Failed)
        );
        if !allowed {
            return Err(LifecycleError::InvalidTransition {
                from: self.state,
                to: next,
            });
        }
        self.state = next;
        sink.emit(ExecutionEvent::StateChanged(next));
        Ok(())
    }

    /// Record progress only while running, with a consistent total.
    pub fn progress(
        &self,
        progress: Progress,
        sink: &mut impl EventSink,
    ) -> Result<(), LifecycleError> {
        if self.state != ExecutionState::Running {
            return Err(LifecycleError::InvalidTransition {
                from: self.state,
                to: ExecutionState::Running,
            });
        }
        if progress
            .total_bytes
            .is_some_and(|total| progress.completed_bytes > total)
        {
            return Err(LifecycleError::InvalidProgress);
        }
        sink.emit(ExecutionEvent::Progress(progress));
        Ok(())
    }

    /// Report a failure and transition to the failed state.
    pub fn fail(
        &mut self,
        failure: ExecutionFailure,
        sink: &mut impl EventSink,
    ) -> Result<(), LifecycleError> {
        if !matches!(
            self.state,
            ExecutionState::Running | ExecutionState::Cancelling
        ) {
            return Err(LifecycleError::InvalidTransition {
                from: self.state,
                to: ExecutionState::Failed,
            });
        }
        sink.emit(ExecutionEvent::Failure(failure));
        self.transition(ExecutionState::Failed, sink)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    use crate::targets::TargetSource;

    #[derive(Default)]
    struct Events(Vec<ExecutionEvent>);

    impl EventSink for Events {
        fn emit(&mut self, event: ExecutionEvent) {
            self.0.push(event);
        }
    }

    fn make_lifecycle() -> ExecutionLifecycle {
        ExecutionLifecycle::new(ExecutionPlan {
            arguments: vec!["--".into(), "video".into()],
            source: TargetSource::Direct(vec!["video".into()]),
        })
    }

    #[test]
    fn successful_execution_has_ordered_events() {
        let mut lifecycle = make_lifecycle();
        let mut events = Events::default();
        lifecycle
            .transition(ExecutionState::Running, &mut events)
            .unwrap();
        lifecycle
            .progress(
                Progress {
                    completed_bytes: 5,
                    total_bytes: Some(10),
                },
                &mut events,
            )
            .unwrap();
        lifecycle
            .transition(ExecutionState::Succeeded, &mut events)
            .unwrap();

        assert!(lifecycle.state().is_terminal());
        assert_eq!(
            events.0,
            vec![
                ExecutionEvent::StateChanged(ExecutionState::Running),
                ExecutionEvent::Progress(Progress {
                    completed_bytes: 5,
                    total_bytes: Some(10)
                }),
                ExecutionEvent::StateChanged(ExecutionState::Succeeded),
            ]
        );
    }

    #[test]
    fn invalid_transitions_do_not_emit_events() {
        let mut lifecycle = make_lifecycle();
        let mut events = Events::default();
        assert!(matches!(
            lifecycle.transition(ExecutionState::Succeeded, &mut events),
            Err(LifecycleError::InvalidTransition { .. })
        ));
        assert!(events.0.is_empty());
        lifecycle
            .transition(ExecutionState::Cancelled, &mut events)
            .unwrap();
        assert!(
            lifecycle
                .transition(ExecutionState::Running, &mut events)
                .is_err()
        );
        assert_eq!(events.0.len(), 1);
    }

    #[test]
    fn cancellation_and_failure_have_distinct_outcomes() {
        let token = CancellationToken::default();
        assert!(!token.is_cancelled());
        token.cancel();
        token.cancel();
        assert!(token.is_cancelled());

        let mut lifecycle = make_lifecycle();
        let mut events = Events::default();
        lifecycle
            .transition(ExecutionState::Running, &mut events)
            .unwrap();
        lifecycle
            .transition(ExecutionState::Cancelling, &mut events)
            .unwrap();
        lifecycle
            .transition(ExecutionState::Cancelled, &mut events)
            .unwrap();
        assert_eq!(lifecycle.state(), ExecutionState::Cancelled);

        let mut failed_lifecycle = make_lifecycle();
        let mut failures = Events::default();
        failed_lifecycle
            .transition(ExecutionState::Running, &mut failures)
            .unwrap();
        failed_lifecycle
            .fail(
                ExecutionFailure {
                    kind: FailureKind::Process,
                    message: "exit status 1".into(),
                },
                &mut failures,
            )
            .unwrap();
        assert_eq!(failed_lifecycle.state(), ExecutionState::Failed);
        assert!(matches!(failures.0[1], ExecutionEvent::Failure(_)));
    }

    #[test]
    fn progress_is_validated_without_side_effects() {
        let mut lifecycle = make_lifecycle();
        let mut events = Events::default();
        let progress = Progress {
            completed_bytes: 11,
            total_bytes: Some(10),
        };
        assert!(lifecycle.progress(progress, &mut events).is_err());
        lifecycle
            .transition(ExecutionState::Running, &mut events)
            .unwrap();
        assert_eq!(
            lifecycle.progress(progress, &mut events),
            Err(LifecycleError::InvalidProgress)
        );
        assert_eq!(events.0.len(), 1);
    }
}
