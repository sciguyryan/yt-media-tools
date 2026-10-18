//! Explicit external-process launch configuration for native Downloader execution.
//!
//! Constructing a command does not spawn it. Process supervision, output parsing,
//! cancellation and Python-compatible download policy are separate responsibilities.

use std::ffi::{OsStr, OsString};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use crate::planning::ExecutionPlan;

/// A caller-selected executable, never resolved through an implicit shell.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Executable(PathBuf);

/// Invalid external-process configuration.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ProcessConfigError {
    /// An empty executable path cannot be launched.
    EmptyExecutable,
    /// The executable path contains an embedded NUL byte.
    InvalidExecutable,
    /// The working directory must be explicitly supplied and non-empty.
    EmptyWorkingDirectory,
}

impl Executable {
    /// Accept a native executable path or command name without filesystem access.
    pub fn new(path: impl Into<PathBuf>) -> Result<Self, ProcessConfigError> {
        let path = path.into();
        if path.as_os_str().is_empty() {
            return Err(ProcessConfigError::EmptyExecutable);
        }
        if contains_nul(path.as_os_str()) {
            return Err(ProcessConfigError::InvalidExecutable);
        }
        Ok(Self(path))
    }

    /// Return the executable path unchanged.
    pub fn as_path(&self) -> &Path {
        &self.0
    }
}

fn contains_nul(value: &OsStr) -> bool {
    value.to_string_lossy().contains('\0')
}

/// Immutable launch specification derived from a validated execution plan.
///
/// The caller must select the executable and working directory. In particular,
/// the adapter does not invoke a shell or reinterpret the planned arguments.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProcessLaunch {
    executable: Executable,
    working_directory: PathBuf,
    arguments: Vec<OsString>,
}

impl ProcessLaunch {
    /// Prepare a launch specification without executing a command.
    pub fn new(
        executable: Executable,
        working_directory: impl Into<PathBuf>,
        plan: &ExecutionPlan,
    ) -> Result<Self, ProcessConfigError> {
        let working_directory = working_directory.into();
        if working_directory.as_os_str().is_empty() {
            return Err(ProcessConfigError::EmptyWorkingDirectory);
        }
        Ok(Self {
            executable,
            working_directory,
            arguments: plan.arguments.iter().map(OsString::from).collect(),
        })
    }

    /// Return the exact executable selected by the caller.
    pub fn executable(&self) -> &Path {
        self.executable.as_path()
    }

    /// Return the working directory without canonicalising it.
    pub fn working_directory(&self) -> &Path {
        &self.working_directory
    }

    /// Return the argument vector in its original order.
    pub fn arguments(&self) -> &[OsString] {
        &self.arguments
    }

    /// Construct an unspawned command with explicit standard-stream handling.
    ///
    /// Standard input is inherited to support `--batch-file -`. Standard output
    /// and error are inherited until a bounded event parser is implemented.
    /// This method does not start a process or change the current directory.
    pub fn command(&self) -> Command {
        let mut command = Command::new(self.executable.as_path());
        command.current_dir(&self.working_directory);
        command.args(&self.arguments);
        command.stdin(Stdio::inherit());
        command.stdout(Stdio::inherit());
        command.stderr(Stdio::inherit());
        command
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    use crate::targets::TargetSource;

    fn plan() -> ExecutionPlan {
        ExecutionPlan {
            arguments: vec!["--".into(), "--leading-dash".into(), "duplicate".into(), "duplicate".into()],
            source: TargetSource::Direct(vec!["--leading-dash".into(), "duplicate".into(), "duplicate".into()]),
        }
    }

    #[test]
    fn preserves_executable_working_directory_and_argument_order() {
        let launch = ProcessLaunch::new(Executable::new("yt-dlp").unwrap(), "downloads", &plan()).unwrap();
        assert_eq!(launch.executable(), Path::new("yt-dlp"));
        assert_eq!(launch.working_directory(), Path::new("downloads"));
        assert_eq!(launch.arguments(), &["--", "--leading-dash", "duplicate", "duplicate"]);
        let command = launch.command();
        assert_eq!(command.get_program(), OsStr::new("yt-dlp"));
        assert_eq!(command.get_current_dir(), Some(Path::new("downloads")));
        assert_eq!(command.get_args().collect::<Vec<_>>(), vec![OsStr::new("--"), OsStr::new("--leading-dash"), OsStr::new("duplicate"), OsStr::new("duplicate")]);
    }

    #[test]
    fn invalid_launch_configuration_fails_before_process_creation() {
        assert_eq!(Executable::new("").unwrap_err(), ProcessConfigError::EmptyExecutable);
        assert_eq!(Executable::new("bad\0name").unwrap_err(), ProcessConfigError::InvalidExecutable);
        assert_eq!(
            ProcessLaunch::new(Executable::new("yt-dlp").unwrap(), "", &plan()).unwrap_err(),
            ProcessConfigError::EmptyWorkingDirectory,
        );
    }

    #[test]
    fn standard_input_batch_arguments_are_preserved() {
        let plan = ExecutionPlan { arguments: vec!["--batch-file".into(), "-".into()], source: TargetSource::Stdin };
        let launch = ProcessLaunch::new(Executable::new("yt-dlp").unwrap(), ".", &plan).unwrap();
        assert_eq!(launch.arguments(), &["--batch-file", "-"]);
    }
}
