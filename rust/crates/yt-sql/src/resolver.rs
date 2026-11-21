//! Semantic resolution for parsed yt-sql queries.
//!
//! Port of `query_resolver.py`, plus `query_scope.py` (relation binding) and
//! `query_traversal.py` (AST walking, exposed as public helpers). Python remains
//! the behavioural reference: error messages, positions and the diagnostic
//! `reason` values are preserved exactly.
//!
//! ## Module wiring
//! `lib.rs` does not yet declare the sibling modules, so they are attached here
//! with explicit `#[path]` attributes. When the crate gains top-level module
//! declarations (`pub mod formatter;` etc.), move these three declarations into
//! `lib.rs` and remove them from here — the files themselves are unchanged.
//!
//! ## Rust literal representation
//! The Rust AST's `LiteralValue` carries `Text`, `Null`, `Bool` and `Raw` only.
//! Numeric literals are stored as unquoted `Text` with the raw source spelling;
//! infinity sentinels are `Raw`. Resolution keeps the raw text (canonicalised
//! for date/datetime/duration kinds) so the evaluator and formatter can decode
//! values deterministically; see `resolve_literal`.

use std::collections::HashMap;
use std::sync::OnceLock;

use regex::Regex;

use crate::dates::{
    DateContext, parse_date_literal, parse_datetime_literal, parse_temporal_infinity,
};
use crate::evaluator::{
    aggregate_query, coerce_char_codepoint, contains_aggregate, contains_random,
};
use crate::formatter::{canonicalise_temporal_expression, format_scalar_expression};
use crate::join_resolution::prepare_join_query;
use crate::model::{
    AggregateFunction, Between, BoolExpr, CaseWhen, CollectionCount, CollectionElementReference,
    CollectionFilter, CollectionPredicate, CollectionProjection, CommonTableExpression, Expr,
    Field, InList, IsNull, JoinClause, Literal, LiteralValue, OrderTerm, Query, QueryError,
    ScalarBinary, ScalarCase, ScalarComparison, ScalarFunction, ScalarIndex, ScalarIsNull,
    ScalarMember, ScalarUnary, SelectTerm, SetOperation, TextPredicate, TruthTest, Unary,
};
use crate::parser::{parse_integer_literal_text, parse_number_text, validate_like_pattern};
use crate::schema::{FieldInfo, QuerySchema};
use crate::semantics::direct_from_sources;
use crate::types::{CollectionOrdering, QueryType};
use crate::units::load_default_unit_registry;
use crate::value::{Value, python_round};

pub use crate::formatter::{
    format_expression, format_query, format_scalar_expression as format_scalar,
};
pub use crate::join_resolution::{prepare_join_query as prepare_join, resolve_join_references};
pub use crate::semantics::direct_from_sources as query_direct_from_sources;

/// Per-source schemas keyed by the `(source, facet)` request pair, mirroring
/// Python's `dict[tuple[str, str | None], QuerySchema]`.
pub type SourceSchemas = Vec<((String, Option<String>), QuerySchema)>;

/// CTE result schemas keyed by name, mirroring Python's `dict[str, QuerySchema]`.
pub type CteSchemas = HashMap<String, QuerySchema>;

/// Select-output alias table (`dict[str, SelectTerm]`).
pub type AliasTable = HashMap<String, SelectTerm>;

const DEFAULT_REASON: &str = "invalid";

fn semantic_error(source: &str, message: impl Into<String>, position: usize) -> QueryError {
    QueryError::semantic(source, message, position, DEFAULT_REASON)
}

/// Python `repr()` approximation for diagnostic messages (single-quoted).
pub fn python_repr(text: &str) -> String {
    let has_single = text.contains('\'');
    let has_double = text.contains('"');
    let mut escaped = String::new();
    for character in text.chars() {
        match character {
            '\\' => escaped.push_str("\\\\"),
            '\n' => escaped.push_str("\\n"),
            '\r' => escaped.push_str("\\r"),
            '\t' => escaped.push_str("\\t"),
            '"' if has_single && !has_double => escaped.push_str("\\\""),
            '\'' if !(has_single && !has_double) => escaped.push_str("\\'"),
            other => escaped.push(other),
        }
    }
    let quote = if has_single && !has_double { '"' } else { '\'' };
    format!("{quote}{escaped}{quote}")
}

// ---------------------------------------------------------------------------
// Relation scope (port of query_scope.py)
// ---------------------------------------------------------------------------

/// Stable semantic identity for one logical relation in a query body.
#[derive(Debug, Clone, PartialEq)]
pub struct RelationIdentity {
    pub name: Option<String>,
    pub facet: Option<String>,
    pub kind: String,
}

impl RelationIdentity {
    /// `(kind, name, facet)` ordering key, matching the Rust relation-key shape.
    pub fn key(&self) -> (String, Option<String>, Option<String>) {
        (self.kind.clone(), self.name.clone(), self.facet.clone())
    }
}

/// One relation identity paired with the schema and visible qualifier.
#[derive(Debug, Clone)]
pub struct RelationBinding {
    pub identity: RelationIdentity,
    pub schema: QuerySchema,
    pub qualifier: Option<String>,
}

/// Semantic ownership of a field after scope resolution.
#[derive(Debug, Clone)]
pub struct ResolvedFieldIdentity {
    pub relation: RelationIdentity,
    pub field: FieldInfo,
}

/// Backend-neutral identity of a logical row within one relation.
#[derive(Debug, Clone)]
pub struct LogicalRowIdentity {
    pub relation: RelationIdentity,
    pub values: Vec<crate::value::Value>,
}

impl LogicalRowIdentity {
    pub fn key(
        &self,
    ) -> (
        (String, Option<String>, Option<String>),
        Vec<crate::value::Value>,
    ) {
        (self.relation.key(), self.values.clone())
    }
}

/// Relations visible while resolving one query body.
#[derive(Debug, Clone)]
pub struct SemanticScope {
    pub relations: Vec<RelationBinding>,
}

impl SemanticScope {
    pub fn single(binding: RelationBinding) -> Self {
        Self {
            relations: vec![binding],
        }
    }

    /// All relation-owned matches for an unqualified field name.
    pub fn field_matches(&self, name: &str) -> Vec<ResolvedFieldIdentity> {
        let mut matches = Vec::new();
        for binding in &self.relations {
            if let Some(field) = binding.schema.resolve(name) {
                matches.push(ResolvedFieldIdentity {
                    relation: binding.identity.clone(),
                    field: field.clone(),
                });
            }
        }
        matches
    }

    /// Resolve an unqualified field, refusing ambiguous multi-relation matches.
    pub fn resolve_unqualified_field(&self, name: &str) -> Option<ResolvedFieldIdentity> {
        let matches = self.field_matches(name);
        if matches.len() == 1 {
            matches.into_iter().next()
        } else {
            None
        }
    }

    /// The uniquely visible relation bound to `qualifier`.
    pub fn binding_for_qualifier(&self, qualifier: &str) -> Option<&RelationBinding> {
        let matches: Vec<&RelationBinding> = self
            .relations
            .iter()
            .filter(|binding| binding.qualifier.as_deref() == Some(qualifier))
            .collect();
        if matches.len() == 1 {
            Some(matches[0])
        } else {
            None
        }
    }
}

fn lookup_source_schema<'a>(
    source_schemas: &'a SourceSchemas,
    source_name: &str,
    source_facet: Option<&str>,
) -> Option<&'a QuerySchema> {
    source_schemas
        .iter()
        .find(|(key, _)| key.0 == source_name && key.1.as_deref() == source_facet)
        .map(|(_, schema)| schema)
}

/// Resolve the single relation used by the current query-body grammar.
pub fn relation_binding(
    source_name: Option<&str>,
    source_facet: Option<&str>,
    physical_schema: &QuerySchema,
    cte_schemas: &CteSchemas,
    source_schemas: &SourceSchemas,
) -> RelationBinding {
    let Some(name) = source_name else {
        return RelationBinding {
            identity: RelationIdentity {
                name: None,
                facet: source_facet.map(str::to_string),
                kind: "implicit".to_string(),
            },
            schema: physical_schema.clone(),
            qualifier: None,
        };
    };
    if let Some(logical) = cte_schemas.get(name) {
        return RelationBinding {
            identity: RelationIdentity {
                name: Some(name.to_string()),
                facet: None,
                kind: "cte".to_string(),
            },
            schema: logical.clone(),
            qualifier: Some(name.to_string()),
        };
    }
    let schema = lookup_source_schema(source_schemas, name, source_facet)
        .cloned()
        .unwrap_or_else(|| physical_schema.clone());
    RelationBinding {
        identity: RelationIdentity {
            name: Some(name.to_string()),
            facet: source_facet.map(str::to_string),
            kind: "physical".to_string(),
        },
        schema,
        qualifier: Some(name.to_string()),
    }
}

// ---------------------------------------------------------------------------
// Traversal (port of query_traversal.py)
// ---------------------------------------------------------------------------

