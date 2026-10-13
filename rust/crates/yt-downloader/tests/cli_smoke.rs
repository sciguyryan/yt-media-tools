use std::process::Command;

fn run(arg: &str) -> std::process::Output {
    Command::new(env!("CARGO_BIN_EXE_yt-download-rs"))
        .arg(arg)
        .output()
        .expect("run experimental Downloader")
}

#[test]
fn help_is_successful_and_explains_status() {
    let output = run("--help");
    assert!(output.status.success());
    let stdout = String::from_utf8(output.stdout).expect("UTF-8 help output");
    assert!(stdout.contains("experimental"));
    assert!(stdout.contains("yt-download.py"));
    assert!(output.stderr.is_empty());
}

#[test]
fn version_is_successful() {
    let output = run("--version");
    assert!(output.status.success());
    let stdout = String::from_utf8(output.stdout).expect("UTF-8 version output");
    assert_eq!(
        stdout.trim(),
        concat!("yt-download-rs ", env!("CARGO_PKG_VERSION"))
    );
    assert!(output.stderr.is_empty());
}

#[test]
fn unimplemented_commands_fail_closed() {
    let output = run("https://example.invalid/video");
    assert!(!output.status.success());
    assert!(output.stdout.is_empty());
    let stderr = String::from_utf8(output.stderr).expect("UTF-8 diagnostic");
    assert!(stderr.contains("not yet implemented"));
}
