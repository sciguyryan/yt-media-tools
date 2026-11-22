//! Semantic relation binding for staged yt-sql JOIN queries.
//!
//! Port of `join_resolution.py`: resolve relation aliases and field ownership
//! without making JOIN executable. Python's generic `_rewrite_value` reflection
//! over dataclass fields becomes explicit recursive rewriting over the Rust AST
//! node enums; the diagnostics and their `reason` values are preserved.

use std::collections::HashMap;
use std::collections::HashSet;

use crate::model::{
    AggregateFunction, Between, BoolExpr, CaseWhen, CollectionCount, CollectionFilter,
    CollectionPredicate, CollectionProjection, Expr, Field, InList, IsNull, JoinClause, OrderTerm,
    Query, QueryError, RelationField, ScalarBinary, ScalarCase, ScalarComparison, ScalarFunction,
    ScalarIndex, ScalarIsNull, ScalarMember, ScalarUnary, SelectTerm, TextPredicate, TruthTest,
    Unary, WindowFunction, WindowSpecification,
};
use crate::resolver::{SemanticScope, SourceSchemas, relation_binding};
use crate::schema::{FieldInfo, QuerySchema};

const DEFAULT_REASON: &str = "invalid";

fn semantic_error(source: &str, message: impl Into<String>, position: usize) -> QueryError {
    QueryError::semantic(source, message, position, DEFAULT_REASON)
}

fn python_repr(text: &str) -> String {
    crate::resolver::python_repr(text)
}

// ---------------------------------------------------------------------------
// Relation-owned field rewriting (Python `_rewrite_value`)
// ---------------------------------------------------------------------------

/// Bind one relation-owned field while preserving later-scope projection
/// aliases.
fn rewrite_field(
    field: &Field,
    scope: &SemanticScope,
    source: &str,
    preserved_field_names: &HashSet<String>,
) -> Result<Expr, QueryError> {
    if preserved_field_names.contains(&field.name) {
        return Ok(Expr::Field(field.clone()));
    }
    let parts: Vec<&str> = field.name.splitn(2, '.').collect();
    if parts.len() == 2 {
        let (qualifier, field_name) = (parts[0], parts[1]);
        if let Some(binding) = scope.binding_for_qualifier(qualifier) {
            let Some(info) = binding.schema.resolve(field_name) else {
                return Err(QueryError::semantic(
                    source,
                    format!(
                        "Relation {} has no field {}.",
                        python_repr(qualifier),
                        python_repr(field_name)
                    ),
                    field.position,
                    "unknown-field",
                ));
            };
            let canonical = info.alias_of.clone().unwrap_or_else(|| info.name.clone());
            return Ok(Expr::RelationField(RelationField {
                qualifier: qualifier.to_string(),
                name: canonical,
                position: field.position,
                kind: Some(info.kind.clone()),
                relation_key: Some(binding.identity.key()),
            }));
        }

        // A dotted identifier can still be an established structured field
        // path. Diagnose an unknown relation qualifier only when the suffix is
        // a visible row field, making the user's relational intent unambiguous.
        if scope
            .relations
            .iter()
            .any(|binding| binding.schema.resolve(field_name).is_some())
        {
            return Err(QueryError::semantic(
                source,
                format!("Unknown relation alias {}.", python_repr(qualifier)),
                field.position,
                "unknown-relation-alias",
            ));
        }
    }

    let matches = scope.field_matches(&field.name);
    if matches.is_empty() {
        return Err(QueryError::semantic(
            source,
            format!("Unknown field {}.", python_repr(&field.name)),
            field.position,
            "unknown-field",
        ));
    }
    if matches.len() > 1 {
        return Err(QueryError::semantic(
            source,
            format!(
                "Ambiguous field {}; qualify it with a relation alias.",
                python_repr(&field.name)
            ),
            field.position,
            "ambiguous-field",
        ));
    }
    let matched = &matches[0];
    let qualifier = scope
        .relations
        .iter()
        .find(|binding| binding.identity == matched.relation)
        .and_then(|binding| binding.qualifier.clone())
        .unwrap_or_default();
    let canonical = matched
        .field
        .alias_of
        .clone()
        .unwrap_or_else(|| matched.field.name.clone());
    Ok(Expr::RelationField(RelationField {
        qualifier,
        name: canonical,
        position: field.position,
        kind: Some(matched.field.kind.clone()),
        relation_key: Some(matched.relation.key()),
    }))
}