/// One visitable AST node reference, in the Python `walk_ast` node taxonomy.
#[derive(Debug, Clone, Copy)]
pub enum AstNode<'a> {
    Query(&'a Query),
    SelectTerm(&'a SelectTerm),
    OrderTerm(&'a OrderTerm),
    JoinClause(&'a JoinClause),
    Cte(&'a CommonTableExpression),
    SetOperation(&'a SetOperation),
    CaseWhen(&'a CaseWhen),
    Field(&'a Field),
    Literal(&'a Literal),
    Bool(&'a BoolExpr),
    Expr(&'a Expr),
}

/// Direct AST children in stable source/semantic order. Leaf nodes have no
/// entries here, so additions to the query model stay visible to traversal.
pub fn ast_children<'a>(node: &AstNode<'a>) -> Vec<AstNode<'a>> {
    match node {
        AstNode::Query(query) => {
            let mut children: Vec<AstNode<'a>> = Vec::new();
            if let Some(left_query) = &query.left_query {
                children.push(AstNode::Query(left_query));
            }
            if let Some(predicate) = &query.predicate {
                children.push(AstNode::Bool(predicate));
            }
            children.extend(query.order_by.iter().map(AstNode::OrderTerm));
            children.extend(query.select.iter().map(AstNode::SelectTerm));
            children.extend(query.group_by.iter().map(AstNode::Expr));
            if let Some(having) = &query.having {
                children.push(AstNode::Bool(having));
            }
            children.extend(query.joins.iter().map(AstNode::JoinClause));
            children.extend(query.ctes.iter().map(AstNode::Cte));
            children.extend(query.set_operations.iter().map(AstNode::SetOperation));
            children
        }
        AstNode::SelectTerm(term) => match &term.expression {
            Some(expression) => vec![AstNode::Expr(expression)],
            None => Vec::new(),
        },
        AstNode::OrderTerm(term) => match &term.expression {
            Some(expression) => vec![AstNode::Expr(expression)],
            None => Vec::new(),
        },
        AstNode::JoinClause(join) => vec![AstNode::Bool(&join.predicate)],
        AstNode::Cte(cte) => vec![AstNode::Query(&cte.query)],
        AstNode::SetOperation(operation) => vec![AstNode::Query(&operation.query)],
        AstNode::CaseWhen(branch) => vec![
            AstNode::Bool(&branch.condition),
            AstNode::Expr(&branch.result),
        ],
        AstNode::Field(_) | AstNode::Literal(_) => Vec::new(),
        AstNode::Bool(node) => match node {
            BoolExpr::Literal(_) => Vec::new(),
            BoolExpr::Unary(unary) => vec![AstNode::Bool(&unary.operand)],
            BoolExpr::Binary(binary) => {
                vec![AstNode::Bool(&binary.left), AstNode::Bool(&binary.right)]
            }
            BoolExpr::Between(between) => vec![
                AstNode::Field(&between.field),
                AstNode::Literal(&between.lower),
                AstNode::Literal(&between.upper),
            ],
            BoolExpr::InList(in_list) => {
                let mut children = vec![AstNode::Field(&in_list.field)];
                children.extend(in_list.values.iter().map(AstNode::Literal));
                children
            }
            BoolExpr::IsNull(is_null) => vec![AstNode::Field(&is_null.field)],
            BoolExpr::TextPredicate(text) => {
                vec![AstNode::Field(&text.field), AstNode::Literal(&text.value)]
            }
            BoolExpr::TruthTest(truth) => vec![AstNode::Bool(&truth.operand)],
            BoolExpr::CollectionPredicate(predicate) => vec![
                AstNode::Expr(&predicate.collection),
                AstNode::Bool(&predicate.predicate),
            ],
            BoolExpr::ScalarIsNull(is_null) => vec![AstNode::Expr(&is_null.expression)],
            BoolExpr::ScalarComparison(comparison) => {
                vec![
                    AstNode::Expr(&comparison.left),
                    AstNode::Expr(&comparison.right),
                ]
            }
        },
        AstNode::Expr(expression) => match expression {
            Expr::Field(_)
            | Expr::RelationField(_)
            | Expr::Literal(_)
            | Expr::CollectionElement(_) => Vec::new(),
            Expr::Unary(unary) => vec![AstNode::Expr(&unary.operand)],
            Expr::Binary(binary) => vec![AstNode::Expr(&binary.left), AstNode::Expr(&binary.right)],
            Expr::Index(index) => vec![
                AstNode::Expr(&index.collection),
                AstNode::Expr(&index.index),
            ],
            Expr::Member(member) => vec![AstNode::Expr(&member.value)],
            Expr::Case(scalar_case) => {
                let mut children: Vec<AstNode<'a>> =
                    scalar_case.whens.iter().map(AstNode::CaseWhen).collect();
                if let Some(else_result) = &scalar_case.else_result {
                    children.push(AstNode::Expr(else_result));
                }
                children
            }
            Expr::Function(function) => function.args.iter().map(AstNode::Expr).collect(),
            Expr::Aggregate(aggregate) => {
                let mut children: Vec<AstNode<'a>> =
                    aggregate.args.iter().map(AstNode::Expr).collect();
                if let Some(predicate) = &aggregate.filter_predicate {
                    children.push(AstNode::Bool(predicate));
                }
                children
            }
            Expr::CollectionCount(count) => {
                vec![
                    AstNode::Expr(&count.collection),
                    AstNode::Bool(&count.predicate),
                ]
            }
            Expr::CollectionFilter(filter) => {
                vec![
                    AstNode::Expr(&filter.collection),
                    AstNode::Bool(&filter.predicate),
                ]
            }
            Expr::CollectionProjection(projection) => {
                vec![
                    AstNode::Expr(&projection.collection),
                    AstNode::Expr(&projection.projection),
                ]
            }
        },
    }
}

/// Yield `root` and descendants depth-first in stable pre-order. `descend`
/// controls whether the children of an already yielded node are visited.
pub fn walk_ast<'a>(root: AstNode<'a>, descend: &dyn Fn(&AstNode<'a>) -> bool) -> Vec<AstNode<'a>> {
    let mut visited: Vec<AstNode<'a>> = Vec::new();
    let mut stack: Vec<AstNode<'a>> = vec![root];
    while let Some(node) = stack.pop() {
        visited.push(node);
        if !descend(&node) {
            continue;
        }
        let mut children = ast_children(&node);
        children.reverse();
        stack.extend(children);
    }
    visited
}

/// The primary source position owned by one node, when it carries one.
pub fn node_position(node: &AstNode<'_>) -> Option<usize> {
    match node {
        AstNode::Query(_) => None,
        AstNode::SelectTerm(term) => Some(term.position),
        AstNode::OrderTerm(term) => Some(term.position),
        AstNode::JoinClause(join) => Some(join.position),
        AstNode::Cte(cte) => Some(cte.position),
        AstNode::SetOperation(operation) => Some(operation.position),
        AstNode::CaseWhen(branch) => Some(branch.position),
        AstNode::Field(field) => Some(field.position),
        AstNode::Literal(literal) => Some(literal.position),
        AstNode::Bool(node) => match node {
            BoolExpr::Literal(literal) => Some(literal.position),
            BoolExpr::CollectionPredicate(predicate) => Some(predicate.position),
            _ => None,
        },
        AstNode::Expr(expression) => Some(expr_position(expression)),
    }
}

/// The position attribute of one scalar expression node (all variants have one).
pub fn expr_position(expression: &Expr) -> usize {
    match expression {
        Expr::Field(field) => field.position,
        Expr::RelationField(field) => field.position,
        Expr::Literal(literal) => literal.position,
        Expr::Unary(unary) => unary.position,
        Expr::Binary(binary) => binary.position,
        Expr::Index(index) => index.position,
        Expr::Member(member) => member.position,
        Expr::Case(scalar_case) => scalar_case.position,
        Expr::Function(function) => function.position,
        Expr::Aggregate(aggregate) => aggregate.position,
        Expr::CollectionElement(element) => element.position,
        Expr::CollectionCount(count) => count.position,
        Expr::CollectionFilter(filter) => filter.position,
        Expr::CollectionProjection(projection) => projection.position,
    }
}

/// The earliest useful source position owned by an AST subtree.
pub fn diagnostic_position(node: &AstNode<'_>, default: usize) -> usize {
    let mut best: Option<usize> = None;
    for visited in walk_ast(*node, &|_| true) {
        if let Some(position) = node_position(&visited) {
            best = Some(match best {
                Some(current) if current <= position => current,
                _ => position,
            });
        }
    }
    best.unwrap_or(default)
}

/// The source position of the first RANDOM expression in a subtree.
pub fn random_position(node: &AstNode<'_>, default: usize) -> usize {
    for visited in walk_ast(*node, &|_| true) {
        if let AstNode::Expr(Expr::Function(function)) = visited
            && function.name == "RANDOM"
        {
            return function.position;
        }
    }
    diagnostic_position(node, default)
}

/// Walk a scalar expression subtree.
pub fn walk_expr<'a>(root: &'a Expr) -> Vec<AstNode<'a>> {
    walk_ast(AstNode::Expr(root), &|_| true)
}

/// Walk a Boolean predicate subtree.
pub fn walk_bool_expr<'a>(root: &'a BoolExpr) -> Vec<AstNode<'a>> {
    walk_ast(AstNode::Bool(root), &|_| true)
}

// ---------------------------------------------------------------------------
// Literal helpers
// ---------------------------------------------------------------------------

fn starts_base_prefix(compact: &str) -> bool {
    let body = compact.strip_prefix(['+', '-']).unwrap_or(compact);
    let mut characters = body.chars();
    characters.next() == Some('0')
        && characters
            .next()
            .map(|second| matches!(second, 'x' | 'X' | 'o' | 'O' | 'b' | 'B'))
            .unwrap_or(false)
}

fn starts_decimal(compact: &str) -> bool {
    compact.starts_with(|character: char| character.is_ascii_digit())
        || (compact.starts_with(['+', '-'])
            && compact[1..].starts_with(|character: char| character.is_ascii_digit()))
}

/// The int/float classification of `_parse_number_text`. The parser port
/// validates numeric text without decoding a value, so the resolver mirrors the
/// Python kind split locally; `parse_number_text` remains the validation and
/// error-message authority. `None` marks an unparseable numeric text.
fn number_kind_of_text(text: &str) -> Option<&'static str> {
    static DECIMAL_INTEGER: OnceLock<Regex> = OnceLock::new();
    static DECIMAL_NUMBER: OnceLock<Regex> = OnceLock::new();
    let decimal_integer =
        DECIMAL_INTEGER.get_or_init(|| Regex::new(r"^[+-]?\d+(?:_\d+)*$").expect("static regex"));
    let decimal_number = DECIMAL_NUMBER.get_or_init(|| {
        Regex::new(r"^[+-]?\d+(?:_\d+)*(?:\.(?:\d+(?:_\d+)*))?$").expect("static regex")
    });
    if starts_base_prefix(text) {
        let body = text.strip_prefix(['+', '-']).unwrap_or(text);
        let mut characters = body.chars();
        let _zero = characters.next();
        let marker = characters.next();
        let digits: String = characters.filter(|character| *character != '_').collect();
        let valid = match marker {
            Some('x') | Some('X') => {
                !digits.is_empty()
                    && digits
                        .chars()
                        .all(|character| character.is_ascii_hexdigit())
            }
            Some('o') | Some('O') => {
                !digits.is_empty()
                    && digits
                        .chars()
                        .all(|character| ('0'..='7').contains(&character))
            }
            Some('b') | Some('B') => {
                !digits.is_empty()
                    && digits
                        .chars()
                        .all(|character| character == '0' || character == '1')
            }
            _ => false,
        };
        return if valid { Some("integer") } else { None };
    }
    if decimal_integer.is_match(text) {
        return Some("integer");
    }
    if text.contains('.') && decimal_number.is_match(text) {
        return Some("number");
    }
    None
}

fn compact_whitespace(text: &str) -> String {
    text.chars()
        .filter(|character| !character.is_whitespace())
        .collect()
}

fn is_infinity_text(text: &str) -> bool {
    parse_temporal_infinity(text).is_some()
}

/// Whether a `Raw`/unquoted-text literal is an infinity sentinel.
fn literal_is_infinity(literal: &Literal) -> bool {
    match &literal.value {
        LiteralValue::Raw => is_infinity_text(&literal.raw),
        _ => false,
    }
}

/// Literal scalar kind, mirroring `_scalar_kind` over the Python value domain.
fn literal_scalar_kind(literal: &Literal) -> Option<String> {
    match &literal.value {
        LiteralValue::Null => None,
        LiteralValue::Bool(_) => Some("boolean".to_string()),
        LiteralValue::Raw => {
            if literal_is_infinity(literal) {
                None
            } else {
                generic_text_kind(&literal.raw)
            }
        }
        LiteralValue::Text(text) => {
            if literal.quoted {
                return Some("string".to_string());
            }
            generic_text_kind(text)
        }
    }
}

/// Kind of an unquoted literal text after Python's `_generic_literal` decoding.
fn generic_text_kind(text: &str) -> Option<String> {
    let lowered = text.to_lowercase();
    if lowered == "true" || lowered == "false" {
        return Some("boolean".to_string());
    }
    let compact = compact_whitespace(text);
    if !starts_base_prefix(&compact) && !starts_decimal(&compact) {
        return Some("string".to_string());
    }
    match number_kind_of_text(&compact) {
        Some("integer") => Some("integer".to_string()),
        Some("number") => Some("number".to_string()),
        _ => Some("string".to_string()),
    }
}

/// Whether a literal's decoded value is non-numeric (and non-NULL), mirroring
/// `not isinstance(operand.value, (int, float))` including Python's bool/int
/// subtyping.
fn literal_is_non_numeric(literal: &Literal) -> bool {
    match &literal.value {
        LiteralValue::Null => false,
        LiteralValue::Bool(_) => false,
        LiteralValue::Raw => generic_text_kind(&literal.raw)
            .map(|kind| !(kind == "integer" || kind == "number"))
            .unwrap_or(true),
        LiteralValue::Text(text) => {
            if literal.quoted {
                return true;
            }
            !matches!(
                generic_text_kind(text).as_deref(),
                Some("integer") | Some("number")
            )
        }
    }
}

/// The integer decoded from a literal, when it decodes as one.
fn literal_integer_value(literal: &Literal) -> Option<i64> {
    let text = match &literal.value {
        LiteralValue::Bool(_) | LiteralValue::Null => return None,
        LiteralValue::Raw => literal.raw.clone(),
        LiteralValue::Text(text) => {
            if literal.quoted {
                return None;
            }
            text.clone()
        }
    };
    let compact = compact_whitespace(&text);
    if number_kind_of_text(&compact) != Some("integer") {
        return None;
    }
    parse_integer_literal_text(&compact, "", 0).ok()
}

fn literal_text(literal: &Literal) -> String {
    match &literal.value {
        LiteralValue::Text(text) => text.clone(),
        LiteralValue::Raw => literal.raw.clone(),
        LiteralValue::Bool(value) => (if *value { "TRUE" } else { "FALSE" }).to_string(),
        LiteralValue::Null => "NULL".to_string(),
    }
}

// ---------------------------------------------------------------------------
// Duration and count parsing (resolver-local in query_resolver.py)
// ---------------------------------------------------------------------------

fn duration_part_regex() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(r"(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>[^\W\d_]+(?:-[^\W\d_]+)*)")
            .expect("static regex")
    })
}

fn fullmatch<'t>(regex: &Regex, text: &'t str) -> Option<regex::Captures<'t>> {
    regex
        .captures(text)
        .filter(|captures| captures.get(0).is_some_and(|m| m.as_str() == text))
}

/// Port of `_parse_duration_text`. Durations round half-to-even to whole
/// seconds; clock forms accept up to three fractional digits. Errors return
/// only the message because `_resolve_literal` re-wraps them at the literal
/// position.
fn parse_duration_text(text: &str) -> Result<i64, String> {
    let value = text.split_whitespace().collect::<Vec<_>>().join(" ");

    static CLOCK: OnceLock<Regex> = OnceLock::new();
    let clock_regex = CLOCK
        .get_or_init(|| Regex::new(r"^\d+(?::\d{1,2}){1,2}(?:\.\d{1,3})?$").expect("static regex"));
    if clock_regex.is_match(&value) {
        let mut clock: Vec<String> = value.split(':').map(str::to_string).collect();
        let mut fraction = 0.0f64;
        let last_index = clock.len() - 1;
        if let Some(dot) = clock[last_index].find('.') {
            let raw_fraction = clock[last_index][dot + 1..].to_string();
            clock[last_index] = clock[last_index][..dot].to_string();
            fraction = format!("0.{}", raw_fraction).parse::<f64>().unwrap_or(0.0);
        }
        let parts: Vec<i128> = clock
            .iter()
            .map(|part| part.parse::<i128>().unwrap_or(0))
            .collect();
        if parts.len() == 2 {
            let (minutes, seconds) = (parts[0], parts[1]);
            if seconds >= 60 {
                return Err("Duration seconds must be below 60.".to_string());
            }
            return Ok(python_round((minutes * 60 + seconds) as f64 + fraction));
        }
        let (hours, minutes, seconds) = (parts[0], parts[1], parts[2]);
        if minutes >= 60 || seconds >= 60 {
            return Err("Duration minutes and seconds must be below 60.".to_string());
        }
        return Ok(python_round(
            (hours * 3600 + minutes * 60 + seconds) as f64 + fraction,
        ));
    }

    static PLAIN: OnceLock<Regex> = OnceLock::new();
    let plain_regex = PLAIN.get_or_init(|| Regex::new(r"^\d+(?:\.\d+)?$").expect("static regex"));
    if plain_regex.is_match(&value) {
        return Err("A duration needs a unit, for example 30s, 10m, 2h, or 1h30m.".to_string());
    }

    let mut value = value;
    let compact = value.replace(' ', "");
    static COMPACT_UNITS: OnceLock<Regex> = OnceLock::new();
    let compact_regex = COMPACT_UNITS
        .get_or_init(|| Regex::new(r"(?i)^(?:\d+(?:\.\d+)?(?:h|m|s))+$").expect("static regex"));
    if compact_regex.is_match(&compact) {
        value = compact;
    }

    let mut total = 0.0f64;
    let mut cursor = 0usize;
    let mut matched = false;
    let registry = load_default_unit_registry();
    for captures in duration_part_regex().captures_iter(&value) {
        let whole = captures.get(0).expect("group 0");
        let number_text = captures.name("number").expect("number group").as_str();
        let unit_text = captures.name("unit").expect("unit group").as_str();
        if !value[cursor..whole.start()].trim().is_empty() {
            return Err(format!(
                "Could not understand duration {}.",
                python_repr(text)
            ));
        }
        let unit = match registry.resolve(unit_text) {
            Ok(unit) => unit,
            Err(_) => return Err(format!("Unknown duration unit {}.", python_repr(unit_text))),
        };
        if unit.kind != crate::units::FIXED {
            return Err(format!(
                "Calendar unit {} cannot be used for a duration.",
                python_repr(unit_text)
            ));
        }
        matched = true;
        total += number_text.parse::<f64>().unwrap_or(0.0) * unit.amount;
        cursor = whole.end();
    }
    if !matched || !value[cursor..].trim().is_empty() {
        return Err(format!(
            "Could not understand duration {}.",
            python_repr(text)
        ));
    }
    Ok(python_round(total))
}

/// Port of `_parse_count_text`. Counts accept signed decimals with k/m/b
/// suffixes and 0x/0o/0b base prefixes.
fn parse_count_text(text: &str, source: &str, position: usize) -> Result<i64, String> {
    let compact = compact_whitespace(text);
    if starts_base_prefix(&compact) {
        return match parse_integer_literal_text(&compact, source, position) {
            Ok(value) => Ok(value),
            Err(error) => Err(error.message),
        };
    }

    static COUNT: OnceLock<Regex> = OnceLock::new();
    let count_regex = COUNT.get_or_init(|| {
        Regex::new(r"^([+-]?)(\d+(?:_\d+)*(?:\.\d+(?:_\d+)*)?)([kKmMbB]?)$").expect("static regex")
    });
    let Some(captures) = fullmatch(count_regex, &compact) else {
        return Err(format!("Could not understand count {}.", python_repr(text)));
    };
    let sign = captures.get(1).map(|m| m.as_str()).unwrap_or("");
    let number_text = captures
        .get(2)
        .map(|m| m.as_str())
        .unwrap_or("")
        .replace('_', "");
    let suffix = captures
        .get(3)
        .map(|m| m.as_str())
        .unwrap_or("")
        .to_lowercase();
    let multiplier: f64 = match suffix.as_str() {
        "" => 1.0,
        "k" => 1_000.0,
        "m" => 1_000_000.0,
        "b" => 1_000_000_000.0,
        _ => 1.0,
    };
    let number = match number_text.parse::<f64>() {
        Ok(number) => number,
        Err(_) => return Err(format!("Could not understand count {}.", python_repr(text))),
    };
    let value = python_round(number * multiplier);
    Ok(if sign == "-" { -value } else { value })
}

