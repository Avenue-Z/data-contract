# tests/test_contract.py
from pathlib import Path

from contract_core.contract import Contract

FIX = Path(__file__).parent / "fixtures"


def test_load_contract():
    c = Contract.from_yaml(FIX / "contract.yaml")
    assert c.system == "aivx-reports"
    assert c.raw[0].schema == "peec.prompts_raw@1"
    assert c.inputs[0].mode == "enforce"
    assert c.outputs[0].name == "report_payload"


def test_boundary_mode_defaults_to_enforce():
    from contract_core.contract import BoundarySpec
    b = BoundarySpec(name="x", schema="a.b@1")
    assert b.mode == "enforce"
