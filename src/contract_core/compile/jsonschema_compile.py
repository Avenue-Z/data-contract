# src/contract_core/compile/jsonschema_compile.py
from contract_core.schema import Schema
from contract_core.types import JSON_SCHEMA_TYPE


def _field_schema(field_type: str, nullable: bool) -> dict:
    base = dict(JSON_SCHEMA_TYPE[field_type])
    if nullable:
        t = base["type"]
        base["type"] = [t, "null"]
    return base


def to_json_schema(schema: Schema, *, open: bool) -> dict:
    if schema.json_schema is not None:
        return schema.json_schema
    props = {f.name: _field_schema(f.type, f.nullable) for f in schema.fields}
    required = [f.name for f in schema.fields if f.required]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": props,
        "required": required,
        "additionalProperties": bool(open),
    }
