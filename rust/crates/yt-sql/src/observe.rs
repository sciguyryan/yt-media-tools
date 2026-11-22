//! Adapter observation assembly for one portable corpus case.
//!
//! Port of the adapter contract in `run_python_candidate.py`: load the case
//! manifest and dataset, bind declared parameters, parse, resolve and evaluate
//! the query, then serialise the observation in the portable version-1 shape.

use crate::dates::DateContext;
use crate::evaluator::{
    CanonicalField, apply_query, canonical_record_value, query_physical_source_requests,
};
use crate::parser::parse_query;
use crate::resolver::{SourceSchemas, resolve_query};
use crate::schema::{QuerySchema, Record};
use crate::value::{Value, to_typed_json};
use serde_json::{Map, Value as Json, json};

/// A case or configuration cannot be faithfully executed by this adapter.
fn adapter_error(message: impl Into<String>) -> String {
    format!("Rust adapter cannot execute the case: {}", message.into())
}

/// Convert one JSON value into the runtime value domain (records keep order).
fn json_to_value(input: &Json) -> Value {
    match input {
        Json::Null => Value::Null,
        Json::Bool(inner) => Value::Bool(*inner),
        Json::Number(number) => {
            if let Some(int) = number.as_i64() {
                Value::Int(int)
            } else {
                Value::Float(number.as_f64().unwrap_or(f64::NAN))
            }
        }
        Json::String(text) => Value::Text(text.clone()),
        Json::Array(items) => Value::Array(items.iter().map(json_to_value).collect()),
        Json::Object(fields) => Value::Record(
            fields
                .iter()
                .map(|(name, value)| (name.clone(), json_to_value(value)))
                .collect(),
        ),
    }
}

fn json_to_record(input: &Json) -> Record {
    match input {
        Json::Object(fields) => fields
            .iter()
            .map(|(name, value)| (name.clone(), json_to_value(value)))
            .collect(),
        _ => Vec::new(),
    }
}

/// Bind portable scalar parameters as SQL literals without changing quoted text.
/// Port of `_bind_portable_parameters` including the `:name` scanning rules.
fn bind_portable_parameters(query: &str, parameters: &Map<String, Json>) -> Result<String, String> {
    let mut literals: Vec<(String, String)> = Vec::new();
    for (name, value) in parameters {
        let literal = match value {
            Json::Null => "NULL".to_string(),
            Json::Bool(inner) => {
                if *inner {
                    "TRUE".to_string()
                } else {
                    "FALSE".to_string()
                }
            }
            Json::Number(number) => number.to_string(),
            Json::String(text) => format!("'{}'", text.replace('\'', "''")),
            Json::Object(fields) => {
                // Typed values use the portable {"type", "value"} contract.
                let kind = fields.get("type").and_then(Json::as_str).unwrap_or("");
                let raw = fields.get("value").and_then(Json::as_str).unwrap_or("");
                match kind {
                    "integer" | "decimal" => raw.to_string(),
                    "timestamp" => {
                        // Normalise to UTC with microsecond precision, as the
                        // Python adapter's timestamp binding does.
                        let normalised = crate::dates::parse_settings_clock(raw).map_err(|_| {
                            adapter_error("portable parameter type is not yet supported")
                        })?;
                        crate::value::datetime_isoformat(&normalised).replace("+00:00", "Z")
                    }
                    _ => {
                        return Err(adapter_error(
                            "portable parameter type is not yet supported",
                        ));
                    }
                }
            }
            _ => {
                return Err(adapter_error(
                    "portable parameter type is not yet supported",
                ));
            }
        };
        literals.push((name.clone(), literal));
    }

    let mut result = String::new();
    let mut used: Vec<String> = Vec::new();
    let bytes: Vec<char> = query.chars().collect();
    let mut index = 0usize;
    while index < bytes.len() {
        let character = bytes[index];
        if character == '\'' || character == '"' {
            result.push(character);
            index += 1;
            while index < bytes.len() {
                if bytes[index] == '\\' && index + 1 < bytes.len() {
                    result.push(bytes[index]);
                    result.push(bytes[index + 1]);
                    index += 2;
                    continue;
                }
                result.push(bytes[index]);
                if bytes[index] == character {
                    index += 1;
                    break;
                }
                index += 1;
            }
            continue;
        }
        if character == ':'
            && index + 1 < bytes.len()
            && (bytes[index + 1].is_ascii_alphabetic() || bytes[index + 1] == '_')
        {
            let mut end = index + 2;
            while end < bytes.len() && (bytes[end].is_ascii_alphanumeric() || bytes[end] == '_') {
                end += 1;
            }
            let name: String = bytes[index + 1..end].iter().collect();
            let Some((_, literal)) = literals.iter().find(|(key, _)| *key == name) else {
                return Err(adapter_error(format!(
                    "missing portable parameter binding: {name}"
                )));
            };
            result.push_str(literal);
            if !used.contains(&name) {
                used.push(name);
            }
            index = end;
            continue;
        }
        result.push(character);
        index += 1;
    }
    let unused: Vec<&String> = literals
        .iter()
        .map(|(name, _)| name)
        .filter(|name| !used.contains(*name))
        .collect();
    if !unused.is_empty() {
        return Err(adapter_error(format!(
            "unused portable parameter bindings: {}",
            unused
                .iter()
                .map(|name| name.as_str())
                .collect::<Vec<&str>>()
                .join(", ")
        )));
    }
    Ok(result)
}