fn rewrite_expr(
    expression: &Expr,
    scope: &SemanticScope,
    source: &str,
    preserved_field_names: &HashSet<String>,
) -> Result<Expr, QueryError> {
    match expression {
        Expr::Field(field) => rewrite_field(field, scope, source, preserved_field_names),
        Expr::RelationField(_) | Expr::Literal(_) | Expr::CollectionElement(_) => {
            Ok(expression.clone())
        }
        Expr::Unary(unary) => Ok(Expr::Unary(ScalarUnary {
            operator: unary.operator.clone(),
            operand: Box::new(rewrite_expr(
                &unary.operand,
                scope,
                source,
                preserved_field_names,
            )?),
            position: unary.position,
            kind: unary.kind.clone(),
        })),
        Expr::Binary(binary) => Ok(Expr::Binary(ScalarBinary {
            operator: binary.operator.clone(),
            left: Box::new(rewrite_expr(
                &binary.left,
                scope,
                source,
                preserved_field_names,
            )?),
            right: Box::new(rewrite_expr(
                &binary.right,
                scope,
                source,
                preserved_field_names,
            )?),
            position: binary.position,
            kind: binary.kind.clone(),
        })),
        Expr::Index(index) => Ok(Expr::Index(ScalarIndex {
            collection: Box::new(rewrite_expr(
                &index.collection,
                scope,
                source,
                preserved_field_names,
            )?),
            index: Box::new(rewrite_expr(
                &index.index,
                scope,
                source,
                preserved_field_names,
            )?),
            position: index.position,
            kind: index.kind.clone(),
            resolved_type: index.resolved_type.clone(),
        })),
        Expr::Member(member) => Ok(Expr::Member(ScalarMember {
            value: Box::new(rewrite_expr(
                &member.value,
                scope,
                source,
                preserved_field_names,
            )?),
            member: member.member.clone(),
            position: member.position,
            kind: member.kind.clone(),
            resolved_type: member.resolved_type.clone(),
        })),
        Expr::Window(window) => Ok(Expr::Window(WindowFunction {
            name: window.name.clone(),
            specification: WindowSpecification {
                partition_by: window
                    .specification
                    .partition_by
                    .iter()
                    .map(|item| rewrite_expr(item, scope, source, preserved_field_names))
                    .collect::<Result<Vec<_>, _>>()?,
                order_by: rewrite_order_terms(
                    &window.specification.order_by,
                    scope,
                    source,
                    preserved_field_names,
                )?,
                position: window.specification.position,
                kind: window.specification.kind.clone(),
            },
            position: window.position,
            kind: window.kind.clone(),
            resolved_type: window.resolved_type.clone(),
        })),
        Expr::Case(scalar_case) => {
            let mut whens = Vec::new();
            for branch in &scalar_case.whens {
                whens.push(CaseWhen {
                    condition: Box::new(rewrite_bool(
                        &branch.condition,
                        scope,
                        source,
                        preserved_field_names,
                    )?),
                    result: Box::new(rewrite_expr(
                        &branch.result,
                        scope,
                        source,
                        preserved_field_names,
                    )?),
                    position: branch.position,
                });
            }
            let else_result = match &scalar_case.else_result {
                Some(else_expression) => Some(Box::new(rewrite_expr(
                    else_expression,
                    scope,
                    source,
                    preserved_field_names,
                )?)),
                None => None,
            };
            Ok(Expr::Case(ScalarCase {
                whens,
                else_result,
                position: scalar_case.position,
                kind: scalar_case.kind.clone(),
            }))
        }
        Expr::Function(function) => {
            let mut args = Vec::new();
            for argument in &function.args {
                args.push(rewrite_expr(
                    argument,
                    scope,
                    source,
                    preserved_field_names,
                )?);
            }
            Ok(Expr::Function(ScalarFunction {
                name: function.name.clone(),
                args,
                position: function.position,
                kind: function.kind.clone(),
                resolved_type: function.resolved_type.clone(),
            }))
        }
        Expr::Aggregate(aggregate) => {
            let mut args = Vec::new();
            for argument in &aggregate.args {
                args.push(rewrite_expr(
                    argument,
                    scope,
                    source,
                    preserved_field_names,
                )?);
            }
            let filter_predicate = match &aggregate.filter_predicate {
                Some(predicate) => Some(Box::new(rewrite_bool(
                    predicate,
                    scope,
                    source,
                    preserved_field_names,
                )?)),
                None => None,
            };
            Ok(Expr::Aggregate(AggregateFunction {
                name: aggregate.name.clone(),
                args,
                count_star: aggregate.count_star,
                filter_predicate,
                position: aggregate.position,
                kind: aggregate.kind.clone(),
            }))
        }
        Expr::CollectionCount(count) => Ok(Expr::CollectionCount(CollectionCount {
            collection: Box::new(rewrite_expr(
                &count.collection,
                scope,
                source,
                preserved_field_names,
            )?),
            binding: count.binding.clone(),
            predicate: Box::new(rewrite_bool(
                &count.predicate,
                scope,
                source,
                preserved_field_names,
            )?),
            position: count.position,
            kind: count.kind.clone(),
            resolved_type: count.resolved_type.clone(),
        })),
        Expr::CollectionFilter(filter) => Ok(Expr::CollectionFilter(CollectionFilter {
            collection: Box::new(rewrite_expr(
                &filter.collection,
                scope,
                source,
                preserved_field_names,
            )?),
            binding: filter.binding.clone(),
            predicate: Box::new(rewrite_bool(
                &filter.predicate,
                scope,
                source,
                preserved_field_names,
            )?),
            position: filter.position,
            kind: filter.kind.clone(),
            resolved_type: filter.resolved_type.clone(),
        })),
        Expr::CollectionProjection(projection) => {
            Ok(Expr::CollectionProjection(CollectionProjection {
                collection: Box::new(rewrite_expr(
                    &projection.collection,
                    scope,
                    source,
                    preserved_field_names,
                )?),
                binding: projection.binding.clone(),
                projection: Box::new(rewrite_expr(
                    &projection.projection,
                    scope,
                    source,
                    preserved_field_names,
                )?),
                position: projection.position,
                kind: projection.kind.clone(),
                resolved_type: projection.resolved_type.clone(),
                evaluation_fusion_safe: projection.evaluation_fusion_safe,
            }))
        }
    }
}

