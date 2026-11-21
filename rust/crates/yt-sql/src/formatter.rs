//! Canonical yt-sql formatting for parsed and resolved query models.
//!
//! Port of `query_formatter.py`. Canonical text is consumed by the resolver's
//! GROUP BY compatibility checks, so the renderings must stay byte-identical to
//! the Python reference for the established expression shapes.
//!
//! Representation note for the Rust literal model (`LiteralValue`): numeric
//! literals are stored as unquoted `Text` with the raw source spelling, and
//! temporal infinity sentinels as `Raw` with a canonicalised `raw`. The
//! formatter therefore re-derives the Python value-based branches from the
//! literal text; resolved literals already carry canonical spellings in `raw`
//! for the date/datetime/duration kinds, which keeps the output identical.

use std::sync::OnceLock;

use regex::Regex;

use crate::model::{
    BoolExpr, Expr, JoinClause, Literal, LiteralValue, Query, RelationField, RelationReference,
    SelectTerm,
};

const RESERVED_IDENTIFIER_WORDS: [&str; 3] = ["TRUE", "FALSE", "NULL"];

fn is_identifier_component(value: &str) -> bool {
    // One ordinary unquoted yt-sql identifier component.
    let mut characters = value.chars();
    let Some(first) = characters.next() else {
        return false;
    };
    if !(first == '_' || unicode_ident::is_xid_start(first)) {
        return false;
    }
    value
        .chars()
        .skip(1)
        .all(|character| unicode_ident::is_xid_continue(character) || character == '-')
}

fn format_identifier_component(value: &str) -> String {
    // Render one identifier component, quoting only when the ordinary grammar
    // cannot express it.
    if is_identifier_component(value)
        && !RESERVED_IDENTIFIER_WORDS.contains(&value.to_uppercase().as_str())
    {
        return value.to_string();
    }
    format!("`{}`", value.replace('`', "``"))
}

fn format_identifier(value: &str) -> String {
    // A possibly dotted legacy field path with independently quoted components.
    value
        .split('.')
        .map(format_identifier_component)
        .collect::<Vec<_>>()
        .join(".")
}

fn format_string_literal(value: &str) -> String {
    // Canonical single-quoted spelling.
    let escaped = value
        .replace('\\', "\\\\")
        .replace('\n', "\\n")
        .replace('\t', "\\t")
        .replace('\'', "''");
    format!("'{escaped}'")
}

fn format_like_pattern(value: &str) -> String {
    // LIKE pattern text without consuming its pattern-level backslash escapes.
    format!("'{}'", value.replace('\'', "''"))
}

fn canonical_numeric_raw(raw: &str) -> String {
    // Normalise numeric spelling while preserving a deliberately chosen base.
    let compact: String = raw.chars().filter(|character| *character != '_').collect();
    static BASE: OnceLock<Regex> = OnceLock::new();
    let regex = BASE.get_or_init(|| {
        Regex::new(r"^(?P<sign>[+-]?)(?P<prefix>0[xX]|0[oO]|0[bB])(?P<digits>[0-9A-Fa-f]+)$")
            .expect("static regex")
    });
    let Some(captures) = regex.captures(&compact) else {
        return compact;
    };
    let sign = captures.name("sign").map(|m| m.as_str()).unwrap_or("");
    let prefix = captures
        .name("prefix")
        .map(|m| m.as_str())
        .unwrap_or("")
        .to_lowercase();
    let digits = captures.name("digits").map(|m| m.as_str()).unwrap_or("");
    let digits = if prefix == "0x" {
        digits.to_lowercase()
    } else {
        digits.to_string()
    };
    format!("{sign}{prefix}{digits}")
}

