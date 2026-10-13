//! Structural validation of versioned Downloader profile files.
//! Typed option validation and reference resolution are deliberately separate work.
use serde_json::{Map, Value};
use crate::valid_profile_name;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ProfileFileError {
    InvalidJson,
    InvalidRoot,
    InvalidVersion,
    UnknownRootKey(String),
    InvalidValues,
    InvalidProfiles,
    InvalidDefaults,
    InvalidProfileName(String),
    InvalidProfile(String),
    InvalidParent(String),
    MissingParent(String),
    InheritanceCycle(Vec<String>),
}

#[derive(Debug, Clone, PartialEq)]
pub struct RawProfileFile {
    pub version: u8,
    pub values: Map<String, Value>,
    pub defaults: Map<String, Value>,
    pub profiles: Map<String, Value>,
}

/// Validate only the outer v2/v3 shape and the inheritance graph.
/// Callers must not mistake this for a fully resolved or validated policy.
pub fn parse_profile_structure(json: &str) -> Result<RawProfileFile, ProfileFileError> {
    let value: Value = serde_json::from_str(json.trim_start_matches('\u{feff}'))
        .map_err(|_| ProfileFileError::InvalidJson)?;
    let root = value.as_object().ok_or(ProfileFileError::InvalidRoot)?;
    let version = match root.get("version") {
        Some(Value::Number(n)) if n.as_u64() == Some(2) => 2,
        Some(Value::Number(n)) if n.as_u64() == Some(3) => 3,
        _ => return Err(ProfileFileError::InvalidVersion),
    };
    for key in root.keys() {
        if !matches!(key.as_str(), "version" | "profiles" | "values")
            && !(version == 3 && key == "$defaults") {
            return Err(ProfileFileError::UnknownRootKey(key.clone()));
        }
    }
    let values = optional_object(root, "values", ProfileFileError::InvalidValues)?;
    let defaults = optional_object(root, "$defaults", ProfileFileError::InvalidDefaults)?;
    let profiles = root.get("profiles").and_then(Value::as_object)
        .ok_or(ProfileFileError::InvalidProfiles)?.clone();
    for (name, raw) in &profiles {
        if !valid_profile_name(name) {
            return Err(ProfileFileError::InvalidProfileName(name.clone()));
        }
        let fields = raw.as_object().ok_or_else(|| ProfileFileError::InvalidProfile(name.clone()))?;
        if let Some(parent) = fields.get("parent") {
            if version != 3 {
                return Err(ProfileFileError::InvalidParent(name.clone()));
            }
            let parent = parent.as_str().ok_or_else(|| ProfileFileError::InvalidParent(name.clone()))?;
            if !valid_profile_name(parent) {
                return Err(ProfileFileError::InvalidParent(name.clone()));
            }
            if !profiles.contains_key(parent) {
                return Err(ProfileFileError::MissingParent(parent.to_owned()));
            }
        }
    }
    // The Python implementation resolves profiles in case-folded name order.
    // Cycle membership is invariant under that order, so use a deterministic sorted traversal.
    let mut complete = std::collections::BTreeSet::new();
    for name in profiles.keys() {
        visit(name, &profiles, &mut complete, &mut Vec::new())?;
    }
    Ok(RawProfileFile { version, values, defaults, profiles })
}

fn optional_object(root: &Map<String, Value>, key: &str, error: ProfileFileError)
    -> Result<Map<String, Value>, ProfileFileError> {
    match root.get(key) {
        None => Ok(Map::new()),
        Some(Value::Object(map)) => Ok(map.clone()),
        _ => Err(error),
    }
}

fn visit(name: &str, profiles: &Map<String, Value>,
    complete: &mut std::collections::BTreeSet<String>, stack: &mut Vec<String>)
    -> Result<(), ProfileFileError> {
    if complete.contains(name) { return Ok(()); }
    if let Some(index) = stack.iter().position(|item| item == name) {
        let mut cycle = stack[index..].to_vec();
        cycle.push(name.to_owned());
        return Err(ProfileFileError::InheritanceCycle(cycle));
    }
    stack.push(name.to_owned());
    if let Some(parent) = profiles[name].get("parent").and_then(Value::as_str) {
        visit(parent, profiles, complete, stack)?;
    }
    stack.pop();
    complete.insert(name.to_owned());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn accepts_legacy_and_current_structures() {
        assert_eq!(parse_profile_structure(r#"{"version":2,"profiles":{"default":{}}}"#).unwrap().version, 2);
        assert_eq!(parse_profile_structure(r#"{"version":3,"$defaults":{},"values":{},"profiles":{"child":{"parent":"base"},"base":{}}}"#).unwrap().version, 3);
    }
    #[test]
    fn rejects_unknown_keys_and_wrong_types() {
        assert_eq!(parse_profile_structure(r#"{"version":2,"$defaults":{},"profiles":{}}"#), Err(ProfileFileError::UnknownRootKey("$defaults".into())));
        assert_eq!(parse_profile_structure(r#"{"version":3,"profiles":[],"values":{}}"#), Err(ProfileFileError::InvalidProfiles));
        assert_eq!(parse_profile_structure(r#"{"version":3,"profiles":{},"values":null}"#), Err(ProfileFileError::InvalidValues));
    }
    #[test]
    fn detects_missing_parents_and_cycles() {
        assert_eq!(parse_profile_structure(r#"{"version":3,"profiles":{"a":{"parent":"missing"}}}"#), Err(ProfileFileError::MissingParent("missing".into())));
        assert!(matches!(parse_profile_structure(r#"{"version":3,"profiles":{"a":{"parent":"b"},"b":{"parent":"a"}}}"#), Err(ProfileFileError::InheritanceCycle(_))));
    }
    #[test]
    fn rejects_invalid_names_and_versions() {
        assert_eq!(parse_profile_structure(r#"{"version":4,"profiles":{}}"#), Err(ProfileFileError::InvalidVersion));
        assert_eq!(parse_profile_structure(r#"{"version":3,"profiles":{".hidden":{}}}"#), Err(ProfileFileError::InvalidProfileName(".hidden".into())));
    }
}
