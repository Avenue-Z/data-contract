# tests/test_reconcile.py
from pathlib import Path

import pytest

from contract_core.contract import Contract
from contract_core.errors import UndeclaredBoundary
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


def test_spec_raises_undeclared_boundary_with_structured_fields():
    _reset_registry()
    rt = _rt("sys-a")
    with pytest.raises(UndeclaredBoundary) as ei:
        @rt.input("not-declared")
        def load():
            return None
    assert ei.value.direction == "input"
    assert ei.value.name == "not-declared"


def test_undeclared_boundary_is_a_keyerror():
    # subclasses KeyError so any existing `except KeyError` around a decorator still catches it.
    assert issubclass(UndeclaredBoundary, KeyError)
