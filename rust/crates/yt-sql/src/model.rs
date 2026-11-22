//! Stable data model for parsed and resolved yt-sql queries.
//!
//! Field names and shapes deliberately mirror `query_model.py` so the parser,
//! resolver and evaluator port stays traceable to the Python reference.

use std::fmt;

pub const SYNTAX: &str = "syntax";
pub const LEXICAL: &str = "lexical";
pub const SEMANTIC: &str = "semantic";

/// One deterministic absolute and line/column location in query source.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SourceLocation {
    pub position: usize,
    pub line: usize,
    pub column: usize,
}

/// Half-open source span owned by yt-sql.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SourceSpan {
    pub start: SourceLocation,
    pub end: SourceLocation,
}

pub fn source_location(source: &str, position: usize) -> SourceLocation {
    let bounded = position.min(source.len());
    // Positions are byte offsets into the decoded query text.
    let prefix = &source[..bounded];
    let line = prefix.matches('\n').count() + 1;
    let line_start = prefix.rfind('\n').map(|index| index + 1).unwrap_or(0);
    let column = source[line_start..bounded].chars().count() + 1;
    SourceLocation {
        position: bounded,
        line,
        column,
    }
}

/// Parser-independent structured context for one yt-sql diagnostic.
#[derive(Debug, Clone)]
pub struct DiagnosticContext {
    pub category: String,
    pub span: SourceSpan,
    pub expected: Vec<String>,
    pub reason: String,
}

/// A diagnostic error: lexical, syntax or semantic.
#[derive(Debug, Clone)]
pub struct QueryError {
    pub kind: &'static str,
    pub message: String,
    pub position: usize,
    pub end_position: usize,
    pub context: DiagnosticContext,
}

impl QueryError {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        kind: &'static str,
        default_category: &str,
        source: &str,
        message: impl Into<String>,
        position: usize,
        end_position: Option<usize>,
        expected: &[&str],
        category: Option<&str>,
        reason: &str,
    ) -> Self {
        let position = position.min(source.len());
        let end_position = end_position
            .unwrap_or(position)
            .max(position)
            .min(source.len());
        let span = SourceSpan {
            start: source_location(source, position),
            end: source_location(source, end_position),
        };
        let mut seen = Vec::new();
        for item in expected {
            if !seen.contains(&item.to_string()) {
                seen.push(item.to_string());
            }
        }
        Self {
            kind,
            message: message.into(),
            position,
            end_position,
            context: DiagnosticContext {
                category: category.unwrap_or(default_category).to_string(),
                span,
                expected: seen,
                reason: reason.to_string(),
            },
        }
    }

    pub fn lexical(
        source: &str,
        message: impl Into<String>,
        position: usize,
        end_position: Option<usize>,
        reason: &str,
    ) -> Self {
        Self::new(
            "lexical",
            LEXICAL,
            source,
            message,
            position,
            end_position,
            &[],
            None,
            reason,
        )
    }

    pub fn syntax(
        source: &str,
        message: impl Into<String>,
        position: usize,
        end_position: Option<usize>,
        reason: &str,
    ) -> Self {
        Self::new(
            "syntax",
            SYNTAX,
            source,
            message,
            position,
            end_position,
            &[],
            None,
            reason,
        )
    }

    pub fn semantic(
        source: &str,
        message: impl Into<String>,
        position: usize,
        reason: &str,
    ) -> Self {
        Self::new(
            "semantic",
            SEMANTIC,
            source,
            message,
            position,
            None,
            &[],
            None,
            reason,
        )
    }

    /// Python's `QuerySyntaxError.format()` rendering.
    pub fn format(&self, source: &str) -> String {
        let line_start = source[..self.position]
            .rfind('\n')
            .map(|i| i + 1)
            .unwrap_or(0);
        let line_end = source[self.position..]
            .find('\n')
            .map(|i| self.position + i)
            .unwrap_or(source.len());
        let line = &source[line_start..line_end];
        let column = self.context.span.start.column.saturating_sub(1);
        format!(
            "{} (line {}, column {})\n  {}\n  {}^",
            self.message,
            self.context.span.start.line,
            self.context.span.start.column,
            line,
            " ".repeat(column)
        )
    }
}