/// Recognise the TODAY()/NOW() relative spelling and return its canonical form.
pub(crate) fn canonicalise_temporal_expression(text: &str) -> Option<String> {
    static TEMPORAL: OnceLock<Regex> = OnceLock::new();
    let regex = TEMPORAL.get_or_init(|| {
        Regex::new(concat!(
            r"(?i)^(TODAY|NOW)\(\)\s*",
            r"(?:(?P<op>[+-])\s*(?P<count>\d+(?:\.\d+)?)\s*(?P<unit>[^\W\d_]+(?:-[^\W\d_]+)*))?$"
        ))
        .expect("static regex")
    });
    let raw = text.split_whitespace().collect::<Vec<_>>().join(" ");
    let captures = regex.captures(&raw)?;
    let base = format!("{}()", captures.get(1)?.as_str().to_uppercase());
    let Some(operator) = captures.name("op").map(|m| m.as_str()) else {
        return Some(base);
    };
    let count = captures.name("count").map(|m| m.as_str()).unwrap_or("");
    let unit = captures.name("unit").map(|m| m.as_str()).unwrap_or("");
    let canonical = crate::units::load_default_unit_registry()
        .canonical_name(unit)
        .ok()?;
    Some(format!("{base}{operator}{count}{canonical}"))
}

/// The canonical INFINITY()/−INFINITY() spelling carried by a Raw sentinel,
/// or `None` when the literal is not an infinity sentinel.
fn infinity_spelling(literal: &Literal) -> Option<String> {
    match &literal.value {
        LiteralValue::Raw => {
            let compact = literal
                .raw
                .split_whitespace()
                .collect::<String>()
                .to_uppercase();
            if compact == "INFINITY()" {
                Some("INFINITY()".to_string())
            } else if compact == "-INFINITY()" {
                Some("-INFINITY()".to_string())
            } else {
                None
            }
        }
        _ => None,
    }
}

/// Whether the literal text is an unquoted number (Rust stand-in for Python's
/// numeric literal `value` domain).
fn is_unquoted_numeric_literal(literal: &Literal) -> bool {
    if literal.quoted {
        return false;
    }
    match &literal.value {
        LiteralValue::Text(_) | LiteralValue::Raw => {
            if infinity_spelling(literal).is_some() {
                return false;
            }
            let text = match &literal.value {
                LiteralValue::Text(text) => text.clone(),
                _ => literal.raw.clone(),
            };
            let compact: String = text
                .chars()
                .filter(|character| !character.is_whitespace())
                .collect();
            let starts_number = {
                let body = compact.strip_prefix(['+', '-']).unwrap_or(&compact);
                body.starts_with(|character: char| character.is_ascii_digit())
                    || (body.starts_with('0')
                        && body.len() > 1
                        && matches!(body.as_bytes()[1], b'x' | b'X' | b'o' | b'O' | b'b' | b'B'))
            };
            if !starts_number {
                return false;
            }
            crate::parser::parse_number_text(&compact, &text, 0).is_ok()
        }
        _ => false,
    }
}

/// Whether the literal's decoded text matches TRUE/FALSE word spellings.
fn is_unquoted_boolean_word(literal: &Literal) -> bool {
    if literal.quoted {
        return false;
    }
    match &literal.value {
        LiteralValue::Text(text) => {
            let lowered = text.to_lowercase();
            lowered == "true" || lowered == "false"
        }
        _ => false,
    }
}

