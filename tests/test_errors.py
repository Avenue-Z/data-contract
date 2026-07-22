# tests/test_errors.py
from contract_core.errors import ContractViolation, FieldDiff


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
