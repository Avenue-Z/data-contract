# `reconcile` Registration-Completeness Gate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `contract reconcile` — a CI-blocking gate that diffs the boundaries a contract *declares* against those *registered* at import time (R3), enforces that each declared raw boundary has a drift test (R2), and hardens the boundary registry against cross-contract leakage (§15 item 5).

**Architecture:** A new `contract_core/reconcile.py` holds pure functions (diff, two AST scans, one exception classifier — "structure in, findings out") plus a thin impure orchestrator that force-imports the target package (evict-then-import so decorators re-run; `walk_packages` with a mandatory `onerror`; leaf-modules imported by the loop, subpackages by the walk). The CLI subcommand in `cli.py` renders findings and sets the exit code, following the existing `lint` pattern. The runtime's `REGISTRY` gains a `system` field and a private reset helper.

**Tech Stack:** Python 3.13, pydantic 2.13, click, pytest, `ast`/`pkgutil`/`importlib` (stdlib), mypy strict, ruff.

**Design doc:** [`docs/superpowers/specs/2026-07-23-reconcile-registration-completeness-design.md`](../specs/2026-07-23-reconcile-registration-completeness-design.md). Section references (§N) below point to it.

## Global Constraints

- **Python** `>=3.13`; **pydantic** `~=2.13`; **click** `>=8.1`. Exact floors in `pyproject.toml` — do not bump.
- **mypy is strict and scoped to `files = ["src"]`** — every new/edited line in `src/` must type-check clean. Tests are not type-checked.
- **ruff** `select = ["E","F","I","UP","B"]`, `line-length = 100`. **When a step says "append to a test file," put any `import`/`from` lines at the TOP of that file** — ruff `E402` forbids module-level imports after code — and **consolidate duplicates** across steps into one import block. Only the test functions/helpers go at the bottom.
- **pytest** runs with `--strict-config --strict-markers`. Do **not** use `@pytest.mark.raw_drift` on any *collected* test (a file matching `test_*.py`); the marker is unregistered and would error. Reconcile's fixture drift files are built in `tmp_path` (never collected) precisely to avoid this.
- **Public API is frozen at 6 names** (`tests/test_public_api.py`). Do **not** add anything to `contract_core/__init__.py.__all__`. `UndeclaredBoundary`, `reconcile`, `Finding`, and `_reset_registry` are **internal** — defined in already-private modules, never exported.
- **Baseline is 212 passing tests.** The suite must stay green plus the new tests. Verify with, and read the output of:
  ```
  .venv/bin/python -m pytest -q && .venv/bin/ruff check . && .venv/bin/mypy
  ```
- **Branch flow:** work on `feat/reconcile-registration-completeness` (already created off `dev`). Never push to `main`.
- **PR merge condition (§6.3):** the PR description MUST report the measured decorator-placement over-match count against real decorated code (this repo, and the pilot once it carries decorators). Do not carry the spec's 20/20 estimate forward silently — Task 4 produces the number.

---

### Task 1: Registry evolution — `(system, direction, name)` + `_reset_registry` + autouse reset

**Files:**
- Modify: `src/contract_core/runtime.py` (`REGISTRY` type at :71, append at :125, add `_reset_registry`)
- Modify: `tests/conftest.py` (add autouse reset fixture)
- Modify: `tests/test_runtime.py:141-149` (existing `test_registry_is_populated` → 3-tuple)
- Test: `tests/test_reconcile.py` (new file — registry attribution + reset)

**Interfaces:**
- Produces: `ContractRuntime.REGISTRY: list[tuple[str, str, str]]` holding `(system, direction, name)`. Module-level `contract_core.runtime._reset_registry() -> None`.

- [ ] **Step 1: Write the failing test** — create `tests/test_reconcile.py`:

```python
# tests/test_reconcile.py
from contract_core.contract import Contract
from contract_core.resolver import Resolver
from contract_core.runtime import ContractRuntime, _reset_registry
from pathlib import Path

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_reconcile.py -q`
Expected: FAIL — `ImportError: cannot import name '_reset_registry'` (and the tuple assertion would fail).

- [ ] **Step 3: Edit `src/contract_core/runtime.py`.**

Change the `REGISTRY` declaration (line 71) from:
```python
    REGISTRY: list[tuple[str, str]] = []
```
to:
```python
    # (system, direction, name). `system` attributes each registration to its contract so
    # reconcile can filter to one contract's boundaries (design §4.1) — without it, two
    # contracts in one process share an unlabelled list and can false-attribute.
    REGISTRY: list[tuple[str, str, str]] = []
```

Change the append (line 125) from:
```python
        ContractRuntime.REGISTRY.append((direction, name))
```
to:
```python
        ContractRuntime.REGISTRY.append((self.contract.system, direction, name))
```

Add, at module scope near the bottom of the file (after `class _DisabledRuntime`):
```python
def _reset_registry() -> None:
    """Clear the process-global registration set (design §4).

    Internal — used by reconcile before a force-import and by an autouse test fixture so
    registry assertions are order-independent (§15 item 5). Not exported; the `runtime`
    module is already declared private in the package docstring, and `__all__` still lists
    exactly the six public names.
    """
    ContractRuntime.REGISTRY.clear()
```

