# tests/test_errors.py
import pytest
from pydantic import ValidationError

import contract_core
from contract_core.errors import ContractFormatError, ContractViolation, FieldDiff
from contract_core.schema import Schema  # only to produce a real ValidationError


def test_violation_message_names_boundary_schema_and_field():
    exc = ContractViolation(
        boundary="peec_prompts", schema_ref="peec.prompts_export@1.0.0", direction="input",
        diffs=[FieldDiff(field="gmv", expected="float", observed="object", problem="retyped")],
    )
    msg = str(exc)
    assert "peec.prompts_export@1.0.0" in msg
    assert "input 'peec_prompts'" in msg
    assert "gmv" in msg
    assert "expected float" in msg
    assert "observed object" in msg


# ---- value-violation detail (design §6.2) ----

def test_structural_diffs_leave_the_value_fields_empty():
    d = FieldDiff(field="position", expected="int", observed="absent", problem="missing")
    assert d.constraint is None
    assert d.violating_rows is None
    assert d.samples == []


def test_a_value_diff_carries_a_typed_count_and_samples():
    # Design §6.2: a consumer must not have to regex a number out of prose.
    d = FieldDiff(field="sentiment", expected="float", observed="float64", problem="value",
                  constraint="maximum=1.0", violating_rows=3, samples=["1.4", "2.7"])
    assert d.violating_rows == 3
    assert d.samples == ["1.4", "2.7"]


def test_samples_default_is_not_shared_between_instances():
    a = FieldDiff(field="a", expected="int", observed="absent", problem="missing")
    b = FieldDiff(field="b", expected="int", observed="absent", problem="missing")
    a.samples.append("leaked")
    assert b.samples == []


def test_rendered_message_names_the_constraint_count_and_samples():
    exc = ContractViolation(
        boundary="prompts", schema_ref="peec.prompts_export@2.0.0", direction="input",
        diffs=[FieldDiff(field="sentiment", expected="float", observed="float64",
                         problem="value", constraint="maximum=1.0", violating_rows=3,
                         samples=["1.4", "2.7", "1.02"])],
    )
    msg = str(exc)
    assert "maximum=1.0" in msg
    assert "3 of" in msg or "3 rows" in msg
    assert "1.4" in msg


def test_structural_message_is_unchanged():
    exc = ContractViolation(
        boundary="prompts", schema_ref="peec.prompts_export@1.0.0", direction="input",
        diffs=[FieldDiff(field="position", expected="int", observed="absent",
                         problem="missing")],
    )
    assert str(exc) == (
        "peec.prompts_export@1.0.0 at input 'prompts': "
        "missing field 'position' expected int, observed absent"
    )


# ---- ContractFormatError (design R10, §5) ----

def test_format_error_is_a_valueerror_and_not_a_contract_violation():
    err = ContractFormatError(path="a.yaml", errors=[("x", "bad")], hint=None)
    assert isinstance(err, ValueError)
    assert not isinstance(err, ContractViolation)


def test_format_error_render_lists_every_error_and_omits_hint_when_none():
    err = ContractFormatError(
        path="s.yaml",
        errors=[("fields.1.pattern", "Extra inputs are not permitted"),
                ("fields.1.max_length", "Extra inputs are not permitted")],
        hint=None,
    )
    text = str(err)
    assert "s.yaml:" in text
    assert "fields.1.pattern: Extra inputs are not permitted" in text
    assert "fields.1.max_length: Extra inputs are not permitted" in text
    assert "Upgrade the pin" not in text


def test_format_error_render_appends_hint_when_present():
    err = ContractFormatError(
        path="s.yaml", errors=[("k", "m")], hint="Upgrade the pin. See CHANGELOG.md.")
    assert str(err).endswith("Upgrade the pin. See CHANGELOG.md.")


@pytest.mark.xfail(reason="Schema strict lands in Task 2", strict=True)
def test_from_validation_error_hints_only_on_extra_forbidden():
    # An extra key -> hint. Reconstruct a real pydantic ValidationError via a strict model.
    try:
        Schema.model_validate({"schema": "a.b", "version": "1.0.0", "kind": "tabular",
                               "fields": [{"name": "x", "type": "int"}], "surprise": 1})
    except ValidationError as exc:
        err = ContractFormatError.from_validation_error("s.yaml", exc)
    assert any("surprise" in loc for loc, _ in err.errors)
    assert err.hint is not None and "Upgrade the pin" in err.hint


def test_from_validation_error_no_hint_on_an_applicability_error():
    # min_length on an int field is a genuine authoring error, NOT version skew (criterion 8).
    # Unlike the extra-forbidden case above, this one does not depend on Schema becoming
    # strict in Task 2: Field._constraints_match_the_declared_type (types.py) already
    # rejects min_length on a non-string field today, so this passes now, not xfail.
    try:
        Schema.model_validate({"schema": "a.b", "version": "1.0.0", "kind": "tabular",
                               "fields": [{"name": "x", "type": "int", "min_length": 1}]})
    except ValidationError as exc:
        err = ContractFormatError.from_validation_error("s.yaml", exc)
    assert err.hint is None


def test_unreadable_version_names_found_and_supported():
    err = ContractFormatError.unreadable_version(
        path="s.yaml", found="v2", supported=frozenset({"v1"}))
    text = str(err)
    assert "v2" in text
    assert "['v1']" in text
    assert err.hint is not None


def test_public_surface_now_exports_the_error():
    assert "ContractFormatError" in contract_core.__all__
    assert contract_core.ContractFormatError is ContractFormatError