impl fmt::Display for QueryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}", self.message)
    }
}

/// One lexical token.
#[derive(Debug, Clone, PartialEq)]
pub struct Token {
    pub kind: &'static str,
    pub text: String,
    pub position: usize,
    /// Decoded value for STRING/QIDENT tokens; otherwise the raw text.
    pub value: Option<String>,
    pub end_position: usize,
}

// Token kinds, mirroring the Python lexer's group names.
pub const TOKEN_SPACE: &str = "SPACE";
pub const TOKEN_COMMENT: &str = "COMMENT";
pub const TOKEN_INFINITY: &str = "INFINITY";
pub const TOKEN_OP: &str = "OP";
pub const TOKEN_LPAREN: &str = "LPAREN";
pub const TOKEN_LBRACKET: &str = "LBRACKET";
pub const TOKEN_RBRACKET: &str = "RBRACKET";
pub const TOKEN_DOT: &str = "DOT";
pub const TOKEN_ATIDENT: &str = "ATIDENT";
pub const TOKEN_RPAREN: &str = "RPAREN";
pub const TOKEN_QIDENT: &str = "QIDENT";
pub const TOKEN_STRING: &str = "STRING";
pub const TOKEN_TEMPORAL: &str = "TEMPORAL";
pub const TOKEN_DATETIME: &str = "DATETIME";
pub const TOKEN_DATE: &str = "DATE";
pub const TOKEN_TIME: &str = "TIME";
pub const TOKEN_LITERAL_WORD: &str = "LITERAL_WORD";
pub const TOKEN_NUMBER: &str = "NUMBER";
pub const TOKEN_IDENT: &str = "IDENT";
pub const TOKEN_COMMA: &str = "COMMA";
pub const TOKEN_STAR: &str = "STAR";
pub const TOKEN_PLUS: &str = "PLUS";
pub const TOKEN_MINUS: &str = "MINUS";
pub const TOKEN_SLASH: &str = "SLASH";
pub const TOKEN_PERCENT: &str = "PERCENT";
pub const TOKEN_MISMATCH: &str = "MISMATCH";
pub const TOKEN_EOF: &str = "EOF";

/// Scalar expression leaf: a named field of the current record.
#[derive(Debug, Clone, PartialEq)]
pub struct Field {
    pub name: String,
    pub position: usize,
    pub kind: Option<String>,
}

/// Projection wildcard owned by one explicitly aliased relation.
#[derive(Debug, Clone, PartialEq)]
pub struct RelationWildcard {
    pub qualifier: String,
    pub position: usize,
}

/// Field resolved to one relation in a multi-relation semantic scope.
#[derive(Debug, Clone, PartialEq)]
pub struct RelationField {
    pub qualifier: String,
    pub name: String,
    pub position: usize,
    pub kind: Option<String>,
    pub relation_key: Option<(String, Option<String>, Option<String>)>,
}

/// A parsed literal value: the decoded text with its raw source spelling.
#[derive(Debug, Clone, PartialEq)]
pub struct Literal {
    pub value: LiteralValue,
    pub raw: String,
    pub position: usize,
    pub quoted: bool,
}

/// The decoded literal value domain at parse time.
#[derive(Debug, Clone, PartialEq)]
pub enum LiteralValue {
    Text(String),
    Null,
    Bool(bool),
    /// Infinity sentinels are decoded during resolution.
    Raw,
}

/// Unary Boolean operator (NOT).
#[derive(Debug, Clone, PartialEq)]
pub struct Unary {
    pub operator: String,
    pub operand: Box<BoolExpr>,
}

/// Boolean binary operator (AND/OR) or row-level comparison with a literal.
#[derive(Debug, Clone, PartialEq)]
pub struct Binary {
    pub operator: String,
    pub left: Box<BoolExpr>,
    pub right: Box<BoolExpr>,
}

/// Field BETWEEN two literals.
#[derive(Debug, Clone, PartialEq)]
pub struct Between {
    pub field: Field,
    pub lower: Literal,
    pub upper: Literal,
    pub negated: bool,
}