- [ ] **Step 4: Update the existing registry test.** In `tests/test_runtime.py`, change `test_registry_is_populated` (lines 141-149) — the assertion becomes the 3-tuple (the `_runtime` helper uses `system="demo"`):
```python
    assert ("demo", "input", "prompts") in ContractRuntime.REGISTRY
```

- [ ] **Step 5: Add the autouse reset fixture** to `tests/conftest.py` (append):
```python
@pytest.fixture(autouse=True)
def _reset_contract_registry():
    """Clear the boundary registry before each test (design §4 / §15 item 5).

    The registry is process-global; without this, one test's registrations leak into
    another's assertions (the order-dependence the pilot reported). Function-scoped and
    before the test body, which is where every test does its own decoration.
    """
    from contract_core.runtime import _reset_registry
    _reset_registry()
    yield
```

- [ ] **Step 6: Run the new + touched tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_reconcile.py tests/test_runtime.py -q`
Expected: PASS.

- [ ] **Step 7: Full verify**

Run: `.venv/bin/python -m pytest -q && .venv/bin/ruff check . && .venv/bin/mypy`
Expected: all green (213+ tests).

- [ ] **Step 8: Commit**
```bash
git add src/contract_core/runtime.py tests/conftest.py tests/test_runtime.py tests/test_reconcile.py
git commit -m "feat(reconcile): attribute REGISTRY by system + add _reset_registry"
```

---

### Task 2: `UndeclaredBoundary` — typed classification for a decorator naming an undeclared boundary

**Files:**
- Modify: `src/contract_core/errors.py` (add `UndeclaredBoundary`)
- Modify: `src/contract_core/runtime.py` (`_spec` at :105-111 raises it; import it)
- Test: `tests/test_reconcile.py` (append)

**Interfaces:**
- Produces: `contract_core.errors.UndeclaredBoundary(KeyError)` with `__init__(*, direction: str, name: str)` and attributes `.direction: str`, `.name: str`. Raised by `ContractRuntime._spec` when a decorator names a boundary the contract does not declare.

- [ ] **Step 1: Write the failing test** (append to `tests/test_reconcile.py`):
```python
import pytest
from contract_core.errors import UndeclaredBoundary


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_reconcile.py -k undeclared -q`
Expected: FAIL — `ImportError: cannot import name 'UndeclaredBoundary'`.

- [ ] **Step 3: Add `UndeclaredBoundary` to `src/contract_core/errors.py`** (after the `Problem` line / before `FieldDiff`, or at end — place near the top-level classes):
```python
class UndeclaredBoundary(KeyError):
    """A boundary decorator named a boundary the contract does not declare (design §2).

    Raised at the decorator (import) boundary. reconcile classifies it as category B **by
    type**, reading `.direction` / `.name` — never by parsing this message (design §2; the
    message-parsing anti-pattern §15 item 5 damns). Subclasses `KeyError` for back-compat
    with any consumer catching `KeyError` around a decorator.
    """

    def __init__(self, *, direction: str, name: str) -> None:
        self.direction = direction
        self.name = name
        super().__init__(f"no {direction} boundary named {name!r} in contract")
```

- [ ] **Step 4: Make `_spec` raise it.** In `src/contract_core/runtime.py`, add the import to the `from contract_core.errors import ...` line (line 19):
```python
from contract_core.errors import ContractViolation, FieldDiff, UndeclaredBoundary
```
Change the raise at the end of `_spec` (line 111) from:
```python
        raise KeyError(f"no {direction} boundary named {name!r} in contract")
```
to:
```python
        raise UndeclaredBoundary(direction=direction, name=name)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_reconcile.py tests/test_runtime.py tests/test_errors.py -q`
Expected: PASS.

- [ ] **Step 6: Full verify**

Run: `.venv/bin/python -m pytest -q && .venv/bin/ruff check . && .venv/bin/mypy`
Expected: all green.

- [ ] **Step 7: Commit**
```bash
git add src/contract_core/errors.py src/contract_core/runtime.py tests/test_reconcile.py
git commit -m "feat(reconcile): raise typed UndeclaredBoundary from _spec"
```

---

### Task 3: `Finding` value type + `diff_boundaries` (category A + defensive reverse)

**Files:**
- Create: `src/contract_core/reconcile.py`
- Test: `tests/test_reconcile.py` (append)

**Interfaces:**
- Produces:
  - `Finding` — `@dataclass(frozen=True)` with `category: str` (`"P"|"A"|"B"|"C"|"D"|"diagnostic"`), `identifier: str`, `message: str`, and property `gating: bool` (True unless category is `"diagnostic"`).
  - `diff_boundaries(declared: set[tuple[str, str]], registered: set[tuple[str, str]]) -> list[Finding]` — each element of the sets is `(direction, name)`. Category A for `declared − registered`; a non-gating `"diagnostic"` for the structurally-empty `registered − declared`.
  - `_CATEGORY_RANK: dict[str, int]` and `_sort_key(f: Finding) -> tuple[int, str]` for deterministic ordering (§5.2).

- [ ] **Step 1: Write the failing test** (append to `tests/test_reconcile.py`):
```python
from contract_core.reconcile import Finding, diff_boundaries


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
    findings = diff_boundaries(declared={("input", "x")}, registered={("input", "x"), ("input", "stray")})
    assert len(findings) == 1
    assert findings[0].category == "diagnostic"
    assert findings[0].gating is False


