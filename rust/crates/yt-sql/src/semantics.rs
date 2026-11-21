//! Semantic identity helpers shared by yt-sql analysis and resolution.
//!
//! Port of `query_semantics.py`, restricted to the helpers the resolver imports.
//! The aggregate helpers (`_aggregate_query`, `_contains_aggregate`,
//! `_contains_random`) and `query_physical_source_requests` live in
//! `crate::evaluator`; this module intentionally does not duplicate them.

use crate::model::Query;

/// Return FROM references directly used by one composed query, excluding nested
/// CTE declarations (Python `_direct_from_sources`).
pub fn direct_from_sources(query: &Query) -> Vec<String> {
    let mut result: Vec<String> = Vec::new();
    if let Some(from_source) = &query.from_source {
        result.push(from_source.clone());
    }
    if let Some(from_relation) = &query.from_relation
        && let Some(derived) = &from_relation.derived
    {
        result.extend(direct_from_sources(&derived.query));
    }
    for join in &query.joins {
        if let Some(source) = &join.relation.source {
            result.push(source.clone());
        } else if let Some(derived) = &join.relation.derived {
            result.extend(direct_from_sources(&derived.query));
        }
    }
    for operation in &query.set_operations {
        result.extend(direct_from_sources(&operation.query));
    }
    result
}