fn format_literal(literal: &Literal, expected_kind: Option<&str>) -> String {
    // Render a literal, normalising established temporal spellings where type
    // information permits.
    match &literal.value {
        LiteralValue::Null => return "NULL".to_string(),
        LiteralValue::Bool(value) => return if *value { "TRUE" } else { "FALSE" }.to_string(),
        _ => {}
    }
    if literal.quoted
        && let LiteralValue::Text(value) = &literal.value
    {
        return format_string_literal(value);
    }

    if let Some(expression) = canonicalise_temporal_expression(&literal.raw) {
        return expression;
    }

    if let Some(spelling) = infinity_spelling(literal) {
        return spelling;
    }
    // Python compares the decoded literal value against date/datetime/numeric
    // types. Resolution canonicalises `raw` for those kinds, so the raw text is
    // the resolved canonical spelling; unresolved literals fall back to it too,
    // exactly like Python's untyped branches.
    if matches!(
        expected_kind,
        Some("date") | Some("datetime") | Some("duration")
    ) {
        // Resolved literals of these kinds carry their canonical spelling in
        // `raw`; numeric values fall through to the numeric spelling exactly
        // like Python's branch ordering.
        if is_unquoted_numeric_literal(literal) {
            return canonical_numeric_raw(&literal.raw);
        }
        return literal.raw.clone();
    }
    if is_unquoted_boolean_word(literal) {
        let lowered = match &literal.value {
            LiteralValue::Text(text) => text.to_lowercase(),
            _ => literal.raw.to_lowercase(),
        };
        return if lowered == "true" { "TRUE" } else { "FALSE" }.to_string();
    }
    if is_unquoted_numeric_literal(literal) {
        return canonical_numeric_raw(&literal.raw);
    }
    literal.raw.clone()
}

fn format_field_literal(kind: Option<&str>, literal: &Literal) -> String {
    format_literal(literal, kind)
}

fn scalar_binary_precedence(operator: &str) -> usize {
    if matches!(operator, "*" | "/" | "%") {
        20
    } else {
        10
    }
}

fn format_scalar_binary_child(expression: &Expr, parent_operator: &str, right: bool) -> String {
    let text = format_scalar_expression(expression);
    let Expr::Binary(child) = expression else {
        return text;
    };
    let child_precedence = scalar_binary_precedence(&child.operator);
    let parent_precedence = scalar_binary_precedence(parent_operator);
    if child_precedence < parent_precedence || (right && child_precedence == parent_precedence) {
        return format!("({text})");
    }
    text
}

fn literal_text(literal: &Literal) -> String {
    match &literal.value {
        LiteralValue::Text(text) => text.clone(),
        LiteralValue::Raw => literal.raw.clone(),
        LiteralValue::Bool(value) => (if *value { "TRUE" } else { "FALSE" }).to_string(),
        LiteralValue::Null => "NULL".to_string(),
    }
}

fn field_kind_text(field: &crate::model::Field) -> Option<&str> {
    field.kind.as_deref()
}

fn is_field_expression(expression: &Expr) -> bool {
    matches!(expression, Expr::Field(_) | Expr::RelationField(_))
}