// ---------------------------------------------------------------------------
// Field and literal resolution
// ---------------------------------------------------------------------------

/// Port of `difflib.get_close_matches(word, candidates, n=1, cutoff=0.6)`.
/// Only the suggestion text depends on this, so an LCS-based ratio with the
/// same cutoff is an acceptable approximation.
fn close_matches(word: &str, candidates: &[String], cutoff: f64) -> Option<String> {
    let word_characters: Vec<char> = word.chars().collect();
    let mut best: Option<(f64, &String)> = None;
    for candidate in candidates {
        let candidate_characters: Vec<char> = candidate.chars().collect();
        let total = word_characters.len() + candidate_characters.len();
        if total == 0 {
            continue;
        }
        let matched = longest_common_subsequence(&word_characters, &candidate_characters) as f64;
        let ratio = 2.0 * matched / total as f64;
        if ratio >= cutoff && best.is_none_or(|(current, _)| ratio > current) {
            best = Some((ratio, candidate));
        }
    }
    best.map(|(_, candidate)| candidate.clone())
}

fn longest_common_subsequence(left: &[char], right: &[char]) -> usize {
    if left.is_empty() || right.is_empty() {
        return 0;
    }
    let mut previous = vec![0usize; right.len() + 1];
    let mut current = vec![0usize; right.len() + 1];
    for l in left {
        for (index, r) in right.iter().enumerate() {
            current[index + 1] = if l == r {
                previous[index] + 1
            } else {
                previous[index + 1].max(current[index])
            };
        }
        std::mem::swap(&mut previous, &mut current);
        current.iter_mut().for_each(|slot| *slot = 0);
    }
    previous[right.len()]
}

/// Resolve one field name against the schema (`_resolve_field`).
fn resolve_field(field: &Field, schema: &QuerySchema, source: &str) -> Result<Field, QueryError> {
    let Some(info) = schema.resolve(&field.name) else {
        let candidates: Vec<String> = schema
            .available_fields()
            .into_iter()
            .map(|info| info.name)
            .collect();
        let mut message = format!("Unknown field {}.", python_repr(&field.name));
        if let Some(suggestion) = close_matches(&field.name, &candidates, 0.6) {
            message += &format!(" Did you mean {}?", python_repr(&suggestion));
        }
        return Err(QueryError::semantic(
            source,
            message,
            field.position,
            "unknown-field",
        ));
    };
    let canonical = info.alias_of.clone().unwrap_or_else(|| info.name.clone());
    Ok(Field {
        name: canonical,
        position: field.position,
        kind: Some(info.kind.clone()),
    })
}

/// Resolve one literal against a field kind (`_resolve_literal`).
///
/// Returns the literal with its `raw` canonicalised for the date, datetime and
/// duration kinds (Python stores decoded date/datetime/duration values in the
/// literal's `value`; the Rust model carries them in `raw` so the evaluator and
/// formatter can decode deterministically).
fn resolve_literal(
    literal: &Literal,
    field_kind: Option<&str>,
    field_name: &str,
    field_position: usize,
    source: &str,
    dates: &DateContext,
) -> Result<Literal, QueryError> {
    let value = match &literal.value {
        LiteralValue::Null | LiteralValue::Bool(_) => return Ok(literal.clone()),
        LiteralValue::Text(text) => text.clone(),
        LiteralValue::Raw => literal.raw.clone(),
    };
    let kind = field_kind.unwrap_or("unknown");

    if is_infinity_text(&value) && kind != "date" && kind != "datetime" {
        return Err(semantic_error(
            source,
            "INFINITY() and -INFINITY() are valid only for date or datetime fields.",
            literal.position,
        ));
    }

    // Every Python branch below raises (subclasses of) ValueError, which
    // `_resolve_literal` catches and re-raises as QuerySemanticError at the
    // literal position, keeping `str(exc)` as the message.
    let resolved: Result<(LiteralValue, Option<String>), String> = (|| {
        if kind == "duration" {
            let seconds = parse_duration_text(&value)?;
            return Ok((LiteralValue::Raw, Some(format!("{seconds}s"))));
        }
        if kind == "count" {
            let _count = parse_count_text(&value, source, literal.position)?;
            return Ok((LiteralValue::Raw, None));
        }
        if kind == "date" {
            if is_infinity_text(&value) {
                return Ok((LiteralValue::Raw, Some(canonical_infinity(&value))));
            }
            // parse_date_literal validates temporal expressions against the
            // expected kind exactly like Python's
            // `parse_temporal_expression(expected="date")`.
            let date = parse_date_literal(&value, dates)?;
            // A TODAY()-form expression keeps its raw spelling: the formatter's
            // temporal-expression branch renders it canonically (Python keeps
            // `raw` and renders from the decoded date otherwise).
            if canonicalise_temporal_expression(&value).is_some() {
                return Ok((LiteralValue::Raw, None));
            }
            return Ok((LiteralValue::Raw, Some(date.to_string())));
        }
        if kind == "datetime" {
            if is_infinity_text(&value) {
                return Ok((LiteralValue::Raw, Some(canonical_infinity(&value))));
            }
            let datetime = parse_datetime_literal(&value, dates)?;
            if canonicalise_temporal_expression(&value).is_some() {
                return Ok((LiteralValue::Raw, None));
            }
            return Ok((LiteralValue::Raw, Some(datetime_isoformat_auto(&datetime))));
        }
        if kind == "integer" {
            // Python calls `_parse_number_text(text, ...)` with the raw literal
            // text; the parser compacts whitespace internally and its error
            // message quotes the original text.
            return match parse_number_text(&value, source, literal.position) {
                Ok(_) => {
                    if number_kind_of_text(&compact_whitespace(&value)) == Some("integer") {
                        Ok((LiteralValue::Text(value.clone()), None))
                    } else {
                        Err(format!(
                            "Field {} requires an integer.",
                            python_repr(field_name)
                        ))
                    }
                }
                Err(error) => Err(error.message),
            };
        }
        if kind == "number" {
            return match parse_number_text(&value, source, literal.position) {
                Ok(_) => Ok((LiteralValue::Text(value.clone()), None)),
                Err(error) => Err(error.message),
            };
        }
        if kind == "boolean" {
            let lowered = value.to_lowercase();
            if lowered != "true" && lowered != "false" {
                return Err(format!(
                    "Field {} requires TRUE or FALSE.",
                    python_repr(field_name)
                ));
            }
            return Ok((LiteralValue::Bool(lowered == "true"), None));
        }
        if kind == "structured" {
            return Err(format!(
                "Field {} is an object or array and cannot be used as a scalar value.",
                python_repr(field_name)
            ));
        }
        if kind == "string" {
            return Ok((LiteralValue::Text(value.clone()), None));
        }
        // "mixed", "unknown", "collection" and anything else: generic literal.
        Ok(generic_literal(&value, literal.quoted, field_position))
    })();
    let (value, raw_override) =
        resolved.map_err(|message| semantic_error(source, message, literal.position))?;
    let mut resolved_literal = literal.clone();
    resolved_literal.value = value;
    if let Some(raw) = raw_override {
        resolved_literal.raw = raw;
    }
    Ok(resolved_literal)
}

fn canonical_infinity(text: &str) -> String {
    if compact_whitespace(text).to_uppercase().starts_with('-') {
        "-INFINITY()".to_string()
    } else {
        "INFINITY()".to_string()
    }
}

/// Python `datetime.isoformat(timespec="auto")` with the UTC offset rendered
/// as `Z`.
fn datetime_isoformat_auto(value: &chrono::DateTime<chrono::FixedOffset>) -> String {
    use chrono::{Datelike, Timelike};
    let base = format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}",
        value.year(),
        value.month(),
        value.day(),
        value.hour(),
        value.minute(),
        value.second()
    );
    let micros = value.nanosecond() / 1000;
    let mut text = if micros == 0 {
        base
    } else {
        format!("{base}.{micros:06}")
    };
    let offset_seconds = value.offset().local_minus_utc();
    if offset_seconds == 0 {
        text.push('Z');
    } else {
        let sign = if offset_seconds < 0 { '-' } else { '+' };
        let magnitude = offset_seconds.abs();
        text.push_str(&format!(
            "{sign}{:02}:{:02}",
            magnitude / 3600,
            (magnitude % 3600) / 60
        ));
    }
    text
}

/// Port of `_generic_literal`. The Rust literal model keeps the text and lets
/// the evaluator/formatter decode numbers and boolean words from it.
fn generic_literal(text: &str, quoted: bool, _position: usize) -> (LiteralValue, Option<String>) {
    let _ = quoted;
    (LiteralValue::Text(text.to_string()), None)
}

// ---------------------------------------------------------------------------
// Scalar kinds and types
// ---------------------------------------------------------------------------

/// `_scalar_kind`: the resolved kind attribute of an expression node, or the
/// decoded literal kind.
pub fn scalar_kind(expression: &Expr) -> Option<String> {
    match expression {
        Expr::Field(field) => field.kind.clone(),
        Expr::RelationField(field) => field.kind.clone(),
        Expr::Literal(literal) => literal_scalar_kind(literal),
        Expr::Unary(unary) => unary.kind.clone(),
        Expr::Binary(binary) => binary.kind.clone(),
        Expr::Index(index) => index.kind.clone(),
        Expr::Member(member) => member.kind.clone(),
        Expr::Case(scalar_case) => scalar_case.kind.clone(),
        Expr::Function(function) => function.kind.clone(),
        Expr::Aggregate(aggregate) => aggregate.kind.clone(),
        Expr::CollectionElement(element) => element.kind.clone(),
        Expr::CollectionCount(count) => count.kind.clone(),
        Expr::CollectionFilter(filter) => filter.kind.clone(),
        Expr::CollectionProjection(projection) => projection.kind.clone(),
    }
}

fn node_resolved_type(expression: &Expr) -> Option<&QueryType> {
    match expression {
        Expr::CollectionElement(element) => element.resolved_type.as_ref(),
        Expr::CollectionCount(count) => count.resolved_type.as_ref(),
        Expr::CollectionFilter(filter) => filter.resolved_type.as_ref(),
        Expr::CollectionProjection(projection) => projection.resolved_type.as_ref(),
        Expr::Index(index) => index.resolved_type.as_ref(),
        Expr::Member(member) => member.resolved_type.as_ref(),
        Expr::Function(function) => function.resolved_type.as_ref(),
        _ => None,
    }
}

/// `_scalar_query_type`: the complete resolved yt-sql type when available.
pub fn scalar_query_type(expression: &Expr, schema: &QuerySchema) -> Option<QueryType> {
    if let Some(resolved) = node_resolved_type(expression) {
        return Some(resolved.clone());
    }
    if let Expr::Field(field) = expression {
        let mut info = schema.resolve(&field.name);
        if field.kind.as_deref() == Some("collection")
            && info.is_none_or(|candidate| candidate.kind != "collection")
        {
            info = schema.resolve_index_operand(&field.name);
        }
        return info.map(|candidate| candidate.query_type());
    }
    let kind = scalar_kind(expression)?;
    Some(QueryType::scalar(&kind, true))
}

/// `_value_preserving_function_type`: a compatible collection or structured
/// result type for preserving functions.
fn value_preserving_function_type(args: &[Expr], schema: &QuerySchema) -> Option<QueryType> {
    let types: Vec<QueryType> = args
        .iter()
        .filter_map(|arg| scalar_query_type(arg, schema))
        .collect();
    let complex_types: Vec<&QueryType> = types
        .iter()
        .filter(|candidate| candidate.is_collection() || candidate.is_structured())
        .collect();
    let first = complex_types.first()?;
    if complex_types.iter().any(|candidate| **candidate != **first) {
        return None;
    }
    if types
        .iter()
        .any(|candidate| !(candidate.is_collection() || candidate.is_structured()))
    {
        return None;
    }
    Some(first.with_nullable(true))
}

fn is_numeric_kind(kind: Option<&str>) -> bool {
    matches!(
        kind,
        Some("integer") | Some("number") | Some("count") | Some("duration")
    )
}

/// The declared element type of a validated collection type. Schemas are
/// caller-supplied runtime data, so an inconsistent collection type becomes a
/// diagnostic instead of a panic.
fn collection_element_type<'a>(
    candidate: &'a QueryType,
    source: &str,
    position: usize,
) -> Result<&'a QueryType, QueryError> {
    candidate.element_type.as_deref().ok_or_else(|| {
        semantic_error(
            source,
            "Collection types must declare an element type.",
            position,
        )
    })
}

fn common_kinds(expressions: &[&Expr]) -> Vec<String> {
    expressions
        .iter()
        .filter_map(|expression| scalar_kind(expression))
        .collect()
}

fn sorted_unique(kinds: &[String]) -> Vec<String> {
    let mut unique = kinds.to_vec();
    unique.sort();
    unique.dedup();
    unique
}

/// `_common_case_kind`: the compatible CASE result kind, ignoring NULL-only
/// branches.
fn common_case_kind(
    expressions: &[&Expr],
    source: &str,
    position: usize,
) -> Result<Option<String>, QueryError> {
    let kinds = common_kinds(expressions);
    if kinds.is_empty() {
        return Ok(None);
    }
    let unique = sorted_unique(&kinds);
    if unique.len() == 1 {
        return Ok(Some(kinds[0].clone()));
    }
    if kinds.iter().all(|kind| is_numeric_kind(Some(kind))) {
        return Ok(Some("number".to_string()));
    }
    if unique
        .iter()
        .any(|kind| kind == "mixed" || kind == "unknown")
    {
        return Ok(Some("mixed".to_string()));
    }
    Err(semantic_error(
        source,
        format!(
            "CASE result expressions must have compatible types; got {}.",
            unique.join(", ")
        ),
        position,
    ))
}

