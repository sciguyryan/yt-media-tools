"""Data-driven unit conversion registry shared by query-language features."""

from __future__ import annotations

import json
from functools import cache
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal


UnitKind = Literal["fixed", "calendar"]
UNIT_FILE_FORMAT = 1


@dataclass(frozen=True)
class ResolvedUnit:
    """A unit reduced to either fixed seconds or Gregorian calendar months."""

    kind: UnitKind
    amount: float


@dataclass(frozen=True)
class UnitDefinition:
    """One terminal or derived unit definition loaded from a data file."""

    name: str
    aliases: tuple[str, ...]
    source: Path
    fixed_seconds: float | None = None
    calendar_months: float | None = None
    value: float | None = None
    unit: str | None = None


class UnitRegistry:
    """Resolve user-facing unit names through recursively defined conversion data."""

    def __init__(
        self,
        definitions: dict[str, UnitDefinition],
        tokens: dict[str, str],
    ) -> None:
        self._definitions = definitions
        self._tokens = tokens
        self._resolved: dict[str, ResolvedUnit] = {}

    @classmethod
    def from_files(cls, paths: Iterable[Path]) -> "UnitRegistry":
        definitions: dict[str, UnitDefinition] = {}
        tokens: dict[str, str] = {}
        for path in sorted((Path(path) for path in paths), key=lambda item: str(item)):
            payload = _read_unit_file(path)
            units = payload.get("units")
            if not isinstance(units, dict):
                raise ValueError(f"Unit file {path} must contain an object named 'units'.")
            for raw_name, raw_definition in units.items():
                if not isinstance(raw_name, str) or not raw_name.strip():
                    raise ValueError(f"Unit file {path} contains an invalid unit name.")
                name = raw_name.casefold()
                if name in definitions:
                    previous = definitions[name].source
                    raise ValueError(f"Unit {raw_name!r} is defined by both {previous} and {path}.")
                definition = _parse_definition(raw_name, raw_definition, path)
                definitions[name] = definition
                for raw_token in (definition.name, *definition.aliases):
                    token = raw_token.casefold()
                    previous_name = tokens.get(token)
                    if previous_name is not None:
                        previous = definitions[previous_name]
                        raise ValueError(
                            f"Unit token {raw_token!r} is reused by {previous.name!r} in "
                            f"{previous.source} and {definition.name!r} in {path}."
                        )
                    tokens[token] = name

        registry = cls(definitions, tokens)
        # Validate the entire graph at load time so broken user files fail clearly even
        # when the bad definition is not exercised by the first query.
        for name in definitions:
            registry.resolve(name)
        return registry

    def resolve(self, token: str) -> ResolvedUnit:
        """Resolve a unit name or alias through derived definitions to a terminal unit."""
        normalised = token.casefold()
        name = self._tokens.get(normalised)
        if name is None:
            raise ValueError(f"Unknown unit {token!r}.")
        return self._resolve_name(name, ())

    def _resolve_name(self, name: str, stack: tuple[str, ...]) -> ResolvedUnit:
        cached = self._resolved.get(name)
        if cached is not None:
            return cached
        definition = self._definitions[name]
        if name in stack:
            chain = " -> ".join((*stack, name))
            raise ValueError(f"Cyclic unit definition detected: {chain}.")

        terminal_count = sum(value is not None for value in (definition.fixed_seconds, definition.calendar_months))
        derived = definition.value is not None or definition.unit is not None
        if terminal_count == 1 and not derived:
            if definition.fixed_seconds is not None:
                resolved = ResolvedUnit("fixed", definition.fixed_seconds)
            else:
                assert definition.calendar_months is not None
                resolved = ResolvedUnit("calendar", definition.calendar_months)
        elif terminal_count == 0 and definition.value is not None and definition.unit is not None:
            target_name = self._tokens.get(definition.unit.casefold())
            if target_name is None:
                chain = " -> ".join((*stack, name, definition.unit))
                raise ValueError(f"Unknown unit {definition.unit!r} while resolving {chain}.")
            target = self._resolve_name(target_name, (*stack, name))
            resolved = ResolvedUnit(target.kind, target.amount * definition.value)
        else:
            raise ValueError(
                f"Unit {definition.name!r} in {definition.source} must define exactly one of "
                "'fixed_seconds', 'calendar_months', or the pair 'value' and 'unit'."
            )

        self._resolved[name] = resolved
        return resolved

    def names(self) -> tuple[str, ...]:
        """Return canonical unit names."""
        return tuple(sorted(definition.name for definition in self._definitions.values()))

    def tokens(self) -> tuple[str, ...]:
        """Return every accepted canonical name and alias."""
        return tuple(sorted(self._tokens))


def default_units_directory() -> Path:
    """Return the editable repository/package unit-definition directory."""
    return Path(__file__).resolve().parent.parent / "units"


@cache
def load_default_unit_registry() -> UnitRegistry:
    """Load all JSON unit files from the default unit-definition directory."""
    directory = default_units_directory()
    if not directory.is_dir():
        raise ValueError(f"Unit definition directory not found: {directory}.")
    paths = list(directory.glob("*.json"))
    if not paths:
        raise ValueError(f"No unit definition files were found in {directory}.")
    return UnitRegistry.from_files(paths)


def _read_unit_file(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not load unit file {path}: {exc}.") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Unit file {path} must contain a JSON object.")
    if payload.get("format") != UNIT_FILE_FORMAT:
        raise ValueError(
            f"Unit file {path} has unsupported format {payload.get('format')!r}; expected {UNIT_FILE_FORMAT}."
        )
    return payload


def _parse_definition(name: str, raw: object, path: Path) -> UnitDefinition:
    if not isinstance(raw, dict):
        raise ValueError(f"Unit {name!r} in {path} must be a JSON object.")

    allowed = {"aliases", "fixed_seconds", "calendar_months", "value", "unit"}
    unknown = set(raw) - allowed
    if unknown:
        joined = ", ".join(sorted(unknown))
        raise ValueError(f"Unit {name!r} in {path} contains unknown keys: {joined}.")

    aliases_raw = raw.get("aliases", [])
    if not isinstance(aliases_raw, list) or any(
        not isinstance(alias, str) or not alias.strip() for alias in aliases_raw
    ):
        raise ValueError(f"Unit {name!r} in {path} requires 'aliases' to be a list of non-empty strings.")
    aliases = tuple(alias.strip() for alias in aliases_raw)
    if len({alias.casefold() for alias in aliases}) != len(aliases):
        raise ValueError(f"Unit {name!r} in {path} contains duplicate aliases.")
    if name.casefold() in {alias.casefold() for alias in aliases}:
        raise ValueError(f"Unit {name!r} in {path} repeats its canonical name as an alias.")

    def number(key: str) -> float | None:
        value = raw.get(key)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"Unit {name!r} in {path} requires positive numeric {key!r}.")
        return float(value)

    target = raw.get("unit")
    if target is not None and (not isinstance(target, str) or not target.strip()):
        raise ValueError(f"Unit {name!r} in {path} requires a non-empty string 'unit'.")

    return UnitDefinition(
        name=name,
        aliases=aliases,
        source=path,
        fixed_seconds=number("fixed_seconds"),
        calendar_months=number("calendar_months"),
        value=number("value"),
        unit=target.strip() if isinstance(target, str) else None,
    )
