# tests/test_compile_jsonschema.py
import pytest

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


def test_passthrough_returns_the_authored_json_schema_body():
    # The raw body is carried through as authored, never recompiled from `fields`. Since F5
    # the compiler also fills `additionalProperties` when the author left it unset — that is
    # the ONLY key it may add, which is what the exact-equality below pins.
    authored = {"type": "object", "properties": {"a": {"type": "string"}}}
    s = Schema.model_validate({
        "schema": "x.y", "version": "1.0.0", "kind": "payload",
        "json_schema": authored,
    })
    assert to_json_schema(s, open=True) == {**authored, "additionalProperties": True}


# ---- passthrough openness (F5) ----
#
# A fields-based payload gets `additionalProperties: false` on an output boundary, so an
# extra key surfaces as a warn. A raw json_schema was returned verbatim with `open` ignored,
# so two payload schemas that behave identically on inputs diverged on outputs.


def _raw(**extra):
    return Schema.model_validate({
        "schema": "x.y", "version": "1.0.0", "kind": "payload",
        "json_schema": {"type": "object",
                        "properties": {"a": {"type": "string"}}, **extra},
    })


def test_passthrough_closes_on_output_when_the_author_did_not_pin_it():
    assert to_json_schema(_raw(), open=False)["additionalProperties"] is False


def test_passthrough_opens_on_input_when_the_author_did_not_pin_it():
    assert to_json_schema(_raw(), open=True)["additionalProperties"] is True


@pytest.mark.parametrize("pinned", [True, False, {"type": "string"}])
def test_an_authored_additional_properties_wins_over_open(pinned):
    # The author of a raw schema owns its openness. `open` only fills a gap.
    s = _raw(additionalProperties=pinned)
    assert to_json_schema(s, open=True)["additionalProperties"] == pinned
    assert to_json_schema(s, open=False)["additionalProperties"] == pinned


def test_passthrough_does_not_mutate_the_authored_schema():
    s = _raw()
    to_json_schema(s, open=False)
    assert "additionalProperties" not in s.json_schema


# ---- value constraints (design §5.1) ----

def _schema(**field_kwargs):
    return Schema(schema="t", version="1.0.0", kind="tabular",
                  fields=[{"name": "f", "type": field_kwargs.pop("type", "int"),
                           **field_kwargs}])


def test_bounds_and_min_length_become_json_schema_keywords():
    js = to_json_schema(_schema(type="float", minimum=-1.0, maximum=1.0), open=True)
    assert js["properties"]["f"]["minimum"] == -1.0
    assert js["properties"]["f"]["maximum"] == 1.0

    js = to_json_schema(_schema(type="string", min_length=1), open=True)
    assert js["properties"]["f"]["minLength"] == 1


def test_enum_becomes_an_enum_keyword():
    js = to_json_schema(_schema(type="int", enum=[0, 1]), open=True)
    assert js["properties"]["f"]["enum"] == [0, 1]


def test_nullable_enum_includes_null():
    # Design §5.1: `enum` is NOT type-scoped, so a nullable field must list null or its
    # own `nullable: true` is contradicted.
    js = to_json_schema(_schema(type="int", enum=[0, 1], nullable=True), open=True)
    assert js["properties"]["f"]["enum"] == [0, 1, None]


def test_non_nullable_enum_does_not_include_null():
    js = to_json_schema(_schema(type="int", enum=[0, 1], nullable=False), open=True)
    assert None not in js["properties"]["f"]["enum"]


def test_unconstrained_field_gains_no_keywords():
    js = to_json_schema(_schema(type="int"), open=True)
    assert set(js["properties"]["f"]) == {"type"}