/// One physical source/facet binding with its record indices.
type SourceBindings = Vec<((String, Option<String>), Vec<usize>)>;

fn load_json(path: &std::path::Path) -> Result<Json, String> {
    let text = std::fs::read_to_string(path)
        .map_err(|error| adapter_error(format!("{path:?}: {error}")))?;
    serde_json::from_str(&text)
        .map_err(|error| adapter_error(format!("{path:?}: invalid JSON: {error}")))
}

/// Map a parse diagnostic onto the portable outcome contract.
fn diagnostic_outcome(error: crate::model::QueryError) -> String {
    match error.kind {
        "lexical" => {
            json!({"version": 1, "outcome": "error", "error": {"category": "syntax"}}).to_string()
        }
        "syntax" => {
            if error.context.category != "syntax" {
                adapter_error(format!(
                    "unclassified language diagnostic: {}",
                    error.context.category
                ))
            } else {
                json!({"version": 1, "outcome": "error", "error": {"category": "syntax"}})
                    .to_string()
            }
        }
        "semantic" => {
            let reason = error.context.reason.clone();
            if ["unknown-field", "unknown-relation-alias", "ambiguous-field"]
                .contains(&reason.as_str())
                || !["invalid"].contains(&reason.as_str())
            {
                match classify_semantic(&reason) {
                    Ok(outcome) => outcome.to_string(),
                    Err(message) => message,
                }
            } else {
                adapter_error(format!(
                    "unclassified language diagnostic: {}/{}",
                    error.context.category, reason
                ))
            }
        }
        other => adapter_error(format!("unknown diagnostic kind: {other}")),
    }
}

/// Classify a semantic diagnostic reason into the portable outcome categories.
/// Port of `classify_semantic` — only explicitly assigned reasons are portable.
fn classify_semantic(reason: &str) -> Result<Json, String> {
    let category = match reason {
        "unknown-field" | "unknown-relation-alias" | "ambiguous-field" => "resolution",
        "non-numeric-aggregate"
        | "invalid-char-codepoint"
        | "invalid-concat-argument"
        | "invalid-text-function-argument"
        | "invalid-text-predicate-field"
        | "incompatible-scalar-argument"
        | "invalid-collection-operand"
        | "aggregate-in-collection-projection"
        | "aggregate-nesting"
        | "aggregate-must-match-group-by"
        | "having-must-match-group-by"
        | "select-star-in-aggregate"
        | "group-by-aggregate"
        | "having-requires-group-by" => "type",
        "invalid-random-placement" | "invalid-position-placement" => "syntax",
        "unsupported-position-set-operation" => "unsupported",
        "invalid-window-placement" | "window-order-required" | "invalid-window-volatile" => {
            "syntax"
        }
        "unsupported-window-aggregate-query" | "unsupported-window-nesting" => "unsupported",
        other => {
            return Err(adapter_error(format!(
                "unclassified language diagnostic reason: {other}"
            )));
        }
    };
    Ok(json!({"version": 1, "outcome": "error", "error": {"category": category}}))
}

