//! Bounded stream decoding for explicitly framed progress records.
//!
//! Unrelated output is discarded, including lines containing sensitive data.
//! An oversized line is discarded through its next newline without allocating
//! proportionally to the process output. The caller owns stream plumbing.

use std::io::{self, Read};

use crate::lifecycle::Progress;
use crate::process_output::{MAX_PROGRESS_LINE_BYTES, parse_progress_line};

/// Maximum number of bytes read from the child in one operation.
const READ_CHUNK_BYTES: usize = 4096;

/// Consume a stream and deliver valid progress records in their original order.
///
/// Invalid framed records are ignored rather than surfaced as potentially
/// sensitive diagnostics. A read error is returned to the caller. This function
/// must run on a reader separate from the child wait loop to prevent pipe stalls.
/// Callers should use a bounded, non-blocking event queue if the receiver may
/// stop consuming events during cancellation.
pub fn read_progress_stream(
    reader: &mut impl Read,
    mut emit: impl FnMut(Progress),
) -> io::Result<()> {
    let mut chunk = [0_u8; READ_CHUNK_BYTES];
    let mut line = Vec::with_capacity(MAX_PROGRESS_LINE_BYTES);
    let mut discarding = false;
    loop {
        let count = reader.read(&mut chunk)?;
        if count == 0 {
            if !discarding {
                emit_line(&line, &mut emit);
            }
            return Ok(());
        }
        for &byte in &chunk[..count] {
            if byte == b'\n' {
                if !discarding {
                    emit_line(&line, &mut emit);
                }
                line.clear();
                discarding = false;
            } else if !discarding {
                if line.len() < MAX_PROGRESS_LINE_BYTES {
                    line.push(byte);
                } else {
                    line.clear();
                    discarding = true;
                }
            }
        }
    }
}

fn emit_line(line: &[u8], emit: &mut impl FnMut(Progress)) {
    if let Ok(value) = std::str::from_utf8(line)
        && let Ok(Some(progress)) = parse_progress_line(value)
    {
        emit(progress);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_chunked_records_and_unterminated_final_record() {
        let input =
            b"unrelated secret\nYT_MEDIA_TOOLS_PROGRESS:3,10\r\nYT_MEDIA_TOOLS_PROGRESS:5,NA";
        let mut values = Vec::new();
        read_progress_stream(&mut &input[..], |progress| values.push(progress)).unwrap();
        assert_eq!(
            values,
            vec![
                Progress {
                    completed_bytes: 3,
                    total_bytes: Some(10)
                },
                Progress {
                    completed_bytes: 5,
                    total_bytes: None
                },
            ]
        );
    }

    #[test]
    fn oversized_and_invalid_lines_do_not_poison_following_progress() {
        let input = format!(
            "{}\nYT_MEDIA_TOOLS_PROGRESS:4,2\nYT_MEDIA_TOOLS_PROGRESS:6,10\n",
            "s".repeat(50_000)
        );
        let mut values = Vec::new();
        read_progress_stream(&mut input.as_bytes(), |progress| values.push(progress)).unwrap();
        assert_eq!(
            values,
            vec![Progress {
                completed_bytes: 6,
                total_bytes: Some(10)
            }]
        );
    }

    #[test]
    fn rejects_invalid_utf8_without_losing_stream_alignment() {
        let mut input = b"YT_MEDIA_TOOLS_PROGRESS:".to_vec();
        input.push(255);
        input.extend_from_slice(b",10\nYT_MEDIA_TOOLS_PROGRESS:7,10\n");
        let mut values = Vec::new();
        read_progress_stream(&mut input.as_slice(), |progress| values.push(progress)).unwrap();
        assert_eq!(
            values,
            vec![Progress {
                completed_bytes: 7,
                total_bytes: Some(10)
            }]
        );
    }
}
