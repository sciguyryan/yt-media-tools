//! Resolved yt-sql type declarations shared by semantic layers.
//!
//! Port of `query_types.py`: scalar, collection and structured value kinds with
//! per-node NULLability, collection ordering contracts and structured schemas.

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StructuredShape {
    Opaque,
    Declared,
    Dynamic,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CollectionOrdering {
    Stable,
    Unordered,
    Unknown,
}

#[derive(Debug, Clone, PartialEq)]
pub struct StructuredMember {
    pub name: String,
    pub value_type: QueryType,
}

#[derive(Debug, Clone, PartialEq)]
pub struct QueryType {
    pub kind: String,
    pub nullable: bool,
    pub element_type: Option<Box<QueryType>>,
    pub ordering: Option<CollectionOrdering>,
    pub structured_shape: Option<StructuredShape>,
    pub members: Vec<StructuredMember>,
}

impl QueryType {
    fn base(kind: &str, nullable: bool) -> Self {
        Self {
            kind: kind.to_string(),
            nullable,
            element_type: None,
            ordering: None,
            structured_shape: None,
            members: Vec::new(),
        }
    }

    pub fn scalar(kind: &str, nullable: bool) -> Self {
        Self::base(kind, nullable)
    }

    pub fn structured(
        members: Vec<StructuredMember>,
        nullable: bool,
        shape: StructuredShape,
    ) -> Self {
        Self {
            kind: "structured".to_string(),
            nullable,
            element_type: None,
            ordering: None,
            structured_shape: Some(shape),
            members,
        }
    }

    pub fn structured_opaque(nullable: bool) -> Self {
        Self::structured(Vec::new(), nullable, StructuredShape::Opaque)
    }

    pub fn collection(
        element_type: QueryType,
        nullable: bool,
        ordering: CollectionOrdering,
    ) -> Self {
        Self {
            kind: "collection".to_string(),
            nullable,
            element_type: Some(Box::new(element_type)),
            ordering: Some(ordering),
            structured_shape: None,
            members: Vec::new(),
        }
    }

    pub fn is_collection(&self) -> bool {
        self.kind == "collection"
    }

    pub fn is_structured(&self) -> bool {
        self.kind == "structured"
    }

    pub fn has_declared_members(&self) -> bool {
        self.is_structured() && self.structured_shape != Some(StructuredShape::Opaque)
    }

    pub fn declared_member_type(&self, name: &str) -> Option<QueryType> {
        if !self.has_declared_members() {
            return None;
        }
        self.members
            .iter()
            .find(|member| member.name == name)
            .map(|member| member.value_type.clone())
    }

    pub fn member_result_type(&self, name: &str) -> Option<QueryType> {
        let member_type = self.declared_member_type(name)?;
        Some(member_type.with_nullable(member_type.nullable || self.nullable))
    }

    pub fn supports_positional_indexing(&self) -> bool {
        self.is_collection() && self.ordering == Some(CollectionOrdering::Stable)
    }

    pub fn with_nullable(&self, nullable: bool) -> Self {
        if self.nullable == nullable {
            return self.clone();
        }
        let mut clone = self.clone();
        clone.nullable = nullable;
        clone
    }

    pub fn indexed_result_type(&self) -> Result<QueryType, String> {
        if !self.is_collection() {
            return Err(format!("Type {} is not a collection.", self.describe()));
        }
        if !self.supports_positional_indexing() {
            return Err(
                "Positional indexing requires a stable logical collection ordering.".to_string(),
            );
        }
        Ok(self.element_type.as_ref().unwrap().with_nullable(true))
    }

    pub fn describe(&self) -> String {
        let suffix = if self.nullable { "?" } else { "" };
        if self.is_collection() {
            let element = self.element_type.as_ref().unwrap().describe();
            let ordering = match self.ordering.unwrap() {
                CollectionOrdering::Stable => "stable",
                CollectionOrdering::Unordered => "unordered",
                CollectionOrdering::Unknown => "unknown",
            };
            return format!("collection<{element}>[{ordering}]{suffix}");
        }
        if self.is_structured() {
            if self.structured_shape == Some(StructuredShape::Opaque) {
                return format!("structured{suffix}");
            }
            let member_text = self
                .members
                .iter()
                .map(|member| format!("{}:{}", member.name, member.value_type.describe()))
                .collect::<Vec<_>>()
                .join(",");
            let shape = if self.structured_shape == Some(StructuredShape::Dynamic) {
                "dynamic"
            } else {
                "declared"
            };
            return format!("structured<{shape}>{{{member_text}}}{suffix}");
        }
        format!("{}{suffix}", self.kind)
    }
}