fn rewrite_bool(
    node: &BoolExpr,
    scope: &SemanticScope,
    source: &str,
    preserved_field_names: &HashSet<String>,
) -> Result<BoolExpr, QueryError> {
    match node {
        BoolExpr::Literal(_) => Ok(node.clone()),
        BoolExpr::Unary(unary) => Ok(BoolExpr::Unary(Unary {
            operator: unary.operator.clone(),
            operand: Box::new(rewrite_bool(
                &unary.operand,
                scope,
                source,
                preserved_field_names,
            )?),
        })),
        BoolExpr::Binary(binary) => Ok(BoolExpr::Binary(crate::model::Binary {
            operator: binary.operator.clone(),
            left: Box::new(rewrite_bool(
                &binary.left,
                scope,
                source,
                preserved_field_names,
            )?),
            right: Box::new(rewrite_bool(
                &binary.right,
                scope,
                source,
                preserved_field_names,
            )?),
        })),
        BoolExpr::Between(between) => {
            let field =
                rewrite_between_field(&between.field, scope, source, preserved_field_names)?;
            Ok(BoolExpr::Between(Between {
                field,
                lower: between.lower.clone(),
                upper: between.upper.clone(),
                negated: between.negated,
            }))
        }
        BoolExpr::InList(in_list) => {
            let field =
                rewrite_between_field(&in_list.field, scope, source, preserved_field_names)?;
            Ok(BoolExpr::InList(InList {
                field,
                values: in_list.values.clone(),
                negated: in_list.negated,
            }))
        }
        BoolExpr::IsNull(is_null) => {
            // A qualified field (`r.id IS NULL`) must keep its relation binding:
            // flattening it to a bare Field would read the left row instead of
            // the relation record, so encode it as a scalar NULL test.
            let rewritten = rewrite_field(&is_null.field, scope, source, preserved_field_names)?;
            match rewritten {
                Expr::Field(field) => Ok(BoolExpr::IsNull(IsNull {
                    field,
                    negated: is_null.negated,
                })),
                Expr::RelationField(relation_field) => Ok(BoolExpr::ScalarIsNull(ScalarIsNull {
                    expression: Box::new(Expr::RelationField(relation_field)),
                    negated: is_null.negated,
                })),
                // `_rewrite_value` only ever yields Field or RelationField nodes here.
                _ => Ok(BoolExpr::IsNull(IsNull {
                    field: is_null.field.clone(),
                    negated: is_null.negated,
                })),
            }
        }
        BoolExpr::TextPredicate(text) => {
            let field = rewrite_between_field(&text.field, scope, source, preserved_field_names)?;
            Ok(BoolExpr::TextPredicate(TextPredicate {
                operator: text.operator.clone(),
                field,
                value: text.value.clone(),
                negated: text.negated,
            }))
        }
        BoolExpr::TruthTest(truth) => Ok(BoolExpr::TruthTest(TruthTest {
            operand: Box::new(rewrite_bool(
                &truth.operand,
                scope,
                source,
                preserved_field_names,
            )?),
            truth: truth.truth.clone(),
            negated: truth.negated,
        })),
        BoolExpr::CollectionPredicate(predicate) => {
            Ok(BoolExpr::CollectionPredicate(CollectionPredicate {
                quantifier: predicate.quantifier.clone(),
                collection: Box::new(rewrite_expr(
                    &predicate.collection,
                    scope,
                    source,
                    preserved_field_names,
                )?),
                binding: predicate.binding.clone(),
                predicate: Box::new(rewrite_bool(
                    &predicate.predicate,
                    scope,
                    source,
                    preserved_field_names,
                )?),
                position: predicate.position,
            }))
        }
        BoolExpr::ScalarIsNull(is_null) => Ok(BoolExpr::ScalarIsNull(ScalarIsNull {
            expression: Box::new(rewrite_expr(
                &is_null.expression,
                scope,
                source,
                preserved_field_names,
            )?),
            negated: is_null.negated,
        })),
        BoolExpr::ScalarComparison(comparison) => {
            Ok(BoolExpr::ScalarComparison(ScalarComparison {
                operator: comparison.operator.clone(),
                left: Box::new(rewrite_expr(
                    &comparison.left,
                    scope,
                    source,
                    preserved_field_names,
                )?),
                right: Box::new(rewrite_expr(
                    &comparison.right,
                    scope,
                    source,
                    preserved_field_names,
                )?),
            }))
        }
    }
}

fn rewrite_between_field(
    field: &Field,
    scope: &SemanticScope,
    source: &str,
    preserved_field_names: &HashSet<String>,
) -> Result<Field, QueryError> {
    match rewrite_field(field, scope, source, preserved_field_names)? {
        Expr::Field(field) => Ok(field),
        Expr::RelationField(field) => Ok(Field {
            name: field.name,
            position: field.position,
            kind: field.kind,
        }),
        // `_rewrite_value` only ever yields Field or RelationField nodes here.
        _ => Ok(field.clone()),
    }
}

