//! Dynamic query schema built from normalised yt-dlp metadata.
//!
//! Port of `schema.py`: known fields, declared collection types, aliases and
//! conservative dynamic inference from observed runtime values.

use crate::types::{CollectionOrdering, QueryType, StructuredMember, StructuredShape};
use crate::value::Value;

/// One metadata record: insertion-ordered field/value pairs.
pub type Record = Vec<(String, Value)>;

fn known_scalar_types() -> [(&'static str, &'static str); 25] {
    [
        ("id", "string"),
        ("title", "string"),
        ("upload_date", "date"),
        ("publish_date", "date"),
        ("duration", "duration"),
        ("view_count", "count"),
        ("like_count", "count"),
        ("comment_count", "count"),
        ("channel_follower_count", "count"),
        ("playlist_index", "count"),
        ("source_index", "count"),
        ("uploader", "string"),
        ("uploader_id", "string"),
        ("channel", "string"),
        ("channel_id", "string"),
        ("live_status", "string"),
        ("availability", "string"),
        ("is_live", "boolean"),
        ("was_live", "boolean"),
        ("webpage_url", "string"),
        ("playlist_id", "string"),
        ("playlist_title", "string"),
        ("timestamp", "datetime"),
        ("release_timestamp", "datetime"),
        ("modified_timestamp", "datetime"),
    ]
}

pub fn known_field_types() -> Vec<(&'static str, &'static str)> {
    known_scalar_types().to_vec()
}

fn member(name: &str, kind: &str) -> StructuredMember {
    StructuredMember {
        name: name.to_string(),
        value_type: QueryType::scalar(kind, true),
    }
}

pub fn format_record_type() -> QueryType {
    QueryType::structured(
        vec![
            member("format_id", "string"),
            member("ext", "string"),
            member("width", "count"),
            member("height", "count"),
            member("resolution", "string"),
            member("fps", "number"),
            member("aspect_ratio", "number"),
            member("vcodec", "string"),
            member("acodec", "string"),
            member("container", "string"),
            member("protocol", "string"),
            member("dynamic_range", "string"),
            member("tbr", "number"),
            member("vbr", "number"),
            member("abr", "number"),
            member("asr", "number"),
            member("audio_channels", "count"),
            member("filesize", "count"),
            member("filesize_approx", "count"),
            member("language", "string"),
            member("format_note", "string"),
        ],
        true,
        StructuredShape::Declared,
    )
}

pub fn chapter_record_type() -> QueryType {
    QueryType::structured(
        vec![
            member("title", "string"),
            member("start_time", "duration"),
            member("end_time", "duration"),
        ],
        true,
        StructuredShape::Declared,
    )
}

pub fn thumbnail_record_type() -> QueryType {
    QueryType::structured(
        vec![
            member("id", "string"),
            member("url", "string"),
            member("width", "count"),
            member("height", "count"),
        ],
        true,
        StructuredShape::Declared,
    )
}

fn known_collection_types() -> Vec<(&'static str, QueryType)> {
    vec![
        (
            "tags",
            QueryType::collection(
                QueryType::scalar("string", true),
                true,
                CollectionOrdering::Stable,
            ),
        ),
        (
            "categories",
            QueryType::collection(
                QueryType::scalar("string", true),
                true,
                CollectionOrdering::Stable,
            ),
        ),
        (
            "formats",
            QueryType::collection(format_record_type(), true, CollectionOrdering::Stable),
        ),
        (
            "chapters",
            QueryType::collection(chapter_record_type(), true, CollectionOrdering::Stable),
        ),
        (
            "thumbnails",
            QueryType::collection(thumbnail_record_type(), true, CollectionOrdering::Stable),
        ),
    ]
}

pub fn aliases() -> [(&'static str, &'static str); 5] {
    [
        ("views", "view_count"),
        ("likes", "like_count"),
        ("comments", "comment_count"),
        ("date", "upload_date"),
        ("url", "webpage_url"),
    ]
}