/// `_common_scalar_kind`: one compatible scalar kind for multi-argument
/// scalar functions.
fn common_scalar_kind(
    expressions: &[&Expr],
    source: &str,
    position: usize,
    function_name: &str,
) -> Result<Option<String>, QueryError> {
    let kinds = common_kinds(expressions);
    if kinds.is_empty() {
        return Ok(None);
    }
    let unique = sorted_unique(&kinds);
    if unique.len() == 1 {
        return Ok(Some(kinds[0].clone()));
    }
    if kinds.iter().all(|kind| is_numeric_kind(Some(kind))) {
        return Ok(Some("number".to_string()));
    }
    if unique
        .iter()
        .any(|kind| kind == "mixed" || kind == "unknown")
    {
        return Ok(Some("mixed".to_string()));
    }
    Err(QueryError::semantic(
        source,
        format!(
            "{} arguments must have compatible types; got {}.",
            function_name,
            unique.join(", ")
        ),
        position,
        "incompatible-scalar-argument",
    ))
}

/// Python `evaluate_scalar_expression(expression, {})`: constant evaluation
/// against an empty record context.
fn evaluate_constant(expression: &Expr) -> Value {
    let empty_context = crate::evaluator::EvaluationContext::new(Vec::new());
    crate::evaluator::evaluate_scalar_expression(expression, &empty_context)
}

/// `_is_constant_scalar_expression`: whether an expression can be evaluated
/// without row metadata.
fn is_constant_scalar_expression(expression: &Expr) -> bool {
    match expression {
        Expr::Literal(_) => true,
        Expr::Unary(unary) => is_constant_scalar_expression(&unary.operand),
        Expr::Binary(binary) => {
            is_constant_scalar_expression(&binary.left)
                && is_constant_scalar_expression(&binary.right)
        }
        Expr::Function(function) => function.args.iter().all(is_constant_scalar_expression),
        Expr::Index(index) => {
            is_constant_scalar_expression(&index.collection)
                && is_constant_scalar_expression(&index.index)
        }
        _ => false,
    }
}