/// Render a scalar expression in canonical yt-sql form.
pub fn format_scalar_expression(expression: &Expr) -> String {
    match expression {
        Expr::Field(field) => format_identifier(&field.name),
        Expr::RelationField(field) => format!(
            "{}.{}",
            format_identifier_component(&field.qualifier),
            format_identifier(&field.name)
        ),
        Expr::CollectionElement(element) => format_identifier_component(&element.binding),
        Expr::Literal(literal) => format_literal(literal, None),
        Expr::Unary(unary) => {
            let mut operand = format_scalar_expression(&unary.operand);
            if matches!(&*unary.operand, Expr::Binary(_)) {
                operand = format!("({operand})");
            }
            format!("{}{}", unary.operator, operand)
        }
        Expr::Binary(binary) => {
            let left = format_scalar_binary_child(&binary.left, &binary.operator, false);
            let right = format_scalar_binary_child(&binary.right, &binary.operator, true);
            format!("{} {} {}", left, binary.operator, right)
        }
        Expr::Index(index) => {
            let mut collection = format_scalar_expression(&index.collection);
            if matches!(&*index.collection, Expr::Binary(_) | Expr::Unary(_)) {
                collection = format!("({collection})");
            }
            format!("{}[{}]", collection, format_scalar_expression(&index.index))
        }
        Expr::Member(member) => {
            let mut value = format_scalar_expression(&member.value);
            // Bare dotted identifiers are an established field-path syntax.
            // Preserve the explicit postfix-member AST when formatting a member
            // whose base would otherwise be re-tokenised as part of that legacy
            // dotted field name.
            if matches!(
                &*member.value,
                Expr::Field(_) | Expr::Literal(_) | Expr::Unary(_) | Expr::Case(_)
            ) {
                value = format!("({value})");
            }
            format!("{}.{}", value, format_identifier_component(&member.member))
        }
        Expr::CollectionCount(count) => format!(
            "COUNT({} AS {} WHERE {})",
            format_scalar_expression(&count.collection),
            format_identifier_component(&count.binding),
            format_expression(&count.predicate)
        ),
        Expr::CollectionFilter(filter) => format!(
            "FILTER({} AS {} WHERE {})",
            format_scalar_expression(&filter.collection),
            format_identifier_component(&filter.binding),
            format_expression(&filter.predicate)
        ),
        Expr::CollectionProjection(projection) => format!(
            "MAP({} AS {} SELECT {})",
            format_scalar_expression(&projection.collection),
            format_identifier_component(&projection.binding),
            format_scalar_expression(&projection.projection)
        ),
        Expr::Function(function) => format!(
            "{}({})",
            function.name,
            function
                .args
                .iter()
                .map(format_scalar_expression)
                .collect::<Vec<_>>()
                .join(", ")
        ),
        Expr::Aggregate(aggregate) => {
            let inner = if aggregate.count_star {
                "*".to_string()
            } else {
                aggregate
                    .args
                    .iter()
                    .map(format_scalar_expression)
                    .collect::<Vec<_>>()
                    .join(", ")
            };
            let mut text = format!("{}({})", aggregate.name, inner);
            if let Some(predicate) = &aggregate.filter_predicate {
                text += &format!(" FILTER (WHERE {})", format_expression(predicate));
            }
            text
        }
        Expr::Case(scalar_case) => {
            let mut parts: Vec<String> = vec!["CASE".to_string()];
            for branch in &scalar_case.whens {
                parts.push(format!(
                    "WHEN {} THEN {}",
                    format_expression(&branch.condition),
                    format_scalar_expression(&branch.result)
                ));
            }
            if let Some(else_result) = &scalar_case.else_result {
                parts.push(format!("ELSE {}", format_scalar_expression(else_result)));
            }
            parts.push("END".to_string());
            parts.join(" ")
        }
    }
}