/// Field IN a list of literals.
#[derive(Debug, Clone, PartialEq)]
pub struct InList {
    pub field: Field,
    pub values: Vec<Literal>,
    pub negated: bool,
}

/// Field IS (NOT) NULL — the optional NOT is written in prose to keep rustdoc happy.
#[derive(Debug, Clone, PartialEq)]
pub struct IsNull {
    pub field: Field,
    pub negated: bool,
}

/// CONTAINS/MATCHES/LIKE/ILIKE family over one field.
#[derive(Debug, Clone, PartialEq)]
pub struct TextPredicate {
    pub operator: String,
    pub field: Field,
    pub value: Literal,
    pub negated: bool,
}

/// Reference to a lexically bound collection element.
#[derive(Debug, Clone, PartialEq)]
pub struct CollectionElementReference {
    pub binding: String,
    pub scope_distance: usize,
    pub position: usize,
    pub kind: Option<String>,
    pub resolved_type: Option<crate::types::QueryType>,
}

/// ANY/ALL quantified predicate over a collection.
#[derive(Debug, Clone, PartialEq)]
pub struct CollectionPredicate {
    pub quantifier: String,
    pub collection: Box<Expr>,
    pub binding: String,
    pub predicate: Box<BoolExpr>,
    pub position: usize,
}

/// COUNT(collection AS b WHERE p).
#[derive(Debug, Clone, PartialEq)]
pub struct CollectionCount {
    pub collection: Box<Expr>,
    pub binding: String,
    pub predicate: Box<BoolExpr>,
    pub position: usize,
    pub kind: Option<String>,
    pub resolved_type: Option<crate::types::QueryType>,
}

/// FILTER(collection AS b WHERE p).
#[derive(Debug, Clone, PartialEq)]
pub struct CollectionFilter {
    pub collection: Box<Expr>,
    pub binding: String,
    pub predicate: Box<BoolExpr>,
    pub position: usize,
    pub kind: Option<String>,
    pub resolved_type: Option<crate::types::QueryType>,
}

/// MAP(collection AS b SELECT e).
#[derive(Debug, Clone, PartialEq)]
pub struct CollectionProjection {
    pub collection: Box<Expr>,
    pub binding: String,
    pub projection: Box<Expr>,
    pub position: usize,
    pub kind: Option<String>,
    pub resolved_type: Option<crate::types::QueryType>,
    pub evaluation_fusion_safe: bool,
}

/// Postfix positional indexing of a collection-valued expression.
#[derive(Debug, Clone, PartialEq)]
pub struct ScalarIndex {
    pub collection: Box<Expr>,
    pub index: Box<Expr>,
    pub position: usize,
    pub kind: Option<String>,
    pub resolved_type: Option<crate::types::QueryType>,
}

/// Postfix member access over a structured-valued expression.
#[derive(Debug, Clone, PartialEq)]
pub struct ScalarMember {
    pub value: Box<Expr>,
    pub member: String,
    pub position: usize,
    pub kind: Option<String>,
    pub resolved_type: Option<crate::types::QueryType>,
}

/// Scalar function call (LOWER..RANDOM).
#[derive(Debug, Clone, PartialEq)]
pub struct ScalarFunction {
    pub name: String,
    pub args: Vec<Expr>,
    pub position: usize,
    pub kind: Option<String>,
    pub resolved_type: Option<crate::types::QueryType>,
}

/// One SQL aggregate evaluated over the current group.
#[derive(Debug, Clone, PartialEq)]
pub struct AggregateFunction {
    pub name: String,
    pub args: Vec<Expr>,
    pub count_star: bool,
    pub filter_predicate: Option<Box<BoolExpr>>,
    pub position: usize,
    pub kind: Option<String>,
}

