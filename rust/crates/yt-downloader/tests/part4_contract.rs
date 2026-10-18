//! Cross-module regression contracts for the side-effect-free Part 4 foundation.

use std::collections::BTreeMap;
use std::path::PathBuf;

use serde_json::{Map, json};
use yt_downloader::invocation::{InvocationError, prepare_invocation};
use yt_downloader::lifecycle::{EventSink, ExecutionEvent, ExecutionLifecycle, ExecutionState, LifecycleError};
use yt_downloader::planning::{PlanningError, plan_invocation};
use yt_downloader::profile_pipeline::load_validated_profiles;
use yt_downloader::profile_settings::ValidatedProfile;
use yt_downloader::targets::{TargetError, TargetRequest, TargetSource};

fn request(targets: &[&str]) -> TargetRequest {
    TargetRequest {
        targets: targets.iter().map(|target| (*target).to_owned()).collect(),
        input_file: None,
        collection_file: None,
        default_input_file: PathBuf::from("/missing-part4-contract-input"),
    }
}

fn profiles() -> BTreeMap<String, ValidatedProfile> {
    load_validated_profiles(&json!({
        "version": 3,
        "$defaults": {"playlist": true},
        "profiles": {"default": {}, "alternate": {"playlist": false}}
    }).to_string()).unwrap()
}

#[derive(Default)]
struct Events(Vec<ExecutionEvent>);

impl EventSink for Events {
    fn emit(&mut self, event: ExecutionEvent) {
        self.0.push(event);
    }
}

#[test]
fn inherited_policy_override_targets_plan_and_lifecycle_compose() {
    let overrides = json!({"write-subs": true});
    let context = prepare_invocation(
        &request(&["--leading-dash", "same", "same"]),
        &profiles(),
        None,
        overrides.as_object().unwrap(),
    ).unwrap();
    assert_eq!(context.policy.setting_sources["playlist"], "$defaults");
    assert_eq!(context.policy.setting_sources["write-subs"], "explicit override");
    assert_eq!(context.source, TargetSource::Direct(vec!["--leading-dash".into(), "same".into(), "same".into()]));

    let plan = plan_invocation(&context).unwrap();
    assert_eq!(plan.arguments, ["--yes-playlist", "--write-subs", "--", "--leading-dash", "same", "same"]);
    let mut lifecycle = ExecutionLifecycle::new(plan);
    let mut events = Events::default();
    lifecycle.transition(ExecutionState::Running, &mut events).unwrap();
    lifecycle.transition(ExecutionState::Succeeded, &mut events).unwrap();
    assert_eq!(events.0, [ExecutionEvent::StateChanged(ExecutionState::Running), ExecutionEvent::StateChanged(ExecutionState::Succeeded)]);
    assert_eq!(lifecycle.transition(ExecutionState::Running, &mut events), Err(LifecycleError::InvalidTransition { from: ExecutionState::Succeeded, to: ExecutionState::Running }));
    assert_eq!(events.0.len(), 2);
}

#[test]
fn explicit_profile_selection_changes_effective_plan() {
    let context = prepare_invocation(&request(&["video"]), &profiles(), Some("alternate"), &Map::new()).unwrap();
    assert_eq!(context.policy.profile_name.as_deref(), Some("alternate"));
    assert_eq!(plan_invocation(&context).unwrap().arguments, ["--no-playlist", "--", "video"]);
}

#[test]
fn unsupported_policy_fails_before_any_lifecycle_exists() {
    let overrides = json!({"preferred-fps": 60});
    let context = prepare_invocation(&request(&["video"]), &profiles(), None, overrides.as_object().unwrap()).unwrap();
    assert_eq!(plan_invocation(&context), Err(PlanningError::UnsupportedSetting("preferred-fps".into())));
}

#[test]
fn ambiguous_input_sources_fail_before_planning() {
    let mut input = request(&["video"]);
    input.input_file = Some(PathBuf::from("queue.txt"));
    assert_eq!(prepare_invocation(&input, &profiles(), None, &Map::new()), Err(InvocationError::Target(TargetError::ConflictingSources("--input-file"))));
    input.input_file = None;
    input.collection_file = Some(PathBuf::from("collection.json"));
    assert_eq!(prepare_invocation(&input, &profiles(), None, &Map::new()), Err(InvocationError::Target(TargetError::ConflictingSources("--collection-file"))));
}

#[test]
fn stdin_and_batch_plans_remain_distinguishable() {
    let stdin = prepare_invocation(&request(&["-"]), &profiles(), None, &Map::new()).unwrap();
    let stdin_plan = plan_invocation(&stdin).unwrap();
    assert_eq!(stdin_plan.source, TargetSource::Stdin);
    assert_eq!(stdin_plan.arguments, ["--yes-playlist", "--batch-file", "-"]);

    let file = std::env::current_exe().unwrap();
    let mut input = request(&[]);
    input.input_file = Some(file.clone());
    let batch = prepare_invocation(&input, &profiles(), None, &Map::new()).unwrap();
    let batch_plan = plan_invocation(&batch).unwrap();
    assert_eq!(batch_plan.source, TargetSource::BatchFile(file.clone()));
    assert_eq!(batch_plan.arguments, ["--yes-playlist", "--batch-file", file.to_string_lossy().as_ref()]);
}