/// Render one Boolean expression node in canonical yt-sql form.
pub fn format_expression(node: &BoolExpr) -> String {
    match node {
        BoolExpr::Literal(literal) => format_literal(literal, None),
        BoolExpr::Unary(unary) => format!("NOT ({})", format_expression(&unary.operand)),
        BoolExpr::Binary(binary) => {
            if binary.operator == "AND" || binary.operator == "OR" {
                return format!(
                    "({} {} {})",
                    format_expression(&binary.left),
                    binary.operator,
                    format_expression(&binary.right)
                );
            }
            // Non-AND/OR Boolean binaries do not occur in the Rust
            // representation: row-level field comparisons are ScalarComparison
            // nodes (see the resolver's representation notes).
            format!(
                "{} {} {}",
                format_expression(&binary.left),
                binary.operator,
                format_expression(&binary.right)
            )
        }
        BoolExpr::Between(between) => {
            let not_part = if between.negated { " NOT" } else { "" };
            format!(
                "{}{} BETWEEN {} AND {}",
                between.field.name,
                not_part,
                format_field_literal(field_kind_text(&between.field), &between.lower),
                format_field_literal(field_kind_text(&between.field), &between.upper)
            )
        }
        BoolExpr::InList(in_list) => {
            let not_part = if in_list.negated { " NOT" } else { "" };
            let values = in_list
                .values
                .iter()
                .map(|value| format_field_literal(field_kind_text(&in_list.field), value))
                .collect::<Vec<_>>()
                .join(", ");
            format!("{}{} IN ({})", in_list.field.name, not_part, values)
        }
        BoolExpr::IsNull(is_null) => format!(
            "{} IS {}NULL",
            is_null.field.name,
            if is_null.negated { "NOT " } else { "" }
        ),
        BoolExpr::TextPredicate(text_predicate) => {
            let not_part = if text_predicate.negated { " NOT" } else { "" };
            let value = if (text_predicate.operator == "LIKE" || text_predicate.operator == "ILIKE")
                && text_predicate.value.quoted
            {
                format_like_pattern(&literal_text(&text_predicate.value))
            } else {
                format_field_literal(
                    field_kind_text(&text_predicate.field),
                    &text_predicate.value,
                )
            };
            format!(
                "{}{} {} {}",
                text_predicate.field.name, not_part, text_predicate.operator, value
            )
        }
        BoolExpr::CollectionPredicate(predicate) => format!(
            "{}({} AS {} WHERE {})",
            predicate.quantifier,
            format_scalar_expression(&predicate.collection),
            predicate.binding,
            format_expression(&predicate.predicate)
        ),
        BoolExpr::ScalarComparison(comparison) => {
            let right = if is_field_expression(&comparison.left)
                && matches!(&*comparison.right, Expr::Literal(_))
            {
                let kind = match &*comparison.left {
                    Expr::Field(field) => field_kind_text(field),
                    Expr::RelationField(field) => field.kind.as_deref(),
                    _ => None,
                };
                match &*comparison.right {
                    Expr::Literal(literal) => format_field_literal(kind, literal),
                    _ => format_scalar_expression(&comparison.right),
                }
            } else {
                format_scalar_expression(&comparison.right)
            };
            format!(
                "{} {} {}",
                format_scalar_expression(&comparison.left),
                comparison.operator,
                right
            )
        }
        BoolExpr::TruthTest(truth) => {
            // Preserve the established compact Boolean-field spelling while
            // making general predicate inspection unambiguous.
            let compact = comparison_field_equals_true(&truth.operand);
            let operand = if let Some(field_text) = compact {
                field_text
            } else {
                format!("({})", format_expression(&truth.operand))
            };
            format!(
                "{} IS {}{}",
                operand,
                if truth.negated { "NOT " } else { "" },
                truth.truth
            )
        }
        BoolExpr::ScalarIsNull(is_null) => format!(
            "{} IS {}NULL",
            format_scalar_expression(&is_null.expression),
            if is_null.negated { "NOT " } else { "" }
        ),
    }
}

/// Detect the `field = TRUE` truth-test sugar for its compact spelling.
fn comparison_field_equals_true(operand: &BoolExpr) -> Option<String> {
    let BoolExpr::ScalarComparison(comparison) = operand else {
        return None;
    };
    if comparison.operator != "=" || !is_field_expression(&comparison.left) {
        return None;
    }
    let Expr::Literal(literal) = &*comparison.right else {
        return None;
    };
    // Python checks `node.operand.right.value is True`.
    match &literal.value {
        LiteralValue::Bool(true) => match &*comparison.left {
            Expr::Field(field) => Some(field.name.clone()),
            Expr::RelationField(field) => Some(format!("{}.{}", field.qualifier, field.name)),
            _ => None,
        },
        _ => None,
    }
}

fn relation_source_regex() -> &'static Regex {
    static SOURCE: OnceLock<Regex> = OnceLock::new();
    SOURCE.get_or_init(|| {
        Regex::new(r"^(@[A-Za-z0-9_.-]+|[A-Za-z_][A-Za-z0-9_.-]*)$").expect("static regex")
    })
}

/// Render one relation reference without changing source identity.
pub fn format_relation_source(
    source: &str,
    facet: Option<&str>,
    alias: Option<&str>,
    identifier_source: bool,
) -> String {
    let mut text = if identifier_source {
        format_identifier_component(source)
    } else if relation_source_regex().is_match(source) {
        source.to_string()
    } else {
        format!("'{}'", source.replace('\'', "''"))
    };
    if let Some(facet) = facet {
        text += &format!(" OF {}", format_identifier_component(facet));
    }
    if let Some(alias) = alias {
        text += &format!(" AS {}", format_identifier_component(alias));
    }
    text
}

