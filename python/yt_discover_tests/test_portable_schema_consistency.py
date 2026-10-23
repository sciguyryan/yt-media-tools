"""Guard the shared portable typed-value schema against contract drift."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "yt-sql" / "schema"


def _schema(name: str) -> dict:
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


def test_parameter_and_result_value_schemas_are_identical() -> None:
    case = _schema("test-case.schema.json")
    expected = _schema("expected.schema.json")
    assert case["$defs"]["value"] == expected["$defs"]["value"]
    assert case["properties"]["parameters"]["additionalProperties"] == {"$ref": "#/$defs/value"}
    assert expected["properties"]["rows"]["items"]["items"] == {"$ref": "#/$defs/value"}


def test_portable_values_reject_untagged_numbers_in_both_schemas() -> None:
    value = _schema("test-case.schema.json")["$defs"]["value"]
    types = {variant.get("type") for variant in value["oneOf"]}
    assert types == {"null", "boolean", "string", "object"}
    assert all(
        variant.get("additionalProperties") is False for variant in value["oneOf"] if variant.get("type") == "object"
    )


def test_schema_value_definitions_are_local_and_closed() -> None:
    for name in ("test-case.schema.json", "expected.schema.json"):
        schema = _schema(name)
        assert schema["additionalProperties"] is False
        assert schema["$defs"]["value"]["oneOf"]
