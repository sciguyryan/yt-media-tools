//! Compose validated target sources and effective profile policy for planning.
//!
//! An invocation context describes the inputs to a future execution plan. It
//! does not construct yt-dlp arguments, read target contents or start a process.

use std::collections::BTreeMap;

use serde_json::{Map, Value};

use crate::profile_selection::{ProfileSelectionError, SelectedProfile, select_profile};
use crate::profile_settings::ValidatedProfile;
use crate::targets::{TargetError, TargetRequest, TargetSource, resolve_targets};

/// Validated inputs for a subsequent, side-effect-free execution planner.
#[derive(Debug, Clone, PartialEq)]
pub struct InvocationContext {
    /// Target source, preserving the ordering of direct targets.
    pub source: TargetSource,
    /// Effective validated policy and its profile/override provenance.
    pub policy: SelectedProfile,
}

/// Failure to resolve either half of an invocation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum InvocationError {
    /// The requested target source is invalid or not yet supported.
    Target(TargetError),
    /// Profile selection or combined policy validation failed.
    Policy(ProfileSelectionError),
}

/// Combine an already validated profile store, explicit overrides and targets.
///
/// Both inputs are resolved before constructing the context. A missing profile
/// or unsupported setting is never treated as an implicit default. The caller
/// remains responsible for loading and validating its profile document.
/// No download operation or target-file read is performed.
pub fn prepare_invocation(
    request: &TargetRequest,
    profiles: &BTreeMap<String, ValidatedProfile>,
    requested_profile: Option<&str>,
    overrides: &Map<String, Value>,
) -> Result<InvocationContext, InvocationError> {
    let selected_name =
        requested_profile.or_else(|| profiles.contains_key("default").then_some("default"));
    let policy =
        select_profile(profiles, selected_name, overrides).map_err(InvocationError::Policy)?;
    let source = resolve_targets(request).map_err(InvocationError::Target)?;

    Ok(InvocationContext { source, policy })
}

/// Return the underlying selection error when a policy failure concerns selection.
pub fn selection_error(error: &InvocationError) -> Option<&ProfileSelectionError> {
    match error {
        InvocationError::Policy(error) => Some(error),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    use std::path::PathBuf;

    use serde_json::json;

    use crate::profile_pipeline::load_validated_profiles;

    fn request(targets: &[&str]) -> TargetRequest {
        TargetRequest {
            targets: targets.iter().map(|value| (*value).to_owned()).collect(),
            input_file: None,
            collection_file: None,
            default_input_file: PathBuf::from("/missing-invocation-default-batch"),
        }
    }

    fn profiles() -> BTreeMap<String, ValidatedProfile> {
        load_validated_profiles(
            &json!({
                "version": 3,
                "$defaults": {"playlist": true},
                "profiles": {
                    "default": {"audio-format": "mp3"},
                    "alternate": {"audio-format": "opus"}
                }
            })
            .to_string(),
        )
        .unwrap()
    }

    #[test]
    fn selects_default_policy_and_preserves_target_order() {
        let context =
            prepare_invocation(&request(&["b", "a", "b"]), &profiles(), None, &Map::new()).unwrap();

        assert_eq!(
            context.source,
            TargetSource::Direct(vec!["b".into(), "a".into(), "b".into()])
        );
        assert_eq!(context.policy.profile_name.as_deref(), Some("default"));
        assert_eq!(context.policy.settings["playlist"], true);
        assert_eq!(context.policy.setting_sources["playlist"], "$defaults");
    }

    #[test]
    fn explicit_selection_and_overrides_keep_provenance() {
        let overrides = json!({"playlist": false});
        let context = prepare_invocation(
            &request(&["video"]),
            &profiles(),
            Some("alternate"),
            overrides.as_object().unwrap(),
        )
        .unwrap();

        assert_eq!(context.policy.profile_name.as_deref(), Some("alternate"));
        assert_eq!(context.policy.settings["audio-format"], "opus");
        assert_eq!(context.policy.settings["playlist"], false);
        assert_eq!(
            context.policy.setting_sources["playlist"],
            "explicit override"
        );
    }

    #[test]
    fn invalid_policy_is_not_silently_ignored() {
        let overrides = json!({"unrecognised-setting": true});
        assert!(matches!(
            prepare_invocation(
                &request(&["video"]),
                &profiles(),
                None,
                overrides.as_object().unwrap()
            ),
            Err(InvocationError::Policy(
                ProfileSelectionError::InvalidSettings(_)
            ))
        ));
    }

    #[test]
    fn target_conflicts_remain_explicit() {
        let mut target = request(&["video"]);
        target.input_file = Some(PathBuf::from("batch.txt"));
        assert_eq!(
            prepare_invocation(&target, &profiles(), None, &Map::new()),
            Err(InvocationError::Target(TargetError::ConflictingSources(
                "--input-file"
            )))
        );
    }

    #[test]
    fn collection_resolution_remains_unavailable() {
        let mut target = request(&[]);
        target.collection_file = Some(PathBuf::from("collection.json"));
        assert_eq!(
            prepare_invocation(&target, &profiles(), None, &Map::new()),
            Err(InvocationError::Target(
                TargetError::CollectionRequiresResolver
            ))
        );
    }
}
