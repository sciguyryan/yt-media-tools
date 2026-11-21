//! Data-driven unit conversion registry shared by query-language features.
//!
//! Port of `units.py`: terminal (fixed seconds or calendar months) and derived
//! unit definitions loaded from the committed `units/*.json` files.

use serde_json::Value as Json;
use std::collections::HashMap;
use std::path::{Path, PathBuf};

pub const FIXED: &str = "fixed";
pub const CALENDAR: &str = "calendar";

/// A unit reduced to either fixed seconds or Gregorian calendar months.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ResolvedUnit {
    pub kind: &'static str,
    pub amount: f64,
}

/// One terminal or derived unit definition loaded from a data file.
#[derive(Debug, Clone)]
pub struct UnitDefinition {
    pub name: String,
    pub aliases: Vec<String>,
    pub source: PathBuf,
    pub fixed_seconds: Option<f64>,
    pub calendar_months: Option<f64>,
    pub value: Option<f64>,
    pub unit: Option<String>,
}

/// Resolve user-facing unit names through recursively defined conversion data.
#[derive(Debug, Default)]
pub struct UnitRegistry {
    definitions: HashMap<String, UnitDefinition>,
    tokens: HashMap<String, String>,
}

fn read_unit_file(path: &Path) -> Json {
    let text = std::fs::read_to_string(path)
        .unwrap_or_else(|error| panic!("unit file {:?} could not be read: {error}", path));
    let payload: Json = serde_json::from_str(&text)
        .unwrap_or_else(|error| panic!("unit file {:?} is invalid JSON: {error}", path));
    payload
}

fn parse_definition(name: &str, raw: &Json, path: &Path) -> UnitDefinition {
    let fields = raw
        .as_object()
        .unwrap_or_else(|| panic!("unit definition {name:?} must be an object"));
    let aliases = match fields.get("aliases") {
        Some(Json::Array(items)) => items
            .iter()
            .map(|item| {
                item.as_str()
                    .unwrap_or_else(|| panic!("unit definition {name:?} has a non-string alias"))
                    .to_string()
            })
            .collect(),
        None => Vec::new(),
        Some(_) => panic!("unit definition {name:?} aliases must be an array"),
    };
    let number = |key: &str| -> Option<f64> {
        match fields.get(key) {
            Some(Json::Number(value)) => value.as_f64(),
            Some(_) => panic!("unit definition {name:?} field {key:?} must be a number"),
            None => None,
        }
    };
    UnitDefinition {
        name: name.to_string(),
        aliases,
        source: path.to_path_buf(),
        fixed_seconds: number("fixed_seconds"),
        calendar_months: number("calendar_months"),
        value: number("value"),
        unit: fields
            .get("unit")
            .and_then(Json::as_str)
            .map(str::to_string),
    }
}

impl UnitRegistry {
    pub fn from_files<I: IntoIterator<Item = PathBuf>>(paths: I) -> Self {
        let mut paths: Vec<PathBuf> = paths.into_iter().collect();
        paths.sort_by_key(|path| path.as_os_str().to_os_string());
        let mut definitions: HashMap<String, UnitDefinition> = HashMap::new();
        let mut tokens: HashMap<String, String> = HashMap::new();
        let mut order: Vec<String> = Vec::new();
        for path in &paths {
            let payload = read_unit_file(path);
            let units = payload
                .get("units")
                .and_then(Json::as_object)
                .unwrap_or_else(|| {
                    panic!("unit file {:?} must contain an object named 'units'", path)
                });
            for (raw_name, raw_definition) in units {
                let name = raw_name.to_casefold();
                if let Some(previous) = definitions.get(&name) {
                    panic!(
                        "unit {raw_name:?} is defined by both {:?} and {:?}",
                        previous.source, path
                    );
                }
                let definition = parse_definition(raw_name, raw_definition, path);
                for token in std::iter::once(&definition.name).chain(definition.aliases.iter()) {
                    let token_key = token.to_casefold();
                    if let Some(previous_name) = tokens.get(&token_key) {
                        let previous = &definitions[previous_name];
                        panic!(
                            "unit token {token:?} is reused by {:?} in {:?} and {:?} in {:?}",
                            previous.name, previous.source, definition.name, path
                        );
                    }
                    tokens.insert(token_key, name.clone());
                }
                order.push(name.clone());
                definitions.insert(name.clone(), definition);
            }
        }
        let registry = Self {
            definitions,
            tokens,
        };
        for name in order {
            let _ = registry
                .resolve_name(&name, &[])
                .unwrap_or_else(|error| panic!("{error}"));
        }
        registry
    }