/// Execute one portable case and return its observation JSON text.
pub fn observe(case: &str, configuration: &str, root: &str) -> Result<String, String> {
    let case_dir = std::path::Path::new(case);
    let root_dir = std::path::Path::new(root);
    let manifest = load_json(&case_dir.join("test.json"))?;

    let configurations = manifest
        .get("execution")
        .and_then(|execution| execution.get("configurations"))
        .and_then(Json::as_array)
        .cloned()
        .unwrap_or_else(|| vec![json!({"id": "default", "settings": {}})]);
    let matches: Vec<&Json> = configurations
        .iter()
        .filter(|entry| entry.get("id").and_then(Json::as_str) == Some(configuration))
        .collect();
    if matches.len() != 1 {
        return Err(adapter_error(format!(
            "undeclared execution configuration: {configuration}"
        )));
    }
    let settings = matches[0]
        .get("settings")
        .and_then(Json::as_object)
        .cloned()
        .unwrap_or_default();
    for key in settings.keys() {
        if !matches!(key.as_str(), "optimisation" | "clock" | "date_order") {
            return Err(adapter_error("unknown portable execution setting"));
        }
    }
    if let Some(order) = settings.get("date_order") {
        let order = order
            .as_str()
            .ok_or_else(|| adapter_error("date_order must be dmy, mdy, or ymd"))?;
        if !matches!(order, "dmy" | "mdy" | "ymd") {
            return Err(adapter_error("date_order must be dmy, mdy, or ymd"));
        }
    }

    let datasets = manifest
        .get("datasets")
        .and_then(Json::as_array)
        .ok_or_else(|| adapter_error("manifest must declare datasets"))?;
    if datasets.len() != 1 {
        return Err(adapter_error(
            "multiple dataset binding is not yet supported by the Rust adapter",
        ));
    }
    let dataset_name = datasets[0]
        .as_str()
        .ok_or_else(|| adapter_error("invalid dataset name"))?;
    let dataset = load_json(
        &root_dir
            .join("datasets")
            .join(format!("{dataset_name}.json")),
    )?;
    let kind = dataset
        .get("kind")
        .and_then(Json::as_str)
        .ok_or_else(|| adapter_error("dataset must declare a kind"))?
        .to_string();
    if !matches!(
        kind.as_str(),
        "static" | "source-topology" | "facet-topology"
    ) {
        return Err(adapter_error(
            "only static, source-topology and facet-topology datasets are supported",
        ));
    }
    let raw_records = dataset
        .get("records")
        .and_then(Json::as_array)
        .ok_or_else(|| adapter_error("dataset must declare records"))?;

    let mut records: Vec<Record> = raw_records.iter().map(json_to_record).collect();
    // Source positions are one-based and derived from the ordered source, but
    // only static datasets carry them: topology datasets keep their committed
    // fields exactly.
    if kind == "static" {
        for (index, record) in records.iter_mut().enumerate() {
            record.retain(|(name, _)| name != "source_index");
            record.push(("source_index".to_string(), Value::Int(index as i64 + 1)));
        }
    }

    // Topology is authoritative; an empty facet remains a declared binding.
    let mut bindings: SourceBindings = Vec::new();
    if kind == "static" {
        bindings.push((
            ("@yt_sql_fixture".to_string(), None),
            (0..records.len()).collect(),
        ));
    } else {
        for entry in dataset
            .get("sources")
            .and_then(Json::as_array)
            .unwrap_or(&vec![])
        {
            let handle = entry
                .get("handle")
                .and_then(Json::as_str)
                .unwrap_or_default()
                .to_string();
            let indices: Vec<usize> = entry
                .get("record_indices")
                .and_then(Json::as_array)
                .map(|items| {
                    items
                        .iter()
                        .filter_map(Json::as_u64)
                        .map(|value| value as usize)
                        .collect()
                })
                .unwrap_or_default();
            bindings.push(((handle, None), indices));
        }
        if kind == "facet-topology" {
            for entry in dataset
                .get("facets")
                .and_then(Json::as_array)
                .unwrap_or(&vec![])
            {
                let source = entry
                    .get("source")
                    .and_then(Json::as_str)
                    .unwrap_or_default()
                    .to_string();
                let facet = entry
                    .get("name")
                    .and_then(Json::as_str)
                    .unwrap_or_default()
                    .to_string();
                let indices: Vec<usize> = entry
                    .get("record_indices")
                    .and_then(Json::as_array)
                    .map(|items| {
                        items
                            .iter()
                            .filter_map(Json::as_u64)
                            .map(|value| value as usize)
                            .collect()
                    })
                    .unwrap_or_default();
                bindings.push(((source, Some(facet)), indices));
            }
        }
    }

    let query_text = std::fs::read_to_string(case_dir.join("query.ysql"))
        .map_err(|error| adapter_error(format!("query.ysql: {error}")))?;
    let parameters = manifest
        .get("parameters")
        .and_then(Json::as_object)
        .cloned()
        .unwrap_or_default();
    let bound_query = bind_portable_parameters(&query_text, &parameters)?;

    let parsed = match parse_query(&bound_query) {
        Ok(parsed) => parsed,
        Err(error) => return Ok(diagnostic_outcome(error)),
    };

    let requests = query_physical_source_requests(&parsed);
    if requests.is_empty() {
        return Err(adapter_error(
            "queries without a physical source binding are not yet supported",
        ));
    }
    for request in &requests {
        if !bindings.iter().any(|(key, _)| key == request) {
            return Err(adapter_error(format!(
                "physical source/facet is not bound to the portable dataset: {request:?}"
            )));
        }
    }

    // Every execution record carries the binding keys regardless of request
    // count: seeded RANDOM derives its record identity from them.
    let mut execution_records: Vec<Record> = Vec::new();
    for request in &requests {
        if let Some((_, indices)) = bindings.iter().find(|(key, _)| key == request) {
            for index in indices {
                let mut record = records.get(*index).cloned().unwrap_or_default();
                record.retain(|(name, _)| !name.starts_with("_yt_sql_source"));
                record.push(("_yt_sql_source".to_string(), Value::Text(request.0.clone())));
                record.push((
                    "_yt_sql_source_facet".to_string(),
                    request.1.clone().map(Value::Text).unwrap_or(Value::Null),
                ));
                execution_records.push(record);
            }
        }
    }

    let source_schemas: SourceSchemas = requests
        .iter()
        .filter_map(|request| {
            bindings
                .iter()
                .find(|(key, _)| key == request)
                .map(|(key, indices)| {
                    let bound: Vec<Record> = indices
                        .iter()
                        .map(|index| records[*index].clone())
                        .collect();
                    (key.clone(), QuerySchema::from_records(bound))
                })
        })
        .collect();

    let date_order = settings
        .get("date_order")
        .and_then(Json::as_str)
        .unwrap_or("dmy")
        .to_string();
    let now = match settings.get("clock").and_then(Json::as_str) {
        Some(clock) => crate::dates::parse_settings_clock(clock).map_err(|_| {
            adapter_error("settings.clock must be an offset-aware RFC 3339 timestamp")
        })?,
        None => DateContext::default_now(),
    };
    let context = DateContext::new(&date_order, now);

    let resolved = match resolve_query(
        &parsed,
        &QuerySchema::from_records(execution_records.clone()),
        &context,
        &source_schemas,
    ) {
        Ok(resolved) => resolved,
        Err(error) => {
            if error.kind == "semantic" {
                return classify_semantic(&error.context.reason)
                    .map(|observation| observation.to_string());
            }
            return Err(adapter_error(format!(
                "unclassified language diagnostic: {}",
                error.context.category
            )));
        }
    };

    let optimisation = settings
        .get("optimisation")
        .and_then(Json::as_str)
        .unwrap_or("enabled")
        != "disabled";

    let result = apply_query(&execution_records, &resolved, optimisation).map_err(adapter_error)?;

    let columns: Vec<String> = resolved
        .select
        .iter()
        .map(|term| term.output_name().to_string())
        .collect();
    let mut rows: Vec<Vec<Json>> = Vec::new();
    for record in &result {
        let mut row: Vec<Json> = Vec::new();
        for term in &resolved.select {
            let value = canonical_record_value(record, &CanonicalField::Select(term.clone()), true);
            row.push(to_typed_json(&value).map_err(adapter_error)?);
        }
        rows.push(row);
    }
    let observation = json!({"version": 1, "outcome": "rows", "columns": columns, "rows": rows});
    Ok(observation.to_string())
}
