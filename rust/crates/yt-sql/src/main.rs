//! Adapter-protocol binary: `observe <case> <configuration> <root>` prints the
//! observation JSON on stdout, or exits non-zero with a message on stderr when
//! the case cannot be faithfully executed.

fn main() {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    if arguments.len() != 4 || arguments[0] != "observe" {
        eprintln!("usage: yt-sql-conformance observe <case> <configuration> <root>");
        std::process::exit(2);
    }
    match yt_sql::observe::observe(&arguments[1], &arguments[2], &arguments[3]) {
        Ok(observation) => {
            println!("{observation}");
        }
        Err(message) => {
            eprintln!("{message}");
            std::process::exit(1);
        }
    }
}
