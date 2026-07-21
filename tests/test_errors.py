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
