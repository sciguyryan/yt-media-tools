//! Test the same response function used by the binary without spawning it.
//! Process-level tests can be added once binary execution is reliable across CI targets.
use std::ffi::OsString;

fn run(arg: &str) -> (u8, String, String) {
    yt_downloader::experimental_cli(&[OsString::from(arg)])
}

#[test]
fn help_is_successful_and_explains_status() {
    let (status, stdout, stderr) = run("--help");
    assert_eq!(status, 0);
    assert!(stdout.contains("experimental"));
    assert!(stdout.contains("yt-download.py"));
    assert!(stderr.is_empty());
}

#[test]
fn version_is_successful() {
    let (status, stdout, stderr) = run("--version");
    assert_eq!(status, 0);
    assert_eq!(
        stdout.trim(),
        concat!("yt-download-rs ", env!("CARGO_PKG_VERSION"))
    );
    assert!(stderr.is_empty());
}

#[test]
fn unimplemented_commands_fail_closed() {
    let (status, stdout, stderr) = run("https://example.invalid/video");
    assert_ne!(status, 0);
    assert!(stdout.is_empty());
    assert!(stderr.contains("not yet implemented"));
}
