# src/contract_core/compile/odcs.py
import json
from importlib import resources
from typing import Any

import jsonschema

from contract_core.contract import Contract
from contract_core.resolver import Resolver
from contract_core.schema import Schema

_ODCS_LOGICAL = {
    "string": "string", "int": "integer", "float": "number",
    "bool": "boolean", "date": "date", "datetime": "date",
}


def _schema_block(name: str, resolved: Schema) -> dict[str, Any]:
    props: list[dict[str, Any]] = []
    if resolved.fields is not None:
        for f in resolved.fields:
            props.append({
                "name": f.name,
                "logicalType": _ODCS_LOGICAL[f.type],
                "required": f.required,
            })
    return {"name": name, "physicalType": "table", "properties": props}


def to_odcs(contract: Contract, resolver: Resolver) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    for group in (contract.raw, contract.inputs, contract.outputs):
        for b in group:
            resolved = resolver.resolve(b.schema)
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
