# tests/test_reconcile.py
from pathlib import Path

import pytest

from contract_core.contract import Contract
from contract_core.errors import UndeclaredBoundary
from contract_core.reconcile import (
    Finding,
    classify_import_error,
    diff_boundaries,
    force_import_package,
    reconcile,
    scan_decorator_placement,
    scan_drift_markers,
)
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


def test_scan_collects_raw_drift_marker_names(tmp_path):
    p = tmp_path / "test_drift.py"
    p.write_text(
        "import pytest\n"
        "@pytest.mark.raw_drift('prompts_raw')\n"
        "def test_rejects_unknown_shape():\n"
        "    pass\n"
    )
    assert scan_drift_markers([p]) == {"prompts_raw"}


def test_scan_matches_bare_mark_attribute_form(tmp_path):
    p = tmp_path / "d.py"
    p.write_text(
        "from pytest import mark\n"
        "@mark.raw_drift('a')\n"
        "def test_x():\n"
        "    pass\n"
    )
    assert scan_drift_markers([p]) == {"a"}


def test_scan_ignores_non_literal_marker_arg(tmp_path):
    # a name/reference is invisible to a non-importing scan → uncovered (over-strict, §7.1).
    p = tmp_path / "d.py"
    p.write_text(
        "import pytest\n"
        "@pytest.mark.raw_drift(SOME_CONST)\n"
        "def test_x():\n"
        "    pass\n"
    )
    assert scan_drift_markers([p]) == set()


def test_scan_empty_when_no_markers(tmp_path):
    p = tmp_path / "d.py"
    p.write_text("def test_x():\n    pass\n")
    assert scan_drift_markers([p]) == set()


def test_classify_undeclared_boundary_is_category_B():
    exc = UndeclaredBoundary(direction="input", name="typo")
    f = classify_import_error("pkg.mod", exc)
    assert f.category == "B"
    assert f.identifier == "typo"
    assert "typo" in f.message


def test_classify_chained_undeclared_boundary_still_category_B():
    inner = UndeclaredBoundary(direction="raw", name="rawtypo")
    try:
        try:
            raise inner
        except UndeclaredBoundary as e:
            raise RuntimeError("wrapped") from e
    except RuntimeError as outer:
        f = classify_import_error("pkg.mod", outer)
    assert f.category == "B"
    assert f.identifier == "rawtypo"


def test_classify_generic_error_is_nongating_diagnostic():
    f = classify_import_error("pkg.mod", ModuleNotFoundError("no numpy"))
    assert f.category == "diagnostic"
    assert f.gating is False
    assert "pkg.mod" in f.message


def test_classify_fatal_generic_error_is_category_P():
    f = classify_import_error("pkg", ImportError("boom"), fatal=True)
    assert f.category == "P"
    assert f.gating is True


def _registered():
    return {(d, n) for (s, d, n) in ContractRuntime.REGISTRY if s == "fix-sys"}


def test_force_import_registers_all_boundaries(make_reconcile_pkg, reconcile_sources):
    pkg = make_reconcile_pkg({"boundaries.py": reconcile_sources.boundaries})
    findings = force_import_package(pkg.package)
    assert findings == []
    assert _registered() == {("raw", "prompts_raw"), ("input", "prompts")}


def test_force_import_is_idempotent_in_process(make_reconcile_pkg, reconcile_sources):
    # B1: the second run must NOT under-register because the module is cached (design §6.2).
    pkg = make_reconcile_pkg({"boundaries.py": reconcile_sources.boundaries})
    force_import_package(pkg.package)
    _reset_registry()
    force_import_package(pkg.package)  # evict-then-import re-runs the decorators
    assert _registered() == {("raw", "prompts_raw"), ("input", "prompts")}


def test_force_import_top_level_failure_is_category_P(make_reconcile_pkg):
    pkg = make_reconcile_pkg({"__init__.py": "raise RuntimeError('boom in __init__')\n"})
    findings = force_import_package(pkg.package)
    assert [f.category for f in findings] == ["P"]


def test_force_import_leaf_failure_is_nongating_diagnostic(make_reconcile_pkg, reconcile_sources):
    pkg = make_reconcile_pkg({
        "boundaries.py": reconcile_sources.boundaries,
        "broken.py": "import a_package_that_does_not_exist\n",
    })
    findings = force_import_package(pkg.package)
    assert [f.category for f in findings] == ["diagnostic"]
    assert ("input", "prompts") in _registered()  # boundaries survive the sibling's failure


def test_force_import_subpackage_init_failure_does_not_abort_walk(
    make_reconcile_pkg, reconcile_sources
):
    # B2-walk: a subpackage __init__ raising a NON-ImportError would terminate walk_packages
    # with no onerror. It must be caught, and sibling modules still walked (design §6.2).
    pkg = make_reconcile_pkg({
        "boundaries.py": reconcile_sources.boundaries,
        "sub/__init__.py": "raise RuntimeError('boom in subpackage')\n",
    })
    findings = force_import_package(pkg.package)
    assert any(f.category == "diagnostic" for f in findings)  # subpackage surfaced
    assert ("input", "prompts") in _registered()  # sibling still imported


def test_force_import_undeclared_name_is_category_B(make_reconcile_pkg):
    mod = (
        "from contract_core import load_runtime\n"
        "runtime = load_runtime(r'{CONTRACT}', schema_paths=[r'{SCHEMAS}'])\n"
        "@runtime.input('not-declared')\n"
        "def load():\n"
        "    return None\n"
    )
    pkg = make_reconcile_pkg({"boundaries.py": mod})
    findings = force_import_package(pkg.package)
    assert any(f.category == "B" and f.identifier == "not-declared" for f in findings)


def _drift_dir(tmp_path, name="prompts_raw"):
    d = tmp_path / "drifts"
    d.mkdir(exist_ok=True)
    (d / f"drift_{name}.py").write_text(
        "import pytest\n"
        f"@pytest.mark.raw_drift('{name}')\n"
        "def test_rejects_unknown_shape():\n"
        "    pass\n"
    )
    return d


def test_reconcile_clean_package_has_no_gating_findings(
    make_reconcile_pkg, reconcile_sources, tmp_path
):
    pkg = make_reconcile_pkg({"boundaries.py": reconcile_sources.boundaries})
    result = reconcile(pkg.contract, pkg.package, [_drift_dir(tmp_path)])
    assert [f for f in result.findings if f.gating] == []
    assert result.system == "fix-sys"
    assert result.n_boundaries == 2


def test_reconcile_incident_2_missing_decorator_is_category_A(
    make_reconcile_pkg, reconcile_sources, tmp_path
):
    # declares raw+input, but the module only wires up input → raw is declared-but-unregistered.
    pkg = make_reconcile_pkg({"boundaries.py": reconcile_sources.input_only})
    result = reconcile(pkg.contract, pkg.package, [_drift_dir(tmp_path)])
    a = [f for f in result.findings if f.category == "A"]
    assert [f.identifier for f in a] == ["raw:prompts_raw"]


def test_reconcile_missing_drift_test_is_category_D(
    make_reconcile_pkg, reconcile_sources, tmp_path
):
    empty = tmp_path / "no_drifts"
    empty.mkdir()
    pkg = make_reconcile_pkg({"boundaries.py": reconcile_sources.boundaries})
    result = reconcile(pkg.contract, pkg.package, [empty])
    d = [f for f in result.findings if f.category == "D"]
    assert [f.identifier for f in d] == ["prompts_raw"]