/// Description of a field visible to the query language.
#[derive(Debug, Clone)]
pub struct FieldInfo {
    pub name: String,
    pub kind: String,
    pub nullable: bool,
    pub alias_of: Option<String>,
    pub dynamic: bool,
    pub resolved_type: Option<QueryType>,
}

impl FieldInfo {
    pub fn query_type(&self) -> QueryType {
        if let Some(resolved) = &self.resolved_type {
            return resolved.clone();
        }
        QueryType::scalar(&self.kind, self.nullable)
    }
}

fn is_scalar_value(value: &Value) -> bool {
    matches!(
        value,
        Value::Null | Value::Bool(_) | Value::Int(_) | Value::Float(_) | Value::Text(_)
    )
}

fn infer_dynamic_value_type(name: &str, values: &[&Value], nullable: bool) -> Option<QueryType> {
    let concrete: Vec<&Value> = values
        .iter()
        .copied()
        .filter(|value| !value.is_null())
        .collect();
    if concrete.is_empty() {
        return Some(QueryType::scalar("unknown", true));
    }
    if concrete
        .iter()
        .all(|value| matches!(value, Value::Record(_)))
    {
        return Some(infer_dynamic_structured_type(&concrete, nullable));
    }
    if concrete
        .iter()
        .any(|value| matches!(value, Value::Record(_)))
    {
        return None;
    }
    if concrete
        .iter()
        .all(|value| matches!(value, Value::Array(_)))
    {
        let owned: Vec<Value> = concrete.iter().map(|value| (*value).clone()).collect();
        return infer_collection_type(name, &owned, nullable, true);
    }
    if concrete
        .iter()
        .any(|value| matches!(value, Value::Array(_)))
    {
        return None;
    }
    if !concrete.iter().all(|value| is_scalar_value(value)) {
        return None;
    }
    let kind = infer_kind(name, &concrete);
    if kind == "mixed" || kind == "structured" {
        return None;
    }
    Some(QueryType::scalar(&kind, nullable))
}

/// Infer a conservative dynamic member schema from provider dictionaries.
pub fn infer_dynamic_structured_type(values: &[&Value], nullable: bool) -> QueryType {
    let mut names: Vec<String> = Vec::new();
    for value in values {
        if let Value::Record(record) = value {
            for (name, _) in record {
                if !names.contains(name) {
                    names.push(name.clone());
                }
            }
        }
    }
    if values.is_empty() || names.is_empty() {
        return QueryType::structured_opaque(nullable);
    }
    names.sort();
    let mut members: Vec<StructuredMember> = Vec::new();
    for member_name in &names {
        let mut present_values: Vec<&Value> = Vec::new();
        for value in values {
            if let Value::Record(record) = value
                && let Some((_, member_value)) = record.iter().find(|(key, _)| key == member_name)
            {
                present_values.push(member_value);
            }
        }
        let member_nullable = present_values.len() < values.len()
            || present_values.iter().any(|value| value.is_null());
        let member_type = infer_dynamic_value_type(member_name, &present_values, member_nullable);
        if let Some(member_type) = member_type {
            members.push(StructuredMember {
                name: member_name.clone(),
                value_type: member_type,
            });
        }
    }
    if members.is_empty() {
        return QueryType::structured_opaque(nullable);
    }
    QueryType::structured(members, nullable, StructuredShape::Dynamic)
}

