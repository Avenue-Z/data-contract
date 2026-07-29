# src/contract_core/compile/odcs.py
import json
from importlib import resources
from typing import Any

import jsonschema

from contract_core.contract import Contract
from contract_core.resolver import Resolver
from contract_core.schema import Schema
from contract_core.types import Field

_ODCS_LOGICAL = {
    "string": "string", "int": "integer", "float": "number",
    # ODCS v3.1's logicalType enum carries a distinct `timestamp`, so collapsing `datetime`
    # onto `date` was our loss, not the standard's: it dropped the time component and left a
    # consumer unable to tell the two apart.
    "bool": "boolean", "date": "date", "datetime": "timestamp",
}

# JSON Schema `type` -> ODCS logicalType, for a payload authored as a raw `json_schema`.
# `date`/`date-time` are carried by `format`, not `type`, so they are resolved separately.
_ODCS_FROM_JSON_TYPE = {
    "string": "string", "integer": "integer", "number": "number",
    "boolean": "boolean", "array": "array", "object": "object",
}
_ODCS_FROM_JSON_FORMAT = {"date": "date", "date-time": "timestamp"}

# `logicalTypeOptions` is validated by an if/then chain keyed on logicalType, with
# additionalProperties: false on every branch — and there is NO boolean branch, so options
# on a boolean field validate vacuously. Only emit the key for a type that has a branch
# (design §5.4).
_TYPES_WITH_OPTIONS = {"string", "integer", "number", "date"}


def _logical_type_options(f: Field) -> dict[str, Any]:
    opts: dict[str, Any] = {}
    if f.minimum is not None:
        opts["minimum"] = f.minimum
    if f.maximum is not None:
        opts["maximum"] = f.maximum
    if f.min_length is not None:
        opts["minLength"] = f.min_length
    return opts


def _quality_rules(f: Field) -> list[dict[str, Any]]:
    """ODCS's home for an allowed-value set and for null tolerance (design §5.4.1/§5.4.2).

    `metric` is required by DataQualityLibrary, and the operator (`mustBe`) comes from a
    `oneOf` in DataQualityOperators — so `mustBe: 0` is load-bearing, not decoration.
    """
    rules: list[dict[str, Any]] = []
    if f.enum is not None:
        # Append None for a nullable field, exactly as the JSON Schema compiler does:
        # `nullValues` and `invalidValues` are separate ODCS metrics, so whether
        # invalidValues counts nulls is engine-defined.
        valid = [*f.enum, None] if f.nullable else list(f.enum)
        rules.append({"type": "library", "metric": "invalidValues",
                      "arguments": {"validValues": valid}, "mustBe": 0})
    if not f.nullable:
        # ODCS `required` is documented as null semantics, not presence, and its polarity
        # is ambiguous in the vendored text — so null tolerance is expressed here, where
        # the metric name says what it means (design §5.4.2).
        rules.append({"type": "library", "metric": "nullValues", "mustBe": 0})
    return rules


def _raw_logical_type(subschema: dict[str, Any]) -> str | None:
    """The ODCS logicalType for one raw JSON Schema property, or None if it declares no type.

    `logicalType` is optional in ODCS (only `name` is required on a property), so a property
    the author left untyped is exported without one. Guessing `string` would assert a type
    the raw schema never claimed.

    A union type (`["number", "null"]`, how a raw schema spells nullable) exports as its
    single non-null member; anything more genuinely has no one logicalType.
    """
    fmt = subschema.get("format")
    if isinstance(fmt, str) and fmt in _ODCS_FROM_JSON_FORMAT:
        return _ODCS_FROM_JSON_FORMAT[fmt]
    declared = subschema.get("type")
    if isinstance(declared, list):
        non_null = [t for t in declared if t != "null"]
        declared = non_null[0] if len(non_null) == 1 else None
    return _ODCS_FROM_JSON_TYPE.get(declared) if isinstance(declared, str) else None


def _raw_schema_props(json_schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Translate a raw `json_schema` payload's `properties` into ODCS properties.

    Without this a raw-`json_schema` payload exported as a named table with no properties:
    the whole shape dropped from the ODCS document, while `lint` (to_odcs + validate_odcs)
    still passed on the hollow block. Shape only — value constraints authored inside a raw
    schema are not translated, because they have no declared-type context to validate
    against the way an authored `Field` does.
    """
    properties = json_schema.get("properties")
    if not isinstance(properties, dict):
        return []
    props: list[dict[str, Any]] = []
    for pname, subschema in properties.items():
        prop: dict[str, Any] = {"name": str(pname)}
        logical = _raw_logical_type(subschema) if isinstance(subschema, dict) else None
        if logical is not None:
            prop["logicalType"] = logical
        props.append(prop)
    return props


def _schema_block(name: str, resolved: Schema) -> dict[str, Any]:
    props: list[dict[str, Any]] = []
    if resolved.json_schema is not None:
        props = _raw_schema_props(resolved.json_schema)
    elif resolved.fields is not None:
        for f in resolved.fields:
            logical = _ODCS_LOGICAL[f.type]
            # `required` is deliberately NOT emitted: the ODCS slot is a null flag, not a
            # presence flag, so this project's `required` does not belong in it. Presence
            # has no unambiguous ODCS slot and is not exported (design §5.4.2).
            prop: dict[str, Any] = {"name": f.name, "logicalType": logical}
            opts = _logical_type_options(f)
            if opts and logical in _TYPES_WITH_OPTIONS:
                prop["logicalTypeOptions"] = opts
            rules = _quality_rules(f)
            if rules:
                prop["quality"] = rules
            props.append(prop)
    return {"name": name, "physicalType": "table", "properties": props}


def to_odcs(contract: Contract, resolver: Resolver) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    for group in (contract.raw, contract.inputs, contract.outputs):
        for b in group:
            resolved = resolver.resolve(b.schema_ref)
            blocks.append(_schema_block(b.name, resolved))
    return {
        "apiVersion": "v3.1.0",
        "kind": "DataContract",
        "id": contract.system,
        "name": contract.system,
        "version": contract.version,
        "status": "active",
        "schema": blocks,
    }


def _load_odcs_schema() -> dict[str, Any]:
    text = (
        resources.files("contract_core.vendor")
        .joinpath("odcs-json-schema-v3.1.0-20260505.json")
        .read_text()
    )
    data: dict[str, Any] = json.loads(text)
    return data


def validate_odcs(doc: dict[str, Any]) -> None:
    jsonschema.validate(instance=doc, schema=_load_odcs_schema())