fn indent(text: &str, spaces: usize) -> String {
    let prefix = " ".repeat(spaces);
    text.split('\n')
        .map(|line| format!("{prefix}{line}"))
        .collect::<Vec<_>>()
        .join("\n")
}

/// Render one physical, CTE or derived relation reference.
pub fn format_relation_reference(
    relation: &RelationReference,
    identifier_sources: &std::collections::HashSet<String>,
) -> String {
    if let Some(derived) = &relation.derived {
        let body = format_query(&derived.query, identifier_sources);
        let mut text = format!("(\n{}\n)", indent(&body, 2));
        if let Some(alias) = &relation.alias {
            text += &format!(" AS {}", format_identifier_component(alias));
        }
        return text;
    }
    match &relation.source {
        Some(source) => format_relation_source(
            source,
            relation.facet.as_deref(),
            relation.alias.as_deref(),
            identifier_sources.contains(source),
        ),
        // Python asserts here; keep a stable rendering instead of panicking.
        None => "NULL".to_string(),
    }
}

/// Render one JOIN edge using the canonical relational layout.
pub fn format_join_lines(
    join: &JoinClause,
    identifier_sources: &std::collections::HashSet<String>,
) -> Vec<String> {
    let keyword = if join.kind.as_str() == "INNER" {
        "JOIN".to_string()
    } else {
        format!("{} JOIN", join.kind.as_str())
    };
    let relation = format_relation_reference(&join.relation, identifier_sources);
    vec![
        format!("{keyword} {relation}"),
        format!("  ON {}", format_expression(&join.predicate)),
    ]
}

/// Render one SELECT term without adding a redundant semantic-name alias.
pub fn format_select_term(term: &SelectTerm) -> String {
    let field_text = &term.field;
    let implicit_name = match term.expression.as_deref() {
        Some(Expr::Field(field)) => field.name.clone(),
        _ => term.field.clone(),
    };
    if let Some(alias) = &term.alias
        && alias != &implicit_name
    {
        return format!("{} AS {}", field_text, format_identifier_component(alias));
    }
    field_text.clone()
}