/// Validate a constant CHAR argument (`_validate_char_codepoint`).
///
/// The evaluator exposes `coerce_char_codepoint` as `Option<u32>` collapsing
/// Python's TypeError/ValueError; the integer-valued discrimination that picks
/// the range message is reproduced here from the original value, exactly like
/// Python's `float(value).is_integer()` check.
fn validate_char_codepoint(value: &Value, source: &str, position: usize) -> Result<(), QueryError> {
    match coerce_char_codepoint(value) {
        Some(_) => Ok(()),
        None => {
            let integer_valued = match value {
                Value::Int(_) => true,
                Value::Float(number) => number.is_finite() && *number == number.trunc(),
                _ => false,
            };
            if integer_valued {
                Err(QueryError::semantic(
                    source,
                    "CHAR code points must be Unicode scalar values from 0 to 1114111, excluding surrogates.",
                    position,
                    "invalid-char-codepoint",
                ))
            } else {
                Err(QueryError::semantic(
                    source,
                    "CHAR requires integer code-point values.",
                    position,
                    "invalid-char-codepoint",
                ))
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Scalar expression resolution
// ---------------------------------------------------------------------------

/// Resolve fields, aliases and types for a scalar expression
/// (`_resolve_scalar_expression`).
#[allow(clippy::too_many_arguments)]
pub fn resolve_scalar_expression(
    expression: &Expr,
    schema: &QuerySchema,
    source: &str,
    dates: &DateContext,
    aliases: Option<&AliasTable>,
    select_context: bool,
    allow_structured: bool,
    collection_scopes: &[QueryType],
) -> Result<Expr, QueryError> {
    match expression {
        // JOIN scope resolution has already established relation ownership and
        // the field kind. Preserve that binding while the ordinary scalar
        // resolver resolves surrounding literals, operators and functions.
        Expr::RelationField(_) => Ok(expression.clone()),
        Expr::CollectionElement(expression) => {
            let scopes_len = collection_scopes.len() as isize;
            let index = scopes_len - 1 - expression.scope_distance as isize;
            if index < 0 || index >= scopes_len {
                return Err(semantic_error(
                    source,
                    format!(
                        "Collection binding {} is outside its lexical scope.",
                        python_repr(&expression.binding)
                    ),
                    expression.position,
                ));
            }
            let result_type = &collection_scopes[index as usize];
            Ok(Expr::CollectionElement(CollectionElementReference {
                binding: expression.binding.clone(),
                scope_distance: expression.scope_distance,
                position: expression.position,
                kind: Some(result_type.kind.clone()),
                resolved_type: Some(result_type.clone()),
            }))
        }
        Expr::Field(expression) => {
            if let Some(aliases) = aliases
                && let Some(alias) = aliases.get(&expression.name)
            {
                return Ok(match &alias.expression {
                    Some(alias_expression) => (**alias_expression).clone(),
                    None => Expr::Field(Field {
                        name: alias.field.clone(),
                        position: expression.position,
                        kind: alias.kind.clone(),
                    }),
                });
            }
            let field = resolve_field(expression, schema, source)?;
            if field.kind.as_deref() == Some("structured") && !allow_structured {
                let message = if select_context {
                    format!(
                        "Cannot SELECT structured field {}; select a scalar nested path instead.",
                        python_repr(&field.name)
                    )
                } else {
                    format!(
                        "Field {} is structured; use a scalar nested path instead.",
                        python_repr(&field.name)
                    )
                };
                return Err(QueryError::semantic(
                    source,
                    message,
                    field.position,
                    "unknown-field",
                ));
            }
            Ok(Expr::Field(field))
        }
        // Numeric, boolean, quoted-string and NULL literals already carry their
        // decoded shape in the Rust model; Python re-wraps them with
        // `_generic_literal`, which is a no-op for these value domains.
        Expr::Literal(_) => Ok(expression.clone()),
        Expr::Unary(expression) => {
            let operand = resolve_scalar_expression(
                &expression.operand,
                schema,
                source,
                dates,
                aliases,
                select_context,
                false,
                collection_scopes,
            )?;
            let kind = scalar_kind(&operand);
            if !is_numeric_kind(kind.as_deref()) && !matches!(operand, Expr::Literal(_)) {
                return Err(semantic_error(
                    source,
                    format!("Unary {} requires a numeric value.", expression.operator),
                    expression.position,
                ));
            }
            if let Expr::Literal(literal) = &operand
                && literal_is_non_numeric(literal)
            {
                return Err(semantic_error(
                    source,
                    format!("Unary {} requires a numeric value.", expression.operator),
                    expression.position,
                ));
            }
            Ok(Expr::Unary(ScalarUnary {
                operator: expression.operator.clone(),
                operand: Box::new(operand),
                position: expression.position,
                kind: Some(kind.unwrap_or_else(|| "number".to_string())),
            }))
        }
        Expr::Binary(expression) => {
            let left = resolve_scalar_expression(
                &expression.left,
                schema,
                source,
                dates,
                aliases,
                select_context,
                false,
                collection_scopes,
            )?;
            let right = resolve_scalar_expression(
                &expression.right,
                schema,
                source,
                dates,
                aliases,
                select_context,
                false,
                collection_scopes,
            )?;
            for operand in [&left, &right] {
                let kind = scalar_kind(operand);
                if kind.is_some() && !is_numeric_kind(kind.as_deref()) {
                    return Err(semantic_error(
                        source,
                        format!(
                            "Arithmetic operator {} requires numeric values.",
                            python_repr(&expression.operator)
                        ),
                        expression.position,
                    ));
                }
                if let Expr::Literal(literal) = operand
                    && literal_is_non_numeric(literal)
                {
                    return Err(semantic_error(
                        source,
                        format!(
                            "Arithmetic operator {} requires numeric values.",
                            python_repr(&expression.operator)
                        ),
                        expression.position,
                    ));
                }
            }
            Ok(Expr::Binary(ScalarBinary {
                operator: expression.operator.clone(),
                left: Box::new(left),
                right: Box::new(right),
                position: expression.position,
                kind: Some("number".to_string()),
            }))
        }
        Expr::Case(expression) => {
            let mut resolved_whens: Vec<CaseWhen> = Vec::new();
            let mut results: Vec<Expr> = Vec::new();
            for branch in &expression.whens {
                let condition =
                    resolve_predicate(&branch.condition, schema, source, dates, collection_scopes)?;
                let result = resolve_scalar_expression(
                    &branch.result,
                    schema,
                    source,
                    dates,
                    aliases,
                    select_context,
                    false,
                    collection_scopes,
                )?;
                resolved_whens.push(CaseWhen {
                    condition: Box::new(condition),
                    result: Box::new(result.clone()),
                    position: branch.position,
                });
                results.push(result);
            }
            let mut else_result: Option<Box<Expr>> = None;
            if let Some(else_expression) = &expression.else_result {
                let resolved_else = resolve_scalar_expression(
                    else_expression,
                    schema,
                    source,
                    dates,
                    aliases,
                    select_context,
                    false,
                    collection_scopes,
                )?;
                results.push(resolved_else.clone());
                else_result = Some(Box::new(resolved_else));
            }
            let results_refs: Vec<&Expr> = results.iter().collect();
            let kind = common_case_kind(&results_refs, source, expression.position)?;
            Ok(Expr::Case(ScalarCase {
                whens: resolved_whens,
                else_result,
                position: expression.position,
                kind,
            }))
        }
        Expr::Member(expression) => {
            let value = resolve_scalar_expression(
                &expression.value,
                schema,
                source,
                dates,
                aliases,
                select_context,
                true,
                collection_scopes,
            )?;
            let value_type = scalar_query_type(&value, schema);
            let structured = value_type
                .as_ref()
                .is_some_and(|candidate| candidate.is_structured());
            if value_type.is_none() || !structured {
                let kind = scalar_kind(&value).unwrap_or_else(|| "unknown".to_string());
                return Err(semantic_error(
                    source,
                    format!("Structured member access requires a structured value; got {kind}."),
                    expression.position,
                ));
            }
            let value_type = value_type.expect("checked above");
            if !value_type.has_declared_members() {
                return Err(semantic_error(
                    source,
                    "Structured member access requires a declared member schema; got opaque structured value.",
                    expression.position,
                ));
            }
            let Some(result_type) = value_type.member_result_type(&expression.member) else {
                return Err(semantic_error(
                    source,
                    format!(
                        "Structured value has no member {}.",
                        python_repr(&expression.member)
                    ),
                    expression.position,
                ));
            };
            Ok(Expr::Member(ScalarMember {
                value: Box::new(value),
                member: expression.member.clone(),
                position: expression.position,
                kind: Some(result_type.kind.clone()),
                resolved_type: Some(result_type),
            }))
        }
        Expr::Index(expression) => {
            let aliased_collection = aliases.is_some_and(|aliases| match &*expression.collection {
                Expr::Field(field) => aliases.contains_key(&field.name),
                _ => false,
            });
            let collection: Expr =
                if matches!(&*expression.collection, Expr::Field(_)) && !aliased_collection {
                    // Resolve a direct field without applying the standalone
                    // structured-value selection restriction first. Indexing owns
                    // the diagnostic for whether that field is a valid collection
                    // operand.
                    let field = match &*expression.collection {
                        Expr::Field(field) => field,
                        _ => unreachable!("checked above"),
                    };
                    match schema.resolve_index_operand(&field.name) {
                        Some(index_field) => Expr::Field(Field {
                            name: index_field.name.clone(),
                            position: field.position,
                            kind: Some(index_field.kind.clone()),
                        }),
                        None => Expr::Field(resolve_field(field, schema, source)?),
                    }
                } else {
                    resolve_scalar_expression(
                        &expression.collection,
                        schema,
                        source,
                        dates,
                        aliases,
                        select_context,
                        false,
                        collection_scopes,
                    )?
                };
            let index = resolve_scalar_expression(
                &expression.index,
                schema,
                source,
                dates,
                aliases,
                select_context,
                false,
                collection_scopes,
            )?;
            let collection_type = scalar_query_type(&collection, schema);
            let is_collection = collection_type
                .as_ref()
                .is_some_and(|candidate| candidate.is_collection());
            if collection_type.is_none() || !is_collection {
                let kind = scalar_kind(&collection).unwrap_or_else(|| "unknown".to_string());
                return Err(semantic_error(
                    source,
                    format!("Collection indexing requires a collection value; got {kind}."),
                    expression.position,
                ));
            }
            let collection_type = collection_type.expect("checked above");
            if !collection_type.supports_positional_indexing() {
                return Err(semantic_error(
                    source,
                    "Collection indexing requires a stable logical collection ordering.",
                    expression.position,
                ));
            }

            let index_kind = scalar_kind(&index);
            if is_constant_scalar_expression(&index) {
                let index_value = evaluate_constant(&index);
                if !matches!(index_value, Value::Null) {
                    if matches!(index_value, Value::Bool(_)) {
                        return Err(semantic_error(
                            source,
                            "Collection index must be an integer value.",
                            expression.position,
                        ));
                    }
                    match index_value {
                        Value::Int(value) => {
                            if value < 0 {
                                return Err(semantic_error(
                                    source,
                                    "Collection index must not be negative.",
                                    expression.position,
                                ));
                            }
                        }
                        _ => {
                            return Err(semantic_error(
                                source,
                                "Collection index must be an integer value.",
                                expression.position,
                            ));
                        }
                    }
                }
            } else if !matches!(
                index_kind.as_deref(),
                None | Some("integer") | Some("count")
            ) {
                return Err(semantic_error(
                    source,
                    "Collection index must be an integer value.",
                    expression.position,
                ));
            }

            let result_type = match collection_type.indexed_result_type() {
                Ok(result_type) => result_type,
                // Both preconditions were checked above, so this only guards
                // against panics on runtime data.
                Err(_) => match collection_type.element_type.as_deref() {
                    Some(element) => element.with_nullable(true),
                    None => {
                        return Err(semantic_error(
                            source,
                            "Collection indexing requires a collection value.",
                            expression.position,
                        ));
                    }
                },
            };
            Ok(Expr::Index(ScalarIndex {
                collection: Box::new(collection),
                index: Box::new(index),
                position: expression.position,
                kind: Some(result_type.kind.clone()),
                resolved_type: Some(result_type),
            }))
        }
        Expr::CollectionCount(expression) => {
            let collection = resolve_scalar_expression(
                &expression.collection,
                schema,
                source,
                dates,
                aliases,
                select_context,
                true,
                collection_scopes,
            )?;
            let collection_type = scalar_query_type(&collection, schema);
            let is_collection = collection_type
                .as_ref()
                .is_some_and(|candidate| candidate.is_collection());
            if collection_type.is_none() || !is_collection {
                let kind = scalar_kind(&collection).unwrap_or_else(|| "unknown".to_string());
                return Err(QueryError::semantic(
                    source,
                    format!("Collection COUNT requires a collection value; got {kind}."),
                    expression.position,
                    "invalid-collection-operand",
                ));
            }
            let collection_type = collection_type.expect("checked above");
            let mut scopes = collection_scopes.to_vec();
            scopes.push(
                collection_element_type(&collection_type, source, expression.position)?.clone(),
            );
            let predicate =
                resolve_predicate(&expression.predicate, schema, source, dates, &scopes)?;
            let result_type = QueryType::scalar("integer", collection_type.nullable);
            Ok(Expr::CollectionCount(CollectionCount {
                collection: Box::new(collection),
                binding: expression.binding.clone(),
                predicate: Box::new(predicate),
                position: expression.position,
                kind: Some("integer".to_string()),
                resolved_type: Some(result_type),
            }))
        }
        Expr::CollectionFilter(expression) => {
            let collection = resolve_scalar_expression(
                &expression.collection,
                schema,
                source,
                dates,
                aliases,
                select_context,
                true,
                collection_scopes,
            )?;
            let collection_type = scalar_query_type(&collection, schema);
            let is_collection = collection_type
                .as_ref()
                .is_some_and(|candidate| candidate.is_collection());
            if collection_type.is_none() || !is_collection {
                let kind = scalar_kind(&collection).unwrap_or_else(|| "unknown".to_string());
                return Err(QueryError::semantic(
                    source,
                    format!("FILTER requires a collection value; got {kind}."),
                    expression.position,
                    "invalid-collection-operand",
                ));
            }
            let collection_type = collection_type.expect("checked above");
            let mut scopes = collection_scopes.to_vec();
            scopes.push(
                collection_element_type(&collection_type, source, expression.position)?.clone(),
            );
            let predicate =
                resolve_predicate(&expression.predicate, schema, source, dates, &scopes)?;
            Ok(Expr::CollectionFilter(CollectionFilter {
                collection: Box::new(collection),
                binding: expression.binding.clone(),
                predicate: Box::new(predicate),
                position: expression.position,
                kind: Some("collection".to_string()),
                resolved_type: Some(collection_type),
            }))
        }
        Expr::CollectionProjection(expression) => {
            let collection = resolve_scalar_expression(
                &expression.collection,
                schema,
                source,
                dates,
                aliases,
                select_context,
                true,
                collection_scopes,
            )?;
            let collection_type = scalar_query_type(&collection, schema);
            let is_collection = collection_type
                .as_ref()
                .is_some_and(|candidate| candidate.is_collection());
            if collection_type.is_none() || !is_collection {
                let kind = scalar_kind(&collection).unwrap_or_else(|| "unknown".to_string());
                return Err(QueryError::semantic(
                    source,
                    format!("MAP requires a collection value; got {kind}."),
                    expression.position,
                    "invalid-collection-operand",
                ));
            }
            let collection_type = collection_type.expect("checked above");
            let mut scopes = collection_scopes.to_vec();
            scopes.push(
                collection_element_type(&collection_type, source, expression.position)?.clone(),
            );
            let projection = resolve_scalar_expression(
                &expression.projection,
                schema,
                source,
                dates,
                aliases,
                false,
                true,
                &scopes,
            )?;
            if contains_aggregate(&projection) {
                return Err(QueryError::semantic(
                    source,
                    "MAP projection cannot contain aggregate functions.",
                    expression.position,
                    "aggregate-in-collection-projection",
                ));
            }
            let projection_type = match scalar_query_type(&projection, schema) {
                Some(projection_type) => projection_type,
                None => QueryType::scalar(
                    &scalar_kind(&projection).unwrap_or_else(|| "unknown".to_string()),
                    true,
                ),
            };
            let result_type = QueryType::collection(
                projection_type,
                collection_type.nullable,
                collection_type
                    .ordering
                    .unwrap_or(CollectionOrdering::Unknown),
            );
            let evaluation_fusion_safe = match &collection {
                Expr::CollectionFilter(filter) => {
                    !contains_random_predicate(Some(&filter.predicate))
                        && !contains_random(&projection)
                }
                _ => false,
            };
            Ok(Expr::CollectionProjection(CollectionProjection {
                collection: Box::new(collection),
                binding: expression.binding.clone(),
                projection: Box::new(projection),
                position: expression.position,
                kind: Some("collection".to_string()),
                resolved_type: Some(result_type),
                evaluation_fusion_safe,
            }))
        }
        Expr::Aggregate(expression) => {
            let mut args: Vec<Expr> = Vec::new();
            for argument in &expression.args {
                args.push(resolve_scalar_expression(
                    argument,
                    schema,
                    source,
                    dates,
                    aliases,
                    select_context,
                    false,
                    collection_scopes,
                )?);
            }
            if args.iter().any(contains_aggregate) {
                return Err(QueryError::semantic(
                    source,
                    "Aggregate functions cannot be nested.",
                    expression.position,
                    "aggregate-nesting",
                ));
            }
            let filter_predicate = match &expression.filter_predicate {
                Some(predicate) => Some(Box::new(resolve_predicate(
                    predicate,
                    schema,
                    source,
                    dates,
                    &[],
                )?)),
                None => None,
            };
            let result_kind: Option<String> = match expression.name.as_str() {
                "COUNT" => Some("integer".to_string()),
                "AVG" => {
                    let arg_kind = args.first().and_then(scalar_kind);
                    if let Some(kind) = &arg_kind
                        && !is_numeric_kind(Some(kind))
                    {
                        return Err(QueryError::semantic(
                            source,
                            "AVG requires a numeric value.",
                            expression.position,
                            "non-numeric-aggregate",
                        ));
                    }
                    Some("number".to_string())
                }
                "SUM" => {
                    let arg_kind = args.first().and_then(scalar_kind);
                    if let Some(kind) = &arg_kind
                        && !is_numeric_kind(Some(kind))
                    {
                        return Err(QueryError::semantic(
                            source,
                            "SUM requires a numeric value.",
                            expression.position,
                            "non-numeric-aggregate",
                        ));
                    }
                    Some(match arg_kind.as_deref() {
                        Some("number") => "number".to_string(),
                        Some(kind) => kind.to_string(),
                        None => "number".to_string(),
                    })
                }
                _ => args.first().and_then(scalar_kind),
            };
            Ok(Expr::Aggregate(AggregateFunction {
                name: expression.name.clone(),
                args,
                count_star: expression.count_star,
                filter_predicate,
                position: expression.position,
                kind: result_kind,
            }))
        }
        Expr::Function(expression) => {
            let preserve_structured =
                allow_structured && matches!(expression.name.as_str(), "COALESCE" | "NULLIF");
            let mut args: Vec<Expr> = Vec::new();
            for argument in &expression.args {
                args.push(resolve_scalar_expression(
                    argument,
                    schema,
                    source,
                    dates,
                    aliases,
                    select_context,
                    preserve_structured,
                    collection_scopes,
                )?);
            }
            let arg_refs: Vec<&Expr> = args.iter().collect();
            let result_kind: Option<String> = match expression.name.as_str() {
                "LOWER" | "UPPER" => {
                    let kind = args.first().and_then(scalar_kind);
                    if !matches!(
                        kind.as_deref(),
                        None | Some("string") | Some("mixed") | Some("unknown")
                    ) {
                        return Err(QueryError::semantic(
                            source,
                            format!("{} requires a text field.", expression.name),
                            expression.position,
                            "invalid-text-function-argument",
                        ));
                    }
                    Some("string".to_string())
                }
                "LENGTH" => {
                    let kind = args.first().and_then(scalar_kind);
                    if !matches!(
                        kind.as_deref(),
                        None | Some("string") | Some("mixed") | Some("unknown")
                    ) {
                        return Err(QueryError::semantic(
                            source,
                            "LENGTH requires a text value.",
                            expression.position,
                            "invalid-text-function-argument",
                        ));
                    }
                    Some("integer".to_string())
                }
                "CARDINALITY" => {
                    let collection_type = args
                        .first()
                        .and_then(|argument| scalar_query_type(argument, schema));
                    let is_collection = collection_type
                        .as_ref()
                        .is_some_and(|candidate| candidate.is_collection());
                    if collection_type.is_none() || !is_collection {
                        let kind = args
                            .first()
                            .and_then(scalar_kind)
                            .unwrap_or_else(|| "unknown".to_string());
                        return Err(QueryError::semantic(
                            source,
                            format!("CARDINALITY requires a collection value; got {kind}."),
                            expression.position,
                            "invalid-collection-operand",
                        ));
                    }
                    Some("integer".to_string())
                }
                "CONCAT" => {
                    for argument in &args {
                        let kind = scalar_kind(argument);
                        if !matches!(
                            kind.as_deref(),
                            None | Some("string") | Some("mixed") | Some("unknown")
                        ) {
                            return Err(QueryError::semantic(
                                source,
                                "CONCAT requires text values.",
                                expression.position,
                                "invalid-concat-argument",
                            ));
                        }
                    }
                    Some("string".to_string())
                }
                "CHAR" => {
                    for argument in &args {
                        let kind = scalar_kind(argument);
                        if let Some(kind) = &kind
                            && !is_numeric_kind(Some(kind))
                        {
                            return Err(QueryError::semantic(
                                source,
                                "CHAR requires integer code-point values.",
                                expression.position,
                                "invalid-char-codepoint",
                            ));
                        }
                        if is_constant_scalar_expression(argument) {
                            let value = evaluate_constant(argument);
                            if !matches!(value, Value::Null) {
                                validate_char_codepoint(&value, source, expression.position)?;
                            }
                        }
                    }
                    Some("string".to_string())
                }
                "NULLIF" => {
                    let mut kind =
                        common_scalar_kind(&arg_refs, source, expression.position, "NULLIF")?;
                    let first_kind = args.first().and_then(scalar_kind);
                    if first_kind.is_some() {
                        kind = first_kind;
                    }
                    kind
                }
                "GREATEST" | "LEAST" => {
                    common_scalar_kind(&arg_refs, source, expression.position, &expression.name)?
                }
                "COALESCE" => {
                    common_scalar_kind(&arg_refs, source, expression.position, "COALESCE")?
                }
                "POSITION" => Some("integer".to_string()),
                "RANDOM" => {
                    if let Some(seed) = args.first() {
                        let valid = match seed {
                            Expr::Literal(literal) => literal_integer_value(literal).is_some(),
                            _ => false,
                        };
                        if !valid {
                            return Err(semantic_error(
                                source,
                                "RANDOM seed must be a constant integer literal.",
                                expression.position,
                            ));
                        }
                    }
                    Some("number".to_string())
                }
                _ => {
                    let non_null_kinds: Vec<String> = args.iter().filter_map(scalar_kind).collect();
                    if !non_null_kinds.is_empty()
                        && non_null_kinds.iter().all(|kind| *kind == non_null_kinds[0])
                    {
                        Some(non_null_kinds[0].clone())
                    } else {
                        Some("mixed".to_string())
                    }
                }
            };
            let mut result_type: Option<QueryType> = None;
            if matches!(expression.name.as_str(), "COALESCE" | "NULLIF") {
                result_type = value_preserving_function_type(&args, schema);
            } else if expression.name == "CARDINALITY"
                && let Some(collection_type) = args
                    .first()
                    .and_then(|argument| scalar_query_type(argument, schema))
                && collection_type.is_collection()
            {
                result_type = Some(QueryType::scalar("integer", collection_type.nullable));
            }
            if result_type.is_none()
                && let Some(kind) = &result_kind
                && kind != "collection"
            {
                result_type = Some(QueryType::scalar(kind, true));
            }
            Ok(Expr::Function(ScalarFunction {
                name: expression.name.clone(),
                args,
                position: expression.position,
                kind: result_kind,
                resolved_type: result_type,
            }))
        }
    }
}

// ---------------------------------------------------------------------------
// Field set helpers
// ---------------------------------------------------------------------------

/// `_fields_outside_aggregates`: field names evaluated once per group rather
/// than inside an aggregate.
pub fn fields_outside_aggregates(expression: &Expr) -> Vec<String> {
    let mut fields = Vec::new();
    collect_fields_outside_aggregates(expression, &mut fields);
    fields
}

fn push_unique(fields: &mut Vec<String>, name: String) {
    if !fields.contains(&name) {
        fields.push(name);
    }
}

fn merge_fields(target: &mut Vec<String>, source: Vec<String>) {
    for name in source {
        push_unique(target, name);
    }
}

fn collect_fields_outside_aggregates(expression: &Expr, fields: &mut Vec<String>) {
    match expression {
        Expr::Literal(_) | Expr::Aggregate(_) => {}
        Expr::Field(field) => push_unique(fields, field.name.clone()),
        Expr::RelationField(_) | Expr::CollectionElement(_) => {}
        Expr::Unary(unary) => collect_fields_outside_aggregates(&unary.operand, fields),
        Expr::Binary(binary) => {
            collect_fields_outside_aggregates(&binary.left, fields);
            collect_fields_outside_aggregates(&binary.right, fields);
        }
        Expr::Index(index) => {
            collect_fields_outside_aggregates(&index.collection, fields);
            collect_fields_outside_aggregates(&index.index, fields);
        }
        Expr::Member(member) => collect_fields_outside_aggregates(&member.value, fields),
        Expr::CollectionCount(count) => {
            collect_fields_outside_aggregates(&count.collection, fields);
            merge_fields(fields, fields_in_predicate(&count.predicate));
        }
        Expr::CollectionFilter(filter) => {
            collect_fields_outside_aggregates(&filter.collection, fields);
            merge_fields(fields, fields_in_predicate(&filter.predicate));
        }
        Expr::CollectionProjection(projection) => {
            collect_fields_outside_aggregates(&projection.collection, fields);
            collect_fields_outside_aggregates(&projection.projection, fields);
        }
        Expr::Function(function) => {
            for argument in &function.args {
                collect_fields_outside_aggregates(argument, fields);
            }
        }
        Expr::Case(scalar_case) => {
            for branch in &scalar_case.whens {
                merge_fields(fields, fields_in_predicate(&branch.condition));
                collect_fields_outside_aggregates(&branch.result, fields);
            }
            if let Some(else_result) = &scalar_case.else_result {
                collect_fields_outside_aggregates(else_result, fields);
            }
        }
    }
}

/// `_fields_in_predicate`: field names referenced by one Boolean node.
pub fn fields_in_predicate(node: &BoolExpr) -> Vec<String> {
    let mut fields = Vec::new();
    collect_fields_in_predicate(node, &mut fields);
    fields
}

fn collect_fields_in_predicate(node: &BoolExpr, fields: &mut Vec<String>) {
    match node {
        BoolExpr::Literal(_) => {}
        BoolExpr::Unary(unary) => collect_fields_in_predicate(&unary.operand, fields),
        BoolExpr::Binary(binary) if binary.operator == "AND" || binary.operator == "OR" => {
            collect_fields_in_predicate(&binary.left, fields);
            collect_fields_in_predicate(&binary.right, fields);
        }
        BoolExpr::Binary(_) => {}
        BoolExpr::Between(between) => push_unique(fields, between.field.name.clone()),
        BoolExpr::InList(in_list) => push_unique(fields, in_list.field.name.clone()),
        BoolExpr::IsNull(is_null) => push_unique(fields, is_null.field.name.clone()),
        BoolExpr::TextPredicate(text) => push_unique(fields, text.field.name.clone()),
        BoolExpr::TruthTest(truth) => collect_fields_in_predicate(&truth.operand, fields),
        BoolExpr::CollectionPredicate(predicate) => {
            collect_fields_outside_aggregates(&predicate.collection, fields);
            merge_fields(fields, fields_in_predicate(&predicate.predicate));
        }
        BoolExpr::ScalarIsNull(is_null) => {
            merge_fields(fields, fields_outside_aggregates(&is_null.expression));
        }
        BoolExpr::ScalarComparison(comparison) => {
            merge_fields(fields, fields_outside_aggregates(&comparison.left));
            merge_fields(fields, fields_outside_aggregates(&comparison.right));
        }
    }
}

// ---------------------------------------------------------------------------
// Predicate resolution
// ---------------------------------------------------------------------------

/// Resolve one Boolean predicate tree against the established query schema
/// (`_resolve_predicate`).
pub fn resolve_predicate(
    node: &BoolExpr,
    schema: &QuerySchema,
    source: &str,
    dates: &DateContext,
    collection_scopes: &[QueryType],
) -> Result<BoolExpr, QueryError> {
    match node {
        BoolExpr::Literal(_) => Ok(node.clone()),
        BoolExpr::TruthTest(truth) => Ok(BoolExpr::TruthTest(TruthTest {
            operand: Box::new(resolve_predicate(
                &truth.operand,
                schema,
                source,
                dates,
                collection_scopes,
            )?),
            truth: truth.truth.clone(),
            negated: truth.negated,
        })),
        BoolExpr::Unary(unary) => Ok(BoolExpr::Unary(Unary {
            operator: unary.operator.clone(),
            operand: Box::new(resolve_predicate(
                &unary.operand,
                schema,
                source,
                dates,
                collection_scopes,
            )?),
        })),
        BoolExpr::Binary(binary) if binary.operator == "AND" || binary.operator == "OR" => {
            Ok(BoolExpr::Binary(crate::model::Binary {
                operator: binary.operator.clone(),
                left: Box::new(resolve_predicate(
                    &binary.left,
                    schema,
                    source,
                    dates,
                    collection_scopes,
                )?),
                right: Box::new(resolve_predicate(
                    &binary.right,
                    schema,
                    source,
                    dates,
                    collection_scopes,
                )?),
            }))
        }
        BoolExpr::CollectionPredicate(predicate) => {
            let collection = resolve_scalar_expression(
                &predicate.collection,
                schema,
                source,
                dates,
                None,
                false,
                true,
                collection_scopes,
            )?;
            let collection_type = scalar_query_type(&collection, schema);
            let is_collection = collection_type
                .as_ref()
                .is_some_and(|candidate| candidate.is_collection());
            if collection_type.is_none() || !is_collection {
                let kind = scalar_kind(&collection).unwrap_or_else(|| "unknown".to_string());
                return Err(semantic_error(
                    source,
                    format!(
                        "{} requires a collection value; got {kind}.",
                        predicate.quantifier
                    ),
                    predicate.position,
                ));
            }
            let mut scopes = collection_scopes.to_vec();
            scopes.push(
                collection_element_type(
                    collection_type.as_ref().expect("checked above"),
                    source,
                    predicate.position,
                )?
                .clone(),
            );
            let resolved = resolve_predicate(&predicate.predicate, schema, source, dates, &scopes)?;
            Ok(BoolExpr::CollectionPredicate(CollectionPredicate {
                quantifier: predicate.quantifier.clone(),
                collection: Box::new(collection),
                binding: predicate.binding.clone(),
                predicate: Box::new(resolved),
                position: predicate.position,
            }))
        }
        BoolExpr::ScalarComparison(comparison) => {
            // The Rust model represents Python's row-level
            // Binary(operator, Field, Literal) predicate nodes as
            // ScalarComparison nodes with a field operand. Those follow the
            // field-comparison path (literal parsing per field kind, no
            // cross-type compatibility diagnostic); everything else follows
            // the scalar-comparison path.
            if let (field_expr, Expr::Literal(literal)) = (&*comparison.left, &*comparison.right)
                && !matches!(
                    comparison.operator.as_str(),
                    "IS DISTINCT FROM" | "IS NOT DISTINCT FROM"
                )
                && matches!(field_expr, Expr::Field(_) | Expr::RelationField(_))
            {
                return resolve_field_comparison(
                    comparison, field_expr, literal, schema, source, dates,
                );
            }
            let left = resolve_scalar_expression(
                &comparison.left,
                schema,
                source,
                dates,
                None,
                false,
                false,
                collection_scopes,
            )?;
            let right = resolve_scalar_expression(
                &comparison.right,
                schema,
                source,
                dates,
                None,
                false,
                false,
                collection_scopes,
            )?;
            let left_kind = scalar_kind(&left);
            let right_kind = scalar_kind(&right);
            if let (Some(left_kind), Some(right_kind)) = (&left_kind, &right_kind)
                && left_kind != right_kind
                && !(is_numeric_kind(Some(left_kind)) && is_numeric_kind(Some(right_kind)))
                && left_kind != "mixed"
                && right_kind != "mixed"
            {
                return Err(semantic_error(
                    source,
                    "WHERE comparison expressions must have compatible types.",
                    diagnostic_position(&AstNode::Bool(node), 0),
                ));
            }
            Ok(BoolExpr::ScalarComparison(ScalarComparison {
                operator: comparison.operator.clone(),
                left: Box::new(left),
                right: Box::new(right),
            }))
        }
        BoolExpr::ScalarIsNull(is_null) => Ok(BoolExpr::ScalarIsNull(ScalarIsNull {
            expression: Box::new(resolve_scalar_expression(
                &is_null.expression,
                schema,
                source,
                dates,
                None,
                false,
                false,
                collection_scopes,
            )?),
            negated: is_null.negated,
        })),
        BoolExpr::Between(between) => {
            let field = resolve_field(&between.field, schema, source)?;
            if field.kind.as_deref() == Some("structured") {
                return Err(semantic_error(
                    source,
                    format!(
                        "Field {} is structured; use a scalar nested path instead.",
                        python_repr(&field.name)
                    ),
                    field.position,
                ));
            }
            let lower = resolve_literal(
                &between.lower,
                field.kind.as_deref(),
                &field.name,
                field.position,
                source,
                dates,
            )?;
            let upper = resolve_literal(
                &between.upper,
                field.kind.as_deref(),
                &field.name,
                field.position,
                source,
                dates,
            )?;
            Ok(BoolExpr::Between(Between {
                field,
                lower,
                upper,
                negated: between.negated,
            }))
        }
        BoolExpr::InList(in_list) => {
            let field = resolve_field(&in_list.field, schema, source)?;
            if field.kind.as_deref() == Some("structured") {
                return Err(semantic_error(
                    source,
                    format!(
                        "Field {} is structured; use a scalar nested path instead.",
                        python_repr(&field.name)
                    ),
                    field.position,
                ));
            }
            let mut values = Vec::new();
            for item in &in_list.values {
                values.push(resolve_literal(
                    item,
                    field.kind.as_deref(),
                    &field.name,
                    field.position,
                    source,
                    dates,
                )?);
            }
            Ok(BoolExpr::InList(InList {
                field,
                values,
                negated: in_list.negated,
            }))
        }
        BoolExpr::IsNull(is_null) => Ok(BoolExpr::IsNull(IsNull {
            field: resolve_field(&is_null.field, schema, source)?,
            negated: is_null.negated,
        })),
        // Python raises AssertionError for a non-AND/OR Binary predicate here;
        // keep the node unchanged instead of panicking on runtime data.
        BoolExpr::Binary(_) => Ok(node.clone()),
        BoolExpr::TextPredicate(text) => {
            let field = resolve_field(&text.field, schema, source)?;
            if field.kind.as_deref() == Some("structured") {
                return Err(semantic_error(
                    source,
                    format!(
                        "Field {} is structured; use a scalar nested path instead.",
                        python_repr(&field.name)
                    ),
                    field.position,
                ));
            }
            let kind_text = field.kind.clone().unwrap_or_else(|| "None".to_string());
            if !matches!(
                field.kind.as_deref(),
                Some("string") | Some("mixed") | Some("unknown")
            ) {
                return Err(QueryError::semantic(
                    source,
                    format!("{} requires a text field, not {kind_text}.", text.operator),
                    field.position,
                    "invalid-text-predicate-field",
                ));
            }
            if text.operator == "LIKE" || text.operator == "ILIKE" {
                let pattern = literal_text(&text.value);
                validate_like_pattern(&pattern, source, text.value.position)?;
                // Python warms the LIKE pattern cache here so row evaluation
                // does not pay compilation later; Rust compiles lazily, so
                // this is a no-op.
            }
            Ok(BoolExpr::TextPredicate(TextPredicate {
                operator: text.operator.clone(),
                field,
                value: text.value.clone(),
                negated: text.negated,
            }))
        }
    }
}

/// Resolve a row-level field comparison, i.e. Python's
/// `Binary(operator, field, literal)` predicate node.
fn resolve_field_comparison(
    comparison: &ScalarComparison,
    field_expression: &Expr,
    literal: &Literal,
    schema: &QuerySchema,
    source: &str,
    dates: &DateContext,
) -> Result<BoolExpr, QueryError> {
    // Python resolves the field through `_resolve_field(node.left, ...)`; a
    // RelationField passes through unchanged (its ownership and kind were
    // already established by JOIN scope resolution).
    let (resolved_left, field_name, field_kind, field_position) = match field_expression {
        Expr::Field(field) => {
            let resolved = resolve_field(field, schema, source)?;
            let name = resolved.name.clone();
            let kind = resolved.kind.clone();
            let position = resolved.position;
            (Expr::Field(resolved), name, kind, position)
        }
        Expr::RelationField(field) => (
            field_expression.clone(),
            field.name.clone(),
            field.kind.clone(),
            field.position,
        ),
        // The caller only dispatches field operands here.
        _ => return Ok(BoolExpr::ScalarComparison(comparison.clone())),
    };
    if field_kind.as_deref() == Some("structured") {
        return Err(semantic_error(
            source,
            format!(
                "Field {} is structured; use a scalar nested path instead.",
                python_repr(&field_name)
            ),
            field_position,
        ));
    }
    let resolved_literal = resolve_literal(
        literal,
        field_kind.as_deref(),
        &field_name,
        field_position,
        source,
        dates,
    )?;
    if matches!(resolved_literal.value, LiteralValue::Null) {
        return Err(semantic_error(
            source,
            "Use IS NULL or IS NOT NULL for NULL tests.",
            resolved_literal.position,
        ));
    }
    Ok(BoolExpr::ScalarComparison(ScalarComparison {
        operator: comparison.operator.clone(),
        left: Box::new(resolved_left),
        right: Box::new(Expr::Literal(resolved_literal)),
    }))
}

/// Resolve one HAVING node against the established query schema and the SELECT
/// alias table (`_resolve_having`).
pub fn resolve_having(
    node: &BoolExpr,
    schema: &QuerySchema,
    source: &str,
    dates: &DateContext,
    aliases: &AliasTable,
) -> Result<BoolExpr, QueryError> {
    match node {
        BoolExpr::TruthTest(truth) => Ok(BoolExpr::TruthTest(TruthTest {
            operand: Box::new(resolve_having(
                &truth.operand,
                schema,
                source,
                dates,
                aliases,
            )?),
            truth: truth.truth.clone(),
            negated: truth.negated,
        })),
        BoolExpr::Unary(unary) => Ok(BoolExpr::Unary(Unary {
            operator: unary.operator.clone(),
            operand: Box::new(resolve_having(
                &unary.operand,
                schema,
                source,
                dates,
                aliases,
            )?),
        })),
        BoolExpr::Binary(binary) if binary.operator == "AND" || binary.operator == "OR" => {
            Ok(BoolExpr::Binary(crate::model::Binary {
                operator: binary.operator.clone(),
                left: Box::new(resolve_having(
                    &binary.left,
                    schema,
                    source,
                    dates,
                    aliases,
                )?),
                right: Box::new(resolve_having(
                    &binary.right,
                    schema,
                    source,
                    dates,
                    aliases,
                )?),
            }))
        }
        BoolExpr::ScalarComparison(comparison) => {
            let left = resolve_scalar_expression(
                &comparison.left,
                schema,
                source,
                dates,
                Some(aliases),
                false,
                false,
                &[],
            )?;
            let right = resolve_scalar_expression(
                &comparison.right,
                schema,
                source,
                dates,
                Some(aliases),
                false,
                false,
                &[],
            )?;
            let left_kind = scalar_kind(&left);
            let right_kind = scalar_kind(&right);
            if let (Some(left_kind), Some(right_kind)) = (&left_kind, &right_kind)
                && left_kind != right_kind
                && !(is_numeric_kind(Some(left_kind)) && is_numeric_kind(Some(right_kind)))
                && left_kind != "mixed"
                && right_kind != "mixed"
            {
                return Err(semantic_error(
                    source,
                    "HAVING comparison expressions must have compatible types.",
                    diagnostic_position(&AstNode::Bool(node), 0),
                ));
            }
            Ok(BoolExpr::ScalarComparison(ScalarComparison {
                operator: comparison.operator.clone(),
                left: Box::new(left),
                right: Box::new(right),
            }))
        }
        BoolExpr::ScalarIsNull(is_null) => Ok(BoolExpr::ScalarIsNull(ScalarIsNull {
            expression: Box::new(resolve_scalar_expression(
                &is_null.expression,
                schema,
                source,
                dates,
                Some(aliases),
                false,
                false,
                &[],
            )?),
            negated: is_null.negated,
        })),
        other => Ok(other.clone()),
    }
}

// ---------------------------------------------------------------------------
// Aggregate-grammar validation
// ---------------------------------------------------------------------------

/// `_validate_group_compatibility`: reject ambiguous row-level expressions in
/// aggregate projection contexts.
fn validate_group_compatibility(
    expression: Option<&Expr>,
    group_by: &[&Expr],
    source: &str,
    position: usize,
) -> Result<(), QueryError> {
    let Some(expression) = expression else {
        return Ok(());
    };
    if fields_outside_aggregates(expression).is_empty() {
        return Ok(());
    }
    let canonical_groups: Vec<String> = group_by
        .iter()
        .map(|item| format_scalar_expression(item))
        .collect();
    if !contains_aggregate(expression)
        && canonical_groups.contains(&format_scalar_expression(expression))
    {
        return Ok(());
    }
    Err(QueryError::semantic(
        source,
        "Non-aggregate SELECT/ORDER BY expressions in an aggregate query must match a GROUP BY expression.",
        position,
        "aggregate-must-match-group-by",
    ))
}

/// `_validate_having_group_compatibility`.
fn validate_having_group_compatibility(
    node: Option<&BoolExpr>,
    group_by: &[&Expr],
    source: &str,
) -> Result<(), QueryError> {
    let Some(node) = node else {
        return Ok(());
    };
    match node {
        BoolExpr::Unary(unary) => {
            validate_having_group_compatibility(Some(&unary.operand), group_by, source)
        }
        BoolExpr::Binary(binary) if binary.operator == "AND" || binary.operator == "OR" => {
            validate_having_group_compatibility(Some(&binary.left), group_by, source)?;
            validate_having_group_compatibility(Some(&binary.right), group_by, source)
        }
        BoolExpr::ScalarComparison(comparison) => {
            validate_having_expressions(&[&comparison.left, &comparison.right], group_by, source)
        }
        BoolExpr::ScalarIsNull(is_null) => {
            validate_having_expressions(&[&is_null.expression], group_by, source)
        }
        _ => Ok(()),
    }
}

fn validate_having_expressions(
    expressions: &[&Expr],
    group_by: &[&Expr],
    source: &str,
) -> Result<(), QueryError> {
    let canonical_groups: Vec<String> = group_by
        .iter()
        .map(|item| format_scalar_expression(item))
        .collect();
    for expression in expressions {
        if fields_outside_aggregates(expression).is_empty() {
            continue;
        }
        if !contains_aggregate(expression)
            && canonical_groups.contains(&format_scalar_expression(expression))
        {
            continue;
        }
        return Err(QueryError::semantic(
            source,
            "Non-aggregate HAVING expressions must match a GROUP BY expression or selected aggregate alias.",
            expr_position(expression),
            "having-must-match-group-by",
        ));
    }
    Ok(())
}

/// `_validate_random_placement`: keep volatile randomness out of row-selection
/// and grouping semantics.
fn validate_random_placement(query: &Query) -> Result<(), QueryError> {
    if contains_random_predicate(query.predicate.as_deref()) {
        return Err(QueryError::semantic(
            &query.source,
            "RANDOM is not allowed in WHERE predicates.",
            query
                .predicate
                .as_deref()
                .map(|predicate| random_position(&AstNode::Bool(predicate), 0))
                .unwrap_or(0),
            "invalid-random-placement",
        ));
    }
    let offending: Vec<&Expr> = query
        .group_by
        .iter()
        .filter(|expression| contains_random(expression))
        .collect();
    if !offending.is_empty() {
        let position = offending
            .iter()
            .map(|expression| random_position(&AstNode::Expr(expression), 0))
            .min()
            .unwrap_or(0);
        return Err(QueryError::semantic(
            &query.source,
            "RANDOM is not allowed in GROUP BY expressions.",
            position,
            "invalid-random-placement",
        ));
    }
    if contains_random_predicate(query.having.as_deref()) {
        return Err(QueryError::semantic(
            &query.source,
            "RANDOM is not allowed in HAVING predicates.",
            query
                .having
                .as_deref()
                .map(|having| random_position(&AstNode::Bool(having), 0))
                .unwrap_or(0),
            "invalid-random-placement",
        ));
    }
    for term in &query.select {
        if let Some(Expr::Aggregate(aggregate)) = term.expression.as_deref()
            && let Some(filter_predicate) = &aggregate.filter_predicate
            && contains_random_predicate(Some(filter_predicate))
        {
            return Err(QueryError::semantic(
                &query.source,
                "RANDOM is not allowed in aggregate FILTER predicates.",
                aggregate.position,
                "invalid-random-placement",
            ));
        }
    }
    Ok(())
}

/// RANDOM containment over a Boolean node. The evaluator exposes the scalar
/// helper (`contains_random`); predicates need the traversal-aware variant
/// because they are `BoolExpr` nodes.
fn contains_random_predicate(node: Option<&BoolExpr>) -> bool {
    let Some(node) = node else {
        return false;
    };
    walk_bool_expr(node).into_iter().any(|visited| {
        matches!(
            visited,
            AstNode::Expr(Expr::Function(function)) if function.name == "RANDOM"
        )
    })
}

/// `_validate_position_placement`: keep final-result positions out of
/// expressions evaluated before final ordering.
fn validate_position_placement(query: &Query) -> Result<(), QueryError> {
    // Rust reproduces Python's `id(...)` identity through pointer equality on
    // the shared expression references.
    let mut allowed: Vec<&Expr> = Vec::new();
    let mut position_terms: Vec<&SelectTerm> = Vec::new();
    for term in &query.select {
        if let Some(expression) = term.expression.as_deref()
            && let Expr::Function(function) = expression
            && function.name == "POSITION"
        {
            allowed.push(expression);
            position_terms.push(term);
        }
    }
    if !position_terms.is_empty()
        && (!query.set_operations.is_empty() || query.left_query.is_some())
    {
        return Err(QueryError::semantic(
            &query.source,
            "POSITION() in set-operation projections is not yet supported.",
            position_terms[0]
                .expression
                .as_ref()
                .map(|expression| expr_position(expression))
                .unwrap_or(0),
            "unsupported-position-set-operation",
        ));
    }
    let position_aliases: Vec<String> = position_terms
        .iter()
        .map(|term| term.output_name().to_lowercase())
        .collect();
    for order in &query.order_by {
        if position_aliases.contains(&order.field.to_lowercase()) {
            return Err(QueryError::semantic(
                &query.source,
                "ORDER BY cannot depend on a POSITION() projection.",
                order.position,
                "invalid-position-placement",
            ));
        }
    }
    let root: AstNode<'_> = AstNode::Query(query);
    for node in walk_ast(root, &|visited: &AstNode<'_>| match visited {
        AstNode::Query(candidate) => std::ptr::eq(*candidate, query),
        _ => true,
    }) {
        if let AstNode::Expr(expression) = node
            && let Expr::Function(function) = expression
        {
            if function.name != "POSITION" {
                continue;
            }
            if !allowed
                .iter()
                .any(|allowed_expression| std::ptr::eq(*allowed_expression, expression))
            {
                return Err(QueryError::semantic(
                    &query.source,
                    "POSITION() is allowed only as a standalone final SELECT projection.",
                    function.position,
                    "invalid-position-placement",
                ));
            }
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Query body resolution
// ---------------------------------------------------------------------------

/// Resolve fields and typed literals after metadata has established a schema
/// (`_resolve_query_body`).
pub fn resolve_query_body(
    query: &Query,
    schema: &QuerySchema,
    dates: &DateContext,
) -> Result<Query, QueryError> {
    let source = query.source.as_str();
    validate_random_placement(query)?;
    validate_position_placement(query)?;

    let predicate = match &query.predicate {
        Some(predicate) => Some(Box::new(resolve_predicate(
            predicate,
            schema,
            source,
            dates,
            &[],
        )?)),
        None => None,
    };
    let mut group_by: Vec<Expr> = Vec::new();
    for item in &query.group_by {
        let resolved =
            resolve_scalar_expression(item, schema, source, dates, None, false, false, &[])?;
        if contains_aggregate(&resolved) {
            return Err(QueryError::semantic(
                source,
                "GROUP BY expressions cannot contain aggregate functions.",
                expr_position(&resolved),
                "group-by-aggregate",
            ));
        }
        group_by.push(resolved);
    }

    let mut select_terms: Vec<SelectTerm> = Vec::new();
    let mut effective_select: Vec<SelectTerm> = if query.select.is_empty() {
        vec![SelectTerm {
            field: "id".to_string(),
            alias: None,
            position: 0,
            kind: None,
            expression: None,
        }]
    } else {
        query.select.clone()
    };
    if effective_select.len() == 1
        && effective_select[0].field == "*"
        && effective_select[0].expression.is_none()
        && (!group_by.is_empty() || query.having.is_some())
    {
        return Err(QueryError::semantic(
            source,
            "SELECT * is not supported in aggregate queries; select grouped and aggregate expressions explicitly.",
            effective_select[0].position,
            "select-star-in-aggregate",
        ));
    }
    if effective_select.len() == 1
        && effective_select[0].field == "*"
        && effective_select[0].expression.is_none()
    {
        let star_position = effective_select[0].position;
        effective_select = schema
            .select_star_fields()
            .into_iter()
            .map(|info| SelectTerm {
                field: info.name.clone(),
                alias: None,
                position: star_position,
                kind: None,
                expression: None,
            })
            .collect();
    }
    let mut output_names: Vec<String> = Vec::new();
    let mut explicit_aliases: AliasTable = HashMap::new();
    for original_term in &effective_select {
        let (expression, field_text, kind): (Option<Box<Expr>>, String, Option<String>) =
            if let Some(original_expression) = &original_term.expression {
                let resolved = resolve_scalar_expression(
                    original_expression,
                    schema,
                    source,
                    dates,
                    None,
                    true,
                    false,
                    &[],
                )?;
                let mut field_text = format_scalar_expression(&resolved);
                let kind = scalar_kind(&resolved);
                if kind.as_deref() == Some("structured") {
                    return Err(semantic_error(
                        source,
                        "Cannot SELECT structured expression; select a scalar nested path instead.",
                        original_term.position,
                    ));
                }
                if matches!(resolved, Expr::Field(_)) {
                    field_text = format_scalar_expression(&resolved);
                }
                (Some(Box::new(resolved)), field_text, kind)
            } else {
                let resolved_field = resolve_field(
                    &Field {
                        name: original_term.field.clone(),
                        position: original_term.position,
                        kind: None,
                    },
                    schema,
                    source,
                )?;
                if resolved_field.kind.as_deref() == Some("structured") {
                    return Err(semantic_error(
                        source,
                        format!(
                            "Cannot SELECT structured field {}; select a scalar nested path instead.",
                            python_repr(&resolved_field.name)
                        ),
                        original_term.position,
                    ));
                }
                let kind = resolved_field.kind.clone();
                (None, resolved_field.name.clone(), kind)
            };
        let output_name = if let Some(alias) = &original_term.alias {
            alias.clone()
        } else if let Some(Expr::Field(field)) = original_term.expression.as_deref() {
            field.name.clone()
        } else {
            original_term.field.clone()
        };
        if output_names.contains(&output_name) {
            return Err(semantic_error(
                source,
                format!(
                    "Duplicate SELECT output name {}; use AS to give fields unique names.",
                    python_repr(&output_name)
                ),
                original_term.position,
            ));
        }
        output_names.push(output_name.clone());
        let resolved_term = SelectTerm {
            field: field_text,
            alias: Some(output_name),
            position: original_term.position,
            kind,
            expression,
        };
        if let Some(alias) = &original_term.alias {
            explicit_aliases.insert(alias.clone(), resolved_term.clone());
        }
        select_terms.push(resolved_term);
    }

    let having = match &query.having {
        Some(having) => Some(Box::new(resolve_having(
            having,
            schema,
            source,
            dates,
            &explicit_aliases,
        )?)),
        None => None,
    };

    let mut order_terms: Vec<OrderTerm> = Vec::new();
    for term in &query.order_by {
        if let Some(Expr::Literal(literal)) = term.expression.as_deref()
            && literal_integer_value(literal).is_some()
        {
            return Err(semantic_error(
                source,
                "ORDER BY ordinals are not supported; order by a field, alias or scalar expression instead.",
                term.position,
            ));
        }
        if let Some(term_expression) = &term.expression {
            let resolved = resolve_scalar_expression(
                term_expression,
                schema,
                source,
                dates,
                Some(&explicit_aliases),
                false,
                false,
                &[],
            )?;
            let mut field_text = format_scalar_expression(&resolved);
            let kind = scalar_kind(&resolved);
            if matches!(resolved, Expr::Field(_)) {
                field_text = format_scalar_expression(&resolved);
            }
            order_terms.push(OrderTerm {
                field: field_text,
                descending: term.descending,
                position: term.position,
                kind,
                expression: Some(Box::new(resolved)),
            });
            continue;
        }
        if let Some(selected_alias) = explicit_aliases.get(&term.field) {
            order_terms.push(OrderTerm {
                field: selected_alias.field.clone(),
                descending: term.descending,
                position: term.position,
                kind: selected_alias.kind.clone(),
                expression: selected_alias.expression.clone(),
            });
            continue;
        }
        let field = resolve_field(
            &Field {
                name: term.field.clone(),
                position: term.position,
                kind: None,
            },
            schema,
            source,
        )?;
        if field.kind.as_deref() == Some("structured") {
            return Err(semantic_error(
                source,
                format!(
                    "Cannot ORDER BY structured field {}.",
                    python_repr(&field.name)
                ),
                term.position,
            ));
        }
        order_terms.push(OrderTerm {
            field: field.name.clone(),
            descending: term.descending,
            position: term.position,
            kind: field.kind.clone(),
            expression: None,
        });
    }

    let resolved = Query {
        predicate,
        order_by: order_terms,
        limit: query.limit,
        source: query.source.clone(),
        select: select_terms,
        from_source: query.from_source.clone(),
        distinct: query.distinct,
        offset: query.offset,
        group_by,
        having,
        ctes: Vec::new(),
        set_operations: Vec::new(),
        from_facet: query.from_facet.clone(),
        from_alias: None,
        joins: Vec::new(),
        left_query: None,
        from_relation: None,
        limit_literal: query.limit_literal.clone(),
        offset_literal: query.offset_literal.clone(),
    };
    if aggregate_query(&resolved) {
        let group_refs: Vec<&Expr> = resolved.group_by.iter().collect();
        for term in &resolved.select {
            validate_group_compatibility(
                term.expression.as_deref(),
                &group_refs,
                source,
                term.position,
            )?;
        }
        for term in &resolved.order_by {
            validate_group_compatibility(
                term.expression.as_deref(),
                &group_refs,
                source,
                term.position,
            )?;
        }
        validate_having_group_compatibility(resolved.having.as_deref(), &group_refs, source)?;
    } else if resolved.having.is_some() {
        let position = resolved
            .having
            .as_deref()
            .map(|having| diagnostic_position(&AstNode::Bool(having), 0))
            .unwrap_or(0);
        return Err(QueryError::semantic(
            source,
            "HAVING requires GROUP BY or an aggregate expression.",
            position,
            "having-requires-group-by",
        ));
    }
    Ok(resolved)
}

/// `_union_common_kind`: the logical kind exported by two positional UNION
/// columns. `Err` carries the Python ValueError message (the caller replaces it
/// with the query diagnostic).
fn union_common_kind(left: Option<&str>, right: Option<&str>) -> Result<String, String> {
    let left_kind = left.unwrap_or("unknown");
    let right_kind = right.unwrap_or("unknown");
    if left_kind == right_kind {
        return Ok(left_kind.to_string());
    }
    if left_kind == "unknown" {
        return Ok(right_kind.to_string());
    }
    if right_kind == "unknown" {
        return Ok(left_kind.to_string());
    }
    let numeric = ["integer", "number", "count", "duration"];
    if numeric.contains(&left_kind) && numeric.contains(&right_kind) {
        return Ok("number".to_string());
    }
    Err(format!(
        "incompatible UNION kinds {} and {}.",
        python_repr(left_kind),
        python_repr(right_kind)
    ))
}

/// `_query_result_schema`: the logical schema exported by a resolved query
/// result.
fn query_result_schema(query: &Query) -> QuerySchema {
    let fields: Vec<FieldInfo> = query
        .select
        .iter()
        .map(|term| FieldInfo {
            name: term.output_name().to_string(),
            kind: term.kind.clone().unwrap_or_else(|| "unknown".to_string()),
            nullable: true,
            alias_of: None,
            dynamic: true,
            resolved_type: None,
        })
        .collect();
    QuerySchema::from_field_infos(fields)
}

/// `_resolve_union_order`: resolve global UNION ordering against the reconciled
/// result relation.
fn resolve_union_order(
    order_by: &[OrderTerm],
    schema: &QuerySchema,
    source: &str,
    dates: &DateContext,
) -> Result<Vec<OrderTerm>, QueryError> {
    let mut terms: Vec<OrderTerm> = Vec::new();
    for term in order_by {
        if let Some(Expr::Literal(literal)) = term.expression.as_deref()
            && literal_integer_value(literal).is_some()
        {
            return Err(semantic_error(
                source,
                "ORDER BY ordinals are not supported; order by a field, alias or scalar expression instead.",
                term.position,
            ));
        }
        let Some(term_expression) = &term.expression else {
            // Python would fail here; retain the term unchanged instead of
            // panicking on runtime data.
            terms.push(term.clone());
            continue;
        };
        let resolved = resolve_scalar_expression(
            term_expression,
            schema,
            source,
            dates,
            None,
            false,
            false,
            &[],
        )?;
        let mut field_text = format_scalar_expression(&resolved);
        let kind = scalar_kind(&resolved);
        if let Expr::Field(field) = &resolved {
            field_text = field.name.clone();
        }
        terms.push(OrderTerm {
            field: field_text,
            descending: term.descending,
            position: term.position,
            kind,
            expression: Some(Box::new(resolved)),
        });
    }
    Ok(terms)
}

/// `_resolve_composed_query`: resolve one query body and its positional
/// set-composition branches.
pub fn resolve_composed_query(
    query: &Query,
    physical_schema: &QuerySchema,
    cte_schemas: &CteSchemas,
    context: &DateContext,
    source_schemas: &SourceSchemas,
) -> Result<Query, QueryError> {
    // Explicit UNION operands do not have a shared final-projection stage yet.
    // Reject deferred positions before splitting the query into independent
    // bodies. Multi-facet OF expansion is source sugar, not an explicit UNION.
    if query
        .set_operations
        .iter()
        .any(|operation| !operation.facet_expansion)
    {
        let mut operands: Vec<&Query> = Vec::new();
        if let Some(left_query) = &query.left_query {
            operands.push(left_query);
        } else {
            operands.push(query);
        }
        operands.extend(
            query
                .set_operations
                .iter()
                .map(|operation| operation.query.as_ref()),
        );
        for operand in operands {
            for term in &operand.select {
                if let Some(Expr::Function(function)) = term.expression.as_deref()
                    && function.name == "POSITION"
                {
                    return Err(QueryError::semantic(
                        &query.source,
                        "POSITION() in set-operation projections is not yet supported.",
                        function.position,
                        "unsupported-position-set-operation",
                    ));
                }
            }
        }
    }

    if query.set_operations.is_empty() && query.left_query.is_none() {
        let mut body = query.clone();
        body.ctes.clear();
        body.set_operations.clear();
        return resolve_body(&body, physical_schema, cte_schemas, context, source_schemas);
    }

    // A parenthesised left primary retains its own complete query semantics.
    let mut left = if let Some(left_query) = &query.left_query {
        resolve_composed_query(
            left_query,
            physical_schema,
            cte_schemas,
            context,
            source_schemas,
        )?
    } else {
        // Unparenthesised ORDER BY/LIMIT/OFFSET belong to the complete set
        // result, not the first branch.
        let mut left_body = query.clone();
        left_body.ctes.clear();
        left_body.set_operations.clear();
        left_body.order_by.clear();
        left_body.limit = None;
        left_body.offset = 0;
        left_body.limit_literal = None;
        left_body.offset_literal = None;
        resolve_body(
            &left_body,
            physical_schema,
            cte_schemas,
            context,
            source_schemas,
        )?
    };
    let mut common_terms: Vec<SelectTerm> = left.select.clone();
    let mut resolved_ops: Vec<SetOperation> = Vec::new();
    for operation in &query.set_operations {
        let branch = if operation.grouped
            || !operation.query.set_operations.is_empty()
            || operation.query.left_query.is_some()
        {
            resolve_composed_query(
                &operation.query,
                physical_schema,
                cte_schemas,
                context,
                source_schemas,
            )?
        } else {
            let mut branch_body = (*operation.query).clone();
            branch_body.ctes.clear();
            branch_body.set_operations.clear();
            branch_body.order_by.clear();
            branch_body.limit = None;
            branch_body.offset = 0;
            branch_body.limit_literal = None;
            branch_body.offset_literal = None;
            resolve_body(
                &branch_body,
                physical_schema,
                cte_schemas,
                context,
                source_schemas,
            )?
        };
        if branch.select.len() != common_terms.len() {
            return Err(semantic_error(
                &query.source,
                format!(
                    "UNION branches must project the same number of columns; expected {}, got {}.",
                    common_terms.len(),
                    branch.select.len()
                ),
                operation.position,
            ));
        }
        let mut reconciled: Vec<SelectTerm> = Vec::new();
        for (index, (left_term, right_term)) in
            common_terms.iter().zip(branch.select.iter()).enumerate()
        {
            let kind = union_common_kind(left_term.kind.as_deref(), right_term.kind.as_deref());
            let kind = match kind {
                Ok(kind) => kind,
                Err(_) => {
                    return Err(semantic_error(
                        &query.source,
                        format!(
                            "UNION column {} has incompatible kinds {} and {}.",
                            index + 1,
                            left_term.kind.as_deref().unwrap_or("unknown"),
                            right_term.kind.as_deref().unwrap_or("unknown")
                        ),
                        operation.position,
                    ));
                }
            };
            let mut term = left_term.clone();
            term.kind = Some(kind);
            reconciled.push(term);
        }
        common_terms = reconciled;
        resolved_ops.push(SetOperation {
            query: Box::new(branch),
            all: operation.all,
            position: operation.position,
            facet_expansion: operation.facet_expansion,
            grouped: operation.grouped,
        });
    }

    left.select = common_terms.clone();
    let pure_facet_expansion = !query.set_operations.is_empty()
        && query
            .set_operations
            .iter()
            .all(|operation| operation.facet_expansion);
    // Multi-facet OF is source-relation sugar, so retain the ordinary
    // source-field ORDER BY scope of the unexpanded query. Explicit UNION
    // continues to order against its reconciled projected result.
    let order_by = if pure_facet_expansion {
        resolve_union_order(&query.order_by, physical_schema, &query.source, context)?
    } else {
        resolve_union_order(
            &query.order_by,
            &query_result_schema(&left),
            &query.source,
            context,
        )?
    };

    if query.left_query.is_some() {
        let mut result = query.clone();
        result.ctes.clear();
        result.select = common_terms.clone();
        let mut inner_left = left.clone();
        inner_left.select = common_terms;
        result.left_query = Some(Box::new(inner_left));
        result.order_by = order_by;
        result.limit = query.limit;
        result.offset = query.offset;
        result.limit_literal = query.limit_literal.clone();
        result.offset_literal = query.offset_literal.clone();
        result.set_operations = resolved_ops;
        Ok(result)
    } else {
        let mut result = left;
        result.order_by = order_by;
        result.limit = query.limit;
        result.offset = query.offset;
        result.limit_literal = query.limit_literal.clone();
        result.offset_literal = query.offset_literal.clone();
        result.set_operations = resolved_ops;
        Ok(result)
    }
}

/// One body of a composed query, including derived relations and joins.
fn resolve_body(
    body: &Query,
    physical_schema: &QuerySchema,
    cte_schemas: &CteSchemas,
    context: &DateContext,
    source_schemas: &SourceSchemas,
) -> Result<Query, QueryError> {
    let mut resolved_relation = body.from_relation.clone();
    let schema: QuerySchema = if let Some(from_relation) = &body.from_relation {
        if let Some(derived) = &from_relation.derived {
            let derived_query = resolve_composed_query(
                &derived.query,
                physical_schema,
                cte_schemas,
                context,
                source_schemas,
            )?;
            if derived_query.select.is_empty() {
                return Err(semantic_error(
                    &body.source,
                    "Derived relation query must export a result schema.",
                    from_relation.position,
                ));
            }
            let mut resolved_derived = derived.clone();
            resolved_derived.query = Box::new(derived_query.clone());
            if let Some(resolved_relation_ref) = &mut resolved_relation {
                resolved_relation_ref.derived = Some(resolved_derived);
            }
            let mut schema = query_result_schema(&derived_query);
            if let Some(alias) = &from_relation.alias {
                let exported = schema.select_star_fields();
                let mut fields: Vec<FieldInfo> = exported.clone();
                for field in exported {
                    fields.push(FieldInfo {
                        name: format!("{alias}.{}", field.name),
                        kind: field.kind.clone(),
                        nullable: field.nullable,
                        alias_of: Some(field.name.clone()),
                        dynamic: field.dynamic,
                        resolved_type: field.resolved_type.clone(),
                    });
                }
                schema = QuerySchema::from_field_infos(fields);
            }
            schema
        } else {
            relation_binding(
                body.from_source.as_deref(),
                body.from_facet.as_deref(),
                physical_schema,
                cte_schemas,
                source_schemas,
            )
            .schema
        }
    } else {
        relation_binding(
            body.from_source.as_deref(),
            body.from_facet.as_deref(),
            physical_schema,
            cte_schemas,
            source_schemas,
        )
        .schema
    };

    if !body.joins.is_empty() {
        let mut resolved_joins: Vec<JoinClause> = Vec::new();
        for join in &body.joins {
            let mut relation = join.relation.clone();
            if let Some(derived) = &relation.derived {
                let nested = resolve_composed_query(
                    &derived.query,
                    physical_schema,
                    cte_schemas,
                    context,
                    source_schemas,
                )?;
                if nested.select.is_empty() {
                    return Err(semantic_error(
                        &body.source,
                        "Derived relation query must export a result schema.",
                        relation.position,
                    ));
                }
                let mut resolved_derived = derived.clone();
                resolved_derived.query = Box::new(nested);
                relation.derived = Some(resolved_derived);
            }
            let mut resolved_join = join.clone();
            resolved_join.relation = relation;
            resolved_joins.push(resolved_join);
        }
        let mut prepared_body = body.clone();
        prepared_body.joins = resolved_joins;
        let prepared =
            prepare_join_query(&prepared_body, physical_schema, cte_schemas, source_schemas)?;
        let mut join_free = prepared.clone();
        join_free.joins.clear();
        let mut resolved_body = resolve_query_body(&join_free, &schema, context)?;
        resolved_body.from_alias = prepared.from_alias.clone();
        resolved_body.joins = prepared.joins.clone();
        resolved_body.from_relation = resolved_relation.clone();
        return Ok(resolved_body);
    }

    let mut resolved_body = resolve_query_body(body, &schema, context)?;
    resolved_body.from_alias = body.from_alias.clone();
    resolved_body.from_relation = resolved_relation;
    Ok(resolved_body)
}

/// Resolve CTEs and positional set composition against logical and per-source
/// schemas (`resolve_query`).
pub fn resolve_query(
    query: &Query,
    schema: &QuerySchema,
    dates: &DateContext,
    source_schemas: &SourceSchemas,
) -> Result<Query, QueryError> {
    let context = dates;

    // Preserve the historical direct resolver path for the overwhelmingly
    // common uncomposed query shape. Relational preparation is semantically
    // unnecessary when there is no source relation, CTE, JOIN or set
    // composition.
    if query.ctes.is_empty()
        && query.joins.is_empty()
        && query.set_operations.is_empty()
        && query.left_query.is_none()
        && query.from_source.is_none()
        && query.from_relation.is_none()
    {
        return resolve_query_body(query, schema, context);
    }

    let mut resolved_ctes: Vec<CommonTableExpression> = Vec::new();
    let mut cte_schemas: CteSchemas = HashMap::new();
    let cte_names: Vec<&str> = query.ctes.iter().map(|cte| cte.name.as_str()).collect();

    for cte in &query.ctes {
        let referenced = direct_from_sources(&cte.query);
        if referenced.iter().any(|name| name == &cte.name) {
            return Err(semantic_error(
                &query.source,
                format!(
                    "Recursive reference to CTE {} is not supported.",
                    python_repr(&cte.name)
                ),
                cte.position,
            ));
        }
        let later: Vec<&String> = referenced
            .iter()
            .filter(|name| cte_names.contains(&name.as_str()) && !cte_schemas.contains_key(*name))
            .collect();
        if !later.is_empty() {
            return Err(semantic_error(
                &query.source,
                format!(
                    "CTE {} cannot reference later CTE {}; forward references are not supported.",
                    python_repr(&cte.name),
                    python_repr(later[0])
                ),
                cte.position,
            ));
        }
        let mut subquery = (*cte.query).clone();
        subquery.ctes.clear();
        let resolved_subquery =
            resolve_composed_query(&subquery, schema, &cte_schemas, context, source_schemas)?;
        cte_schemas.insert(cte.name.clone(), query_result_schema(&resolved_subquery));
        resolved_ctes.push(CommonTableExpression {
            name: cte.name.clone(),
            query: Box::new(resolved_subquery),
            position: cte.position,
        });
    }

    let mut body = query.clone();
    body.ctes.clear();
    let mut resolved =
        resolve_composed_query(&body, schema, &cte_schemas, context, source_schemas)?;
    resolved.ctes = resolved_ctes;
    Ok(resolved)
}