fn rewrite_order_term(
    term: &OrderTerm,
    scope: &SemanticScope,
    source: &str,
    preserved_field_names: &HashSet<String>,
) -> Result<OrderTerm, QueryError> {
    let expression = match &term.expression {
        Some(expression) => Some(Box::new(rewrite_expr(
            expression,
            scope,
            source,
            preserved_field_names,
        )?)),
        None => None,
    };
    Ok(OrderTerm {
        field: term.field.clone(),
        descending: term.descending,
        position: term.position,
        kind: term.kind.clone(),
        expression,
    })
}

/// Rebuild the order terms of a window specification through relation rewriting.
fn rewrite_order_terms(
    terms: &[OrderTerm],
    scope: &SemanticScope,
    source: &str,
    preserved_field_names: &HashSet<String>,
) -> Result<Vec<OrderTerm>, QueryError> {
    terms
        .iter()
        .map(|term| rewrite_order_term(term, scope, source, preserved_field_names))
        .collect()
}

// ---------------------------------------------------------------------------
// Relation scopes
// ---------------------------------------------------------------------------

/// The relations visible to one JOIN edge, including its right side.
fn scope_through_join(scope: &SemanticScope, join_index: usize) -> SemanticScope {
    SemanticScope {
        relations: scope.relations[..join_index + 2].to_vec(),
    }
}

fn scope_for_query(
    query: &Query,
    physical_schema: &QuerySchema,
    cte_schemas: &HashMap<String, QuerySchema>,
    source_schemas: &SourceSchemas,
) -> Result<SemanticScope, QueryError> {
    let Some(from_alias) = &query.from_alias else {
        let position = query.source.find("FROM").unwrap_or(0);
        return Err(semantic_error(
            &query.source,
            "The primary relation in a JOIN query requires an AS alias.",
            position,
        ));
    };

    let left = if let Some(from_relation) = &query.from_relation {
        if let Some(derived) = &from_relation.derived {
            let exported: Vec<FieldInfo> = derived
                .query
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
            relation_binding(
                None,
                None,
                &QuerySchema::from_field_infos(exported),
                &HashMap::new(),
                &Vec::new(),
            )
        } else {
            relation_binding(
                query.from_source.as_deref(),
                query.from_facet.as_deref(),
                physical_schema,
                cte_schemas,
                source_schemas,
            )
        }
    } else {
        relation_binding(
            query.from_source.as_deref(),
            query.from_facet.as_deref(),
            physical_schema,
            cte_schemas,
            source_schemas,
        )
    };

    let mut bindings: Vec<crate::resolver::RelationBinding> =
        vec![crate::resolver::RelationBinding {
            identity: left.identity.clone(),
            schema: left.schema.clone(),
            qualifier: Some(from_alias.clone()),
        }];
    let mut aliases: HashSet<String> = HashSet::from([from_alias.clone()]);
    for join in &query.joins {
        let Some(alias) = &join.relation.alias else {
            return Err(semantic_error(
                &query.source,
                "Each joined relation requires an AS alias.",
                join.relation.position,
            ));
        };
        if aliases.contains(alias) {
            return Err(semantic_error(
                &query.source,
                format!("Duplicate relation alias {}.", python_repr(alias)),
                join.relation.position,
            ));
        }
        aliases.insert(alias.clone());
        let binding = if let Some(derived) = &join.relation.derived {
            let exported: Vec<FieldInfo> = derived
                .query
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
            relation_binding(
                None,
                None,
                &QuerySchema::from_field_infos(exported),
                &HashMap::new(),
                &Vec::new(),
            )
        } else {
            relation_binding(
                join.relation.source.as_deref(),
                join.relation.facet.as_deref(),
                physical_schema,
                cte_schemas,
                source_schemas,
            )
        };
        bindings.push(crate::resolver::RelationBinding {
            identity: binding.identity.clone(),
            schema: binding.schema.clone(),
            qualifier: Some(alias.clone()),
        });
    }
    Ok(SemanticScope {
        relations: bindings,
    })
}

// ---------------------------------------------------------------------------
// JOIN predicate validation
// ---------------------------------------------------------------------------