/// Scalar expression used by every scalar-valued node.
#[derive(Debug, Clone, PartialEq)]
pub enum Expr {
    Field(Field),
    RelationField(RelationField),
    Literal(Literal),
    Unary(ScalarUnary),
    Binary(ScalarBinary),
    Index(ScalarIndex),
    Member(ScalarMember),
    Case(ScalarCase),
    Function(ScalarFunction),
    Aggregate(AggregateFunction),
    Window(WindowFunction),
    CollectionElement(CollectionElementReference),
    CollectionCount(CollectionCount),
    CollectionFilter(CollectionFilter),
    CollectionProjection(CollectionProjection),
}

/// The OVER (...) definition of a window: partitioning and window-local ordering.
///
/// Both parts are optional at the grammar level because future window functions
/// give an empty or partition-only specification meaning. Whether a particular
/// window function accepts either part is resolved separately.
#[derive(Debug, Clone, PartialEq)]
pub struct WindowSpecification {
    pub partition_by: Vec<Expr>,
    pub order_by: Vec<OrderTerm>,
    pub position: usize,
    pub kind: Option<String>,
}

/// A window function evaluated over its window specification.
///
/// The function name is recorded so future window functions extend the same
/// node rather than adding an isolated ROW_NUMBER special case.
#[derive(Debug, Clone, PartialEq)]
pub struct WindowFunction {
    pub name: String,
    pub specification: WindowSpecification,
    pub position: usize,
    pub kind: Option<String>,
    pub resolved_type: Option<crate::types::QueryType>,
}

/// Comparison between scalar expressions, used by aggregate HAVING and joins.
#[derive(Debug, Clone, PartialEq)]
pub struct ScalarComparison {
    pub operator: String,
    pub left: Box<Expr>,
    pub right: Box<Expr>,
}

/// NULL test over a scalar expression, used by aggregate HAVING.
#[derive(Debug, Clone, PartialEq)]
pub struct ScalarIsNull {
    pub expression: Box<Expr>,
    pub negated: bool,
}

/// Total TRUE/FALSE inspection of a three-valued Boolean predicate.
#[derive(Debug, Clone, PartialEq)]
pub struct TruthTest {
    pub operand: Box<BoolExpr>,
    pub truth: String,
    pub negated: bool,
}

/// Unary + / - over a scalar expression.
#[derive(Debug, Clone, PartialEq)]
pub struct ScalarUnary {
    pub operator: String,
    pub operand: Box<Expr>,
    pub position: usize,
    pub kind: Option<String>,
}

/// Scalar arithmetic (+, -, *, /, %).
#[derive(Debug, Clone, PartialEq)]
pub struct ScalarBinary {
    pub operator: String,
    pub left: Box<Expr>,
    pub right: Box<Expr>,
    pub position: usize,
    pub kind: Option<String>,
}

/// One CASE WHEN branch.
#[derive(Debug, Clone, PartialEq)]
pub struct CaseWhen {
    pub condition: Box<BoolExpr>,
    pub result: Box<Expr>,
    pub position: usize,
}

/// Scalar CASE expression.
#[derive(Debug, Clone, PartialEq)]
pub struct ScalarCase {
    pub whens: Vec<CaseWhen>,
    pub else_result: Option<Box<Expr>>,
    pub position: usize,
    pub kind: Option<String>,
}

/// One ORDER BY term.
#[derive(Debug, Clone, PartialEq)]
pub struct OrderTerm {
    pub field: String,
    pub descending: bool,
    pub position: usize,
    pub kind: Option<String>,
    pub expression: Option<Box<Expr>>,
}

/// One SELECT projection term.
#[derive(Debug, Clone, PartialEq)]
pub struct SelectTerm {
    pub field: String,
    pub alias: Option<String>,
    pub position: usize,
    pub kind: Option<String>,
    pub expression: Option<Box<Expr>>,
}

impl SelectTerm {
    pub fn output_name(&self) -> &str {
        self.alias.as_deref().unwrap_or(&self.field)
    }
}

/// One non-recursive common table expression.
#[derive(Debug, Clone, PartialEq)]
pub struct CommonTableExpression {
    pub name: String,
    pub query: Box<Query>,
    pub position: usize,
}

/// One positional UNION or UNION ALL branch.
#[derive(Debug, Clone, PartialEq)]
pub struct SetOperation {
    pub query: Box<Query>,
    pub all: bool,
    pub position: usize,
    pub facet_expansion: bool,
    pub grouped: bool,
}

