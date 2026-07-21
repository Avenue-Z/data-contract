# tests/test_compile_jsonschema.py
from contract_core.compile.jsonschema_compile import to_json_schema
from contract_core.schema import Schema


def _payload():
    return Schema.model_validate({
        "schema": "aivx.report", "version": "1.0.0", "kind": "payload",
        "fields": [
            {"name": "slug", "type": "string", "required": True},
            {"name": "score", "type": "float", "required": True, "nullable": True},
        ],
    })


def test_open_payload_allows_additional_properties():
    js = to_json_schema(_payload(), open=True)
    assert js["additionalProperties"] is True
    assert js["required"] == ["slug", "score"]
    assert js["properties"]["slug"] == {"type": "string"}
    assert js["properties"]["score"] == {"type": ["number", "null"]}


def test_closed_payload_forbids_additional_properties():
    js = to_json_schema(_payload(), open=False)
    assert js["additionalProperties"] is False


def test_passthrough_returns_authored_json_schema():
    authored = {"type": "object", "properties": {"a": {"type": "string"}}}
    s = Schema.model_validate({
        "schema": "x.y", "version": "1.0.0", "kind": "payload",
        "json_schema": authored,
    })
    assert to_json_schema(s, open=True) == authored