/// Reject row-unsafe expressions from a JOIN ON predicate.
fn validate_join_predicate(predicate: &BoolExpr, source: &str) -> Result<(), QueryError> {
    for node in crate::resolver::walk_bool_expr(predicate) {
        if let crate::resolver::AstNode::Expr(expression) = node {
            match expression {
                Expr::Aggregate(aggregate) => {
                    return Err(semantic_error(
                        source,
                        "Aggregate functions are not allowed in JOIN ON predicates.",
                        aggregate.position,
                    ));
                }
                Expr::Function(function) if function.name == "RANDOM" => {
                    return Err(QueryError::semantic(
                        source,
                        "RANDOM is not allowed in JOIN ON predicates.",
                        function.position,
                        "invalid-random-placement",
                    ));
                }
                _ => {}
            }
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Projection expansion
// ---------------------------------------------------------------------------

/// The externally visible name of one resolved projection term.
fn projection_output_name(term: &SelectTerm) -> String {
    if let Some(alias) = &term.alias {
        return alias.clone();
    }
    if let Some(Expr::RelationField(field)) = term.expression.as_deref() {
        return field.name.clone();
    }
    term.field.clone()
}

/// Detect the relation-wildcard shape `alias.*`. The Rust model has no
/// RelationWildcard expression variant; the parser represents it as a
/// wildcard-marked term (no expression, dotted-star field text).
fn relation_wildcard_qualifier(term: &SelectTerm) -> Option<String> {
    if let Some(Expr::Field(field)) = term.expression.as_deref() {
        // Defensive: a field whose name carries the wildcard spelling.
        if let Some(stripped) = field.name.strip_suffix(".*") {
            return Some(unquote_identifier_component(stripped));
        }
        return None;
    }
    if term.expression.is_some() {
        return None;
    }
    let field = term.field.strip_suffix(".*")?;
    Some(unquote_identifier_component(field))
}

fn unquote_identifier_component(value: &str) -> String {
    if value.starts_with('`') && value.ends_with('`') && value.len() >= 2 {
        value[1..value.len() - 1].replace("``", "`")
    } else {
        value.to_string()
    }
}

/// Expand relation wildcards and enforce unique joined projection names.
fn expand_join_projection(
    query: &Query,
    scope: &SemanticScope,
) -> Result<Vec<SelectTerm>, QueryError> {
    let selected: Vec<SelectTerm> = if query.select.is_empty() {
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
    let mut expanded: Vec<SelectTerm> = Vec::new();

    if selected.len() == 1 && selected[0].field == "*" && selected[0].expression.is_none() {
        let primary = &scope.relations[0];
        for info in primary.schema.select_star_fields() {
            let canonical = info.alias_of.clone().unwrap_or_else(|| info.name.clone());
            let expression = Expr::RelationField(RelationField {
                qualifier: primary.qualifier.clone().unwrap_or_default(),
                name: canonical.clone(),
                position: selected[0].position,
                kind: Some(info.kind.clone()),
                relation_key: Some(primary.identity.key()),
            });
            expanded.push(SelectTerm {
                field: canonical.clone(),
                alias: Some(canonical),
                position: selected[0].position,
                kind: Some(info.kind.clone()),
                expression: Some(Box::new(expression)),
            });
        }
    } else {
        for term in &selected {
            if let Some(qualifier) = relation_wildcard_qualifier(term) {
                let Some(binding) = scope.binding_for_qualifier(&qualifier) else {
                    return Err(QueryError::semantic(
                        &query.source,
                        format!("Unknown relation alias {}.", python_repr(&qualifier)),
                        term.position,
                        "unknown-relation-alias",
                    ));
                };
                for info in binding.schema.select_star_fields() {
                    let canonical = info.alias_of.clone().unwrap_or_else(|| info.name.clone());
                    let expression = Expr::RelationField(RelationField {
                        qualifier: binding.qualifier.clone().unwrap_or_default(),
                        name: canonical.clone(),
                        position: term.position,
                        kind: Some(info.kind.clone()),
                        relation_key: Some(binding.identity.key()),
                    });
                    expanded.push(SelectTerm {
                        field: canonical.clone(),
                        alias: Some(canonical),
                        position: term.position,
                        kind: Some(info.kind.clone()),
                        expression: Some(Box::new(expression)),
                    });
                }
            } else {
                let output_name = projection_output_name(term);
                let mut resolved_term = term.clone();
                resolved_term.alias = Some(output_name);
                expanded.push(resolved_term);
            }
        }
    }

    let mut names: HashSet<String> = HashSet::new();
    for term in &expanded {
        let output_name = projection_output_name(term);
        if names.contains(&output_name) {
            return Err(semantic_error(
                &query.source,
                format!(
                    "Duplicate SELECT output name {}; use AS to give fields unique names.",
                    python_repr(&output_name)
                ),
                term.position,
            ));
        }
        names.insert(output_name);
    }
    Ok(expanded)
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/// Resolve aliases and field ownership for one JOIN query body
/// (`resolve_join_references`).
pub fn resolve_join_references(
    query: &Query,
    physical_schema: &QuerySchema,
    cte_schemas: &HashMap<String, QuerySchema>,
    source_schemas: &SourceSchemas,
) -> Result<Query, QueryError> {
    if query.joins.is_empty() {
        return Ok(query.clone());
    }
    let scope = scope_for_query(query, physical_schema, cte_schemas, source_schemas)?;

    let mut resolved_joins: Vec<JoinClause> = Vec::new();
    for (index, join) in query.joins.iter().enumerate() {
        let join_scope = scope_through_join(&scope, index);
        let predicate = rewrite_bool(&join.predicate, &join_scope, &query.source, &HashSet::new())?;
        validate_join_predicate(&predicate, &query.source)?;
        let mut resolved_join = join.clone();
        resolved_join.predicate = Box::new(predicate);
        resolved_joins.push(resolved_join);
    }

    let mut select: Vec<SelectTerm> = Vec::new();
    for term in &query.select {
        let expression = match &term.expression {
            Some(expression) => Some(Box::new(rewrite_expr(
                expression,
                &scope,
                &query.source,
                &HashSet::new(),
            )?)),
            None => None,
        };
        select.push(SelectTerm {
            field: term.field.clone(),
            alias: term.alias.clone(),
            position: term.position,
            kind: term.kind.clone(),
            expression,
        });
    }

    let projection_query = Query {
        select: select.clone(),
        ..query.clone()
    };
    let select = expand_join_projection(&projection_query, &scope)?;

    // ORDER BY has a later name-resolution scope than relation-owned clauses:
    // explicit SELECT aliases take precedence over input fields, including when
    // an alias collides with an otherwise ambiguous unqualified JOIN field.
    let projection_aliases: HashSet<String> = query
        .select
        .iter()
        .filter_map(|term| term.alias.clone())
        .collect();
    let mut order_by: Vec<OrderTerm> = Vec::new();
    for term in &query.order_by {
        order_by.push(rewrite_order_term(
            term,
            &scope,
            &query.source,
            &projection_aliases,
        )?);
    }
    let mut group_by: Vec<Expr> = Vec::new();
    for item in &query.group_by {
        group_by.push(rewrite_expr(item, &scope, &query.source, &HashSet::new())?);
    }
    let predicate = match &query.predicate {
        Some(predicate) => Some(Box::new(rewrite_bool(
            predicate,
            &scope,
            &query.source,
            &HashSet::new(),
        )?)),
        None => None,
    };
    let having = match &query.having {
        Some(having) => Some(Box::new(rewrite_bool(
            having,
            &scope,
            &query.source,
            &HashSet::new(),
        )?)),
        None => None,
    };

    let mut resolved = query.clone();
    resolved.joins = resolved_joins;
    resolved.select = select;
    resolved.order_by = order_by;
    resolved.group_by = group_by;
    resolved.predicate = predicate;
    resolved.having = having;
    Ok(resolved)
}

/// Prepare one executable single JOIN after relation-scope resolution
/// (`prepare_join_query`).
pub fn prepare_join_query(
    query: &Query,
    physical_schema: &QuerySchema,
    cte_schemas: &HashMap<String, QuerySchema>,
    source_schemas: &SourceSchemas,
) -> Result<Query, QueryError> {
    let resolved = resolve_join_references(query, physical_schema, cte_schemas, source_schemas)?;
    if resolved.joins.len() != 1 {
        let position = if resolved.joins.len() > 1 {
            resolved.joins[1].position
        } else {
            0
        };
        return Err(semantic_error(
            &query.source,
            "Multi-way JOIN execution is not implemented yet.",
            position,
        ));
    }
    let join = &resolved.joins[0];
    if !matches!(
        join.kind,
        crate::model::JoinKind::Semi
            | crate::model::JoinKind::Anti
            | crate::model::JoinKind::Inner
            | crate::model::JoinKind::Left
    ) {
        return Err(semantic_error(
            &query.source,
            "JOIN syntax is recognised, but JOIN execution is not implemented yet.",
            join.position,
        ));
    }

    if matches!(
        join.kind,
        crate::model::JoinKind::Inner | crate::model::JoinKind::Left
    ) {
        return Ok(resolved);
    }

    let primary_alias = resolved.from_alias.clone().unwrap_or_default();
    let kind_label = join.kind.as_str();

    fn left_only_expr(
        expression: &Expr,
        primary_alias: &str,
        kind_label: &str,
        source: &str,
    ) -> Result<Expr, QueryError> {
        if let Expr::RelationField(field) = expression {
            if field.qualifier != primary_alias {
                return Err(semantic_error(
                    source,
                    format!(
                        "{} JOIN does not expose fields from relation {}.",
                        kind_label,
                        python_repr(&field.qualifier)
                    ),
                    field.position,
                ));
            }
            return Ok(Expr::Field(Field {
                name: field.name.clone(),
                position: field.position,
                kind: field.kind.clone(),
            }));
        }
        // `left_only` is only ever applied to already-resolved JOIN queries, so
        // every other variant is either a plain leaf or a rebuildable node.
        match expression {
            Expr::RelationField(_) => Ok(expression.clone()),
            Expr::Literal(_) | Expr::CollectionElement(_) | Expr::Field(_) => {
                Ok(expression.clone())
            }
            Expr::Unary(unary) => Ok(Expr::Unary(ScalarUnary {
                operator: unary.operator.clone(),
                operand: Box::new(left_only_expr(
                    &unary.operand,
                    primary_alias,
                    kind_label,
                    source,
                )?),
                position: unary.position,
                kind: unary.kind.clone(),
            })),
            Expr::Binary(binary) => Ok(Expr::Binary(ScalarBinary {
                operator: binary.operator.clone(),
                left: Box::new(left_only_expr(
                    &binary.left,
                    primary_alias,
                    kind_label,
                    source,
                )?),
                right: Box::new(left_only_expr(
                    &binary.right,
                    primary_alias,
                    kind_label,
                    source,
                )?),
                position: binary.position,
                kind: binary.kind.clone(),
            })),
            Expr::Index(index) => Ok(Expr::Index(ScalarIndex {
                collection: Box::new(left_only_expr(
                    &index.collection,
                    primary_alias,
                    kind_label,
                    source,
                )?),
                index: Box::new(left_only_expr(
                    &index.index,
                    primary_alias,
                    kind_label,
                    source,
                )?),
                position: index.position,
                kind: index.kind.clone(),
                resolved_type: index.resolved_type.clone(),
            })),
            Expr::Member(member) => Ok(Expr::Member(ScalarMember {
                value: Box::new(left_only_expr(
                    &member.value,
                    primary_alias,
                    kind_label,
                    source,
                )?),
                member: member.member.clone(),
                position: member.position,
                kind: member.kind.clone(),
                resolved_type: member.resolved_type.clone(),
            })),
            Expr::Window(window) => Ok(Expr::Window(WindowFunction {
                name: window.name.clone(),
                specification: WindowSpecification {
                    partition_by: window
                        .specification
                        .partition_by
                        .iter()
                        .map(|item| left_only_expr(item, primary_alias, kind_label, source))
                        .collect::<Result<Vec<_>, _>>()?,
                    order_by: left_only_order_terms(
                        &window.specification.order_by,
                        primary_alias,
                        kind_label,
                        source,
                    )?,
                    position: window.specification.position,
                    kind: window.specification.kind.clone(),
                },
                position: window.position,
                kind: window.kind.clone(),
                resolved_type: window.resolved_type.clone(),
            })),
            Expr::Case(scalar_case) => {
                let mut whens = Vec::new();
                for branch in &scalar_case.whens {
                    whens.push(CaseWhen {
                        condition: Box::new(left_only_bool(
                            &branch.condition,
                            primary_alias,
                            kind_label,
                            source,
                        )?),
                        result: Box::new(left_only_expr(
                            &branch.result,
                            primary_alias,
                            kind_label,
                            source,
                        )?),
                        position: branch.position,
                    });
                }
                let else_result = match &scalar_case.else_result {
                    Some(else_expression) => Some(Box::new(left_only_expr(
                        else_expression,
                        primary_alias,
                        kind_label,
                        source,
                    )?)),
                    None => None,
                };
                Ok(Expr::Case(ScalarCase {
                    whens,
                    else_result,
                    position: scalar_case.position,
                    kind: scalar_case.kind.clone(),
                }))
            }
            Expr::Function(function) => {
                let mut args = Vec::new();
                for argument in &function.args {
                    args.push(left_only_expr(argument, primary_alias, kind_label, source)?);
                }
                Ok(Expr::Function(ScalarFunction {
                    name: function.name.clone(),
                    args,
                    position: function.position,
                    kind: function.kind.clone(),
                    resolved_type: function.resolved_type.clone(),
                }))
            }
            Expr::Aggregate(aggregate) => {
                let mut args = Vec::new();
                for argument in &aggregate.args {
                    args.push(left_only_expr(argument, primary_alias, kind_label, source)?);
                }
                let filter_predicate = match &aggregate.filter_predicate {
                    Some(predicate) => Some(Box::new(left_only_bool(
                        predicate,
                        primary_alias,
                        kind_label,
                        source,
                    )?)),
                    None => None,
                };
                Ok(Expr::Aggregate(AggregateFunction {
                    name: aggregate.name.clone(),
                    args,
                    count_star: aggregate.count_star,
                    filter_predicate,
                    position: aggregate.position,
                    kind: aggregate.kind.clone(),
                }))
            }
            Expr::CollectionCount(count) => Ok(Expr::CollectionCount(CollectionCount {
                collection: Box::new(left_only_expr(
                    &count.collection,
                    primary_alias,
                    kind_label,
                    source,
                )?),
                binding: count.binding.clone(),
                predicate: Box::new(left_only_bool(
                    &count.predicate,
                    primary_alias,
                    kind_label,
                    source,
                )?),
                position: count.position,
                kind: count.kind.clone(),
                resolved_type: count.resolved_type.clone(),
            })),
            Expr::CollectionFilter(filter) => Ok(Expr::CollectionFilter(CollectionFilter {
                collection: Box::new(left_only_expr(
                    &filter.collection,
                    primary_alias,
                    kind_label,
                    source,
                )?),
                binding: filter.binding.clone(),
                predicate: Box::new(left_only_bool(
                    &filter.predicate,
                    primary_alias,
                    kind_label,
                    source,
                )?),
                position: filter.position,
                kind: filter.kind.clone(),
                resolved_type: filter.resolved_type.clone(),
            })),
            Expr::CollectionProjection(projection) => {
                Ok(Expr::CollectionProjection(CollectionProjection {
                    collection: Box::new(left_only_expr(
                        &projection.collection,
                        primary_alias,
                        kind_label,
                        source,
                    )?),
                    binding: projection.binding.clone(),
                    projection: Box::new(left_only_expr(
                        &projection.projection,
                        primary_alias,
                        kind_label,
                        source,
                    )?),
                    position: projection.position,
                    kind: projection.kind.clone(),
                    resolved_type: projection.resolved_type.clone(),
                    evaluation_fusion_safe: projection.evaluation_fusion_safe,
                }))
            }
        }
    }

    fn left_only_bool(
        node: &BoolExpr,
        primary_alias: &str,
        kind_label: &str,
        source: &str,
    ) -> Result<BoolExpr, QueryError> {
        match node {
            BoolExpr::Literal(_) => Ok(node.clone()),
            BoolExpr::Unary(unary) => Ok(BoolExpr::Unary(Unary {
                operator: unary.operator.clone(),
                operand: Box::new(left_only_bool(
                    &unary.operand,
                    primary_alias,
                    kind_label,
                    source,
                )?),
            })),
            BoolExpr::Binary(binary) => Ok(BoolExpr::Binary(crate::model::Binary {
                operator: binary.operator.clone(),
                left: Box::new(left_only_bool(
                    &binary.left,
                    primary_alias,
                    kind_label,
                    source,
                )?),
                right: Box::new(left_only_bool(
                    &binary.right,
                    primary_alias,
                    kind_label,
                    source,
                )?),
            })),
            BoolExpr::Between(between) => Ok(BoolExpr::Between(Between {
                field: left_only_field(&between.field, primary_alias, kind_label, source)?,
                lower: between.lower.clone(),
                upper: between.upper.clone(),
                negated: between.negated,
            })),
            BoolExpr::InList(in_list) => Ok(BoolExpr::InList(InList {
                field: left_only_field(&in_list.field, primary_alias, kind_label, source)?,
                values: in_list.values.clone(),
                negated: in_list.negated,
            })),
            BoolExpr::IsNull(is_null) => Ok(BoolExpr::IsNull(IsNull {
                field: left_only_field(&is_null.field, primary_alias, kind_label, source)?,
                negated: is_null.negated,
            })),
            BoolExpr::TextPredicate(text) => Ok(BoolExpr::TextPredicate(TextPredicate {
                operator: text.operator.clone(),
                field: left_only_field(&text.field, primary_alias, kind_label, source)?,
                value: text.value.clone(),
                negated: text.negated,
            })),
            BoolExpr::TruthTest(truth) => Ok(BoolExpr::TruthTest(TruthTest {
                operand: Box::new(left_only_bool(
                    &truth.operand,
                    primary_alias,
                    kind_label,
                    source,
                )?),
                truth: truth.truth.clone(),
                negated: truth.negated,
            })),
            BoolExpr::CollectionPredicate(predicate) => {
                Ok(BoolExpr::CollectionPredicate(CollectionPredicate {
                    quantifier: predicate.quantifier.clone(),
                    collection: Box::new(left_only_expr(
                        &predicate.collection,
                        primary_alias,
                        kind_label,
                        source,
                    )?),
                    binding: predicate.binding.clone(),
                    predicate: Box::new(left_only_bool(
                        &predicate.predicate,
                        primary_alias,
                        kind_label,
                        source,
                    )?),
                    position: predicate.position,
                }))
            }
            BoolExpr::ScalarIsNull(is_null) => Ok(BoolExpr::ScalarIsNull(ScalarIsNull {
                expression: Box::new(left_only_expr(
                    &is_null.expression,
                    primary_alias,
                    kind_label,
                    source,
                )?),
                negated: is_null.negated,
            })),
            BoolExpr::ScalarComparison(comparison) => {
                Ok(BoolExpr::ScalarComparison(ScalarComparison {
                    operator: comparison.operator.clone(),
                    left: Box::new(left_only_expr(
                        &comparison.left,
                        primary_alias,
                        kind_label,
                        source,
                    )?),
                    right: Box::new(left_only_expr(
                        &comparison.right,
                        primary_alias,
                        kind_label,
                        source,
                    )?),
                }))
            }
        }
    }

    fn left_only_field(
        field: &Field,
        primary_alias: &str,
        kind_label: &str,
        source: &str,
    ) -> Result<Field, QueryError> {
        match left_only_expr(
            &Expr::Field(field.clone()),
            primary_alias,
            kind_label,
            source,
        )? {
            Expr::Field(resolved) => Ok(resolved),
            // `Field` inputs are returned unchanged; RelationField conversion
            // failures surface through the RelationField arm.
            _ => Ok(field.clone()),
        }
    }

    fn left_only_terms(
        terms: &[SelectTerm],
        primary_alias: &str,
        kind_label: &str,
        source: &str,
    ) -> Result<Vec<SelectTerm>, QueryError> {
        let mut rewritten = Vec::new();
        for term in terms {
            let expression = match &term.expression {
                Some(expression) => Some(Box::new(left_only_expr(
                    expression,
                    primary_alias,
                    kind_label,
                    source,
                )?)),
                None => None,
            };
            rewritten.push(SelectTerm {
                field: term.field.clone(),
                alias: term.alias.clone(),
                position: term.position,
                kind: term.kind.clone(),
                expression,
            });
        }
        Ok(rewritten)
    }

    fn left_only_order_terms(
        terms: &[OrderTerm],
        primary_alias: &str,
        kind_label: &str,
        source: &str,
    ) -> Result<Vec<OrderTerm>, QueryError> {
        let mut rewritten = Vec::new();
        for term in terms {
            let expression = match &term.expression {
                Some(expression) => Some(Box::new(left_only_expr(
                    expression,
                    primary_alias,
                    kind_label,
                    source,
                )?)),
                None => None,
            };
            rewritten.push(OrderTerm {
                field: term.field.clone(),
                descending: term.descending,
                position: term.position,
                kind: term.kind.clone(),
                expression,
            });
        }
        Ok(rewritten)
    }

    let mut group_by: Vec<Expr> = Vec::new();
    for item in &resolved.group_by {
        group_by.push(left_only_expr(
            item,
            &primary_alias,
            kind_label,
            &query.source,
        )?);
    }
    let predicate = match &resolved.predicate {
        Some(predicate) => Some(Box::new(left_only_bool(
            predicate,
            &primary_alias,
            kind_label,
            &query.source,
        )?)),
        None => None,
    };
    let having = match &resolved.having {
        Some(having) => Some(Box::new(left_only_bool(
            having,
            &primary_alias,
            kind_label,
            &query.source,
        )?)),
        None => None,
    };

    let mut prepared = resolved;
    prepared.select = left_only_terms(&prepared.select, &primary_alias, kind_label, &query.source)?;
    prepared.order_by = left_only_order_terms(
        &prepared.order_by,
        &primary_alias,
        kind_label,
        &query.source,
    )?;
    prepared.group_by = group_by;
    prepared.predicate = predicate;
    prepared.having = having;
    Ok(prepared)
}