def test_diff_clean_returns_nothing():
    s = {("input", "x")}
    assert diff_boundaries(s, s) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_reconcile.py -k "finding or diff" -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'contract_core.reconcile'`.

- [ ] **Step 3: Create `src/contract_core/reconcile.py`** with the value type + diff:
```python
# src/contract_core/reconcile.py
"""reconcile — the registration-completeness gate (design 2026-07-23).

Pure functions (diff + AST scans + exception classification) plus a thin impure
orchestrator. Internal module — nothing here is on the public surface (R9).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Finding:
    category: str      # "P" | "A" | "B" | "C" | "D" | "diagnostic"
    identifier: str    # portable id: "direction:name", boundary name, module, or "file:line"
    message: str       # human-readable line for the CLI

    @property
    def gating(self) -> bool:
        return self.category != "diagnostic"


# Fixed render/sort order so golden CLI tests and CI diffs are stable (design §5.2).
_CATEGORY_RANK = {"P": 0, "A": 1, "B": 2, "C": 3, "D": 4, "diagnostic": 5}


def _sort_key(f: Finding) -> tuple[int, str]:
    return (_CATEGORY_RANK[f.category], f.identifier)


def diff_boundaries(
    declared: set[tuple[str, str]], registered: set[tuple[str, str]]
) -> list[Finding]:
    """Category A for every declared boundary no decorator registered (design §5, §2).

    The reverse (registered − declared) is structurally empty — an undeclared name raises
    `UndeclaredBoundary` before the append — so it is reported only as a non-gating
    diagnostic if it ever somehow occurs.
    """
    findings: list[Finding] = []
    for direction, name in declared - registered:
        findings.append(Finding(
            "A", f"{direction}:{name}",
            f"declared but no decorator registered it: {direction} '{name}'"))
    for direction, name in registered - declared:
        findings.append(Finding(
            "diagnostic", f"{direction}:{name}",
            f"registered but not declared: {direction} '{name}'"))
    return sorted(findings, key=_sort_key)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_reconcile.py -k "finding or diff" -q`
Expected: PASS.

- [ ] **Step 5: Full verify**

Run: `.venv/bin/python -m pytest -q && .venv/bin/ruff check . && .venv/bin/mypy`
Expected: all green.

- [ ] **Step 6: Commit**
```bash
git add src/contract_core/reconcile.py tests/test_reconcile.py
git commit -m "feat(reconcile): Finding type + diff_boundaries (category A)"
```

---

### Task 4: `scan_decorator_placement` (category C) + the over-match measurement

**Files:**
- Modify: `src/contract_core/reconcile.py` (add scan + AST predicate)
- Test: `tests/test_reconcile.py` (append)

**Interfaces:**
- Consumes: `Finding`, `_sort_key` (Task 3).
- Produces: `scan_decorator_placement(files: Iterable[Path]) -> list[Finding]` — parses each file; a boundary decorator (`@<x>.raw|input|output("literal")`) on a function **not** a direct child of the module body yields a category-C finding with identifier `"<path>:<lineno>"`. Files that fail to parse (`SyntaxError`) are skipped (surfaced elsewhere as an import diagnostic).

- [ ] **Step 1: Write the failing test** (append to `tests/test_reconcile.py`):
```python
from contract_core.reconcile import scan_decorator_placement


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_reconcile.py -k placement -q`
Expected: FAIL — `ImportError: cannot import name 'scan_decorator_placement'`.

- [ ] **Step 3: Add the scan to `src/contract_core/reconcile.py`.** Add imports at the top (below the module docstring):
```python
import ast
from collections.abc import Iterable
from pathlib import Path
```
Add the predicate and scan (after `diff_boundaries`):
```python
_BOUNDARY_ATTRS = {"raw", "input", "output"}


def _is_boundary_decorator(dec: ast.expr) -> bool:
    """`@<x>.raw|input|output("literal")` — decorator position, attribute form, one string
    literal arg (design §6.3). The narrowings keep the over-match small and measured."""
    return (
        isinstance(dec, ast.Call)
        and isinstance(dec.func, ast.Attribute)
        and dec.func.attr in _BOUNDARY_ATTRS
        and len(dec.args) == 1
        and isinstance(dec.args[0], ast.Constant)
        and isinstance(dec.args[0].value, str)
    )


def scan_decorator_placement(files: Iterable[Path]) -> list[Finding]:
    """Category C: a boundary decorator not at module top level would not run at import,
    so force-import never registers it — a silent false pass (design §6.3, R3)."""
    findings: list[Finding] = []
    for path in files:
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except SyntaxError:
            continue  # unparseable file surfaces as an import diagnostic, not here
        top_level = {
            id(n) for n in ast.iter_child_nodes(tree)
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if id(node) in top_level:
                continue
            for dec in node.decorator_list:
                if _is_boundary_decorator(dec):
                    assert isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                    name = dec.args[0].value
                    findings.append(Finding(
                        "C", f"{path}:{node.lineno}",
                        f"boundary decorator @…{dec.func.attr}('{name}') not at module "
                        f"top level ({path}:{node.lineno})"))
    return sorted(findings, key=_sort_key)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_reconcile.py -k placement -q`
Expected: PASS.

- [ ] **Step 5: Measure the over-match (PR merge condition, §6.3).** Run the scan over this repo's real source + tests and confirm zero false matches, then record the count for the PR description:
```bash
.venv/bin/python -c "
from pathlib import Path
from contract_core.reconcile import scan_decorator_placement
files = [*Path('src').rglob('*.py'), *Path('tests').rglob('*.py')]
findings = scan_decorator_placement(files)
print('placement findings (this repo):', len(findings))
for f in findings: print(' ', f.message)
"
```
Expected: `0` (all boundary decorators in this repo are top-level). **Write the number into the PR description**, noting the pilot has no decorators yet (a pilot figure is vacuous today).

- [ ] **Step 6: Full verify**

Run: `.venv/bin/python -m pytest -q && .venv/bin/ruff check . && .venv/bin/mypy`
Expected: all green.

- [ ] **Step 7: Commit**
```bash
git add src/contract_core/reconcile.py tests/test_reconcile.py
git commit -m "feat(reconcile): scan_decorator_placement (category C)"
```

---

### Task 5: `scan_drift_markers` (R2 / category D coverage set)

**Files:**
- Modify: `src/contract_core/reconcile.py`
- Test: `tests/test_reconcile.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces: `scan_drift_markers(files: Iterable[Path]) -> set[str]` — parses each file; collects every string-literal argument of a `@<x>.raw_drift(...)` **decorator** into the covered set (design §7.1). Decorator-position + attribute-form + string-literal only; unparseable files skipped.

- [ ] **Step 1: Write the failing test** (append to `tests/test_reconcile.py`):
```python
from contract_core.reconcile import scan_drift_markers


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_reconcile.py -k drift -q`
Expected: FAIL — `ImportError: cannot import name 'scan_drift_markers'`.

- [ ] **Step 3: Add the scan to `src/contract_core/reconcile.py`** (after `scan_decorator_placement`):
```python
def scan_drift_markers(files: Iterable[Path]) -> set[str]:
    """The set of raw-boundary names covered by an `@…raw_drift("name")` decorator (§7.1).

    Decorator position only, attribute form (`.attr == "raw_drift"`), string-literal args
    only — every residual fails toward firing category D (over-strict, never a false pass)."""
    covered: set[str] = set()
    for path in files:
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for dec in node.decorator_list:
                if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                        and dec.func.attr == "raw_drift"):
                    for arg in dec.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            covered.add(arg.value)
    return covered
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_reconcile.py -k drift -q`
Expected: PASS.

- [ ] **Step 5: Full verify**

Run: `.venv/bin/python -m pytest -q && .venv/bin/ruff check . && .venv/bin/mypy`
Expected: all green.

- [ ] **Step 6: Commit**
```bash
git add src/contract_core/reconcile.py tests/test_reconcile.py
git commit -m "feat(reconcile): scan_drift_markers (R2 coverage set)"
```

---

### Task 6: `classify_import_error` (category B / P / diagnostic + chain walk)

**Files:**
- Modify: `src/contract_core/reconcile.py`
- Test: `tests/test_reconcile.py` (append)

**Interfaces:**
- Consumes: `Finding` (Task 3), `UndeclaredBoundary` (Task 2).
- Produces: `classify_import_error(module: str, exc: BaseException, *, fatal: bool = False) -> Finding`. Walks `__cause__`/`__context__` for an `UndeclaredBoundary` → **B** (identifier = the undeclared name); else **P** if `fatal` (top-level import, no A backstop) else non-gating **diagnostic**. Messages carry only `type(exc).__name__` (portable — no env-specific paths, §5.2).

- [ ] **Step 1: Write the failing test** (append to `tests/test_reconcile.py`):
```python
from contract_core.reconcile import classify_import_error


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_reconcile.py -k classify -q`
Expected: FAIL — `ImportError: cannot import name 'classify_import_error'`.

- [ ] **Step 3: Add the classifier to `src/contract_core/reconcile.py`.** Add the import near the top:
```python
from contract_core.errors import UndeclaredBoundary
```
Add (after `scan_drift_markers`):
```python
def _find_undeclared(exc: BaseException) -> UndeclaredBoundary | None:
    """Walk the exception chain — a module may catch and re-raise `from` an
    UndeclaredBoundary; missing it would silently drop an undeclared boundary (design §6.2)."""
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, UndeclaredBoundary):
            return cur
        cur = cur.__cause__ or cur.__context__
    return None


def classify_import_error(
    module: str, exc: BaseException, *, fatal: bool = False
) -> Finding:
    """Turn an import-time exception into a finding (design §6.2).

    `UndeclaredBoundary` anywhere in the chain gates as B (by type, never message-parsing).
    Otherwise: P when fatal (top-level import — no category-A backstop below it), else a
    non-gating diagnostic. Message carries only the exception type, never env-specific
    text (§5.2)."""
    ub = _find_undeclared(exc)
    if ub is not None:
        return Finding("B", ub.name,
                       f"decorator names an undeclared boundary '{ub.name}' (in {module})")
    if fatal:
        return Finding("P", module,
                       f"package '{module}' could not be imported: {type(exc).__name__}")
    return Finding("diagnostic", module,
                   f"module '{module}' failed to import: {type(exc).__name__}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_reconcile.py -k classify -q`
Expected: PASS.

- [ ] **Step 5: Full verify**

Run: `.venv/bin/python -m pytest -q && .venv/bin/ruff check . && .venv/bin/mypy`
Expected: all green.

- [ ] **Step 6: Commit**
```bash
git add src/contract_core/reconcile.py tests/test_reconcile.py
git commit -m "feat(reconcile): classify_import_error (B/P/diagnostic + chain walk)"
```

---

### Task 7: `force_import_package` (evict → import → walk with `onerror`) + fixture builder

**Files:**
- Modify: `src/contract_core/reconcile.py` (impure force-import)
- Modify: `tests/conftest.py` (add `make_reconcile_pkg` fixture)
- Test: `tests/test_reconcile.py` (append)

**Interfaces:**
- Consumes: `classify_import_error` (Task 6).
- Produces:
  - `force_import_package(package: str) -> list[Finding]` — evicts the `package` namespace from `sys.modules`, imports the top level (fatal → single P finding, no walk), then `walk_packages(..., onerror=...)` importing **leaf modules** in the loop (subpackages are imported by the walk). Returns B/diagnostic findings; registrations land in `ContractRuntime.REGISTRY` as a side effect.
  - conftest fixture `make_reconcile_pkg(files: dict[str, str], *, contract: str, name: str = "fixpkg") -> SimpleNamespace` with `.package`, `.contract` (path str), `.root` (Path). Writes an importable package tree under `tmp_path`, writes the contract file, and prepends `tmp_path` to `sys.path`.

- [ ] **Step 1: Add the shared sources + fixture builder to `tests/conftest.py`** (append). Constants + a `reconcile_sources` fixture live here so both `test_reconcile.py` and `test_cli.py` share them **without cross-test-module imports** (fragile under pytest import modes):
```python
from types import SimpleNamespace

# Shared reconcile fixture sources. `{SCHEMAS}`/`{CONTRACT}` are substituted by str .replace
# (NOT str.format — a fixture module may contain literal braces, e.g. a dict).
_RECONCILE_CONTRACT = (
    "system: fix-sys\n"
    "version: 1.0.0\n"
    "raw:\n"
    "  - {name: prompts_raw, schema: peec.prompts_export@1.0.0, mode: enforce}\n"
    "inputs:\n"
    "  - {name: prompts, schema: peec.prompts_export@1.0.0, mode: enforce}\n"
)
_RECONCILE_BOUNDARIES = (
    "from contract_core import load_runtime\n"
    "runtime = load_runtime(r'{CONTRACT}', schema_paths=[r'{SCHEMAS}'])\n"
    "\n"
    "@runtime.raw('prompts_raw')\n"
    "def fetch():\n"
    "    return None\n"
    "\n"
    "@runtime.input('prompts')\n"
    "def load():\n"
    "    return None\n"
)
# Same as _RECONCILE_BOUNDARIES but wires up ONLY input — raw is left declared-but-unregistered
# (the incident-#2 replay, category A).
_RECONCILE_INPUT_ONLY = (
    "from contract_core import load_runtime\n"
    "runtime = load_runtime(r'{CONTRACT}', schema_paths=[r'{SCHEMAS}'])\n"
    "\n"
    "@runtime.input('prompts')\n"
    "def load():\n"
    "    return None\n"
)


@pytest.fixture
def reconcile_sources():
    return SimpleNamespace(
        contract=_RECONCILE_CONTRACT,
        boundaries=_RECONCILE_BOUNDARIES,
        input_only=_RECONCILE_INPUT_ONLY,
    )


@pytest.fixture
def make_reconcile_pkg(tmp_path, monkeypatch):
    """Build an importable fixture package under tmp_path for force-import tests.

    `files` maps a path relative to the package root ("boundaries.py", "sub/__init__.py",
    ...) to source text; `{SCHEMAS}`/`{CONTRACT}` in it are substituted via .replace. A
    package `__init__.py` is created empty if absent. `contract` defaults to the shared
    raw+input contract. reconcile only *imports* the modules, so decorated function bodies
    never run and can be trivial.
    """
    from pathlib import Path
    SCHEMAS = Path(__file__).parent / "fixtures" / "schemas"

    def build(files, *, contract=_RECONCILE_CONTRACT, name="fixpkg"):
        cpath = tmp_path / f"{name}.contract.yaml"
        root = tmp_path / name
        for rel, src in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(src.replace("{SCHEMAS}", str(SCHEMAS)).replace("{CONTRACT}", str(cpath)))
        if not (root / "__init__.py").exists():
            (root / "__init__.py").write_text("")
        cpath.write_text(contract)
        monkeypatch.syspath_prepend(str(tmp_path))
        return SimpleNamespace(package=name, contract=str(cpath), root=root)

    return build
```

- [ ] **Step 2: Write the failing tests** (append to `tests/test_reconcile.py`). These use the `make_reconcile_pkg` and `reconcile_sources` fixtures from `conftest.py` (Step 1) — no module-level fixture constants, no cross-test-module imports:
```python
from contract_core.reconcile import force_import_package
from contract_core.runtime import ContractRuntime, _reset_registry


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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_reconcile.py -k force_import -q`
Expected: FAIL — `ImportError: cannot import name 'force_import_package'`.

- [ ] **Step 4: Add `force_import_package` to `src/contract_core/reconcile.py`.** Add imports near the top:
```python
import importlib
import pkgutil
import sys
```
Add (after `classify_import_error`):
```python
def force_import_package(package: str) -> list[Finding]:
    """Import every module under `package` so its top-level decorators register (design §6.2).

    Evict the package namespace first, so an already-cached module re-executes (reset+import
    is a no-op otherwise). Top-level import failure is fatal → a single category-P finding,
    no walk. Then walk: `walk_packages` imports subpackages itself (failures routed through
    `onerror`); the loop imports only *leaf* modules (`walk_packages` does not), so there is
    no double-import. Both paths classify via `classify_import_error`.
    """
    findings: list[Finding] = []
    for mod in [m for m in list(sys.modules) if m == package or m.startswith(package + ".")]:
        del sys.modules[mod]

    try:
        pkg = importlib.import_module(package)
    except Exception as exc:  # noqa: BLE001 — every import failure is a finding, not a crash
        return [classify_import_error(package, exc, fatal=True)]

    pkg_path = getattr(pkg, "__path__", None)
    if pkg_path is None:  # a single module, already executed by the import above
        return findings

    def _on_walk_error(name: str) -> None:
        exc = sys.exc_info()[1]
        if exc is not None:  # walk calls onerror from inside its except block
            findings.append(classify_import_error(name, exc))

    for info in pkgutil.walk_packages(pkg_path, package + ".", onerror=_on_walk_error):
        if info.ispkg:
            continue  # subpackages are imported (and their errors handled) by walk itself
        try:
            importlib.import_module(info.name)
        except Exception as exc:  # noqa: BLE001
            findings.append(classify_import_error(info.name, exc))
    return findings
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_reconcile.py -k force_import -q`
Expected: PASS.

- [ ] **Step 6: Full verify**

Run: `.venv/bin/python -m pytest -q && .venv/bin/ruff check . && .venv/bin/mypy`
Expected: all green. (If ruff flags `BLE001` — blind-except — the `# noqa: BLE001` comments are intentional and already present; a blanket catch is the design, §6.2.)

- [ ] **Step 7: Commit**
```bash
git add src/contract_core/reconcile.py tests/conftest.py tests/test_reconcile.py
git commit -m "feat(reconcile): force_import_package (evict/import/walk with onerror)"
```

---

### Task 8: `reconcile` orchestrator + CLI subcommand (end-to-end gate)

**Files:**
- Modify: `src/contract_core/reconcile.py` (add `ReconcileResult`, `reconcile`, file helpers)
- Modify: `src/contract_core/cli.py` (add `reconcile` subcommand)
- Test: `tests/test_reconcile.py` (orchestrator) + `tests/test_cli.py` (CLI, incident-#2 replay)

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `ReconcileResult` — `@dataclass(frozen=True)` with `findings: list[Finding]`, `system: str`, `version: str`, `n_boundaries: int`.
  - `reconcile(contract_path: str | Path, package: str, test_paths: Sequence[Path]) -> ReconcileResult` — loads the contract (may raise `ContractFormatError`), resets the registry, force-imports, runs the three scans + diff, returns sorted findings. On a category-P import failure, returns early with just that finding (no scans).
  - CLI `contract reconcile --contract PATH --package NAME --tests PATH...` — exit 1 on any gating finding (prints all findings under `RECONCILE FAILED:`), else prints any diagnostics and `OK: <system>@<version> — N boundaries reconciled`, exit 0.

- [ ] **Step 1: Write the failing orchestrator + CLI tests.** All use the shared `conftest.py` fixtures — no cross-test-module imports. A small local `_drift_dir` helper writes a marker file (named `drift_*.py`, **not** `test_*.py`, so pytest never collects it and `--strict-markers` never sees the unregistered marker). Append to `tests/test_reconcile.py`:
```python
from contract_core.reconcile import reconcile


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
```
Append to `tests/test_cli.py`:
```python
def _drift_dir(tmp_path):
    d = tmp_path / "drifts"
    d.mkdir()
    (d / "drift_prompts_raw.py").write_text(
        "import pytest\n@pytest.mark.raw_drift('prompts_raw')\ndef test_x():\n    pass\n")
    return d


def test_reconcile_clean_exits_zero(make_reconcile_pkg, reconcile_sources, tmp_path):
    pkg = make_reconcile_pkg({"boundaries.py": reconcile_sources.boundaries})
    res = CliRunner().invoke(main, ["reconcile", "--contract", pkg.contract,
                                    "--package", pkg.package,
                                    "--tests", str(_drift_dir(tmp_path))])
    assert res.exit_code == 0, res.output
    assert "OK: fix-sys@1.0.0" in res.output


def test_reconcile_incident_2_replay_exits_one(make_reconcile_pkg, reconcile_sources, tmp_path):
    pkg = make_reconcile_pkg({"boundaries.py": reconcile_sources.input_only})
    res = CliRunner().invoke(main, ["reconcile", "--contract", pkg.contract,
                                    "--package", pkg.package,
                                    "--tests", str(_drift_dir(tmp_path))])
    assert res.exit_code == 1
    assert "RECONCILE FAILED" in res.output
    assert "prompts_raw" in res.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_reconcile.py -k "reconcile_" tests/test_cli.py -k reconcile -q`
Expected: FAIL — `cannot import name 'reconcile'` / `No such command 'reconcile'`.

- [ ] **Step 3: Add the orchestrator to `src/contract_core/reconcile.py`.** Add imports:
```python
from collections.abc import Sequence

from contract_core.contract import Contract
from contract_core.runtime import ContractRuntime, _reset_registry
```
Add:
```python
@dataclass(frozen=True)
class ReconcileResult:
    findings: list[Finding]
    system: str
    version: str
    n_boundaries: int


def _declared_set(contract: Contract) -> set[tuple[str, str]]:
    return (
        {("raw", b.name) for b in contract.raw}
        | {("input", b.name) for b in contract.inputs}
        | {("output", b.name) for b in contract.outputs}
    )


def _python_files(paths: Iterable[Path]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        if p.is_dir():
            out.extend(sorted(p.rglob("*.py")))
        elif p.suffix == ".py":
            out.append(p)
    return out


def _package_source_files(package: str) -> list[Path]:
    pkg = sys.modules[package]
    pkg_path = getattr(pkg, "__path__", None)
    if pkg_path is not None:
        return _python_files(Path(p) for p in pkg_path)
    file = getattr(pkg, "__file__", None)
    return [Path(file)] if file else []


def reconcile(
    contract_path: str | Path, package: str, test_paths: Sequence[Path]
) -> ReconcileResult:
    """Load the contract, force-import the package, diff + scan, return findings (design §3).

    Raises ContractFormatError (like `lint`) if the contract is malformed — the CLI renders
    it. A category-P import failure short-circuits: nothing can be scanned, so return it alone.
    """
    contract = Contract.from_yaml(contract_path)
    declared = _declared_set(contract)
    n_boundaries = len(declared)

    _reset_registry()
    import_findings = force_import_package(package)
    if any(f.category == "P" for f in import_findings):
        return ReconcileResult(import_findings, contract.system, contract.version, n_boundaries)

    placement = scan_decorator_placement(_package_source_files(package))
    registered = {(d, n) for (s, d, n) in ContractRuntime.REGISTRY if s == contract.system}
    diff = diff_boundaries(declared, registered)
    covered = scan_drift_markers(_python_files(test_paths))
    drift = [
        Finding("D", b.name, f"raw boundary '{b.name}' declared but no drift test found")
        for b in contract.raw if b.name not in covered
    ]
    findings = sorted(import_findings + placement + diff + drift, key=_sort_key)
    return ReconcileResult(findings, contract.system, contract.version, n_boundaries)
```

- [ ] **Step 4: Add the CLI subcommand to `src/contract_core/cli.py`.** Add the import at the top:
```python
from pathlib import Path
```
(if `Path` is already imported, skip). Append the command at the end of the file:
```python
@main.command()
@click.option("--contract", "contract_path", required=True, type=click.Path(exists=True))
@click.option("--package", "package", required=True)
@click.option("--tests", "test_paths", multiple=True, required=True,
              type=click.Path(exists=True))
def reconcile(contract_path: str, package: str, test_paths: tuple[str, ...]) -> None:
    """Diff declared vs registered boundaries; enforce raw-boundary drift tests (design)."""
    from contract_core.reconcile import reconcile as run
    try:
        result = run(contract_path, package, [Path(p) for p in test_paths])
    except ContractFormatError as exc:
        click.echo("RECONCILE FAILED — malformed contract:")
        _echo_format_error(exc)
        sys.exit(1)
    gating = [f for f in result.findings if f.gating]
    if gating:
        click.echo("RECONCILE FAILED:")
        for f in result.findings:
            click.echo(f"  - {f.message}")
        sys.exit(1)
    for f in result.findings:  # non-gating diagnostics, if any
        click.echo(f"  - {f.message}")
    click.echo(f"OK: {result.system}@{result.version} — "
               f"{result.n_boundaries} boundaries reconciled")
```

- [ ] **Step 5: Run the CLI tests.** (`cli.py` already imports `Path` at line 4 — the Step-4 import is a no-op there; skip it if present. Ruff would flag a duplicate import.)

Run: `.venv/bin/python -m pytest tests/test_cli.py -k reconcile -q`
Expected: PASS.

- [ ] **Step 6: Run all reconcile tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_reconcile.py tests/test_cli.py -q`
Expected: PASS.

- [ ] **Step 7: Full verify**

Run: `.venv/bin/python -m pytest -q && .venv/bin/ruff check . && .venv/bin/mypy`
Expected: all green.

- [ ] **Step 8: Commit**
```bash
git add src/contract_core/reconcile.py src/contract_core/cli.py tests/test_reconcile.py tests/test_cli.py
git commit -m "feat(reconcile): orchestrator + CLI subcommand (R3+R2 gate)"
```

---

### Task 9: Determinism pin, risk-row closures, CHANGELOG, final verify

**Files:**
- Test: `tests/test_reconcile.py` (determinism)
- Modify: `docs/superpowers/specs/2026-07-16-data-contract-system-design.md` (R2, R3, §15 item 5)
- Modify: `CHANGELOG.md`

**Interfaces:** none new.

- [ ] **Step 1: Write the determinism test** (append to `tests/test_reconcile.py`) — assert the pinned order (§5.2) on portable fields only:
```python
def test_findings_render_in_pinned_category_order():
    from contract_core.reconcile import _sort_key
    unsorted = [
        Finding("D", "prompts_raw", "d"),
        Finding("A", "input:x", "a"),
        Finding("diagnostic", "m", "diag"),
        Finding("P", "pkg", "p"),
        Finding("C", "f.py:3", "c"),
        Finding("B", "typo", "b"),
    ]
    ordered = [f.category for f in sorted(unsorted, key=_sort_key)]
    assert ordered == ["P", "A", "B", "C", "D", "diagnostic"]
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/python -m pytest tests/test_reconcile.py -k pinned -q`
Expected: PASS (no code change needed — `_sort_key` already exists).

- [ ] **Step 3: Close the risk rows.** In `docs/superpowers/specs/2026-07-16-data-contract-system-design.md`, edit the **R3** and **R2** rows of §14 and **§15 item 5** to record closure with date + commit + option taken, following the format of the already-closed R8/R9/R10 rows. Use today's date (2026-07-23) and the merge commit (fill the real SHA at merge time; use the feature-branch HEAD until then). Example insert for R3's mitigation cell:
  > **CLOSED 2026-07-23** (`<sha>`, PR #NN). Shipped `contract reconcile` as a single gate: force-imports every module under `--package` (evict-then-import; `walk_packages` with a mandatory `onerror`; leaf modules imported by the loop, subpackages by the walk), diffs declared vs `(system,direction,name)`-attributed registrations, and lint-bans boundary decorators outside module top level as category C. Dynamic-factory boundaries remain the accepted residual (§5.4). Design: `2026-07-23-reconcile-registration-completeness-design.md`.

  For R2: record that reconcile emits category D when a declared raw boundary lacks an `@pytest.mark.raw_drift("<name>")` drift test (static existence+linkage; the semantics ceiling is stated in the design §7.2). For §15 item 5: record only the **registry** slice as addressed — `(system,direction,name)` + `_reset_registry` + the autouse reset fixture — and leave the other item-5 entries (event-log reader/sink, error-classification fragility, `schema`-field shadowing) explicitly still open.

- [ ] **Step 4: Add a CHANGELOG entry.** In `CHANGELOG.md`, add an `[Unreleased]` (or next-version) entry noting: `contract reconcile` subcommand (R3 + R2 gate); `REGISTRY` now records `(system, direction, name)` — **internal** behavior change, not a public-API change; new internal `UndeclaredBoundary` exception. State plainly that the frozen 6-name public surface is unchanged.

- [ ] **Step 5: Final full verify — read the output.**

Run: `.venv/bin/python -m pytest -q && .venv/bin/ruff check . && .venv/bin/mypy`
Expected: all green; test count = baseline 212 + all new reconcile/CLI tests. Confirm the public-API test still passes (surface unchanged).

- [ ] **Step 6: Commit**
```bash
git add docs/superpowers/specs/2026-07-16-data-contract-system-design.md CHANGELOG.md tests/test_reconcile.py
git commit -m "docs(reconcile): close R3/R2 + registry slice of item 5; determinism pin"
```

---

## Self-Review

**Spec coverage** (each design section → task):
- §2 asymmetric diff / `UndeclaredBoundary` → Tasks 2, 6. §3 command surface/flow → Task 8. §3.1 no `--schemas` → Task 8 (orchestrator takes no schema paths). §4 registry `(system,direction,name)` + `_reset_registry` → Task 1. §4.1 attribution → Task 1 tests + Task 8. §5 taxonomy P/A/B/C/D + diagnostics → Tasks 3 (A), 4 (C), 6 (B/P/diag), 8 (D). §5.1 non-gating soundness → Task 7 (leaf diagnostic + backstop). §5.2 determinism + env-specific bodies out of golden → Tasks 6 (type-only messages), 9 (order pin), 8 (CLI asserts names not bodies). §6.1 pure/impure split + `classify_import_error` seam → Tasks 3–8. §6.2 evict/import/walk/onerror/`__path__` → Task 7. §6.3 placement + over-match measurement → Task 4. §7 R2 marker + ceiling → Tasks 5, 8. §8 test pins (A, B1, B2, B2-walk, B-chain, P, B, C, D, attribution, determinism, clean) → distributed across Tasks 1,4,5,6,7,8,9. §9 non-goals → respected (no test execution, no scanner). §10 closures → Task 9.
- **B2 sound-backstop pin** ("submodule fails AND holds a declared boundary ⇒ category A"): covered by `test_force_import_leaf_failure_is_nongating_diagnostic` (registration survives) composed with `diff_boundaries` A logic; if a stricter end-to-end pin is wanted, add a fixture whose *only* boundary module is the broken one and assert reconcile yields both a diagnostic and category A. Add in Task 8 if the reviewer requires the literal composite.

**Placeholder scan:** the risk-row SHA in Task 9 is intentionally deferred to merge time (the commit doesn't exist yet); every code step carries complete code. No TBD/TODO in shipped code.

**Type consistency:** `Finding(category, identifier, message)` positional order is identical in every task. `force_import_package(package) -> list[Finding]`, `classify_import_error(module, exc, *, fatal=False)`, `reconcile(contract_path, package, test_paths) -> ReconcileResult`, `_reset_registry() -> None`, `UndeclaredBoundary(*, direction, name)` — signatures match between their defining task and every consumer.

**Known follow-up (not this plan):** the CLI reconcile subcommand adds no new public export; `contract_core/__init__.py` is untouched, so `test_public_api.py` stays green.