/// Infer a collection type conservatively from observed runtime values.
pub fn infer_collection_type(
    name: &str,
    values: &[Value],
    nullable: bool,
    allow_structured_elements: bool,
) -> Option<QueryType> {
    let concrete: Vec<&Value> = values.iter().filter(|value| !value.is_null()).collect();
    if concrete.is_empty()
        || !concrete
            .iter()
            .all(|value| matches!(value, Value::Array(_)))
    {
        return None;
    }
    let mut elements: Vec<Value> = Vec::new();
    for value in &concrete {
        if let Value::Array(items) = value {
            elements.extend(items.iter().cloned());
        }
    }
    let element_concrete: Vec<&Value> = elements.iter().filter(|value| !value.is_null()).collect();
    let element_nullable = elements.iter().any(|value| value.is_null());
    let element_type = if element_concrete.is_empty() {
        QueryType::scalar("unknown", element_nullable)
    } else if element_concrete
        .iter()
        .all(|value| matches!(value, Value::Array(_)))
    {
        let nested: Vec<Value> = element_concrete
            .iter()
            .map(|value| (*value).clone())
            .collect();

        infer_collection_type(name, &nested, element_nullable, allow_structured_elements)?
    } else if element_concrete
        .iter()
        .any(|value| matches!(value, Value::Array(_)))
    {
        return None;
    } else if allow_structured_elements
        && element_concrete
            .iter()
            .all(|value| matches!(value, Value::Record(_)))
    {
        infer_dynamic_structured_type(&element_concrete, element_nullable)
    } else if element_concrete
        .iter()
        .any(|value| matches!(value, Value::Record(_)))
    {
        return None;
    } else {
        QueryType::scalar(&infer_kind(name, &element_concrete), element_nullable)
    };
    Some(QueryType::collection(
        element_type,
        nullable,
        CollectionOrdering::Stable,
    ))
}

/// Infer a conservative query type from a metadata field and its values.
pub fn infer_kind(name: &str, values: &[&Value]) -> String {
    let lowered = name.to_lowercase();
    if let Some((_, kind)) = known_field_types()
        .into_iter()
        .find(|(key, _)| *key == lowered)
    {
        return kind.to_string();
    }
    if known_collection_types()
        .iter()
        .any(|(key, _)| *key == lowered)
    {
        return "collection".to_string();
    }
    if lowered.ends_with("_timestamp") || lowered == "timestamp" {
        return "datetime".to_string();
    }
    if lowered.ends_with("_date") {
        return "date".to_string();
    }
    if lowered.ends_with("_count") || lowered.ends_with("_index") {
        return "count".to_string();
    }

    let concrete: Vec<&Value> = values
        .iter()
        .copied()
        .filter(|value| !value.is_null())
        .collect();
    if concrete.is_empty() {
        return "unknown".to_string();
    }
    let mut kinds: Vec<&str> = Vec::new();
    for value in concrete {
        let kind = match value {
            Value::Bool(_) => "boolean",
            Value::Int(_) => "integer",
            Value::Float(_) => "number",
            Value::Text(_) => "string",
            _ => "structured",
        };
        if !kinds.contains(&kind) {
            kinds.push(kind);
        }
    }
    if kinds
        .iter()
        .all(|kind| *kind == "integer" || *kind == "number")
    {
        return if kinds.contains(&"number") {
            "number"
        } else {
            "integer"
        }
        .to_string();
    }
    if kinds.len() == 1 {
        return kinds[0].to_string();
    }
    "mixed".to_string()
}

/// Resolve known, aliased and observed top-level metadata fields.
#[derive(Debug, Clone, Default)]
pub struct QuerySchema {
    pub records: Vec<Record>,
    fields: Vec<FieldInfo>,
    logical: bool,
}

impl QuerySchema {
    pub fn from_records(records: Vec<Record>) -> Self {
        let mut schema = Self {
            records,
            fields: Vec::new(),
            logical: false,
        };
        schema.build();
        schema
    }

    /// Construct a logical schema from already resolved query-result columns.
    pub fn from_field_infos(fields: Vec<FieldInfo>) -> Self {
        Self {
            records: Vec::new(),
            fields,
            logical: true,
        }
    }

