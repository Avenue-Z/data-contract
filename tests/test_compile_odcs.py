# tests/test_compile_odcs.py
from pathlib import Path

import jsonschema
import pytest

from contract_core.compile.odcs import _schema_block, to_odcs, validate_odcs
from contract_core.contract import Contract
from contract_core.resolver import Resolver
from contract_core.schema import Schema

FIX = Path(__file__).parent / "fixtures"


def test_odcs_document_is_valid_and_inlines_schemas():
    contract = Contract(
        system="demo", version="1.0.0",
        inputs=[{"name": "prompts", "schema": "peec.prompts_export@1.0.0",
                 "source": {"kind": "file", "format": "csv"}}],
    )
    resolver = Resolver([FIX / "schemas"])
    doc = to_odcs(contract, resolver)
    assert doc["kind"] == "DataContract"
    assert doc["version"] == "1.0.0"
    # the resolved schema's fields are inlined as ODCS properties
    names = [p["name"] for s in doc["schema"] for p in s["properties"]]
    assert "prompt" in names
    validate_odcs(doc)  # must not raise


def test_validate_odcs_rejects_malformed():
    with pytest.raises(jsonschema.ValidationError):
        validate_odcs({"not": "an odcs document"})


# ---- value constraints (design §5.4) ----

def _block(**field_kwargs):
    s = Schema(schema="t", version="1.0.0", kind="tabular",
               fields=[{"name": "f", **field_kwargs}])
    return _schema_block("b", s)["properties"][0]


def _doc(block_prop):
    return {"apiVersion": "v3.1.0", "kind": "DataContract", "id": "x", "name": "x",
            "version": "1.0.0", "status": "active",
            "schema": [{"name": "b", "physicalType": "table", "properties": [block_prop]}]}


def test_bounds_go_to_logical_type_options():
    p = _block(type="float", minimum=-1.0, maximum=1.0)
    assert p["logicalTypeOptions"] == {"minimum": -1.0, "maximum": 1.0}
    validate_odcs(_doc(p))


def test_min_length_goes_to_logical_type_options():
    p = _block(type="string", min_length=1)
    assert p["logicalTypeOptions"] == {"minLength": 1}
    validate_odcs(_doc(p))


def test_enum_goes_to_a_quality_rule_not_logical_type_options():
    # Design §5.4.1: ODCS has no `enum` option. Emitting one FAILS validation on
    # string/integer/number and passes vacuously on boolean.
    p = _block(type="int", enum=[0, 1])
    assert "logicalTypeOptions" not in p
    # Membership, not list equality: this field is non-nullable, so `_quality_rules` also
    # emits the `nullValues` rule that test_non_nullable_field_emits_a_null_values_rule
    # requires. The claim under test is where `enum` lands, not how long the list is.
    assert {"type": "library", "metric": "invalidValues",
            "arguments": {"validValues": [0, 1]}, "mustBe": 0} in p["quality"]
    validate_odcs(_doc(p))


def test_a_nullable_enum_lists_null_among_the_valid_values():
    # The ODCS analogue of the JSON Schema fix (§5.1): `nullValues` and `invalidValues`
    # are separate metrics, so whether invalidValues counts nulls is engine-defined.
    p = _block(type="int", enum=[0, 1], nullable=True)
    assert p["quality"][0]["arguments"]["validValues"] == [0, 1, None]
    validate_odcs(_doc(p))


def test_non_nullable_field_emits_a_null_values_rule():
    p = _block(type="float", nullable=False)
    assert {"type": "library", "metric": "nullValues", "mustBe": 0} in p["quality"]
    validate_odcs(_doc(p))


def test_nullable_field_emits_no_null_values_rule():
    p = _block(type="float", nullable=True)
    assert not any(q.get("metric") == "nullValues" for q in p.get("quality", []))


def test_presence_is_not_exported_as_odcs_required():
    # ODCS `required` is null semantics, not presence (§5.4.2). Emitting our presence flag
    # there asserts the opposite of what the schema says about nulls.
    assert "required" not in _block(type="float", nullable=True)
    assert "required" not in _block(type="float", required=False)


def test_no_logical_type_options_for_a_type_with_no_odcs_branch():
    # Regression guard (§5.4, criterion 16): no authorable schema reaches this today,
    # because enum routes to quality and bounds are confined to int/float/string. It
    # catches a future re-route of enum into logicalTypeOptions, where boolean would pass
    # vacuously — {"totally_made_up": "x"} on a boolean field also validates.
    assert "logicalTypeOptions" not in _block(type="bool", enum=[True, False])


