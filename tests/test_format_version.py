from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from contract_core.compile.odcs import validate_odcs
from contract_core.contract import Contract
from contract_core.errors import ContractFormatError
from contract_core.schema import Schema
from contract_core.types import CURRENT_FORMAT_VERSION, READABLE_FORMAT_VERSIONS

VALID_SCHEMA = {
    "schema": "peec.prompts_export", "version": "2.0.0", "kind": "tabular",
    "fields": [{"name": "sentiment", "type": "float", "minimum": -1.0, "maximum": 1.0}],
}


def _write(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "s.yaml"
    p.write_text(yaml.safe_dump(data))
    return p


# ---- Control A: strict keys (criteria 1, 2, 3, 4) ----

def test_unknown_key_on_a_schema_is_refused_not_dropped(tmp_path):
    # Criterion 1: §1 as a literal test — a future-format key does NOT validate a weaker form.
    p = _write(tmp_path, {**VALID_SCHEMA, "fields": [
        {"name": "x", "type": "int", "future_key": 42}]})
    with pytest.raises(ContractFormatError):
        Schema.from_yaml(p)


def test_a_realistic_typo_is_rejected(tmp_path):
    # Criterion 3: `requird` no longer silently defaults `required`.
    p = _write(tmp_path, {**VALID_SCHEMA, "fields": [
        {"name": "x", "type": "int", "requird": True}]})
    with pytest.raises(ContractFormatError):
        Schema.from_yaml(p)


def test_every_extra_key_is_reported_not_just_the_first(tmp_path):
    # Criterion 4: two unknown keys -> two entries in `.errors`.
    p = _write(tmp_path, {**VALID_SCHEMA, "fields": [
        {"name": "x", "type": "int", "a1": 1, "a2": 2}]})
    with pytest.raises(ContractFormatError) as ei:
        Schema.from_yaml(p)
    locs = {loc for loc, _ in ei.value.errors}
    assert any("a1" in loc for loc in locs)
    assert any("a2" in loc for loc in locs)


def test_each_model_rejects_an_unknown_key_at_its_own_level(tmp_path):
    # Criterion 2: top-level Schema, and BoundarySpec inside a Contract.
    ps = _write(tmp_path, {**VALID_SCHEMA, "surprise": 1})
    with pytest.raises(ContractFormatError):
        Schema.from_yaml(ps)
    pc = tmp_path / "c.yaml"
    pc.write_text(yaml.safe_dump({
        "system": "x", "version": "1.0.0",
        "inputs": [{"name": "b", "schema": "a.b@1", "surprise": 1}]}))
    with pytest.raises(ContractFormatError):
        Contract.from_yaml(pc)


# ---- Control B: format_version (criteria 5, 6) ----

def test_missing_format_version_defaults_to_v1(tmp_path):
    p = _write(tmp_path, VALID_SCHEMA)  # no format_version key
    s = Schema.from_yaml(p)
    assert s.format_version == CURRENT_FORMAT_VERSION


def test_explicit_v1_parses(tmp_path):
    p = _write(tmp_path, {"format_version": "v1", **VALID_SCHEMA})
    assert Schema.from_yaml(p).format_version == "v1"


def test_unreadable_version_through_from_yaml_is_refused_naming_found_and_supported(tmp_path):
    # Criterion 5 (dispatcher half): v2 is not in READABLE today.
    assert "v2" not in READABLE_FORMAT_VERSIONS
    p = _write(tmp_path, {"format_version": "v2", **VALID_SCHEMA})
    with pytest.raises(ContractFormatError) as ei:
        Schema.from_yaml(p)
    text = str(ei.value)
    assert "v2" in text and "v1" in text


def test_direct_construction_of_a_non_current_version_raises_plain_validationerror():
    # Criterion 5 (model half) / criterion 9: direct construction is NOT wrapped.
    with pytest.raises(ValidationError):
        Schema(schema="a.b", version="1.0.0", kind="tabular",
               fields=[{"name": "x", "type": "int"}], format_version="v2")


def test_from_yaml_never_leaks_a_yaml_error(tmp_path):
    # Criterion 6: a syntax error becomes ContractFormatError, not yaml.YAMLError.
    p = tmp_path / "s.yaml"
    p.write_text("kind: tabular\n  bad: indent")
    with pytest.raises(ContractFormatError):
        Schema.from_yaml(p)
    # And it is catchable as ValueError (criterion 7, boundary side).
    try:
        Schema.from_yaml(p)
    except ValueError:
        pass


# ---- criterion 9: applicability errors stay unwrapped on direct construction ----

def test_applicability_error_on_direct_field_construction_is_unwrapped():
    from contract_core.types import Field
    with pytest.raises(ValidationError):
        Field(name="brand", type="string", minimum=1)


# ---- criterion 13: format_version never reaches the ODCS export ----

def test_format_version_is_not_a_valid_odcs_key():
    # The vendored ODCS schema forbids extra top-level keys; a leak fails validation.
    doc = {"apiVersion": "v3.1.0", "kind": "DataContract", "id": "x", "name": "x",
           "version": "1.0.0", "status": "active", "schema": []}
    validate_odcs(doc)  # clean
    import jsonschema
    with pytest.raises(jsonschema.ValidationError):
        validate_odcs(doc | {"format_version": "v1"})
