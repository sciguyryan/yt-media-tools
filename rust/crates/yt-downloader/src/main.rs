//! Native Downloader entry point.

use std::env;
use std::io::{self, Write};
use std::process::ExitCode;

fn main() -> ExitCode {
    let args: Vec<_> = env::args_os().skip(1).collect();
    let (status, stdout, stderr) = yt_downloader::experimental_cli(&args);
    if io::stdout().write_all(stdout.as_bytes()).is_err()
        || io::stderr().write_all(stderr.as_bytes()).is_err()
    {
        return ExitCode::FAILURE;
    }
    ExitCode::from(status)
}