    pub fn resolve(&self, token: &str) -> Result<ResolvedUnit, String> {
        let normalised = token.to_casefold();
        let Some(name) = self.tokens.get(&normalised) else {
            return Err(format!("Unknown unit {token:?}."));
        };
        self.resolve_name(name, &[]).map(|unit| ResolvedUnit {
            kind: unit.kind,
            amount: unit.amount,
        })
    }

    pub fn canonical_name(&self, token: &str) -> Result<String, String> {
        let name = self
            .tokens
            .get(&token.to_casefold())
            .ok_or_else(|| format!("Unknown unit {token:?}."))?;
        Ok(self.definitions[name].name.clone())
    }

    fn resolve_name(&self, name: &str, stack: &[String]) -> Result<ResolvedUnit, String> {
        let definition = &self.definitions[name];
        if stack.iter().any(|entry| entry == name) {
            let mut chain = stack.to_vec();
            chain.push(name.to_string());
            return Err(format!(
                "Cyclic unit definition detected: {}.",
                chain.join(" -> ")
            ));
        }
        let terminal_count = usize::from(definition.fixed_seconds.is_some())
            + usize::from(definition.calendar_months.is_some());
        let derived = definition.value.is_some() || definition.unit.is_some();
        let resolved = if terminal_count == 1 && !derived {
            if let Some(seconds) = definition.fixed_seconds {
                ResolvedUnit {
                    kind: FIXED,
                    amount: seconds,
                }
            } else {
                ResolvedUnit {
                    kind: CALENDAR,
                    amount: definition.calendar_months.unwrap(),
                }
            }
        } else if terminal_count == 0 && definition.value.is_some() && definition.unit.is_some() {
            let unit_text = definition.unit.clone().unwrap();
            let Some(target_name) = self.tokens.get(&unit_text.to_casefold()) else {
                let mut chain = stack.to_vec();
                chain.push(name.to_string());
                chain.push(unit_text.clone());
                return Err(format!(
                    "Unknown unit {unit_text:?} while resolving {}.",
                    chain.join(" -> ")
                ));
            };
            let mut next_stack = stack.to_vec();
            next_stack.push(name.to_string());
            let target = self.resolve_name(target_name, &next_stack)?;
            ResolvedUnit {
                kind: target.kind,
                amount: target.amount * definition.value.unwrap(),
            }
        } else {
            return Err(format!(
                "Unit {:?} in {:?} must define exactly one of 'fixed_seconds', 'calendar_months', or the pair 'value' and 'unit'.",
                definition.name, definition.source
            ));
        };
        Ok(resolved)
    }

    pub fn names(&self) -> Vec<String> {
        let mut names: Vec<String> = self
            .definitions
            .values()
            .map(|definition| definition.name.clone())
            .collect();
        names.sort();
        names
    }

    pub fn tokens(&self) -> Vec<String> {
        let mut tokens: Vec<String> = self.tokens.keys().cloned().collect();
        tokens.sort();
        tokens
    }
}

pub fn default_units_directory() -> PathBuf {
    // The crate lives at <repo>/rust/crates/yt-sql/src; the unit files are at
    // <repo>/units.
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .expect("crate manifest must sit inside the repository")
        .join("units")
}

/// Load every JSON unit file from the default unit-definition directory.
pub fn load_default_unit_registry() -> UnitRegistry {
    let directory = default_units_directory();
    let entries = std::fs::read_dir(&directory).unwrap_or_else(|error| {
        panic!(
            "unit definition directory {:?} unavailable: {error}",
            directory
        )
    });
    let paths: Vec<PathBuf> = entries
        .flatten()
        .map(|entry| entry.path())
        .filter(|path| path.extension().and_then(|extension| extension.to_str()) == Some("json"))
        .collect();
    if paths.is_empty() {
        panic!("No unit definition files were found in {:?}.", directory);
    }
    UnitRegistry::from_files(paths)
}

trait CaseFold {
    fn to_casefold(&self) -> String;
}

impl CaseFold for str {
    /// Conservative ASCII-oriented case folding; the corpus unit tokens are
    /// ASCII, and full Unicode case folding is only needed for text predicates.
    fn to_casefold(&self) -> String {
        self.to_lowercase()
    }
}
