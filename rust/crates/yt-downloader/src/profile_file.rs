//! Profile document parsing and resolution.
//!
//! Option-specific validation is handled separately.
use serde_json::{Map, Value};
use std::collections::BTreeMap;

use crate::valid_profile_name;

/// Errors encountered while reading or resolving a profile document.
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
    InvalidValueReference(String),
    UnknownValueReference(String),
    ValueReferenceCycle(Vec<String>),
}

/// A parsed profile document before references and inheritance are resolved.
#[derive(Debug, Clone, PartialEq)]
pub struct RawProfileFile {
    /// Profile format version declared by the document.
    pub version: u8,
    /// Named values available to `$values` references.
    pub values: Map<String, Value>,
    /// Settings applied before individual profiles and their ancestors.
    pub defaults: Map<String, Value>,
    /// Profile definitions, indexed by their declared names.
    pub profiles: Map<String, Value>,
}

/// Validate only the outer v3 shape and the inheritance graph.
/// Callers must not mistake this for a fully resolved or validated policy.
pub fn parse_profile_structure(json: &str) -> Result<RawProfileFile, ProfileFileError> {
    let value: Value = serde_json::from_str(json.trim_start_matches('\u{feff}'))
        .map_err(|_| ProfileFileError::InvalidJson)?;
    let root = value.as_object().ok_or(ProfileFileError::InvalidRoot)?;

    let version = match root.get("version") {
        Some(Value::Number(n)) if n.as_u64() == Some(3) => 3,
        _ => return Err(ProfileFileError::InvalidVersion),
    };

    for key in root.keys() {
        if !matches!(key.as_str(), "version" | "profiles" | "values") && key != "$defaults" {
            return Err(ProfileFileError::UnknownRootKey(key.clone()));
        }
    }

    let values = optional_object(root, "values", ProfileFileError::InvalidValues)?;
    let defaults = optional_object(root, "$defaults", ProfileFileError::InvalidDefaults)?;

    let profiles = root
        .get("profiles")
        .and_then(Value::as_object)
        .ok_or(ProfileFileError::InvalidProfiles)?
        .clone();

    for (name, raw) in &profiles {
        if !valid_profile_name(name) {
            return Err(ProfileFileError::InvalidProfileName(name.clone()));
        }

        let fields = raw
            .as_object()
            .ok_or_else(|| ProfileFileError::InvalidProfile(name.clone()))?;
        if let Some(parent) = fields.get("parent") {
            let parent = parent
                .as_str()
                .ok_or_else(|| ProfileFileError::InvalidParent(name.clone()))?;
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
    Ok(RawProfileFile {
        version,
        values,
        defaults,
        profiles,
    })
}

/// A resolved profile before option-specific type and policy validation.
#[derive(Debug, Clone, PartialEq)]
pub struct ResolvedProfile {
    /// Effective JSON settings after defaults, inheritance and references.
    pub settings: Map<String, Value>,
    /// Immediate parent profile, when one is declared.
    pub parent: Option<String>,
    /// Ancestors in inheritance order, from the oldest to the immediate parent.
    pub ancestry: Vec<String>,
    /// Origin of each effective setting, for diagnostics and inspection.
    pub setting_sources: BTreeMap<String, String>,
}

/// Resolve reusable values and single-parent inheritance without changing JSON value types.
/// The returned settings still require Downloader-specific option validation.
pub fn resolve_profile_structure(
    raw: &RawProfileFile,
) -> Result<BTreeMap<String, ResolvedProfile>, ProfileFileError> {
    let defaults = resolve_settings(&raw.defaults, &raw.values)?;
    let mut result = BTreeMap::new();

    for name in raw.profiles.keys() {
        resolve_profile(name, raw, &defaults, &mut result, &mut Vec::new())?;
    }
    Ok(result)
}

fn resolve_profile(
    name: &str,
    raw: &RawProfileFile,
    defaults: &Map<String, Value>,
    result: &mut BTreeMap<String, ResolvedProfile>,
    stack: &mut Vec<String>,
) -> Result<(), ProfileFileError> {
    if result.contains_key(name) {
        return Ok(());
    }

    if let Some(index) = stack.iter().position(|entry| entry == name) {
        let mut cycle = stack[index..].to_vec();
        cycle.push(name.to_owned());
        return Err(ProfileFileError::InheritanceCycle(cycle));
    }
    stack.push(name.to_owned());

    let fields = raw
        .profiles
        .get(name)
        .and_then(Value::as_object)
        .ok_or_else(|| ProfileFileError::InvalidProfile(name.to_owned()))?;
    let parent = fields
        .get("parent")
        .and_then(Value::as_str)
        .map(str::to_owned);
    let mut settings = defaults.clone();
    let mut sources: BTreeMap<String, String> = defaults
        .keys()
        .map(|key| (key.clone(), "$defaults".to_owned()))
        .collect();
    let mut ancestry = Vec::new();

    if let Some(ref parent_name) = parent {
        if !raw.profiles.contains_key(parent_name) {
            return Err(ProfileFileError::MissingParent(parent_name.clone()));
        }

        resolve_profile(parent_name, raw, defaults, result, stack)?;
        let inherited = &result[parent_name];
        settings.extend(inherited.settings.clone());
        sources.extend(inherited.setting_sources.clone());
        ancestry.extend(inherited.ancestry.clone());
        ancestry.push(parent_name.clone());
    }

    let own: Map<String, Value> = fields
        .iter()
        .filter(|(key, _)| key.as_str() != "parent")
        .map(|(key, value)| (key.clone(), value.clone()))
        .collect();
    let own = resolve_settings(&own, &raw.values)?;

    for (key, value) in own {
        sources.insert(key.clone(), format!("profile '{name}'"));
        settings.insert(key, value);
    }

    stack.pop();
    result.insert(
        name.to_owned(),
        ResolvedProfile {
            settings,
            parent,
            ancestry,
            setting_sources: sources,
        },
    );
    Ok(())
}

fn resolve_settings(
    settings: &Map<String, Value>,
    values: &Map<String, Value>,
) -> Result<Map<String, Value>, ProfileFileError> {
    settings
        .iter()
        .map(|(key, value)| {
            resolve_value(value, values, &mut Vec::new()).map(|resolved| (key.clone(), resolved))
        })
        .collect()
}

fn resolve_value(
    value: &Value,
    values: &Map<String, Value>,
    chain: &mut Vec<String>,
) -> Result<Value, ProfileFileError> {
    match value {
        Value::String(text) if text.starts_with("$$") => Ok(Value::String(text[1..].to_owned())),
        Value::String(text) if text.starts_with('$') => {
            let Some(path) = text.strip_prefix("$values.") else {
                return Err(ProfileFileError::InvalidValueReference(text.clone()));
            };
            if path.is_empty()
                || path.split('.').any(|segment| {
                    segment.is_empty()
                        || !segment
                            .bytes()
                            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-'))
                })
            {
                return Err(ProfileFileError::InvalidValueReference(text.clone()));
            }

            if let Some(index) = chain.iter().position(|entry| entry == text) {
                let mut cycle = chain[index..].to_vec();
                cycle.push(text.clone());
                return Err(ProfileFileError::ValueReferenceCycle(cycle));
            }

            let mut current = values.get(path.split('.').next().unwrap());
            for segment in path.split('.').skip(1) {
                current = current
                    .and_then(Value::as_object)
                    .and_then(|map| map.get(segment));
            }

            let current =
                current.ok_or_else(|| ProfileFileError::UnknownValueReference(text.clone()))?;

            chain.push(text.clone());
            let resolved = resolve_value(current, values, chain);
            chain.pop();
            resolved
        }
        Value::Array(items) => items
            .iter()
            .map(|item| resolve_value(item, values, chain))
            .collect::<Result<Vec<_>, _>>()
            .map(Value::Array),
        Value::Object(items) => items
            .iter()
            .map(|(key, item)| {
                resolve_value(item, values, chain).map(|resolved| (key.clone(), resolved))
            })
            .collect::<Result<Map<_, _>, _>>()
            .map(Value::Object),
        _ => Ok(value.clone()),
    }
}

fn optional_object(
    root: &Map<String, Value>,
    key: &str,
    error: ProfileFileError,
) -> Result<Map<String, Value>, ProfileFileError> {
    match root.get(key) {
        None => Ok(Map::new()),
        Some(Value::Object(map)) => Ok(map.clone()),
        _ => Err(error),
    }
}

fn visit(
    name: &str,
    profiles: &Map<String, Value>,
    complete: &mut std::collections::BTreeSet<String>,
    stack: &mut Vec<String>,
) -> Result<(), ProfileFileError> {
    if complete.contains(name) {
        return Ok(());
    }

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
    fn accepts_current_structure_only() {
        assert_eq!(
            parse_profile_structure(r#"{"version":2,"profiles":{"default":{}}}"#),
            Err(ProfileFileError::InvalidVersion)
        );
        assert_eq!(parse_profile_structure(r#"{"version":3,"$defaults":{},"values":{},"profiles":{"child":{"parent":"base"},"base":{}}}"#).unwrap().version, 3);
    }
    #[test]
    fn rejects_unknown_keys_and_wrong_types() {
        assert_eq!(
            parse_profile_structure(r#"{"version":2,"$defaults":{},"profiles":{}}"#),
            Err(ProfileFileError::InvalidVersion)
        );
        assert_eq!(
            parse_profile_structure(r#"{"version":3,"profiles":[],"values":{}}"#),
            Err(ProfileFileError::InvalidProfiles)
        );
        assert_eq!(
            parse_profile_structure(r#"{"version":3,"profiles":{},"values":null}"#),
            Err(ProfileFileError::InvalidValues)
        );
    }
    #[test]
    fn detects_missing_parents_and_cycles() {
        assert_eq!(
            parse_profile_structure(r#"{"version":3,"profiles":{"a":{"parent":"missing"}}}"#),
            Err(ProfileFileError::MissingParent("missing".into()))
        );
        assert!(matches!(
            parse_profile_structure(
                r#"{"version":3,"profiles":{"a":{"parent":"b"},"b":{"parent":"a"}}}"#
            ),
            Err(ProfileFileError::InheritanceCycle(_))
        ));
    }
    #[test]
    fn resolves_references_in_nested_values_and_escaped_dollars() {
        let raw = parse_profile_structure(r#"{"version":3,"values":{"formats":{"best":["mp4",7]},"alias":"$values.formats.best"},"$defaults":{"format":"$values.alias","literal":"$$values.alias"},"profiles":{"base":{"extra":{"nested":["$values.formats.best",true]}}}}"#).unwrap();
        let profiles = resolve_profile_structure(&raw).unwrap();
        let settings = &profiles["base"].settings;
        assert_eq!(settings["format"], serde_json::json!(["mp4", 7]));
        assert_eq!(settings["literal"], "$values.alias");
        assert_eq!(
            settings["extra"],
            serde_json::json!({"nested":[["mp4",7],true]})
        );
    }
    #[test]
    fn resolves_inheritance_with_sources_and_ancestry() {
        let raw = parse_profile_structure(r#"{"version":3,"$defaults":{"a":1,"b":2},"profiles":{"root":{"b":3},"middle":{"parent":"root","c":4},"leaf":{"parent":"middle","a":5}}}"#).unwrap();
        let profiles = resolve_profile_structure(&raw).unwrap();
        let leaf = &profiles["leaf"];
        assert_eq!(
            leaf.settings,
            serde_json::from_str::<Map<String, Value>>(r#"{"a":5,"b":3,"c":4}"#).unwrap()
        );
        assert_eq!(leaf.ancestry, vec!["root", "middle"]);
        assert_eq!(leaf.setting_sources["a"], "profile 'leaf'");
        assert_eq!(leaf.setting_sources["b"], "profile 'root'");
        assert_eq!(leaf.setting_sources["c"], "profile 'middle'");
    }
    #[test]
    fn rejects_unknown_malformed_and_cyclic_references() {
        for reference in ["$values.missing", "$values.a.missing"] {
            let json = format!(
                r#"{{"version":3,"values":{{"a":1}},"profiles":{{"p":{{"a":"{reference}"}}}}}}"#
            );
            assert!(matches!(
                resolve_profile_structure(&parse_profile_structure(&json).unwrap()),
                Err(ProfileFileError::UnknownValueReference(_))
            ));
        }

        let raw =
            parse_profile_structure(r#"{"version":3,"profiles":{"p":{"a":"$other.a"}}}"#).unwrap();
        assert!(matches!(
            resolve_profile_structure(&raw),
            Err(ProfileFileError::InvalidValueReference(_))
        ));
        let raw = parse_profile_structure(r#"{"version":3,"values":{"a":"$values.b","b":"$values.a"},"profiles":{"p":{"a":"$values.a"}}}"#).unwrap();
        assert!(matches!(
            resolve_profile_structure(&raw),
            Err(ProfileFileError::ValueReferenceCycle(_))
        ));
    }
    #[test]
    fn rejects_invalid_names_and_versions() {
        assert_eq!(
            parse_profile_structure(r#"{"version":4,"profiles":{}}"#),
            Err(ProfileFileError::InvalidVersion)
        );
        assert_eq!(
            parse_profile_structure(r#"{"version":3,"profiles":{".hidden":{}}}"#),
            Err(ProfileFileError::InvalidProfileName(".hidden".into()))
        );
    }
}
