# tests/test_reconcile.py
from pathlib import Path

import pytest

from contract_core.contract import Contract
from contract_core.errors import UndeclaredBoundary
from contract_core.reconcile import Finding, diff_boundaries, scan_decorator_placement
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


def test_finding_gating_flag():
    assert Finding("A", "input:x", "msg").gating is True
    assert Finding("diagnostic", "m", "msg").gating is False


def test_diff_reports_declared_but_unregistered_as_category_A():
    declared = {("input", "prompts"), ("raw", "prompts_raw")}
    registered = {("input", "prompts")}
    findings = diff_boundaries(declared, registered)
    assert [f.category for f in findings] == ["A"]
    assert findings[0].identifier == "raw:prompts_raw"


def test_diff_reverse_is_nongating_diagnostic():
    findings = diff_boundaries(
        declared={("input", "x")}, registered={("input", "x"), ("input", "stray")}
    )
    assert len(findings) == 1
    assert findings[0].category == "diagnostic"
    assert findings[0].gating is False


def test_diff_clean_returns_nothing():
    s = {("input", "x")}
    assert diff_boundaries(s, s) == []


def _write(tmp_path, body):
    p = tmp_path / "mod.py"
    p.write_text(body)
    return [p]


def test_nested_boundary_decorator_is_flagged(tmp_path):
    files = _write(tmp_path, (
        "def factory():\n"
        "    @runtime.input('prompts')\n"
        "    def load():\n"
        "        return None\n"
        "    return load\n"
    ))
    findings = scan_decorator_placement(files)
    assert [f.category for f in findings] == ["C"]
    assert "prompts" in findings[0].message


def test_top_level_boundary_decorator_is_not_flagged(tmp_path):
    files = _write(tmp_path, (
        "@runtime.input('prompts')\n"
        "def load():\n"
        "    return None\n"
    ))
    assert scan_decorator_placement(files) == []


def test_unrelated_nested_decorator_is_not_flagged(tmp_path):
    # a nested @property or @foo.bar(...) that is not raw/input/output must not match.
    files = _write(tmp_path, (
        "def factory():\n"
        "    @app.route('/x')\n"
        "    def view():\n"
        "        return None\n"
    ))
    assert scan_decorator_placement(files) == []


def test_conditional_top_level_decorator_is_flagged(tmp_path):
    # inside an `if` at module level: runs only conditionally, so it is not guaranteed at
    # import — flagged (over-strict, safe direction) per design §6.3.
    files = _write(tmp_path, (
        "if CONFIG:\n"
        "    @runtime.raw('prompts_raw')\n"
        "    def fetch():\n"
        "        return None\n"
    ))
    assert [f.category for f in scan_decorator_placement(files)] == ["C"]


def test_syntax_error_file_is_skipped_not_crashed(tmp_path):
    files = _write(tmp_path, "def broken(:\n")
    assert scan_decorator_placement(files) == []
