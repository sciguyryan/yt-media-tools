//! Bounded yt-dlp metadata decoding without acquisition side effects.
//!
//! This module recognises a deliberately small stable subset of the JSON
//! returned by `--dump-single-json`. It does not infer download policy from
//! metadata, and it never retains arbitrary provider fields or raw output.

use serde_json::Value;

/// Maximum metadata document accepted by the native adapter (8 MiB).
pub const MAX_METADATA_BYTES: usize = 8 * 1024 * 1024;

/// A minimal, validated media identity for subsequent acquisition planning.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MediaMetadata {
    /// Extractor-defined media identifier.
    pub id: String,
    /// Optional human-readable title.
    pub title: Option<String>,
    /// Duration in whole seconds, when known.
    pub duration_seconds: Option<u64>,
    /// Extractor name when supplied.
    pub extractor: Option<String>,
}

/// Failure categories do not contain raw metadata or sensitive URLs.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MetadataError {
    /// The input exceeds the configured resource boundary.
    TooLarge,
    /// The output is not one valid JSON document.
    InvalidJson,
    /// The result is not a single video-like metadata record.
    UnsupportedRecord,
    /// A required identity is absent or malformed.
    InvalidIdentity,
    /// A recognised optional field has an invalid type or value.
    InvalidField,
}

/// Decode one complete metadata document without retaining unknown fields.
///
/// Playlist and collection results are rejected rather than silently
/// selecting the first entry or claiming single-item equivalence.
pub fn decode_metadata(bytes: &[u8]) -> Result<MediaMetadata, MetadataError> {
    if bytes.len() > MAX_METADATA_BYTES {
        return Err(MetadataError::TooLarge);
    }
    let value: Value = serde_json::from_slice(bytes).map_err(|_| MetadataError::InvalidJson)?;
    let object = value.as_object().ok_or(MetadataError::UnsupportedRecord)?;
    if object.contains_key("entries")
        || object
            .get("_type")
            .and_then(Value::as_str)
            .is_some_and(|kind| kind != "video")
    {
        return Err(MetadataError::UnsupportedRecord);
    }
    let id = object
        .get("id")
        .and_then(Value::as_str)
        .filter(|id| !id.trim().is_empty() && id.len() <= 4096)
        .ok_or(MetadataError::InvalidIdentity)?;
    let title = optional_text(object.get("title"))?;
    let extractor = optional_text(object.get("extractor"))?;
    let duration_seconds = match object.get("duration") {
        None | Some(Value::Null) => None,
        Some(value) => {
            let duration = value.as_u64().ok_or(MetadataError::InvalidField)?;
            Some(duration)
        }
    };
    Ok(MediaMetadata {
        id: id.to_owned(),
        title,
        duration_seconds,
        extractor,
    })
}

fn optional_text(value: Option<&Value>) -> Result<Option<String>, MetadataError> {
    match value {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(text)) if text.len() <= 4096 => Ok(Some(text.clone())),
        _ => Err(MetadataError::InvalidField),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn decodes_known_fields_without_retaining_provider_payloads() {
        let record = decode_metadata(br#"{"id":"abc","title":"Example","duration":42,"extractor":"youtube","webpage_url":"https://secret.example/"}"#).unwrap();
        assert_eq!(
            record,
            MediaMetadata {
                id: "abc".into(),
                title: Some("Example".into()),
                duration_seconds: Some(42),
                extractor: Some("youtube".into())
            }
        );
    }

    #[test]
    fn accepts_missing_optional_values() {
        let record = decode_metadata(br#"{"id":"abc","title":null,"duration":null}"#).unwrap();
        assert_eq!(record.duration_seconds, None);
        assert_eq!(record.title, None);
    }

    #[test]
    fn rejects_collection_and_malformed_records() {
        assert_eq!(
            decode_metadata(br#"{"_type":"playlist","id":"p","entries":[]}"#),
            Err(MetadataError::UnsupportedRecord)
        );
        assert_eq!(
            decode_metadata(br#"{"id":" "}"#),
            Err(MetadataError::InvalidIdentity)
        );
        assert_eq!(
            decode_metadata(br#"{"id":"x","duration":-1}"#),
            Err(MetadataError::InvalidField)
        );
        assert_eq!(
            decode_metadata(br#"{"id":"x","title":12}"#),
            Err(MetadataError::InvalidField)
        );
        assert_eq!(
            decode_metadata(b"not json"),
            Err(MetadataError::InvalidJson)
        );
    }

    #[test]
    fn enforces_bounded_document_size() {
        assert_eq!(
            decode_metadata(&vec![b' '; MAX_METADATA_BYTES + 1]),
            Err(MetadataError::TooLarge)
        );
    }
}
