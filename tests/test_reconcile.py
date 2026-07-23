# tests/test_reconcile.py
from pathlib import Path

from contract_core.contract import Contract
from contract_core.resolver import Resolver
from contract_core.runtime import ContractRuntime, _reset_registry

FIX = Path(__file__).parent / "fixtures"


def _rt(system, boundary_name="prompts"):
    contract = Contract.model_validate({
        "system": system, "version": "1.0.0",
        "inputs": [{"name": boundary_name, "schema": "peec.prompts_export@1.0.0"}],
    })
    return ContractRuntime(contract, Resolver([FIX / "schemas"]))


def test_registry_records_system_direction_name():
    _reset_registry()
    rt = _rt("sys-a")

    @rt.input("prompts")
    def load():
        return None

    assert ("sys-a", "input", "prompts") in ContractRuntime.REGISTRY


def test_reset_registry_clears_entries():
    rt = _rt("sys-a")

    @rt.input("prompts")
    def load():
        return None

    assert ContractRuntime.REGISTRY  # non-empty
    _reset_registry()
    assert ContractRuntime.REGISTRY == []
