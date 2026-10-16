//! Construct inspectable yt-dlp argument plans without executing external tools.
//!
//! Only settings with an explicit, reviewed argument mapping are accepted.
//! Validated settings without a mapping fail closed rather than disappearing
//! from the plan. Further policy translation belongs to later implementation.

use serde_json::Value;

use crate::invocation::InvocationContext;
use crate::targets::TargetSource;

/// A deterministic argument plan, excluding the executable path.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExecutionPlan {
    /// Arguments to pass directly to yt-dlp, in their planned order.
    pub arguments: Vec<String>,
    /// The validated target source used to construct the argument suffix.
    pub source: TargetSource,
}

/// A setting cannot yet be translated without risking a change of meaning.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PlanningError {
    /// No reviewed yt-dlp mapping exists for this setting.
    UnsupportedSetting(String),
    /// The validated setting unexpectedly has a different JSON representation.
    InvalidSetting(String),
}

/// Build a side-effect-free plan from an already validated invocation.
///
/// The planner does not read input files, resolve media metadata, invoke yt-dlp,
/// or imply that the resulting arguments are ready for a production download.
/// Settings are visited in lexical order for reproducible diagnostics and output.
/// The target suffix preserves positional order and duplicates.
pub fn plan_invocation(context: &InvocationContext) -> Result<ExecutionPlan, PlanningError> {
    let mut arguments = Vec::new();
    let mut settings: Vec<_> = context.policy.settings.iter().collect();
    settings.sort_by(|left, right| left.0.cmp(right.0));

    for (name, value) in settings {
        let option = match name.as_str() {
            "playlist" => Some(("--yes-playlist", "--no-playlist")),
            "write-info-json" => Some(("--write-info-json", "--no-write-info-json")),
            "write-thumbnail" => Some(("--write-thumbnail", "--no-write-thumbnail")),
            "write-subs" => Some(("--write-subs", "--no-write-subs")),
            "write-auto-subs" => Some(("--write-auto-subs", "--no-write-auto-subs")),
            _ => None,
        };
        let Some((positive, negative)) = option else {
            return Err(PlanningError::UnsupportedSetting(name.clone()));
        };
        match value {
            Value::Bool(enabled) => {
                arguments.push(if *enabled { positive } else { negative }.to_owned())
            }
            _ => return Err(PlanningError::InvalidSetting(name.clone())),
        }
    }

    context.source.append_arguments(&mut arguments);
    Ok(ExecutionPlan {
        arguments,
        source: context.source.clone(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    use std::collections::BTreeMap;

    use serde_json::{Map, json};

    use crate::profile_selection::SelectedProfile;

    fn context(source: TargetSource, settings: Value) -> InvocationContext {
        InvocationContext {
            source,
            policy: SelectedProfile {
                settings: settings.as_object().cloned().unwrap_or_else(Map::new),
                profile_name: None,
                ancestry: Vec::new(),
                setting_sources: BTreeMap::new(),
            },
        }
    }

    #[test]
    fn direct_targets_are_escaped_and_preserve_duplicates() {
        let input = context(
            TargetSource::Direct(vec!["--odd".into(), "same".into(), "same".into()]),
            json!({}),
        );
        let plan = plan_invocation(&input).unwrap();
        assert_eq!(plan.arguments, ["--", "--odd", "same", "same"]);
        assert_eq!(plan.source, input.source);
    }

    #[test]
    fn batch_and_standard_input_keep_distinct_sources() {
        let batch = context(TargetSource::BatchFile("queue.txt".into()), json!({}));
        assert_eq!(
            plan_invocation(&batch).unwrap().arguments,
            ["--batch-file", "queue.txt"]
        );
        let stdin = context(TargetSource::Stdin, json!({}));
        assert_eq!(
            plan_invocation(&stdin).unwrap().arguments,
            ["--batch-file", "-"]
        );
    }

    #[test]
    fn supported_switches_have_deterministic_order_and_polarity() {
        let input = context(
            TargetSource::Direct(vec!["video".into()]),
            json!({"write-subs": false, "playlist": true}),
        );
        assert_eq!(
            plan_invocation(&input).unwrap().arguments,
            ["--yes-playlist", "--no-write-subs", "--", "video"]
        );
    }

    #[test]
    fn unported_policy_fails_instead_of_being_silently_dropped() {
        let input = context(TargetSource::Stdin, json!({"preferred-fps": 60}));
        assert_eq!(
            plan_invocation(&input),
            Err(PlanningError::UnsupportedSetting("preferred-fps".into()))
        );
    }

    #[test]
    fn unexpected_types_fail_closed() {
        let input = context(TargetSource::Stdin, json!({"playlist": "true"}));
        assert_eq!(
            plan_invocation(&input),
            Err(PlanningError::InvalidSetting("playlist".into()))
        );
    }
}