    fn build(&mut self) {
        let record_count = self.records.len();
        for (name, kind) in known_field_types() {
            let nullable = self
                .records
                .iter()
                .any(|record| record_get_is_null(record, name))
                || record_count == 0;
            self.fields.push(FieldInfo {
                name: name.to_string(),
                kind: kind.to_string(),
                nullable,
                alias_of: None,
                dynamic: false,
                resolved_type: None,
            });
        }
        for (name, declared_type) in known_collection_types() {
            let nullable = self
                .records
                .iter()
                .any(|record| record_get_is_null(record, name))
                || record_count == 0;
            let resolved_type = declared_type.with_nullable(nullable);
            self.fields.push(FieldInfo {
                name: name.to_string(),
                kind: "collection".to_string(),
                nullable,
                alias_of: None,
                dynamic: false,
                resolved_type: Some(resolved_type),
            });
        }

        // Observed dynamic fields: only scalar and list values participate.
        let mut observed: Vec<(String, Vec<Value>)> = Vec::new();
        for record in &self.records {
            for (name, value) in record {
                if name.starts_with('_') {
                    continue;
                }
                let participates = is_scalar_value(value) || matches!(value, Value::Array(_));
                if !participates {
                    continue;
                }
                match observed.iter_mut().find(|(key, _)| key == name) {
                    Some((_, values)) => values.push(value.clone()),
                    None => observed.push((name.clone(), vec![value.clone()])),
                }
            }
        }
        for (name, values) in observed {
            if self.fields.iter().any(|field| field.name == name) {
                continue;
            }
            let nullable =
                values.iter().any(|value| value.is_null()) || values.len() < record_count;
            if let Some(collection_type) = infer_collection_type(&name, &values, nullable, false) {
                self.fields.push(FieldInfo {
                    name: name.clone(),
                    kind: "collection".to_string(),
                    nullable,
                    alias_of: None,
                    dynamic: true,
                    resolved_type: Some(collection_type),
                });
                continue;
            }
            let references: Vec<&Value> = values.iter().collect();
            let kind = infer_kind(&name, &references);
            self.fields.push(FieldInfo {
                name: name.clone(),
                kind,
                nullable,
                alias_of: None,
                dynamic: true,
                resolved_type: None,
            });
        }

        for (alias, target) in aliases() {
            let target_info = self
                .fields
                .iter()
                .find(|field| field.name == target)
                .cloned();
            if let Some(target_info) = target_info {
                self.fields.push(FieldInfo {
                    name: alias.to_string(),
                    kind: target_info.kind,
                    nullable: target_info.nullable,
                    alias_of: Some(target_info.name),
                    dynamic: false,
                    resolved_type: None,
                });
            }
        }
    }

    pub fn resolve(&self, name: &str) -> Option<&FieldInfo> {
        self.fields.iter().find(|field| field.name == name)
    }

    pub fn resolve_index_operand(&self, name: &str) -> Option<&FieldInfo> {
        self.resolve(name)
    }

    /// Visible fields in deterministic display order.
    pub fn available_fields(&self) -> Vec<FieldInfo> {
        let mut unique: Vec<FieldInfo> = Vec::new();
        for info in &self.fields {
            if !unique
                .iter()
                .any(|field| field.name == info.name && field.alias_of == info.alias_of)
            {
                unique.push(info.clone());
            }
        }
        unique.sort_by(|left, right| {
            let left_alias = usize::from(left.alias_of.is_some());
            let right_alias = usize::from(right.alias_of.is_some());
            left_alias
                .cmp(&right_alias)
                .then_with(|| left.name.to_lowercase().cmp(&right.name.to_lowercase()))
        });
        unique
    }

    /// The deterministic scalar field set expanded by `SELECT *`.
    pub fn select_star_fields(&self) -> Vec<FieldInfo> {
        if self.logical {
            return self.fields.clone();
        }
        let builtins: Vec<FieldInfo> = known_field_types()
            .iter()
            .map(|(name, _)| {
                self.fields
                    .iter()
                    .find(|field| field.name == *name)
                    .cloned()
                    .expect("known fields are always registered")
            })
            .collect();
        let builtin_keys: Vec<&str> = builtins.iter().map(|info| info.name.as_str()).collect();
        let mut dynamic: Vec<FieldInfo> = self
            .fields
            .iter()
            .filter(|info| {
                info.dynamic
                    && info.kind != "collection"
                    && info.alias_of.is_none()
                    && !builtin_keys.contains(&info.name.as_str())
            })
            .cloned()
            .collect();
        dynamic.sort_by_key(|left| left.name.to_lowercase());
        let mut fields = builtins;
        fields.extend(dynamic);
        fields
    }
}

fn record_get_is_null(record: &Record, key: &str) -> bool {
    record
        .iter()
        .find(|(name, _)| name == key)
        .map(|(_, value)| value.is_null())
        .unwrap_or(false)
}
