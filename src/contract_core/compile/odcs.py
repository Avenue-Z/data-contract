# src/contract_core/compile/odcs.py
import json
from importlib import resources

import jsonschema

from contract_core.contract import Contract
from contract_core.resolver import Resolver
from contract_core.schema import Schema

_ODCS_LOGICAL = {
    "string": "string", "int": "integer", "float": "number",
    "bool": "boolean", "date": "date", "datetime": "date",
}


def _schema_block(name: str, resolved: Schema) -> dict:
    props = []
    if resolved.fields is not None:
        for f in resolved.fields:
            props.append({
                "name": f.name,
                "logicalType": _ODCS_LOGICAL[f.type],
                "required": f.required,
            })
    return {"name": name, "physicalType": "table", "properties": props}


def to_odcs(contract: Contract, resolver: Resolver) -> dict:
    blocks = []
    for group in (contract.raw, contract.inputs, contract.outputs):
        for b in group:  # type: BoundarySpec
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


def _load_odcs_schema() -> dict:
    text = (
        resources.files("contract_core.vendor")
        .joinpath("odcs-json-schema-v3.1.0-20260505.json")
        .read_text()
    )
    return json.loads(text)


def validate_odcs(doc: dict) -> None:
    jsonschema.validate(instance=doc, schema=_load_odcs_schema())
