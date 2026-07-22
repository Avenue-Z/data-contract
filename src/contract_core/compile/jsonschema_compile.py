# src/contract_core/compile/jsonschema_compile.py
from typing import Any

from contract_core.schema import Schema
from contract_core.types import JSON_SCHEMA_TYPE, Field


def _field_schema(field: Field) -> dict[str, Any]:
    base = dict(JSON_SCHEMA_TYPE[field.type])
    if field.nullable:
        t = base["type"]
        base["type"] = [t, "null"]
    if field.enum is not None:
        # `minimum`/`minLength` apply only to instances of their type, so null passes them
        # for free. `enum` is a flat set of permitted instances and is NOT type-scoped, so a
        # nullable field must list null explicitly or it rejects its own legal value
        # (design §5.1).
        base["enum"] = [*field.enum, None] if field.nullable else list(field.enum)
    if field.minimum is not None:
        base["minimum"] = field.minimum
    if field.maximum is not None:
        base["maximum"] = field.maximum
    if field.min_length is not None:
        base["minLength"] = field.min_length
    return base


def to_json_schema(schema: Schema, *, open: bool) -> dict[str, Any]:
    if schema.json_schema is not None:
        return schema.json_schema
    assert schema.fields is not None  # non-passthrough schema always has fields (validator)
    props = {f.name: _field_schema(f) for f in schema.fields}
    required = [f.name for f in schema.fields if f.required]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": props,
        "required": required,
        "additionalProperties": bool(open),
    }
