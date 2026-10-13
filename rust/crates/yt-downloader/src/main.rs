//! Experimental native Downloader entry point.
//! Python remains the production implementation.

use std::env;
use std::process::ExitCode;

const VERSION: &str = env!("CARGO_PKG_VERSION");

fn main() -> ExitCode {
    let mut args = env::args_os();
    let _program = args.next();
    match (args.next(), args.next()) {
        (Some(arg), None) if arg == "--version" => {
            println!("yt-download-rs {VERSION}");
            ExitCode::SUCCESS
        }
        (Some(arg), None) if arg == "--help" || arg == "-h" => {
            println!(
                "yt-download-rs (experimental)\n\nUSAGE:\n    yt-download-rs [--help | --version]\n\nThe native downloader is under development. Use yt-download.py for downloads."
            );
            ExitCode::SUCCESS
        }
        _ => {
            eprintln!(
                "yt-download-rs: download functionality is not yet implemented; use yt-download.py"
            );
            ExitCode::FAILURE
        }
    }
}