/// Render a query in deterministic canonical yt-sql form.
pub fn format_query(
    query: &Query,
    _identifier_sources: &std::collections::HashSet<String>,
) -> String {
    let mut local_identifier_sources = _identifier_sources.clone();
    for cte in &query.ctes {
        local_identifier_sources.insert(cte.name.clone());
    }
    let facet_expansions: Vec<&crate::model::SetOperation> = query
        .set_operations
        .iter()
        .filter(|operation| operation.facet_expansion)
        .collect();
    let set_operations: Vec<&crate::model::SetOperation> = query
        .set_operations
        .iter()
        .filter(|operation| !operation.facet_expansion)
        .collect();
    let multiline = !query.ctes.is_empty()
        || !query.joins.is_empty()
        || !set_operations.is_empty()
        || query.left_query.is_some();
    let mut parts: Vec<String> = Vec::new();

    if !query.ctes.is_empty() {
        let mut cte_blocks: Vec<String> = Vec::new();
        for cte in &query.ctes {
            let body = format_query(&cte.query, &local_identifier_sources);
            cte_blocks.push(format!(
                "{} AS (\n{}\n)",
                format_identifier_component(&cte.name),
                indent(&body, 2)
            ));
        }
        parts.push("WITH ".to_string() + &cte_blocks.join(",\n"));
    }

    if let Some(left_query) = &query.left_query {
        let left = format_query(left_query, &local_identifier_sources);
        parts.push(format!("(\n{}\n)", indent(&left, 2)));
    } else if !query.select.is_empty() {
        let terms = query
            .select
            .iter()
            .map(format_select_term)
            .collect::<Vec<_>>()
            .join(", ");
        parts.push(format!(
            "{}{}",
            if query.distinct {
                "SELECT DISTINCT "
            } else {
                "SELECT "
            },
            terms
        ));
    }

    let render_from_source = |from_source: &str| -> String {
        if !facet_expansions.is_empty() {
            let mut text = format_relation_source(
                from_source,
                None,
                None,
                local_identifier_sources.contains(from_source),
            );
            let mut facets: Vec<Option<&str>> = vec![query.from_facet.as_deref()];
            for operation in &facet_expansions {
                facets.push(operation.query.from_facet.as_deref());
            }
            let rendered = facets
                .iter()
                .flatten()
                .map(|facet| format_identifier_component(facet))
                .collect::<Vec<_>>()
                .join(", ");
            text += &format!(" OF {rendered}");
            if let Some(from_alias) = &query.from_alias {
                text += &format!(" AS {}", format_identifier_component(from_alias));
            }
            text
        } else {
            format_relation_source(
                from_source,
                query.from_facet.as_deref(),
                query.from_alias.as_deref(),
                local_identifier_sources.contains(from_source),
            )
        }
    };

    if let Some(from_relation) = &query.from_relation {
        if from_relation.derived.is_some() {
            let source_text = format_relation_reference(from_relation, &local_identifier_sources);
            parts.push(format!("FROM {source_text}"));
            for join in &query.joins {
                parts.extend(format_join_lines(join, &local_identifier_sources));
            }
        } else if let Some(from_source) = &query.from_source {
            let source_text = render_from_source(from_source);
            parts.push(format!("FROM {source_text}"));
            for join in &query.joins {
                parts.extend(format_join_lines(join, &local_identifier_sources));
            }
        }
    } else if let Some(from_source) = &query.from_source {
        let source_text = render_from_source(from_source);
        parts.push(format!("FROM {source_text}"));
        for join in &query.joins {
            parts.extend(format_join_lines(join, &local_identifier_sources));
        }
    }

    if let Some(predicate) = &query.predicate {
        parts.push(format!("WHERE {}", format_expression(predicate)));
    }
    if !query.group_by.is_empty() {
        parts.push(format!(
            "GROUP BY {}",
            query
                .group_by
                .iter()
                .map(format_scalar_expression)
                .collect::<Vec<_>>()
                .join(", ")
        ));
    }
    if let Some(having) = &query.having {
        parts.push(format!("HAVING {}", format_expression(having)));
    }

    for operation in &set_operations {
        parts.push(if operation.all {
            "UNION ALL".to_string()
        } else {
            "UNION".to_string()
        });
        let branch = format_query(&operation.query, &local_identifier_sources);
        if operation.grouped {
            parts.push(format!("(\n{}\n)", indent(&branch, 2)));
        } else {
            parts.push(branch);
        }
    }

    if !query.order_by.is_empty() {
        parts.push(format!(
            "ORDER BY {}",
            query
                .order_by
                .iter()
                .map(|term| format!(
                    "{} {}",
                    term.field,
                    if term.descending { "DESC" } else { "ASC" }
                ))
                .collect::<Vec<_>>()
                .join(", ")
        ));
    }
    if let Some(limit) = query.limit {
        parts.push(format!(
            "LIMIT {}",
            query
                .limit_literal
                .clone()
                .unwrap_or_else(|| limit.to_string())
        ));
    }
    if query.offset != 0 || query.offset_literal.is_some() {
        parts.push(format!(
            "OFFSET {}",
            query
                .offset_literal
                .clone()
                .unwrap_or_else(|| query.offset.to_string())
        ));
    }

    if parts.is_empty() {
        return "<no projection, source, filtering, ordering, or limit>".to_string();
    }
    if multiline {
        parts.join("\n")
    } else {
        parts.join(" ")
    }
}

/// Relation-field helper retained for parity with the Python module surface.
pub fn format_relation_field(field: &RelationField) -> String {
    format!(
        "{}.{}",
        format_identifier_component(&field.qualifier),
        format_identifier(&field.name)
    )
}