def test_a_schema_with_all_four_constraints_compiles_to_valid_odcs():
    s = Schema(schema="t", version="2.0.0", kind="tabular", fields=[
        {"name": "sentiment", "type": "float", "nullable": True,
         "minimum": -1.0, "maximum": 1.0},
        {"name": "rank", "type": "int", "minimum": 1},
        {"name": "brand", "type": "string", "min_length": 1},
        {"name": "is_owned", "type": "int", "enum": [0, 1]},
    ])
    block = _schema_block("prompts", s)
    validate_odcs({"apiVersion": "v3.1.0", "kind": "DataContract", "id": "x", "name": "x",
                   "version": "1.0.0", "status": "active", "schema": [block]})


def test_datetime_exports_as_timestamp_not_date():
    # ODCS v3.1's logicalType enum has a distinct `timestamp`; mapping `datetime` to `date`
    # dropped the time component and left a consumer unable to tell the two types apart.
    assert _block(type="date")["logicalType"] == "date"
    assert _block(type="datetime")["logicalType"] == "timestamp"
    validate_odcs(_doc(_block(type="datetime")))


# ---- raw `json_schema` payloads (F6) ----

def _raw_payload():
    return Schema(schema="x.raw", version="1.0.0", kind="payload", json_schema={
        "type": "object",
        "properties": {
            "slug": {"type": "string"},
            "score": {"type": "number"},
            "day": {"type": "string", "format": "date"},
            "at": {"type": "string", "format": "date-time"},
            "ok": {"type": "boolean"},
            "count": {"type": "integer"},
            "tags": {"type": "array"},
            "meta": {"type": "object"},
            "nullable_score": {"type": ["number", "null"]},
            "untyped": {},
        },
        "required": ["slug"],
    })


def test_json_schema_payload_exports_its_shape_to_odcs():
    # `_schema_block` walked only `resolved.fields`, so a raw-json_schema payload exported
    # as a named table with NO properties — the whole shape silently dropped, and `lint`
    # (to_odcs + validate_odcs) still passed on the hollow block.
    props = _schema_block("raw_out", _raw_payload())["properties"]
    assert [(p["name"], p.get("logicalType")) for p in props] == [
        ("slug", "string"), ("score", "number"), ("day", "date"), ("at", "timestamp"),
        ("ok", "boolean"), ("count", "integer"), ("tags", "array"), ("meta", "object"),
        ("nullable_score", "number"),
        # `logicalType` is optional in ODCS. A raw schema that declares no type has no type
        # to export, and guessing `string` would assert something the author did not.
        ("untyped", None),
    ]
    validate_odcs(_doc_blocks([_schema_block("raw_out", _raw_payload())]))


def test_json_schema_payload_without_properties_exports_an_empty_block():
    # A raw schema that pins no `properties` (e.g. a bare `{"type": "object"}`) has no shape
    # to translate. An empty property list is the honest export, and stays ODCS-valid.
    s = Schema(schema="x.bare", version="1.0.0", kind="payload",
               json_schema={"type": "object"})
    block = _schema_block("bare", s)
    assert block["properties"] == []
    validate_odcs(_doc_blocks([block]))


def _doc_blocks(blocks):
    return {"apiVersion": "v3.1.0", "kind": "DataContract", "id": "x", "name": "x",
            "version": "1.0.0", "status": "active", "schema": blocks}


def test_a_legacy_unconstrained_schema_has_a_pinned_odcs_shape():
    # The ODCS export changed for schemas that did NOT change. peec.prompts_export@1.0.0
    # declares zero constraints and was untouched by the value-constraints work, yet every
    # property lost `required` and every non-nullable one grew a `nullValues` rule. A
    # downstream consumer diffing ODCS documents sees churn on schemas nobody edited.
    # Pinned here so the next change to this export is a deliberate one.
    legacy = Schema.from_yaml(FIX / "schemas" / "peec" / "prompts_export" / "1.0.0.yaml")
    props = _schema_block("prompts", legacy)["properties"]
    assert props == [
        {"name": "prompt", "logicalType": "string",
         "quality": [{"type": "library", "metric": "nullValues", "mustBe": 0}]},
        {"name": "sentiment", "logicalType": "number"},
        {"name": "position", "logicalType": "integer"},
        {"name": "share_of_voice", "logicalType": "number"},
    ]
    # `sentiment` is `required: true, nullable: true` and emits neither fact: null
    # tolerance is true so no rule fires, and presence has no ODCS slot (§5.4.2).
    # That information loss is deliberate, and documented for consumers.
    validate_odcs({"apiVersion": "v3.1.0", "kind": "DataContract", "id": "x", "name": "x",
                   "version": "1.0.0", "status": "active",
                   "schema": [_schema_block("prompts", legacy)]})