/// Parser-stable join kinds.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum JoinKind {
    Inner,
    Left,
    Semi,
    Anti,
}

impl JoinKind {
    pub fn as_str(&self) -> &'static str {
        match self {
            JoinKind::Inner => "INNER",
            JoinKind::Left => "LEFT",
            JoinKind::Semi => "SEMI",
            JoinKind::Anti => "ANTI",
        }
    }
}

/// One parenthesised query used as a logical relation operand.
#[derive(Debug, Clone, PartialEq)]
pub struct DerivedRelation {
    pub query: Box<Query>,
    pub position: usize,
}

/// One physical, CTE or derived relation participating in composition.
#[derive(Debug, Clone, PartialEq)]
pub struct RelationReference {
    pub source: Option<String>,
    pub facet: Option<String>,
    pub alias: Option<String>,
    pub position: usize,
    pub derived: Option<DerivedRelation>,
}

/// One parser-level JOIN edge whose executable semantics are resolved later.
#[derive(Debug, Clone, PartialEq)]
pub struct JoinClause {
    pub kind: JoinKind,
    pub relation: RelationReference,
    pub predicate: Box<BoolExpr>,
    pub position: usize,
}

/// Boolean expression domain.
#[derive(Debug, Clone, PartialEq)]
pub enum BoolExpr {
    Literal(Literal),
    Unary(Unary),
    Binary(Binary),
    Between(Between),
    InList(InList),
    IsNull(IsNull),
    TextPredicate(TextPredicate),
    TruthTest(TruthTest),
    CollectionPredicate(CollectionPredicate),
    ScalarIsNull(ScalarIsNull),
    ScalarComparison(ScalarComparison),
}

/// A whole query, before or after resolution.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct Query {
    pub predicate: Option<Box<BoolExpr>>,
    pub order_by: Vec<OrderTerm>,
    pub limit: Option<i64>,
    pub source: String,
    pub select: Vec<SelectTerm>,
    pub from_source: Option<String>,
    pub distinct: bool,
    pub offset: i64,
    pub group_by: Vec<Expr>,
    pub having: Option<Box<BoolExpr>>,
    pub ctes: Vec<CommonTableExpression>,
    pub set_operations: Vec<SetOperation>,
    pub from_facet: Option<String>,
    pub from_alias: Option<String>,
    pub joins: Vec<JoinClause>,
    pub left_query: Option<Box<Query>>,
    pub from_relation: Option<RelationReference>,
    pub limit_literal: Option<String>,
    pub offset_literal: Option<String>,
}

impl Query {
    /// Python `dataclasses.replace` for the fields used by composed execution.
    pub fn as_body(&self) -> Query {
        Query {
            predicate: self.predicate.clone(),
            order_by: Vec::new(),
            limit: None,
            source: self.source.clone(),
            select: self.select.clone(),
            from_source: self.from_source.clone(),
            distinct: false,
            offset: 0,
            group_by: self.group_by.clone(),
            having: self.having.clone(),
            ctes: Vec::new(),
            set_operations: Vec::new(),
            from_facet: self.from_facet.clone(),
            from_alias: self.from_alias.clone(),
            joins: self.joins.clone(),
            left_query: None,
            from_relation: self.from_relation.clone(),
            limit_literal: None,
            offset_literal: None,
        }
    }

    pub fn as_facet_expansion_body(&self) -> Query {
        Query {
            predicate: self.predicate.clone(),
            order_by: Vec::new(),
            limit: None,
            source: self.source.clone(),
            select: self.select.clone(),
            from_source: self.from_source.clone(),
            distinct: false,
            offset: 0,
            group_by: self.group_by.clone(),
            having: self.having.clone(),
            ctes: Vec::new(),
            set_operations: Vec::new(),
            from_facet: self.from_facet.clone(),
            from_alias: self.from_alias.clone(),
            joins: self.joins.clone(),
            left_query: None,
            from_relation: self.from_relation.clone(),
            limit_literal: None,
            offset_literal: None,
        }
    }
}
