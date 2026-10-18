//! Bounded parsing of explicitly framed yt-dlp progress observations.
//!
//! This parser accepts only lines produced by a caller-configured progress
//! template. Arbitrary process output is never interpreted as progress or
//! included in diagnostics. Stream capture and child integration follow later.

use crate::lifecycle::Progress;

/// Prefix reserved for the native adapter's progress template.
pub const PROGRESS_PREFIX: &str = "YT_MEDIA_TOOLS_PROGRESS:";
/// Maximum permitted size of a single progress record, in bytes.
pub const MAX_PROGRESS_LINE_BYTES: usize = 256;

/// A progress record that cannot be safely interpreted.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ProgressParseError {
    /// The record exceeds the permitted byte count.
    TooLong,
    /// The record is framed but malformed or has an invalid numeric value.
    InvalidRecord,
}

/// Parse a single progress line without retaining arbitrary process output.
///
/// Returns `None` for unrelated stdout/stderr lines. A recognised record must
/// contain exactly two comma-separated fields: completed bytes and either the
/// total number of bytes or `NA` when yt-dlp does not know the total.
/// Invalid framed records are errors rather than silently reported as progress.
pub fn parse_progress_line(line: &str) -> Result<Option<Progress>, ProgressParseError> {
    if line.len() > MAX_PROGRESS_LINE_BYTES {
        return if line.starts_with(PROGRESS_PREFIX) {
            Err(ProgressParseError::TooLong)
        } else {
            Ok(None)
        };
    }
    let Some(payload) = line.strip_prefix(PROGRESS_PREFIX) else {
        return Ok(None);
    };
    let payload = payload.trim_end_matches('\r');
    let (completed, total) = payload
        .split_once(',')
        .ok_or(ProgressParseError::InvalidRecord)?;
    if total.contains(',')
        || completed.is_empty()
        || !completed.bytes().all(|byte| byte.is_ascii_digit())
    {
        return Err(ProgressParseError::InvalidRecord);
    }
    let completed_bytes = completed
        .parse::<u64>()
        .map_err(|_| ProgressParseError::InvalidRecord)?;
    let total_bytes = if total == "NA" {
        None
    } else {
        if total.is_empty() || !total.bytes().all(|byte| byte.is_ascii_digit()) {
            return Err(ProgressParseError::InvalidRecord);
        }
        Some(
            total
                .parse::<u64>()
                .map_err(|_| ProgressParseError::InvalidRecord)?,
        )
    };
    if total_bytes.is_some_and(|value| completed_bytes > value) {
        return Err(ProgressParseError::InvalidRecord);
    }
    Ok(Some(Progress {
        completed_bytes,
        total_bytes,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_known_and_unknown_totals() {
        assert_eq!(
            parse_progress_line("YT_MEDIA_TOOLS_PROGRESS:25,100"),
            Ok(Some(Progress {
                completed_bytes: 25,
                total_bytes: Some(100)
            }))
        );
        assert_eq!(
            parse_progress_line("YT_MEDIA_TOOLS_PROGRESS:25,NA\r"),
            Ok(Some(Progress {
                completed_bytes: 25,
                total_bytes: None
            }))
        );
        assert_eq!(
            parse_progress_line("YT_MEDIA_TOOLS_PROGRESS:0,0"),
            Ok(Some(Progress {
                completed_bytes: 0,
                total_bytes: Some(0)
            }))
        );
    }

    #[test]
    fn ignores_unrelated_output_without_interpreting_it() {
        assert_eq!(parse_progress_line("[download] 25%"), Ok(None));
        assert_eq!(
            parse_progress_line("YT_MEDIA_TOOLS_PROGRESS 25,100"),
            Ok(None)
        );
        assert_eq!(parse_progress_line(&"x".repeat(1024)), Ok(None));
    }

    #[test]
    fn rejects_malformed_or_unbounded_framed_records() {
        for line in [
            "YT_MEDIA_TOOLS_PROGRESS:",
            "YT_MEDIA_TOOLS_PROGRESS:1",
            "YT_MEDIA_TOOLS_PROGRESS:1,2,3",
            "YT_MEDIA_TOOLS_PROGRESS:-1,2",
            "YT_MEDIA_TOOLS_PROGRESS:2,1",
            "YT_MEDIA_TOOLS_PROGRESS:1,unknown",
            "YT_MEDIA_TOOLS_PROGRESS:18446744073709551616,NA",
            "YT_MEDIA_TOOLS_PROGRESS:1,18446744073709551616",
            "YT_MEDIA_TOOLS_PROGRESS:1,2\nother",
        ] {
            assert_eq!(
                parse_progress_line(line),
                Err(ProgressParseError::InvalidRecord),
                "{line:?}"
            );
        }
        let long_line = format!("{PROGRESS_PREFIX}{}", "1".repeat(MAX_PROGRESS_LINE_BYTES));
        assert_eq!(
            parse_progress_line(&long_line),
            Err(ProgressParseError::TooLong)
        );
    }
}
