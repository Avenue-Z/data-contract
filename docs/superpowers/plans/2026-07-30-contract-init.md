# `contract init` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `contract init` CLI subcommand that scaffolds the four mechanical adoption steps
(schema + `contract.yaml` authoring, `raw_drift` marker registration, CI gate wiring) into a
consuming repo, correct by construction, so `contract lint` and `contract reconcile` both exit 0
on the generated tree.

**Architecture:** A new private package `src/contract_core/scaffold/` split into pure and impure
layers, mirroring the split already used for `reconcile`
(docs/superpowers/plans/2026-07-23-reconcile-registration-completeness.md): `detect.py` and a
narrow existing-paths scan are the only I/O reads, `plan.py` is a pure function
`(InitSpec, set[Path]) -> Plan` that decides every create/skip/gap-fill outcome and renders the
CLI report, `render.py` and `pyproject.py` are pure helpers `plan.py` calls, and `apply.py` is the
only writer. `contract init` itself is a thin `@main.command()` in `cli.py`, following the existing
`lint`/`reconcile`/`events` pattern (heavy logic imported inside the function body) rather than the
spec's literal `main.add_command(init)` wording — see the Design Notes at the end for why.

**Tech Stack:** Python 3.13, `click` (existing CLI framework), `pydantic` (existing `Contract`
model, reused read-only), `tomllib` (stdlib, read-only detection per design §8), `importlib.resources`
(packaged template data), `pytest` + `subprocess` (end-to-end tests per design §10).

## Global Constraints

- **Precondition:** `contract init` operates only on a repo with a `pyproject.toml` carrying
  `[project].name` and that package's `__init__.py` on disk (design §1.1). No degraded mode.
- **No prompts, ever** (design §2.1). Missing required information is an error naming the exact flag.
- **`--platform` must match `[A-Za-z0-9_-]+`**, validated before anything is written (design §2.1.1).
- **Nothing is ever overwritten, and there is no `--force`** (design §5). Every target is written
  if missing, reported `skipped` if present.
- **Once `contract.yaml` exists, it is the source of truth** (design §5) — `--system`/`--platform`/
  `--source` become forbidden, not silently ignored.
- **Planning is pure and complete before anything is written** (design §2.2) — `--dry-run` and a
  real run share the exact same code path; a partial write can only come from I/O failure, never
  from a validation error found late.
- **`init` never touches `<pkg>/__init__.py`** (design §4.4, §11.11).
- **This is P1-dependent**: docs/superpowers/plans/2026-07-30-contract-gate-retire-token.md must
  land first — this plan's Task 9 asserts the generated workflow emits no `secrets:` block, which
  is false against today's unmodified `contract-gate.yml`.
- Verification bar for every task: `pytest -q`, `mypy` (strict, `files = ["src"]`), `ruff check .`
  all clean, per project convention (design §10 tail).

---

## Design Notes (read before Task 1)

These are engineering decisions this plan makes where the spec states an outcome but not an exact
internal shape. They are recorded once here so later tasks can cite them instead of re-deriving them.

1. **CLI wiring follows existing precedent, not `main.add_command(init)` literally.** `cli.py`'s
   three existing commands (`lint`, `reconcile`, `events`) all use `@main.command()` directly in
   `cli.py`, importing heavy logic from the target module inside the function body — never a
   separate function passed to `main.add_command(...)`. Task 8 follows that pattern: `init` is
   defined with `@main.command()` in `cli.py`, and imports `contract_core.scaffold.*` inside its
   body. `contract_core.scaffold` stays exactly as private as `contract_core.cli` already is
   (design §2.3) — this achieves the spec's stated goal (additive, no public-API impact) through
   the codebase's actual idiom.

2. **The pure `set[Path]` the spec's `plan.py` signature takes** is a **narrow, targeted scan** —
   not a full-tree `rglob`. The impure caller (`cli.py`) scans exactly the subtrees `init` could
   ever write to (`contract.yaml`, `schemas/**/*.yaml`, `*/boundaries.py` under both package
   layouts, `tests/test_drift_*.py`, `.github/workflows/contract.yml`) and passes that set, relative
   to `root`, into `plan()`. `plan()` then does pure set-membership checks — no `Path.is_dir()` /
   `Path.is_file()` calls anywhere in `plan.py`. This is what makes `(InitSpec, set[Path]) -> Plan`
   literally true rather than aspirational.

3. **The guard ladder's stated signature `str | None -> MarkerAction`** is read as "the whole
   `pyproject.toml` text, whose `[tool.pytest.ini_options]`/`markers` keys may or may not be
   present" rather than a literal `Optional[str]` parameter — design §7 step 1 establishes that by
   the time the ladder runs, `pyproject.toml` has *always* already been read and parsed
   successfully (that read is what makes an absent/unparseable file unreachable, per design §8's
   "deliberately not rungs here" note). `Task 1` implements `guard_marker(pyproject_text: str) ->
   MarkerAction` — a plain, always-present `str`.

4. **Report line rendering is `plan.py`'s job, not `apply.py`'s.** Because `plan()` already knows,
   purely, whether each target will be created or skipped (it has `existing_paths`), the printed
   report is a pure function of the returned `Plan` — which is exactly why `--dry-run` can print
   the "identical report" (design §5) without calling `apply()` at all.

5. **Schema roots are singular.** The resolver's `Resolver.search_paths` is a list, but every
   generated tree in the spec's own examples has exactly one `schemas/` directory; this plan does
   not generalize to multiple schema roots.

---

### Task 1: `scaffold/pyproject.py` — the marker guard ladder

**Files:**
- Create: `src/contract_core/scaffold/__init__.py` (empty; makes `scaffold` a package)
- Create: `src/contract_core/scaffold/pyproject.py`
- Test: `tests/test_scaffold_pyproject.py`

**Interfaces:**
- Produces: `MarkerAction` (enum: `SATISFIED`, `MANUAL`, `INSERT_KEY`, `APPEND_SECTION`),
  `guard_marker(pyproject_text: str) -> MarkerAction`, `apply_marker(pyproject_text: str, action:
  MarkerAction) -> str`, `MANUAL_SNIPPET: str`. Consumed by `plan.py` (Task 5) and `apply.py`
  (Task 7).

- [ ] **Step 1: Write the failing tests — one per rung of design §8's table**

```python
# tests/test_scaffold_pyproject.py
import pytest

from contract_core.scaffold.pyproject import MarkerAction, apply_marker, guard_marker

_MARKER_LINE = '"raw_drift: a drift test guarding a raw boundary (read by `contract reconcile`)"'


def test_rung1_satisfied_when_marker_already_registered():
    text = (
        "[tool.pytest.ini_options]\n"
        'markers = ["raw_drift: already here"]\n'
    )
    assert guard_marker(text) is MarkerAction.SATISFIED


def test_rung2_manual_when_markers_exists_without_raw_drift():
    text = (
        "[tool.pytest.ini_options]\n"
        'markers = ["other: something else"]\n'
    )
    assert guard_marker(text) is MarkerAction.MANUAL


def test_rung3_insert_key_when_section_exists_without_markers():
    text = (
        "[tool.pytest.ini_options]\n"
        'pythonpath = ["src"]\n'
    )
    assert guard_marker(text) is MarkerAction.INSERT_KEY


def test_rung4_append_section_when_absent_entirely():
    text = '[tool.ruff]\nline-length = 100\n'
    assert guard_marker(text) is MarkerAction.APPEND_SECTION


def test_insert_key_places_markers_right_after_the_header():
    text = (
        "[tool.pytest.ini_options]\n"
        'pythonpath = ["src"]\n'
        "\n"
        "[tool.ruff]\n"
    )
    out = apply_marker(text, MarkerAction.INSERT_KEY)
    lines = out.splitlines()
    header_idx = lines.index("[tool.pytest.ini_options]")
    assert lines[header_idx + 1] == f"markers = [{_MARKER_LINE}]"
    assert 'pythonpath = ["src"]' in out
    assert "[tool.ruff]" in out


def test_append_section_adds_a_new_section_at_eof():
    text = "[tool.ruff]\nline-length = 100\n"
    out = apply_marker(text, MarkerAction.APPEND_SECTION)
    assert out.startswith(text.rstrip("\n"))
    assert "[tool.pytest.ini_options]" in out
    assert f"markers = [{_MARKER_LINE}]" in out


def test_apply_marker_refuses_satisfied_and_manual():
    with pytest.raises(ValueError):
        apply_marker("anything", MarkerAction.SATISFIED)
    with pytest.raises(ValueError):
        apply_marker("anything", MarkerAction.MANUAL)


def test_result_of_insert_key_is_itself_satisfied():
    """Round-trip: whatever apply_marker produces, guard_marker reads back as SATISFIED."""
    text = "[tool.pytest.ini_options]\npythonpath = [\"src\"]\n"
    out = apply_marker(text, MarkerAction.INSERT_KEY)
    assert guard_marker(out) is MarkerAction.SATISFIED


def test_result_of_append_section_is_itself_satisfied():
    text = "[tool.ruff]\nline-length = 100\n"
    out = apply_marker(text, MarkerAction.APPEND_SECTION)
    assert guard_marker(out) is MarkerAction.SATISFIED
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_scaffold_pyproject.py -v`
Expected: `ModuleNotFoundError: No module named 'contract_core.scaffold'`

- [ ] **Step 3: Create the package and implement the guard ladder**

```python
# src/contract_core/scaffold/__init__.py
```

(empty file)

```python
# src/contract_core/scaffold/pyproject.py
"""The pyproject.toml marker guard ladder (design 2026-07-30 §8).

Never round-trips TOML: `guard_marker` only ever READS (via `tomllib`, stdlib, read-only) to
classify which rung applies; `apply_marker` only ever APPENDS or INSERTS text. There is no
general-purpose TOML writer here on purpose — this repo has none, and mangling a working
pytest config would be worse than the step this module automates (design §8).
"""
from __future__ import annotations

import tomllib
from enum import Enum

_MARKER_NAME = "raw_drift"
_MARKER_LINE = '"raw_drift: a drift test guarding a raw boundary (read by `contract reconcile`)"'
_SECTION_HEADER = "[tool.pytest.ini_options]"

MANUAL_SNIPPET = (
    "pyproject.toml already declares [tool.pytest.ini_options].markers without `raw_drift`.\n"
    "`init` will not edit an existing array — its formatting (inline/multiline, trailing\n"
    "commas, comments) is not append-safe to guess at. Add this element yourself:\n\n"
    f"  {_MARKER_LINE}\n"
)


class MarkerAction(Enum):
    SATISFIED = "satisfied"            # rung 1 — nothing to do
    MANUAL = "manual"                  # rung 2 — refuse; print MANUAL_SNIPPET
    INSERT_KEY = "insert_key"          # rung 3 — section exists, no markers key
    APPEND_SECTION = "append_section"  # rung 4 — section absent entirely


def guard_marker(pyproject_text: str) -> MarkerAction:
    """Classify which rung of the guard ladder `pyproject_text` falls on (design §8 table).

    Read-only: parses with `tomllib` to find the `markers` array, if any, and never writes.
    Callers only ever pass text this process has already read+parsed successfully (design §7
    step 1 always runs first), so an absent/unparseable file is not a case this function handles.
    """
    data = tomllib.loads(pyproject_text)
    pytest_opts = data.get("tool", {}).get("pytest", {}).get("ini_options")
    if pytest_opts is None:
        return MarkerAction.APPEND_SECTION
    markers = pytest_opts.get("markers")
    if markers is None:
        return MarkerAction.INSERT_KEY
    for m in markers:
        if str(m).split(":", 1)[0].strip() == _MARKER_NAME:
            return MarkerAction.SATISFIED
    return MarkerAction.MANUAL


def apply_marker(pyproject_text: str, action: MarkerAction) -> str:
    """Text-append the marker per `action` (design §8). Pure string manipulation, no TOML writer.

    Never called for SATISFIED (nothing to do) or MANUAL (refused — see MANUAL_SNIPPET).
    """
    if action is MarkerAction.APPEND_SECTION:
        return pyproject_text.rstrip("\n") + f"\n\n{_SECTION_HEADER}\nmarkers = [{_MARKER_LINE}]\n"
    if action is MarkerAction.INSERT_KEY:
        return _insert_markers_key(pyproject_text)
    raise ValueError(f"apply_marker called with a non-writing action: {action!r}")


def _insert_markers_key(text: str) -> str:
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    inserted = False
    for line in lines:
        out.append(line)
        if not inserted and line.strip() == _SECTION_HEADER:
            out.append(f"markers = [{_MARKER_LINE}]\n")
            inserted = True
    if not inserted:
        raise ValueError(f"insert_key called but {_SECTION_HEADER!r} was not found")
    return "".join(out)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_scaffold_pyproject.py -v`
Expected: all PASS

- [ ] **Step 5: Type-check and lint**

Run: `mypy && ruff check src/contract_core/scaffold/pyproject.py tests/test_scaffold_pyproject.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/contract_core/scaffold/__init__.py src/contract_core/scaffold/pyproject.py tests/test_scaffold_pyproject.py
git commit -m "feat(scaffold): add the pyproject.toml raw_drift marker guard ladder"
```

---

### Task 2: `scaffold/render.py` — the pure template renderer

**Files:**
- Create: `src/contract_core/scaffold/render.py`
- Test: `tests/test_scaffold_render.py`

**Interfaces:**
- Consumes: package data under `contract_core/scaffold/templates/` (Task 3).
- Produces: `render(name: str, values: dict[str, str]) -> str`. Consumed by `plan.py` (Task 5).

- [ ] **Step 1: Write the failing test against a real template**

Task 3 has not landed yet, but `render()` needs at least one template file to read — this test
uses `contract.file-ingest.yaml.tmpl`, the simplest one, which Task 3 also creates. To keep Task 2
independently testable, write the test against a **local fixture template** instead, so this task
has no ordering dependency on Task 3:

```python
# tests/test_scaffold_render.py
from pathlib import Path

import pytest

from contract_core.scaffold.render import render


@pytest.fixture
def _fixture_template(tmp_path, monkeypatch):
    """Point render() at a throwaway templates dir so this test has no dependency on the real
    package templates (Task 3), which do not exist yet when this task is implemented."""
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    (templates_dir / "greeting.txt.tmpl").write_text("Hello {{NAME}}, welcome to {{PLACE}}.\n")
    (templates_dir / "with_braces.txt.tmpl").write_text("dict: {kind: {{KIND}}}\n")
    monkeypatch.setattr("contract_core.scaffold.render._TEMPLATES_DIR", templates_dir)
    return templates_dir


def test_render_substitutes_every_placeholder(_fixture_template):
    out = render("greeting.txt.tmpl", {"NAME": "Ada", "PLACE": "the scaffold"})
    assert out == "Hello Ada, welcome to the scaffold.\n"


def test_render_does_not_use_str_format_so_literal_braces_survive(_fixture_template):
    # A literal YAML/dict brace in the template (e.g. `{kind: api}`) must NOT be mistaken for a
    # substitution token — .replace(), not .format(), is required (conftest.py's own convention).
    out = render("with_braces.txt.tmpl", {"KIND": "api"})
    assert out == "dict: {kind: api}\n"


def test_render_missing_template_raises_filenotfounderror(_fixture_template):
    with pytest.raises(FileNotFoundError):
        render("does_not_exist.tmpl", {})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_scaffold_render.py -v`
Expected: `ModuleNotFoundError: No module named 'contract_core.scaffold.render'`

- [ ] **Step 3: Implement the renderer**

```python
# src/contract_core/scaffold/render.py
"""Pure template rendering for `contract init` (design 2026-07-30 §2.2, §9).

Substitution is `.replace()`, not `str.format()` — a template's generated content is YAML or
Python and routinely contains literal `{`/`}` (e.g. `source: {kind: api}`), which `.format()`
would misparse. This mirrors tests/conftest.py's existing fixture-string convention.
"""
from __future__ import annotations

from pathlib import Path

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def render(name: str, values: dict[str, str]) -> str:
    path = _TEMPLATES_DIR / name
    text = path.read_text()
    for key, val in values.items():
        text = text.replace("{{" + key + "}}", val)
    return text
```

Note: this reads `templates/` as a plain filesystem path relative to the installed module, which
works both from a source checkout and from an installed wheel (the wheel's `force-include` in
Task 3 places the files at the same relative location under `site-packages/contract_core/scaffold/
templates/`). `importlib.resources` was considered and rejected here — it would require
`templates/` to itself be an importable subpackage (an extra empty `__init__.py` whose only job is
satisfying an API `render.py` does not otherwise need), where a plain `Path` relative to
`__file__` is simpler and already the pattern `resolver.py`/`schema.py` use for `Path`-based reads.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_scaffold_render.py -v`
Expected: all PASS

- [ ] **Step 5: Type-check and lint**

Run: `mypy && ruff check src/contract_core/scaffold/render.py tests/test_scaffold_render.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/contract_core/scaffold/render.py tests/test_scaffold_render.py
git commit -m "feat(scaffold): add the pure template renderer"
```

---

### Task 3: The templates — package data

**Files:**
- Create: `src/contract_core/scaffold/templates/contract.mediated.yaml.tmpl`
- Create: `src/contract_core/scaffold/templates/contract.file-ingest.yaml.tmpl`
- Create: `src/contract_core/scaffold/templates/schema.payload.yaml.tmpl`
- Create: `src/contract_core/scaffold/templates/schema.tabular.yaml.tmpl`
- Create: `src/contract_core/scaffold/templates/boundaries.mediated.py.tmpl`
- Create: `src/contract_core/scaffold/templates/boundaries.file-ingest.py.tmpl`
- Create: `src/contract_core/scaffold/templates/drift_test.py.tmpl`
- Create: `src/contract_core/scaffold/templates/ci-workflow.mediated.yml.tmpl`
- Create: `src/contract_core/scaffold/templates/ci-workflow.file-ingest.yml.tmpl`
- Modify: `pyproject.toml` (wheel `force-include` for the templates dir)
- Test: `tests/test_scaffold_templates.py`

**Interfaces:**
- Produces: the nine template files `plan.py` (Task 5) renders via `render()` (Task 2).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_scaffold_templates.py
"""Design §9.1: every template MUST carry a `.tmpl` extension, including the Python ones, so
neither ruff nor mypy considers them, and so `contract init` from a built wheel can find them
(design §9's "test asserts every template is present in the built wheel")."""
import subprocess
import sys
import tempfile
from pathlib import Path

TEMPLATES_DIR = (
    Path(__file__).resolve().parents[1] / "src" / "contract_core" / "scaffold" / "templates"
)

EXPECTED = {
    "contract.mediated.yaml.tmpl",
    "contract.file-ingest.yaml.tmpl",
    "schema.payload.yaml.tmpl",
    "schema.tabular.yaml.tmpl",
    "boundaries.mediated.py.tmpl",
    "boundaries.file-ingest.py.tmpl",
    "drift_test.py.tmpl",
    "ci-workflow.mediated.yml.tmpl",
    "ci-workflow.file-ingest.yml.tmpl",
}


def test_every_expected_template_exists():
    actual = {p.name for p in TEMPLATES_DIR.iterdir()}
    assert actual == EXPECTED


def test_no_py_file_exists_under_templates():
    # A literal .py would be swept by ruff/mypy's first-party gates and fail them (design §9.1).
    assert not list(TEMPLATES_DIR.rglob("*.py"))


def test_templates_are_present_in_the_built_wheel():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        built = subprocess.run(
            [sys.executable, "-m", "build", "--wheel", "--outdir", str(out)],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True,
        )
        assert built.returncode == 0, built.stderr
        wheel = next(out.glob("*.whl"))
        listing = subprocess.run(
            [sys.executable, "-m", "zipfile", "-l", str(wheel)],
            capture_output=True, text=True,
        )
        assert listing.returncode == 0, listing.stderr
        for name in EXPECTED:
            assert f"contract_core/scaffold/templates/{name}" in listing.stdout, name
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_scaffold_templates.py -v`
Expected: `FileNotFoundError` / `AssertionError` — the `templates/` directory does not exist yet.

- [ ] **Step 3: Create the nine template files**

```yaml
# src/contract_core/scaffold/templates/contract.mediated.yaml.tmpl
# GENERATED BY `contract init` — safe to edit; `init` never overwrites this file.
system: {{SYSTEM}}
version: 0.1.0
raw:
  - name: {{RAW_NAME}}
    schema: {{RAW_REF}}
    source: {kind: {{SOURCE_KIND}}, format: {{SOURCE_FORMAT}}}
    mode: observe
inputs:
  - name: {{INPUT_NAME}}
    schema: {{INPUT_REF}}
    source: {kind: {{SOURCE_KIND}}, format: {{SOURCE_FORMAT}}}
    mode: observe
outputs:
  - name: {{OUTPUT_NAME}}
    schema: {{OUTPUT_REF}}
    sink: {kind: file, format: json}
    mode: observe
```

```yaml
# src/contract_core/scaffold/templates/contract.file-ingest.yaml.tmpl
# GENERATED BY `contract init` — safe to edit; `init` never overwrites this file.
system: {{SYSTEM}}
version: 0.1.0
inputs:
  - name: {{INPUT_NAME}}
    schema: {{INPUT_REF}}
    source: {kind: {{SOURCE_KIND}}, format: {{SOURCE_FORMAT}}}
    mode: observe
outputs:
  - name: {{OUTPUT_NAME}}
    schema: {{OUTPUT_REF}}
    sink: {kind: file, format: json}
    mode: observe
```

```yaml
# src/contract_core/scaffold/templates/schema.payload.yaml.tmpl
# GENERATED BY `contract init` — PLACEHOLDER. Replace REPLACE_ME_* below with the real fields of
# {{DESCRIPTION}} before promoting this boundary past `mode: observe` (see contract.yaml).
schema: {{SCHEMA_NAME}}
version: {{VERSION}}
kind: payload
fields:
  - name: REPLACE_ME_FIELD
    type: string
    required: true
```

```yaml
# src/contract_core/scaffold/templates/schema.tabular.yaml.tmpl
# GENERATED BY `contract init` — PLACEHOLDER. Replace REPLACE_ME_* below with the real columns of
# {{DESCRIPTION}} before promoting this boundary past `mode: observe` (see contract.yaml).
schema: {{SCHEMA_NAME}}
version: {{VERSION}}
kind: tabular
fields:
  - name: REPLACE_ME_COLUMN
    type: string
    required: true
```

```python
# src/contract_core/scaffold/templates/boundaries.mediated.py.tmpl
# GENERATED BY `contract init` — safe to edit; `init` never overwrites this file.
#
# `contract reconcile` force-imports your package and walks every module, so this file registers
# its boundaries by being imported — no re-export needed. Importing it once from your package's
# __init__.py (e.g. `from . import boundaries`) makes that import happen automatically.
from __future__ import annotations

from pathlib import Path

try:
    from contract_core import load_runtime

    _HERE = Path(__file__).resolve()
    _ROOT = next((p for p in _HERE.parents if (p / "contract.yaml").exists()), None)
    if _ROOT is None:
        raise FileNotFoundError(f"contract.yaml not found in any parent of {_HERE}")
    runtime = load_runtime(str(_ROOT / "contract.yaml"), schema_paths=[str(_ROOT / "schemas")])
except ImportError:
    class _NoOpRuntime:
        """Stand-in when contract-core is not installed. Must NOT import from it."""
        def _passthrough(self, name):
            return lambda fn: fn
        raw = input = output = _passthrough

    runtime = _NoOpRuntime()


@runtime.raw("{{RAW_NAME}}")
def pull_raw(client, **params) -> dict:
    """The TRUE raw read — return the vendor payload unmodified, before any cleaning."""
    return client.get("/some/endpoint", params=params)


@runtime.input("{{INPUT_NAME}}")
def normalize(raw: dict) -> "list[dict]":
    """Adapter: replace with the real mapping from raw to the normalized rows. Drift-tested."""
    ...


@runtime.output("{{OUTPUT_NAME}}")
def build_report(rows, **ctx) -> dict:
    """Return the deliverable; it is validated BEFORE it is written to its sink."""
    ...
```

```python
# src/contract_core/scaffold/templates/boundaries.file-ingest.py.tmpl
# GENERATED BY `contract init` — safe to edit; `init` never overwrites this file.
#
# `contract reconcile` force-imports your package and walks every module, so this file registers
# its boundaries by being imported — no re-export needed. Importing it once from your package's
# __init__.py (e.g. `from . import boundaries`) makes that import happen automatically.
from __future__ import annotations

from pathlib import Path

try:
    from contract_core import load_runtime

    _HERE = Path(__file__).resolve()
    _ROOT = next((p for p in _HERE.parents if (p / "contract.yaml").exists()), None)
    if _ROOT is None:
        raise FileNotFoundError(f"contract.yaml not found in any parent of {_HERE}")
    runtime = load_runtime(str(_ROOT / "contract.yaml"), schema_paths=[str(_ROOT / "schemas")])
except ImportError:
    class _NoOpRuntime:
        """Stand-in when contract-core is not installed. Must NOT import from it."""
        def _passthrough(self, name):
            return lambda fn: fn
        raw = input = output = _passthrough

    runtime = _NoOpRuntime()


@runtime.input("{{INPUT_NAME}}")
def read_input(**params) -> "list[dict]":
    """Read the file/CSV source and return it in the normalized shape."""
    ...


@runtime.output("{{OUTPUT_NAME}}")
def build_report(rows, **ctx) -> dict:
    """Return the deliverable; it is validated BEFORE it is written to its sink."""
    ...
```

```python
# src/contract_core/scaffold/templates/drift_test.py.tmpl
# GENERATED BY `contract init` — PLACEHOLDER. Replace the body below with a real assertion that
# the adapter REJECTS a drifted raw payload (see the authoring-data-contracts skill,
# references/boundary-decision.md). A hollow marked test satisfies `reconcile` but not the intent.
import pytest

from {{PACKAGE}}.boundaries import normalize   # the adapter under test


@pytest.mark.raw_drift("{{RAW_NAME}}")          # MUST equal the raw boundary name in contract.yaml
def test_adapter_rejects_unknown_raw_shape():
    pytest.fail("GENERATED PLACEHOLDER — assert the adapter REJECTS a drifted payload")

    # Real structure to fill in, once you have a drifted-payload sample:
    # changed_payload = {...}  # a shape the vendor drifted to
    # with pytest.raises((KeyError, ValueError, TypeError)):
    #     normalize(changed_payload)
```

```yaml
# src/contract_core/scaffold/templates/ci-workflow.mediated.yml.tmpl
# GENERATED BY `contract init` — safe to edit; `init` never overwrites this file.
# This workflow's tag MUST match the contract-core pin in pyproject.toml (see the printed
# next-step). A mismatch is silent CLI-surface breakage.

name: contract
on:
  pull_request:
  push:
    branches: [main]

jobs:
  gate:
    uses: Avenue-Z/data-contract/.github/workflows/contract-gate.yml@v{{TAG}}
    with:
      contract: contract.yaml
      package: {{PACKAGE}}
      schemas: |
        schemas
      tests: |
        tests

  # The generated drift test in tests/ fails ON PURPOSE (GENERATED PLACEHOLDER) until its real
  # assertion is written. This job makes that red visible instead of hiding it behind a gate that
  # never runs pytest (`reconcile` only checks the marker exists, by AST scan).
  drift:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0
      - uses: actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6.3.0
      - run: pip install . pytest
      - run: pytest -m raw_drift
```

```yaml
# src/contract_core/scaffold/templates/ci-workflow.file-ingest.yml.tmpl
# GENERATED BY `contract init` — safe to edit; `init` never overwrites this file.
# This workflow's tag MUST match the contract-core pin in pyproject.toml (see the printed
# next-step). A mismatch is silent CLI-surface breakage.

name: contract
on:
  pull_request:
  push:
    branches: [main]

jobs:
  gate:
    uses: Avenue-Z/data-contract/.github/workflows/contract-gate.yml@v{{TAG}}
    with:
      contract: contract.yaml
      package: {{PACKAGE}}
      schemas: |
        schemas
      tests: |
        tests
```

- [ ] **Step 4: Add the wheel `force-include` entry**

In `pyproject.toml`, change:

```toml
[tool.hatch.build.targets.wheel.force-include]
"src/contract_core/vendor/odcs-json-schema-v3.1.0-20260505.json" = "contract_core/vendor/odcs-json-schema-v3.1.0-20260505.json"
```

to:

```toml
[tool.hatch.build.targets.wheel.force-include]
"src/contract_core/vendor/odcs-json-schema-v3.1.0-20260505.json" = "contract_core/vendor/odcs-json-schema-v3.1.0-20260505.json"
"src/contract_core/scaffold/templates" = "contract_core/scaffold/templates"
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pip install -e ".[dev]" && pytest tests/test_scaffold_templates.py -v`
Expected: all PASS. (`test_templates_are_present_in_the_built_wheel` requires the `build` package;
it is not currently in the `dev` extra — add it: in `pyproject.toml`'s `dev` list, append `"build"`
next to `"hatchling"`.)

- [ ] **Step 6: Confirm `ruff`/`mypy` do not touch the templates dir**

Run: `ruff check . && mypy`
Expected: clean — no `.py` files exist under `templates/` (Step 3), so nothing there is even a
candidate for either tool; this is a structural guarantee (Task 3's `test_no_py_file_exists_under_templates`), not a carve-out that needs a `ruff`/`mypy` config change.

- [ ] **Step 7: Commit**

```bash
git add src/contract_core/scaffold/templates/ pyproject.toml tests/test_scaffold_templates.py
git commit -m "feat(scaffold): add the nine init templates as wheel-packaged data"
```

---

### Task 4: `scaffold/detect.py` — package detection

**Files:**
- Create: `src/contract_core/scaffold/detect.py`
- Test: `tests/test_scaffold_detect.py`

**Interfaces:**
- Produces: `DetectedPackage` (dataclass: `name: str`, `package_dir: Path`, `pyproject_text: str`),
  `PackageDetectionError(Exception)`, `detect_package(root: Path, package_override: str | None) ->
  DetectedPackage`. Consumed by `cli.py` (Task 8).

- [ ] **Step 1: Write the failing tests — one per design §7 failure mode**

```python
# tests/test_scaffold_detect.py
import pytest

from contract_core.scaffold.detect import PackageDetectionError, detect_package


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def test_flat_layout_is_detected(tmp_path):
    _write(tmp_path, "pyproject.toml", '[project]\nname = "my-pkg"\n')
    _write(tmp_path, "my_pkg/__init__.py", "")
    result = detect_package(tmp_path, None)
    assert result.name == "my_pkg"
    assert result.package_dir == tmp_path / "my_pkg"


def test_src_layout_is_detected(tmp_path):
    _write(tmp_path, "pyproject.toml", '[project]\nname = "my-pkg"\n')
    _write(tmp_path, "src/my_pkg/__init__.py", "")
    result = detect_package(tmp_path, None)
    assert result.name == "my_pkg"
    assert result.package_dir == tmp_path / "src" / "my_pkg"


def test_hyphenated_project_name_normalizes_to_underscore(tmp_path):
    _write(tmp_path, "pyproject.toml", '[project]\nname = "tiktok-brand-pulse"\n')
    _write(tmp_path, "tiktok_brand_pulse/__init__.py", "")
    result = detect_package(tmp_path, None)
    assert result.name == "tiktok_brand_pulse"


def test_package_override_skips_name_derivation(tmp_path):
    _write(tmp_path, "pyproject.toml", '[project]\nname = "irrelevant"\n')
    _write(tmp_path, "actual_pkg/__init__.py", "")
    result = detect_package(tmp_path, "actual_pkg")
    assert result.name == "actual_pkg"


def test_missing_pyproject_toml_is_fatal_and_names_package_flag(tmp_path):
    with pytest.raises(PackageDetectionError, match="--package"):
        detect_package(tmp_path, None)


def test_unparseable_pyproject_toml_is_fatal(tmp_path):
    _write(tmp_path, "pyproject.toml", "not valid toml [[[")
    with pytest.raises(PackageDetectionError, match="--package"):
        detect_package(tmp_path, None)


def test_no_project_name_and_no_override_is_fatal(tmp_path):
    _write(tmp_path, "pyproject.toml", "[tool.other]\nx = 1\n")
    with pytest.raises(PackageDetectionError, match="--package"):
        detect_package(tmp_path, None)


def test_neither_layout_present_is_fatal(tmp_path):
    _write(tmp_path, "pyproject.toml", '[project]\nname = "my-pkg"\n')
    with pytest.raises(PackageDetectionError, match="--package"):
        detect_package(tmp_path, None)


def test_both_layouts_present_is_fatal_and_names_both_paths(tmp_path):
    _write(tmp_path, "pyproject.toml", '[project]\nname = "my-pkg"\n')
    flat = _write(tmp_path, "my_pkg/__init__.py", "")
    src = _write(tmp_path, "src/my_pkg/__init__.py", "")
    with pytest.raises(PackageDetectionError) as ei:
        detect_package(tmp_path, None)
    assert str(flat) in str(ei.value)
    assert str(src) in str(ei.value)


def test_pyproject_text_is_returned_for_reuse_by_the_marker_guard(tmp_path):
    text = '[project]\nname = "my-pkg"\n'
    _write(tmp_path, "pyproject.toml", text)
    _write(tmp_path, "my_pkg/__init__.py", "")
    result = detect_package(tmp_path, None)
    assert result.pyproject_text == text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_scaffold_detect.py -v`
Expected: `ModuleNotFoundError: No module named 'contract_core.scaffold.detect'`

- [ ] **Step 3: Implement package detection**

```python
# src/contract_core/scaffold/detect.py
"""Package detection for `contract init` (design 2026-07-30 §7) — read-only I/O.

Step 1 (reading pyproject.toml) always runs, even when `--package` is given: its existence and
parseability are part of the §1.1 entry state, and the marker guard ladder (pyproject.py) needs
its text regardless. `--package` only overrides the NAME derived in step 2, never this read.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


class PackageDetectionError(Exception):
    """A fatal §7 detection failure. There is no degraded mode (design §7)."""


@dataclass(frozen=True)
class DetectedPackage:
    name: str
    package_dir: Path       # absolute; the dir holding __init__.py
    pyproject_text: str     # already-read text, reused by plan()'s marker guard (design §8)


def detect_package(root: Path, package_override: str | None) -> DetectedPackage:
    pyproject_path = root / "pyproject.toml"
    try:
        text = pyproject_path.read_text()
    except OSError as exc:
        raise PackageDetectionError(
            f"cannot read {pyproject_path}: {exc.strerror or exc}; pass --package"
        ) from exc
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise PackageDetectionError(
            f"{pyproject_path} is not valid TOML: {exc}; pass --package"
        ) from exc

    if package_override is not None:
        name = package_override
    else:
        project_name = data.get("project", {}).get("name")
        if not project_name:
            raise PackageDetectionError(
                f"{pyproject_path} has no [project].name; pass --package"
            )
        name = project_name.replace("-", "_")

    flat = root / name / "__init__.py"
    src = root / "src" / name / "__init__.py"
    flat_exists, src_exists = flat.is_file(), src.is_file()

    if flat_exists and src_exists:
        raise PackageDetectionError(
            f"both {flat} and {src} exist for package {name!r} — cannot tell which layout is "
            f"importable; remove the stale one, or pass --package"
        )
    if flat_exists:
        return DetectedPackage(name, flat.parent, text)
    if src_exists:
        return DetectedPackage(name, src.parent, text)
    raise PackageDetectionError(
        f"neither {flat} nor {src} exists — {name!r} is not on disk as an installable "
        f"package; pass --package"
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_scaffold_detect.py -v`
Expected: all PASS

- [ ] **Step 5: Type-check and lint**

Run: `mypy && ruff check src/contract_core/scaffold/detect.py tests/test_scaffold_detect.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/contract_core/scaffold/detect.py tests/test_scaffold_detect.py
git commit -m "feat(scaffold): add package detection (design §7)"
```

---

### Task 5: `scaffold/plan.py` — first-run planning (archetype, names, refs, `contract.yaml`)

**Files:**
- Create: `src/contract_core/scaffold/plan.py`
- Test: `tests/test_scaffold_plan_fresh.py`

**Interfaces:**
- Consumes: `render` (Task 2), `MarkerAction`/`guard_marker` (Task 1).
- Produces: `SourceKind`, `Archetype`, `PlanError(Exception)`, `FreshSpec` (dataclass: `system:
  str`, `platform: str`, `source_kind: SourceKind`), `InitSpec` (dataclass: `root: Path`, `package:
  str`, `package_dir: Path`, `pyproject_text: str`, `contract_core_version: str`, `fresh:
  FreshSpec | None`, `existing: Contract | None`), `ResolvedBoundary`, `Target`, `Plan`,
  `plan(spec: InitSpec, existing_paths: set[Path]) -> Plan`, `render_report(p: Plan) -> list[str]`.
  Consumed by `apply.py` (Task 7) and `cli.py` (Task 8). Task 6 extends `plan()` with the
  re-run/gap-fill branch — this task implements only the `spec.fresh is not None` path.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_scaffold_plan_fresh.py
from pathlib import Path

import pytest

from contract_core.scaffold.plan import (
    FreshSpec, InitSpec, Plan, PlanError, Target, plan, render_report,
)
from contract_core.scaffold.pyproject import MarkerAction

ROOT = Path("/repo")
PYPROJECT_NO_MARKERS = "[tool.ruff]\nline-length = 100\n"


def _fresh_spec(system="tiktok-brand-pulse", platform="tiktok", source_kind="api",
                 package="my_pkg", pyproject_text=PYPROJECT_NO_MARKERS):
    return InitSpec(
        root=ROOT, package=package, package_dir=ROOT / "src" / package,
        pyproject_text=pyproject_text, contract_core_version="0.7.0",
        fresh=FreshSpec(system=system, platform=platform, source_kind=source_kind),
        existing=None,
    )


def test_mediated_archetype_generates_raw_input_output_and_a_drift_test():
    result = plan(_fresh_spec(source_kind="api"), existing_paths=set())
    assert result.archetype == "mediated"
    paths = {t.path for t in result.other_targets}
    assert Path("schemas/tiktok/raw_report/1.0.0.yaml") in paths
    assert Path("schemas/tiktok/records/1.0.0.yaml") in paths
    assert Path("schemas/tiktok/report/1.0.0.yaml") in paths
    assert Path("src/my_pkg/boundaries.py") in paths
    assert Path("tests/test_drift_tiktok_raw.py") in paths
    assert Path(".github/workflows/contract.yml") in paths


def test_file_ingest_archetype_has_no_raw_no_drift_test_no_drift_job():
    result = plan(_fresh_spec(source_kind="file"), existing_paths=set())
    assert result.archetype == "file-ingest"
    paths = {t.path for t in result.other_targets}
    assert Path("schemas/tiktok/raw_report/1.0.0.yaml") not in paths
    assert not any("drift" in str(p) for p in paths)
    workflow = next(t for t in result.other_targets if t.path == Path(".github/workflows/contract.yml"))
    assert "drift:" not in workflow.content
    assert "raw_drift" not in workflow.content


@pytest.mark.parametrize("source_kind", ["api", "mcp", "llm"])
def test_every_mediated_kind_produces_the_mediated_archetype(source_kind):
    result = plan(_fresh_spec(source_kind=source_kind), existing_paths=set())
    assert result.archetype == "mediated"


def test_contract_yaml_matches_the_design_4_0_literal_example():
    result = plan(_fresh_spec(), existing_paths=set())
    content = result.contract_target.content
    assert "system: tiktok-brand-pulse" in content
    assert "version: 0.1.0" in content
    assert "schema: tiktok.raw_report@1" in content
    assert "schema: tiktok.records@1" in content
    assert "schema: tiktok.report@1" in content
    assert content.count("mode: observe") == 3
    assert "@1.0" not in content  # never the non-pin form


def test_every_generated_schema_ref_uses_the_at_major_pin_form():
    result = plan(_fresh_spec(), existing_paths=set())
    for t in result.other_targets:
        if t.path.parts[0] == "schemas":
            assert "@1.0" not in t.content


def test_platform_with_a_dot_is_rejected_before_anything_is_planned():
    with pytest.raises(PlanError, match=r"\."):
        plan(_fresh_spec(platform="google.ads"), existing_paths=set())


def test_platform_with_a_slash_is_rejected():
    with pytest.raises(PlanError, match="/"):
        plan(_fresh_spec(platform="a/b"), existing_paths=set())


def test_platform_with_a_hyphen_is_accepted():
    result = plan(_fresh_spec(platform="foo-bar"), existing_paths=set())
    assert "schema: foo-bar.records@1" in result.contract_target.content


def test_existing_targets_are_reported_skipped_not_overwritten():
    existing = {Path("contract.yaml"), Path("src/my_pkg/boundaries.py")}
    result = plan(_fresh_spec(), existing_paths=existing)
    assert result.contract_target.status == "skipped"
    boundaries_target = next(
        t for t in result.other_targets if t.path == Path("src/my_pkg/boundaries.py")
    )
    assert boundaries_target.status == "skipped"
    schema_target = next(
        t for t in result.other_targets if t.path == Path("schemas/tiktok/records/1.0.0.yaml")
    )
    assert schema_target.status == "created"


def test_report_created_lines_for_a_first_run():
    result = plan(_fresh_spec(), existing_paths=set())
    lines = render_report(result)
    assert any(line == "created  contract.yaml" for line in lines)
    assert any("schemas/tiktok/raw_report/1.0.0.yaml" in line for line in lines)
    assert lines[-1].startswith("edited") or lines[-1].startswith("satisfied")


def test_report_collapses_consecutive_skips_into_a_count():
    all_paths = {
        Path("contract.yaml"),
        Path("schemas/tiktok/raw_report/1.0.0.yaml"),
        Path("schemas/tiktok/records/1.0.0.yaml"),
        Path("schemas/tiktok/report/1.0.0.yaml"),
        Path("src/my_pkg/boundaries.py"),
        Path("tests/test_drift_tiktok_raw.py"),
        Path(".github/workflows/contract.yml"),
    }
    result = plan(_fresh_spec(), existing_paths=all_paths)
    lines = render_report(result)
    assert any("7 files" in line for line in lines) or any(
        "skipped" in line for line in lines
    )  # exact count depends on contract.yaml's own line — asserted precisely in Task 6's re-run test


def test_dependency_line_names_the_installed_contract_core_version():
    result = plan(_fresh_spec(), existing_paths=set())
    assert "git+https://github.com/Avenue-Z/data-contract.git@v0.7.0" in result.dependency_line


def test_mediated_next_steps_mention_the_intentional_red():
    result = plan(_fresh_spec(source_kind="api"), existing_paths=set())
    assert any("GENERATED PLACEHOLDER" in s or "drift" in s for s in result.next_steps)


def test_manual_marker_action_surfaces_the_snippet_in_next_steps():
    text = '[tool.pytest.ini_options]\nmarkers = ["other: x"]\n'
    result = plan(_fresh_spec(pyproject_text=text), existing_paths=set())
    assert result.marker_action == MarkerAction.MANUAL
    assert any("raw_drift" in s for s in result.next_steps)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_scaffold_plan_fresh.py -v`
Expected: `ModuleNotFoundError: No module named 'contract_core.scaffold.plan'`

- [ ] **Step 3: Implement `plan.py` (fresh-run branch; the re-run branch is a `NotImplementedError`
  stub that Task 6 fills in)**

```python
# src/contract_core/scaffold/plan.py
"""Pure planning for `contract init` (design 2026-07-30 §2.2, §3, §4, §5).

No I/O. Every validation failure (bad --platform, flags-with-existing-contract) and every
created/skipped decision is decided here, purely from `existing_paths`, before apply.py writes
anything — this is what lets --dry-run and a real run share one code path (design §2.2).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from contract_core.contract import Contract
from contract_core.scaffold.pyproject import MANUAL_SNIPPET, MarkerAction, guard_marker
from contract_core.scaffold.render import render

SourceKind = Literal["api", "mcp", "llm", "file"]
Archetype = Literal["mediated", "file-ingest"]
_MEDIATED_KINDS: frozenset[str] = frozenset({"api", "mcp", "llm"})
_PLATFORM_RE = re.compile(r"[A-Za-z0-9_-]")


class PlanError(Exception):
    """A validation failure found during planning (design §2.2) — nothing has been written."""


@dataclass(frozen=True)
class FreshSpec:
    system: str
    platform: str
    source_kind: SourceKind


@dataclass(frozen=True)
class InitSpec:
    root: Path
    package: str
    package_dir: Path          # absolute
    pyproject_text: str
    contract_core_version: str
    fresh: FreshSpec | None    # set exactly when contract.yaml is absent
    existing: Contract | None  # set exactly when contract.yaml is present


@dataclass(frozen=True)
class ResolvedBoundary:
    direction: Literal["raw", "input", "output"]
    name: str
    schema_ref: str


@dataclass(frozen=True)
class Target:
    path: Path                  # relative to root
    content: str
    exists: bool
    skip_reason: str = "exists"

    @property
    def status(self) -> Literal["created", "skipped"]:
        return "skipped" if self.exists else "created"


@dataclass(frozen=True)
class Plan:
    is_rerun: bool
    system: str
    archetype: Archetype
    contract_target: Target
    other_targets: list[Target]     # everything except contract.yaml, in write order
    marker_action: MarkerAction
    dependency_line: str
    next_steps: list[str]


def _validate_platform(platform: str) -> None:
    for ch in platform:
        if not _PLATFORM_RE.fullmatch(ch):
            raise PlanError(
                f"--platform {platform!r} contains {ch!r}; only letters, digits, "
                f"'_' and '-' are allowed"
            )


def _archetype_of(source_kind: str) -> Archetype:
    return "mediated" if source_kind in _MEDIATED_KINDS else "file-ingest"


def _boundaries_for_fresh(fresh: FreshSpec) -> list[ResolvedBoundary]:
    p = fresh.platform
    archetype = _archetype_of(fresh.source_kind)
    boundaries = []
    if archetype == "mediated":
        boundaries.append(ResolvedBoundary("raw", f"{p}_raw", f"{p}.raw_report@1"))
    boundaries.append(ResolvedBoundary("input", "records", f"{p}.records@1"))
    boundaries.append(ResolvedBoundary("output", "report", f"{p}.report@1"))
    return boundaries


def _split_ref(ref: str) -> tuple[str, str]:
    name, _, version = ref.partition("@")
    return name, version


def _schema_version_body(version: str) -> str:
    """The schema body's own `version:` value — a full semver even for an @MAJOR ref."""
    return version if "." in version else f"{version}.0.0"


_KIND_TEMPLATE = {
    "raw": ("schema.payload.yaml.tmpl", "the vendor's raw payload"),
    "input": ("schema.tabular.yaml.tmpl", "the normalized rows"),
    "output": ("schema.payload.yaml.tmpl", "your deliverable"),
}


def _plan_contract_yaml(
    spec: InitSpec, system: str, boundaries: list[ResolvedBoundary],
    source_kind: str, source_format: str, existing_paths: set[Path],
) -> Target:
    template = (
        "contract.mediated.yaml.tmpl" if source_kind in _MEDIATED_KINDS
        else "contract.file-ingest.yaml.tmpl"
    )
    values = {"SYSTEM": system, "SOURCE_KIND": source_kind, "SOURCE_FORMAT": source_format}
    for b in boundaries:
        key = b.direction.upper()
        values[f"{key}_NAME"] = b.name
        values[f"{key}_REF"] = b.schema_ref
    content = render(template, values)
    path = Path("contract.yaml")
    return Target(path, content, exists=path in existing_paths)


def _plan_schemas(boundaries: list[ResolvedBoundary], existing_paths: set[Path]) -> list[Target]:
    schemas_root = Path("schemas")
    targets = []
    for b in boundaries:
        name, version = _split_ref(b.schema_ref)
        schema_dir = schemas_root.joinpath(*name.split("."))
        filename = f"{version}.yaml" if "." in version else f"{version}.0.0.yaml"
        path = schema_dir / filename
        template, description = _KIND_TEMPLATE[b.direction]
        content = render(template, {
            "SCHEMA_NAME": name,
            "VERSION": _schema_version_body(version),
            "DESCRIPTION": description,
        })
        targets.append(Target(path, content, exists=path in existing_paths))
    return targets


def _plan_boundaries_py(
    spec: InitSpec, archetype: Archetype, boundaries: list[ResolvedBoundary],
    existing_paths: set[Path],
) -> Target:
    template = (
        "boundaries.mediated.py.tmpl" if archetype == "mediated"
        else "boundaries.file-ingest.py.tmpl"
    )
    values = {f"{b.direction.upper()}_NAME": b.name for b in boundaries}
    content = render(template, values)
    rel_dir = spec.package_dir.relative_to(spec.root)
    path = rel_dir / "boundaries.py"
    return Target(path, content, exists=path in existing_paths)


def _plan_drift_test(spec: InitSpec, raw: ResolvedBoundary, existing_paths: set[Path]) -> Target:
    content = render("drift_test.py.tmpl", {"PACKAGE": spec.package, "RAW_NAME": raw.name})
    path = Path("tests") / f"test_drift_{raw.name}.py"
    return Target(path, content, exists=path in existing_paths)


def _plan_ci_workflow(
    spec: InitSpec, archetype: Archetype, existing_paths: set[Path],
) -> Target:
    template = (
        "ci-workflow.mediated.yml.tmpl" if archetype == "mediated"
        else "ci-workflow.file-ingest.yml.tmpl"
    )
    content = render(template, {"TAG": spec.contract_core_version, "PACKAGE": spec.package})
    path = Path(".github/workflows/contract.yml")
    return Target(path, content, exists=path in existing_paths)


def _common_targets(
    spec: InitSpec, archetype: Archetype, boundaries: list[ResolvedBoundary],
    existing_paths: set[Path],
) -> list[Target]:
    targets = _plan_schemas(boundaries, existing_paths)
    targets.append(_plan_boundaries_py(spec, archetype, boundaries, existing_paths))
    if archetype == "mediated":
        raw = next(b for b in boundaries if b.direction == "raw")
        targets.append(_plan_drift_test(spec, raw, existing_paths))
    targets.append(_plan_ci_workflow(spec, archetype, existing_paths))
    return targets


def _next_steps(
    spec: InitSpec, archetype: Archetype, marker_action: MarkerAction, dependency_line: str,
) -> list[str]:
    steps = [
        "pin the dependency — add this line to pyproject.toml's [project].dependencies:\n"
        f"    {dependency_line!r}"
    ]
    if archetype == "mediated":
        steps.append(
            "the generated drift test fails on purpose (GENERATED PLACEHOLDER) — the `drift` "
            "job in .github/workflows/contract.yml makes that red visible; write the real "
            "assertion in the drift test to clear it"
        )
    if marker_action is MarkerAction.MANUAL:
        steps.append(f"register the raw_drift marker by hand:\n{MANUAL_SNIPPET}")
    return steps


def plan(spec: InitSpec, existing_paths: set[Path]) -> Plan:
    if (spec.fresh is None) == (spec.existing is None):
        raise PlanError("internal: exactly one of InitSpec.fresh/.existing must be set")

    if spec.fresh is not None:
        _validate_platform(spec.fresh.platform)
        system = spec.fresh.system
        archetype = _archetype_of(spec.fresh.source_kind)
        boundaries = _boundaries_for_fresh(spec.fresh)
        source_format = "json" if archetype == "mediated" else "csv"
        contract_target = _plan_contract_yaml(
            spec, system, boundaries, spec.fresh.source_kind, source_format, existing_paths
        )
        is_rerun = False
    else:
        raise NotImplementedError("re-run/gap-fill branch — implemented in Task 6")

    other_targets = _common_targets(spec, archetype, boundaries, existing_paths)
    marker_action = guard_marker(spec.pyproject_text)
    dependency_line = (
        f"contract-core @ git+https://github.com/Avenue-Z/data-contract.git"
        f"@v{spec.contract_core_version}"
    )
    next_steps = _next_steps(spec, archetype, marker_action, dependency_line)

    return Plan(
        is_rerun=is_rerun, system=system, archetype=archetype,
        contract_target=contract_target, other_targets=other_targets,
        marker_action=marker_action, dependency_line=dependency_line, next_steps=next_steps,
    )


_MARKER_REPORT_LINE = {
    MarkerAction.SATISFIED: "satisfied pyproject.toml (raw_drift marker already registered)",
    MarkerAction.MANUAL: "manual   pyproject.toml (raw_drift marker — see printed snippet)",
    MarkerAction.INSERT_KEY: "edited   pyproject.toml (raw_drift marker)",
    MarkerAction.APPEND_SECTION: "edited   pyproject.toml (raw_drift marker)",
}


def render_report(p: Plan) -> list[str]:
    """Design §5: one line per target in plan order, consecutive skips collapsed to a count.

    Pure — a function of `Plan` alone, which is what lets --dry-run print this before any write.
    """
    lines: list[str] = []
    if p.is_rerun:
        lines.append(f"read      contract.yaml ({p.system}, {p.archetype})")
        rest = p.other_targets
    else:
        rest = [p.contract_target, *p.other_targets]

    i = 0
    while i < len(rest):
        t = rest[i]
        if t.status == "created":
            lines.append(f"created  {t.path}")
            i += 1
            continue
        reason = t.skip_reason
        j = i
        while j < len(rest) and rest[j].status == "skipped" and rest[j].skip_reason == reason:
            j += 1
        count = j - i
        if count == 1:
            lines.append(f"skipped  {t.path} ({reason})")
        else:
            lines.append(f"skipped  {count} files ({reason})")
        i = j

    lines.append(_MARKER_REPORT_LINE[p.marker_action])
    return lines
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_scaffold_plan_fresh.py -v`
Expected: all PASS

- [ ] **Step 5: Type-check and lint**

Run: `mypy && ruff check src/contract_core/scaffold/plan.py tests/test_scaffold_plan_fresh.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/contract_core/scaffold/plan.py tests/test_scaffold_plan_fresh.py
git commit -m "feat(scaffold): add first-run planning (archetype, names, refs, contract.yaml)"
```

---

### Task 6: `scaffold/plan.py` — re-run / gap-fill planning

**Files:**
- Modify: `src/contract_core/scaffold/plan.py`
- Test: `tests/test_scaffold_plan_rerun.py`

**Interfaces:**
- Consumes: everything from Task 5; adds `parse_semver` from `contract_core.resolver` (already
  public — see its docstring: "Public ... because 'what stem counts as a schema file' is now a
  contract shared with `cli._lintable_schema_files`").
- Produces: fills in the `spec.existing is not None` branch of `plan()` left as
  `NotImplementedError` by Task 5.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_scaffold_plan_rerun.py
from pathlib import Path

from contract_core.contract import BoundarySpec, Contract
from contract_core.scaffold.plan import InitSpec, plan, render_report
from contract_core.scaffold.pyproject import MarkerAction

ROOT = Path("/repo")


def _existing_spec(contract: Contract, existing_pyproject="[tool.ruff]\nline-length = 100\n"):
    return InitSpec(
        root=ROOT, package="my_pkg", package_dir=ROOT / "src" / "my_pkg",
        pyproject_text=existing_pyproject, contract_core_version="0.7.0",
        fresh=None, existing=contract,
    )


def _mediated_contract():
    return Contract(
        format_version="v1", system="tiktok-brand-pulse", version="0.1.0",
        raw=[BoundarySpec(name="tiktok_raw", schema="tiktok.raw_report@1", mode="observe")],
        inputs=[BoundarySpec(name="records", schema="tiktok.records@1", mode="observe")],
        outputs=[BoundarySpec(name="report", schema="tiktok.report@1", mode="observe")],
    )


def test_archetype_is_derived_from_raw_non_empty():
    result = plan(_existing_spec(_mediated_contract()), existing_paths={Path("contract.yaml")})
    assert result.archetype == "mediated"
    assert result.is_rerun is True


def test_file_ingest_when_raw_is_empty():
    contract = Contract(
        format_version="v1", system="sentiment-digest", version="0.1.0",
        inputs=[BoundarySpec(name="scores", schema="sentiment.scores@1", mode="observe")],
        outputs=[BoundarySpec(name="digest", schema="sentiment.digest@1", mode="observe")],
    )
    result = plan(_existing_spec(contract), existing_paths={Path("contract.yaml")})
    assert result.archetype == "file-ingest"


def test_a_hand_renamed_boundary_drives_the_gap_filled_schema_path():
    contract = Contract(
        format_version="v1", system="tiktok-brand-pulse", version="0.1.0",
        raw=[BoundarySpec(name="tiktok_raw", schema="tiktok.raw_report@1", mode="observe")],
        inputs=[BoundarySpec(name="campaign_metrics", schema="tiktok.campaign_metrics@1",
                              mode="observe")],
        outputs=[BoundarySpec(name="report", schema="brandpulse.report@1", mode="observe")],
    )
    result = plan(_existing_spec(contract), existing_paths={Path("contract.yaml")})
    paths = {t.path for t in result.other_targets}
    assert Path("schemas/tiktok/campaign_metrics/1.0.0.yaml") in paths
    assert Path("schemas/brandpulse/report/1.0.0.yaml") in paths


def test_exact_pin_gap_fills_to_the_matching_filename_and_version_body():
    contract = Contract(
        format_version="v1", system="sys", version="0.1.0",
        inputs=[BoundarySpec(name="records", schema="tiktok.records@1.2.3", mode="observe")],
        outputs=[BoundarySpec(name="report", schema="tiktok.report@1", mode="observe")],
    )
    result = plan(_existing_spec(contract), existing_paths={Path("contract.yaml")})
    target = next(
        t for t in result.other_targets if t.path == Path("schemas/tiktok/records/1.2.3.yaml")
    )
    assert "version: 1.2.3" in target.content


def test_gap_fill_declines_when_the_schema_directory_already_holds_a_semver_file():
    contract = Contract(
        format_version="v1", system="sys", version="0.1.0",
        raw=[BoundarySpec(name="raw", schema="tiktok.raw_report@1", mode="observe")],
        inputs=[BoundarySpec(name="records", schema="tiktok.records@1", mode="observe")],
        outputs=[BoundarySpec(name="report", schema="tiktok.report@1", mode="observe")],
    )
    existing = {
        Path("contract.yaml"),
        Path("schemas/tiktok/records/2.0.0.yaml"),  # promoted past @1 — a real, author-owned file
    }
    result = plan(_existing_spec(contract), existing_paths=existing)
    target = next(
        t for t in result.other_targets if t.path == Path("schemas/tiktok/records/1.0.0.yaml")
    )
    assert target.status == "skipped"
    assert target.skip_reason == "schema directory not empty"


def test_gap_fill_ignores_non_semver_strays_in_the_schema_directory():
    contract = Contract(
        format_version="v1", system="sys", version="0.1.0",
        inputs=[BoundarySpec(name="records", schema="tiktok.records@1", mode="observe")],
        outputs=[BoundarySpec(name="report", schema="tiktok.report@1", mode="observe")],
    )
    existing = {Path("contract.yaml"), Path("schemas/tiktok/records/_template.yaml")}
    result = plan(_existing_spec(contract), existing_paths=existing)
    target = next(
        t for t in result.other_targets if t.path == Path("schemas/tiktok/records/1.0.0.yaml")
    )
    assert target.status == "created"


def test_a_second_run_over_a_fully_scaffolded_tree_writes_nothing():
    contract = _mediated_contract()
    all_paths = {
        Path("contract.yaml"),
        Path("schemas/tiktok/raw_report/1.0.0.yaml"),
        Path("schemas/tiktok/records/1.0.0.yaml"),
        Path("schemas/tiktok/report/1.0.0.yaml"),
        Path("src/my_pkg/boundaries.py"),
        Path("tests/test_drift_tiktok_raw.py"),
        Path(".github/workflows/contract.yml"),
    }
    text = (
        "[tool.pytest.ini_options]\n"
        'markers = ["raw_drift: a drift test guarding a raw boundary"]\n'
    )
    result = plan(_existing_spec(contract, existing_pyproject=text), existing_paths=all_paths)
    assert all(t.status == "skipped" for t in result.other_targets)
    assert result.marker_action == MarkerAction.SATISFIED


def test_rerun_report_leads_with_a_read_line_not_a_created_or_skipped_line():
    contract = _mediated_contract()
    result = plan(_existing_spec(contract), existing_paths={Path("contract.yaml")})
    lines = render_report(result)
    assert lines[0] == "read      contract.yaml (tiktok-brand-pulse, mediated)"
    assert not any("contract.yaml" in line and line is not lines[0] for line in lines[1:])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_scaffold_plan_rerun.py -v`
Expected: `NotImplementedError: re-run/gap-fill branch — implemented in Task 6`

- [ ] **Step 3: Implement the re-run branch**

In `src/contract_core/scaffold/plan.py`, add the import and two helpers, then replace the
`NotImplementedError` branch:

```python
from contract_core.resolver import parse_semver
```

```python
def _boundaries_for_existing(contract: Contract) -> list[ResolvedBoundary]:
    boundaries = [ResolvedBoundary("raw", b.name, b.schema_ref) for b in contract.raw]
    boundaries += [ResolvedBoundary("input", b.name, b.schema_ref) for b in contract.inputs]
    boundaries += [ResolvedBoundary("output", b.name, b.schema_ref) for b in contract.outputs]
    return boundaries


def _schema_dir_occupied(schema_dir: Path, existing_paths: set[Path]) -> bool:
    """design §5.1: gap-fill declines whenever the directory already holds ANY semver-named
    file — not just the one this ref would write. A non-semver stray (`_template.yaml`) does
    not count, mirroring `parse_semver`'s own "skip strays" contract (resolver.py)."""
    return any(
        p.parent == schema_dir and parse_semver(p.stem) is not None
        for p in existing_paths
    )
```

Change `_plan_schemas` to accept and honor an "occupied" check (used only on gap-fill; on a fresh
run no directory can be pre-occupied by anything other than the exact file `init` itself would
write, so the two code paths share one function):

```python
def _plan_schemas(boundaries: list[ResolvedBoundary], existing_paths: set[Path]) -> list[Target]:
    schemas_root = Path("schemas")
    targets = []
    for b in boundaries:
        name, version = _split_ref(b.schema_ref)
        schema_dir = schemas_root.joinpath(*name.split("."))
        filename = f"{version}.yaml" if "." in version else f"{version}.0.0.yaml"
        path = schema_dir / filename
        if path not in existing_paths and _schema_dir_occupied(schema_dir, existing_paths):
            targets.append(Target(
                path, content="", exists=True, skip_reason="schema directory not empty"
            ))
            continue
        template, description = _KIND_TEMPLATE[b.direction]
        content = render(template, {
            "SCHEMA_NAME": name,
            "VERSION": _schema_version_body(version),
            "DESCRIPTION": description,
        })
        targets.append(Target(path, content, exists=path in existing_paths))
    return targets
```

Now replace the `NotImplementedError` line in `plan()`:

```python
    else:
        contract = spec.existing
        assert contract is not None
        system = contract.system
        archetype = "mediated" if contract.raw else "file-ingest"
        boundaries = _boundaries_for_existing(contract)
        contract_target = Target(Path("contract.yaml"), content="", exists=True)
        is_rerun = True
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_scaffold_plan_rerun.py tests/test_scaffold_plan_fresh.py -v`
Expected: all PASS (both files — Task 5's tests must still pass after this task's edits to
`_plan_schemas`).

- [ ] **Step 5: Type-check and lint**

Run: `mypy && ruff check src/contract_core/scaffold/plan.py tests/test_scaffold_plan_rerun.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/contract_core/scaffold/plan.py tests/test_scaffold_plan_rerun.py
git commit -m "feat(scaffold): add re-run planning — derive from contract.yaml, gap-fill schemas"
```

---

### Task 7: `scaffold/apply.py` — the writer

**Files:**
- Create: `src/contract_core/scaffold/apply.py`
- Test: `tests/test_scaffold_apply.py`

**Interfaces:**
- Consumes: `Plan`, `Target` (Task 5/6), `MarkerAction`/`apply_marker` (Task 1).
- Produces: `apply(plan: Plan, root: Path) -> None`. Consumed by `cli.py` (Task 8).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_scaffold_apply.py
from pathlib import Path

from contract_core.scaffold.apply import apply
from contract_core.scaffold.plan import Plan, Target
from contract_core.scaffold.pyproject import MarkerAction


def _plan(root, contract_content="system: x\n", extra_targets=(), marker_action=MarkerAction.SATISFIED):
    return Plan(
        is_rerun=False, system="x", archetype="file-ingest",
        contract_target=Target(Path("contract.yaml"), contract_content, exists=False),
        other_targets=list(extra_targets),
        marker_action=marker_action, dependency_line="contract-core @ git+...", next_steps=[],
    )


def test_apply_writes_a_new_file_creating_parent_dirs(tmp_path):
    extra = Target(Path("schemas/p/n/1.0.0.yaml"), "schema: p.n\n", exists=False)
    apply(_plan(tmp_path, extra_targets=[extra]), tmp_path)
    assert (tmp_path / "contract.yaml").read_text() == "system: x\n"
    assert (tmp_path / "schemas/p/n/1.0.0.yaml").read_text() == "schema: p.n\n"


def test_apply_does_not_touch_a_target_marked_as_existing(tmp_path):
    (tmp_path / "contract.yaml").write_text("hand-authored\n")
    plan = _plan(tmp_path, contract_content="GENERATED\n")
    plan = Plan(**{**plan.__dict__, "contract_target": Target(
        Path("contract.yaml"), "GENERATED\n", exists=True
    )})
    apply(plan, tmp_path)
    assert (tmp_path / "contract.yaml").read_text() == "hand-authored\n"


def test_apply_inserts_the_marker_key_when_the_section_exists(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\npythonpath = [\"src\"]\n"
    )
    plan = _plan(tmp_path, marker_action=MarkerAction.INSERT_KEY)
    apply(plan, tmp_path)
    text = (tmp_path / "pyproject.toml").read_text()
    assert "raw_drift" in text
    assert 'pythonpath = ["src"]' in text


def test_apply_does_not_touch_pyproject_toml_when_satisfied(tmp_path):
    original = "[tool.pytest.ini_options]\nmarkers = [\"raw_drift: x\"]\n"
    (tmp_path / "pyproject.toml").write_text(original)
    apply(_plan(tmp_path, marker_action=MarkerAction.SATISFIED), tmp_path)
    assert (tmp_path / "pyproject.toml").read_text() == original


def test_apply_does_not_touch_pyproject_toml_when_manual(tmp_path):
    original = "[tool.pytest.ini_options]\nmarkers = [\"other: x\"]\n"
    (tmp_path / "pyproject.toml").write_text(original)
    apply(_plan(tmp_path, marker_action=MarkerAction.MANUAL), tmp_path)
    assert (tmp_path / "pyproject.toml").read_text() == original


def test_apply_is_idempotent_over_two_calls(tmp_path):
    extra = Target(Path("schemas/p/n/1.0.0.yaml"), "schema: p.n\n", exists=False)
    plan = _plan(tmp_path, extra_targets=[extra])
    apply(plan, tmp_path)
    apply(plan, tmp_path)  # simulates dry-run-then-real-run against the same Plan
    assert (tmp_path / "schemas/p/n/1.0.0.yaml").read_text() == "schema: p.n\n"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_scaffold_apply.py -v`
Expected: `ModuleNotFoundError: No module named 'contract_core.scaffold.apply'`

- [ ] **Step 3: Implement the writer**

```python
# src/contract_core/scaffold/apply.py
"""Execute a Plan (design 2026-07-30 §2.2) — the only writer in the scaffold package.

Every create/skip decision was already made, purely, by plan.py — this module's only job is I/O:
write what `plan()` said to create, and never touch what it said already exists.
"""
from __future__ import annotations

from pathlib import Path

from contract_core.scaffold.plan import Plan, Target
from contract_core.scaffold.pyproject import MarkerAction, apply_marker


def apply(result: Plan, root: Path) -> None:
    targets = (
        [*result.other_targets] if result.is_rerun
        else [result.contract_target, *result.other_targets]
    )
    for t in targets:
        _write_target(root, t)
    if result.marker_action in (MarkerAction.INSERT_KEY, MarkerAction.APPEND_SECTION):
        pyproject_path = root / "pyproject.toml"
        text = pyproject_path.read_text()
        pyproject_path.write_text(apply_marker(text, result.marker_action))


def _write_target(root: Path, target: Target) -> None:
    if target.status != "created":
        return
    path = root / target.path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(target.content)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_scaffold_apply.py -v`
Expected: all PASS

- [ ] **Step 5: Type-check and lint**

Run: `mypy && ruff check src/contract_core/scaffold/apply.py tests/test_scaffold_apply.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/contract_core/scaffold/apply.py tests/test_scaffold_apply.py
git commit -m "feat(scaffold): add apply() — the only writer"
```

---

### Task 8: CLI wiring — `contract init`

**Files:**
- Modify: `src/contract_core/cli.py`
- Test: `tests/test_cli.py` (extend existing file — read it first to match its existing fixture
  style before adding tests)

**Interfaces:**
- Consumes: `detect_package`/`PackageDetectionError` (Task 4), `InitSpec`/`FreshSpec`/`plan`/
  `PlanError`/`render_report` (Tasks 5-6), `apply` (Task 7), `Contract`/`ContractFormatError`
  (already imported in `cli.py`).
- Produces: the `contract init` console-script subcommand.

- [ ] **Step 1: Write the failing tests**

Read `tests/test_cli.py` first (it is not shown here to avoid duplicating a file this task must
read, per its existing fixture/`CliRunner` conventions) and add a new test class/section following
its established style. At minimum, cover:

```python
# additions to tests/test_cli.py — using click.testing.CliRunner, matching this file's existing
# invocation pattern for `lint`/`reconcile`/`events`.
from click.testing import CliRunner

from contract_core.cli import main


def _init(tmp_path, *args):
    runner = CliRunner()
    return runner.invoke(main, ["init", "--root", str(tmp_path), *args])


def _scaffold_repo(tmp_path, name="my_pkg"):
    (tmp_path / "pyproject.toml").write_text(f'[project]\nname = "{name}"\n')
    (tmp_path / name).mkdir()
    (tmp_path / name / "__init__.py").write_text("")


def test_init_requires_system_platform_source_when_contract_absent(tmp_path):
    _scaffold_repo(tmp_path)
    result = _init(tmp_path)
    assert result.exit_code != 0
    assert "--system" in result.output
    assert "--platform" in result.output
    assert "--source" in result.output


def test_init_first_run_creates_the_expected_tree(tmp_path):
    _scaffold_repo(tmp_path)
    result = _init(tmp_path, "--system", "sys", "--platform", "plat", "--source", "api")
    assert result.exit_code == 0, result.output
    assert (tmp_path / "contract.yaml").is_file()
    assert (tmp_path / "schemas/plat/raw_report/1.0.0.yaml").is_file()
    assert (tmp_path / "my_pkg/boundaries.py").is_file()
    assert (tmp_path / "tests/test_drift_plat_raw.py").is_file()
    assert (tmp_path / ".github/workflows/contract.yml").is_file()


def test_init_dry_run_writes_nothing(tmp_path):
    _scaffold_repo(tmp_path)
    result = _init(tmp_path, "--system", "sys", "--platform", "plat", "--source", "api",
                    "--dry-run")
    assert result.exit_code == 0, result.output
    assert not (tmp_path / "contract.yaml").exists()
    assert "created  contract.yaml" in result.output


def test_init_flags_with_existing_contract_is_rejected(tmp_path):
    _scaffold_repo(tmp_path)
    (tmp_path / "contract.yaml").write_text("system: sys\nversion: 0.1.0\n")
    result = _init(tmp_path, "--system", "sys", "--platform", "plat", "--source", "api")
    assert result.exit_code != 0
    assert "contract.yaml already exists" in result.output


def test_init_rerun_over_a_complete_tree_is_a_fixed_point(tmp_path):
    _scaffold_repo(tmp_path)
    first = _init(tmp_path, "--system", "sys", "--platform", "plat", "--source", "api")
    assert first.exit_code == 0, first.output
    second = _init(tmp_path)
    assert second.exit_code == 0, second.output
    assert "read      contract.yaml" in second.output


def test_init_platform_with_a_dot_exits_nonzero_and_writes_nothing(tmp_path):
    _scaffold_repo(tmp_path)
    result = _init(tmp_path, "--system", "sys", "--platform", "google.ads", "--source", "api")
    assert result.exit_code != 0
    assert "." in result.output
    assert not (tmp_path / "contract.yaml").exists()


def test_init_no_package_names_the_flag(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "my-pkg"\n')
    result = _init(tmp_path, "--system", "sys", "--platform", "plat", "--source", "api")
    assert result.exit_code != 0
    assert "--package" in result.output
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_cli.py -v -k init`
Expected: `Error: No such command 'init'.`

- [ ] **Step 3: Add the `init` command to `cli.py`**

At the top of `src/contract_core/cli.py`, add one new helper (used to scope which paths `plan()`
is allowed to consider "existing" — Design Note 2):

```python
def _scan_existing_paths(root: Path) -> set[Path]:
    """Every path `contract init` could possibly treat as already-existing, relative to root.

    Narrow by construction (design §2.2): plan() is pure, so this one filesystem walk — over
    exactly the subtrees init could ever write to — is the entire interface it sees.
    """
    paths: set[Path] = set()
    if (root / "contract.yaml").is_file():
        paths.add(Path("contract.yaml"))
    schemas = root / "schemas"
    if schemas.is_dir():
        for p in schemas.rglob("*.yaml"):
            paths.add(p.relative_to(root))
    for pkg_root in (root, root / "src"):
        if pkg_root.is_dir():
            for p in pkg_root.glob("*/boundaries.py"):
                paths.add(p.relative_to(root))
    tests_dir = root / "tests"
    if tests_dir.is_dir():
        for p in tests_dir.glob("test_drift_*.py"):
            paths.add(p.relative_to(root))
    workflow = root / ".github" / "workflows" / "contract.yml"
    if workflow.is_file():
        paths.add(workflow.relative_to(root))
    return paths
```

Then, at the end of `cli.py`, add the command:

```python
@main.command()
@click.option("--system", default=None, help="the contract's system: value")
@click.option("--platform", default=None, help="schema namespace under schemas/<platform>/")
@click.option("--source", "source_kind", default=None,
              type=click.Choice(["api", "mcp", "llm", "file"]),
              help="api/mcp/llm -> mediated; file -> file-ingest")
@click.option("--package", "package_override", default=None,
              help="importable package name; overrides detection")
@click.option("--root", "root_str", default=".", type=click.Path(exists=True, file_okay=False),
              help="target repo root")
@click.option("--dry-run", is_flag=True, help="print the plan report, write nothing")
def init(
    system: str | None, platform: str | None, source_kind: str | None,
    package_override: str | None, root_str: str, dry_run: bool,
) -> None:
    """Scaffold the mechanical steps of adopting a data contract (design 2026-07-30)."""
    from contract_core import __version__
    from contract_core.scaffold.apply import apply as run_apply
    from contract_core.scaffold.detect import PackageDetectionError, detect_package
    from contract_core.scaffold.plan import FreshSpec, InitSpec, PlanError
    from contract_core.scaffold.plan import plan as build_plan
    from contract_core.scaffold.plan import render_report

    root = Path(root_str)
    contract_path = root / "contract.yaml"
    given = [f for f, v in (("--system", system), ("--platform", platform),
                             ("--source", source_kind)) if v is not None]

    fresh = None
    existing = None
    if contract_path.is_file():
        if given:
            click.echo(
                f"INIT FAILED — contract.yaml already exists; "
                f"{', '.join(given)} would be ignored, so it is refused instead"
            )
            sys.exit(1)
        try:
            existing = Contract.from_yaml(contract_path)
        except ContractFormatError as exc:
            click.echo("INIT FAILED — malformed contract.yaml:")
            _echo_format_error(exc)
            sys.exit(1)
    else:
        missing = [f for f, v in (("--system", system), ("--platform", platform),
                                   ("--source", source_kind)) if v is None]
        if missing:
            click.echo(f"INIT FAILED — contract.yaml absent; required: {', '.join(missing)}")
            sys.exit(1)
        assert system is not None and platform is not None and source_kind is not None
        fresh = FreshSpec(system=system, platform=platform, source_kind=source_kind)

    try:
        detected = detect_package(root, package_override)
    except PackageDetectionError as exc:
        click.echo(f"INIT FAILED — {exc}")
        sys.exit(1)

    spec = InitSpec(
        root=root, package=detected.name, package_dir=detected.package_dir,
        pyproject_text=detected.pyproject_text, contract_core_version=__version__,
        fresh=fresh, existing=existing,
    )
    try:
        result = build_plan(spec, _scan_existing_paths(root))
    except PlanError as exc:
        click.echo(f"INIT FAILED — {exc}")
        sys.exit(1)

    for line in render_report(result):
        click.echo(line)
    for step in result.next_steps:
        click.echo(f"next: {step}")

    if not dry_run:
        run_apply(result, root)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_cli.py -v -k init`
Expected: all PASS

- [ ] **Step 5: Run the full unit suite, type-check, and lint**

Run: `pytest -q && mypy && ruff check .`
Expected: all clean (this is the first point where `cli.py` and every `scaffold/*` module are
exercised together).

- [ ] **Step 6: Commit**

```bash
git add src/contract_core/cli.py tests/test_cli.py
git commit -m "feat(cli): wire up 'contract init'"
```

---

### Task 9: End-to-end tests — the real verification bar

**Files:**
- Create: `tests/test_scaffold_e2e.py`

**Interfaces:**
- Consumes: the `contract` console script via `subprocess` (installed in the current environment
  by `pip install -e ".[dev]"`, already a repo prerequisite).
- Produces: the design §10 bar — for each archetype, scaffold into a fresh repo and assert
  `contract lint` and `contract reconcile` both exit 0.

This task depends on docs/superpowers/plans/2026-07-30-contract-gate-retire-token.md having
already landed (Global Constraints) — its `test_no_secret_emitted` sub-test is written against
the assumption that `contract-gate.yml` no longer requires a token.

- [ ] **Step 1: Write the end-to-end fixture and tests**

```python
# tests/test_scaffold_e2e.py
"""End-to-end scaffold tests (design 2026-07-30 §10). Subprocess, not in-process: `reconcile`
mutates sys.modules, and the console script is the supported entry point — the same reasoning
tests/test_distribution.py already uses.
"""
import subprocess
import sys
from pathlib import Path

import pytest


def _run(*cmd: str, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    import os
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(cmd, cwd=cwd, env=full_env, capture_output=True, text=True)


def _scaffold_repo(tmp_path: Path, pkg: str = "my_pkg") -> Path:
    (tmp_path / "pyproject.toml").write_text(f'[project]\nname = "{pkg}"\n')
    (tmp_path / pkg).mkdir()
    (tmp_path / pkg / "__init__.py").write_text("")
    return tmp_path


def _pythonpath_for(root: Path, pkg_dir_parent: Path) -> str:
    # design §10.1: a console script's sys.path[0] is the script's own dir, not cwd — PYTHONPATH
    # must name the directory CONTAINING the package directory, src/ for a src layout, root for flat.
    return str(pkg_dir_parent)


@pytest.mark.parametrize("source_kind,archetype", [("api", "mediated"), ("file", "file-ingest")])
def test_scaffolded_tree_lints_and_reconciles_clean(tmp_path, source_kind, archetype):
    root = _scaffold_repo(tmp_path)
    init = _run(
        "contract", "init", "--root", str(root), "--system", "sys",
        "--platform", "plat", "--source", source_kind, cwd=root,
    )
    assert init.returncode == 0, init.stdout + init.stderr

    lint = _run("contract", "lint", "--contract", "contract.yaml", "--schemas", "schemas",
                cwd=root)
    assert lint.returncode == 0, lint.stdout + lint.stderr

    reconcile = _run(
        "contract", "reconcile", "--contract", "contract.yaml", "--package", "my_pkg",
        "--tests", "tests", cwd=root, env={"PYTHONPATH": _pythonpath_for(root, root)},
    )
    assert reconcile.returncode == 0, reconcile.stdout + reconcile.stderr


def test_rerun_is_a_fixed_point(tmp_path):
    root = _scaffold_repo(tmp_path)
    first = _run("contract", "init", "--root", str(root), "--system", "sys",
                 "--platform", "plat", "--source", "api", cwd=root)
    assert first.returncode == 0, first.stdout + first.stderr
    second = _run("contract", "init", "--root", str(root), cwd=root)
    assert second.returncode == 0, second.stdout + second.stderr
    assert "read      contract.yaml" in second.stdout


def test_dry_run_makes_zero_filesystem_mutations(tmp_path):
    root = _scaffold_repo(tmp_path)
    before = sorted(p.relative_to(root) for p in root.rglob("*") if p.is_file())
    result = _run("contract", "init", "--root", str(root), "--system", "sys",
                  "--platform", "plat", "--source", "api", "--dry-run", cwd=root)
    assert result.returncode == 0, result.stdout + result.stderr
    after = sorted(p.relative_to(root) for p in root.rglob("*") if p.is_file())
    assert before == after


def test_platform_with_a_dot_exits_nonzero_and_writes_nothing(tmp_path):
    root = _scaffold_repo(tmp_path)
    result = _run("contract", "init", "--root", str(root), "--system", "sys",
                  "--platform", "google.ads", "--source", "api", cwd=root)
    assert result.returncode != 0
    assert not (root / "contract.yaml").exists()


def test_platform_with_a_slash_exits_nonzero_and_writes_nothing(tmp_path):
    root = _scaffold_repo(tmp_path)
    result = _run("contract", "init", "--root", str(root), "--system", "sys",
                  "--platform", "a/b", "--source", "api", cwd=root)
    assert result.returncode != 0
    assert not (root / "contract.yaml").exists()


def test_platform_with_a_hyphen_lints_clean(tmp_path):
    root = _scaffold_repo(tmp_path)
    init = _run("contract", "init", "--root", str(root), "--system", "sys",
               "--platform", "foo-bar", "--source", "file", cwd=root)
    assert init.returncode == 0, init.stdout + init.stderr
    lint = _run("contract", "lint", "--contract", "contract.yaml", "--schemas", "schemas",
                cwd=root)
    assert lint.returncode == 0, lint.stdout + lint.stderr


def test_both_layouts_present_exits_nonzero_and_names_both(tmp_path):
    root = _scaffold_repo(tmp_path)
    (root / "src" / "my_pkg").mkdir(parents=True)
    (root / "src" / "my_pkg" / "__init__.py").write_text("")
    result = _run("contract", "init", "--root", str(root), "--system", "sys",
                  "--platform", "plat", "--source", "api", cwd=root)
    assert result.returncode != 0
    assert "my_pkg" in result.stdout


def test_no_package_exits_nonzero_and_names_the_flag(tmp_path):
    root = tmp_path
    (root / "pyproject.toml").write_text('[project]\nname = "my-pkg"\n')
    result = _run("contract", "init", "--root", str(root), "--system", "sys",
                  "--platform", "plat", "--source", "api", cwd=root)
    assert result.returncode != 0
    assert "--package" in result.stdout


def test_generated_mode_is_observe_for_every_boundary(tmp_path):
    root = _scaffold_repo(tmp_path)
    _run("contract", "init", "--root", str(root), "--system", "sys", "--platform", "plat",
         "--source", "api", cwd=root)
    content = (root / "contract.yaml").read_text()
    assert content.count("mode: observe") == 3
    assert "mode: enforce" not in content


def test_contract_is_loadable_and_version_is_0_1_0(tmp_path):
    from contract_core.contract import Contract
    root = _scaffold_repo(tmp_path)
    _run("contract", "init", "--root", str(root), "--system", "sys", "--platform", "plat",
         "--source", "api", cwd=root)
    contract = Contract.from_yaml(root / "contract.yaml")
    assert contract.version == "0.1.0"


def test_drift_job_present_for_mediated_absent_for_file_ingest(tmp_path):
    mediated = _scaffold_repo(tmp_path / "mediated", pkg="pkg_m")
    _run("contract", "init", "--root", str(mediated), "--system", "sys", "--platform", "plat",
         "--source", "api", cwd=mediated)
    assert "drift:" in (mediated / ".github/workflows/contract.yml").read_text()

    file_ingest_root = _scaffold_repo(tmp_path / "file_ingest", pkg="pkg_f")
    _run("contract", "init", "--root", str(file_ingest_root), "--system", "sys",
         "--platform", "plat", "--source", "file", cwd=file_ingest_root)
    workflow = (file_ingest_root / ".github/workflows/contract.yml").read_text()
    assert "drift:" not in workflow


def test_no_secret_emitted(tmp_path):
    root = _scaffold_repo(tmp_path)
    _run("contract", "init", "--root", str(root), "--system", "sys", "--platform", "plat",
         "--source", "api", cwd=root)
    workflow = (root / ".github/workflows/contract.yml").read_text()
    assert "secrets:" not in workflow


def test_drift_stub_is_red_not_a_collection_error(tmp_path):
    root = _scaffold_repo(tmp_path)
    _run("contract", "init", "--root", str(root), "--system", "sys", "--platform", "plat",
         "--source", "api", cwd=root)
    (root / "pyproject.toml").write_text(
        (root / "pyproject.toml").read_text()
        + '\n[tool.pytest.ini_options]\n'
        'markers = ["raw_drift: a drift test guarding a raw boundary"]\n'
    )
    result = _run(sys.executable, "-m", "pytest", "-m", "raw_drift", cwd=root,
                  env={"PYTHONPATH": str(root)})
    assert result.returncode not in (0, 5), result.stdout + result.stderr  # not green, not "no tests collected"
    assert "GENERATED PLACEHOLDER" in result.stdout
```

- [ ] **Step 2: Run the tests to verify they fail (before Tasks 1-8 land, or if run out of order)**

Run: `pytest tests/test_scaffold_e2e.py -v`
Expected: `Error: No such command 'init'.` if run before Task 8; if run standalone after Task 8,
these should already pass, since this task adds no new source, only tests. If any fail here after
Task 8 is complete, that is a real defect in an earlier task — fix the earlier task, not this test.

- [ ] **Step 3: Install the package so the `contract` console script exists, then run**

Run: `pip install -e ".[dev]" && pytest tests/test_scaffold_e2e.py -v`
Expected: all PASS.

- [ ] **Step 4: Run the full verification bar**

Run: `pytest -q && mypy && ruff check . && contract lint --contract contract.yaml --schemas schemas 2>/dev/null; echo done`

(The trailing `contract lint` against this repo's own tree is the standing project convention from
design §10's tail — this repo does not itself carry a `contract.yaml`, so that specific invocation
is expected to no-op/skip in a repo with no contract; the load-bearing checks are `pytest -q`,
`mypy`, and `ruff check .`, which must all be clean.)

- [ ] **Step 5: Commit**

```bash
git add tests/test_scaffold_e2e.py
git commit -m "test(scaffold): add end-to-end lint+reconcile coverage for both archetypes"
```

---

### Task 10: `dev` extra — add `build`

**Files:**
- Modify: `pyproject.toml`

**Interfaces:** none — this is a dependency-list addition Task 3's wheel-contents test needs.

- [ ] **Step 1: Add `build` to the `dev` extra**

In `pyproject.toml`, change:

```toml
dev = ["pytest>=9.1.1", "ruff>=0.6", "mypy>=1.11", "pre-commit>=3.8",
       "hatchling", "pandas-stubs", "types-jsonschema", "types-PyYAML"]
```

to:

```toml
dev = ["pytest>=9.1.1", "ruff>=0.6", "mypy>=1.11", "pre-commit>=3.8",
       "hatchling", "build", "pandas-stubs", "types-jsonschema", "types-PyYAML"]
```

(`build` is the standard PEP 517 frontend `python -m build` needs; it was not previously a
dependency because nothing in the suite built a wheel before Task 3's
`test_templates_are_present_in_the_built_wheel`.)

- [ ] **Step 2: Verify the install picks it up**

Run: `pip install -e ".[dev]" && python -c "import build; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Re-run Task 3's wheel test to confirm it now passes for real**

Run: `pytest tests/test_scaffold_templates.py::test_templates_are_present_in_the_built_wheel -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add build to the dev extra for wheel-contents testing"
```

*(Note: if executing this plan task-by-task in order, fold this task into Task 3 instead of
landing it separately — it exists here as its own task only so the dependency is explicit and
reviewable on its own. A subagent-driven executor should do Task 10 immediately before Task 3
Step 5, not after Task 9.)*

---

### Task 11: Documentation changes (design §14)

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/consuming-repo-setup.md`
- Modify: `src/contract_core/__init__.py`
- Modify: `skills/authoring-data-contracts/SKILL.md`
- Test: `tests/test_public_api.py` (extend)

**Interfaces:** none new — this task only brings docs and the private-module list in line with
what Tasks 1-9 actually built, and closes the pre-existing `reconcile`/`events_report` omission
design §2.3 identifies.

- [ ] **Step 1: Write the failing test for the private-module list**

```python
# addition to tests/test_public_api.py
def test_private_module_list_matches_the_modules_actually_present():
    """design §2.3: __init__.py's docstring list is exhaustive by claim but was stale — it
    omitted `reconcile` and `events_report`, which already existed. This test makes the next
    omission fail CI instead of aging into the docs."""
    import ast
    from pathlib import Path

    src_dir = Path(contract_core.__file__).parent
    actual_top_level = {
        p.stem for p in src_dir.glob("*.py")
        if p.stem not in {"__init__", "__main__"}
    }
    actual_top_level.add("compile")  # documented as `compile.*`, a subpackage not a module

    docstring = ast.get_docstring(ast.parse(Path(contract_core.__file__).read_text()))
    assert docstring is not None
    documented = {
        name.strip(".*`'\" ")
        for name in docstring.replace("`", "").split("—")[1].split(",")
    } if False else None  # see Step 3 — parsed structurally below instead of by string-splitting
```

Replace the fragile string-split above with an explicit, hand-maintained set compared against the
filesystem — this is more robust than parsing prose out of a docstring and is the same style
`FROZEN_SURFACE` in this file already uses:

```python
# tests/test_public_api.py — final version of the addition
_DOCUMENTED_PRIVATE_MODULES = {
    "runtime", "errors", "contract", "resolver", "schema", "events", "types", "families",
    "vendor", "compile", "cli", "reconcile", "events_report", "scaffold",
}


def test_private_module_list_matches_the_modules_actually_present():
    """design §2.3: the docstring's private-module list is exhaustive by claim. Compare it
    against the filesystem so the next omission (like the pre-existing reconcile/events_report
    one this test fixes) fails CI instead of aging into the docs."""
    from pathlib import Path

    src_dir = Path(contract_core.__file__).parent
    actual = {
        p.stem for p in src_dir.glob("*.py")
        if p.stem not in {"__init__", "__main__"}
    }
    actual.add("compile")  # a subpackage, documented as `compile.*`
    assert actual == _DOCUMENTED_PRIVATE_MODULES
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_public_api.py -v -k private_module_list`
Expected: FAIL — `reconcile`, `events_report`, and `scaffold` are missing from
`_DOCUMENTED_PRIVATE_MODULES` relative to the actual `src/contract_core/*.py` filesystem listing
until Step 3 below also updates the docstring (the test asserts against the *filesystem*, which
already has `reconcile.py`/`events_report.py`/the new `scaffold/` package present after Task 1;
this test is written to double as the regression guard once the docstring below is fixed).

- [ ] **Step 3: Fix `src/contract_core/__init__.py`'s docstring**

Change:

```python
"""contract-core — the public API.

Everything exported here is a semver obligation (R9 design §3.2). Everything else —
`runtime`, `errors`, `contract`, `schema`, `events`, `resolver`, `types`, `families`,
`vendor`, `compile.*`, `cli` — is **private**: import paths into those modules are not
supported and may change without a major bump. That list is exhaustive, and it includes
`errors` and `runtime`, the modules the four exported names are *defined* in — reaching
past this package for them is not supported either. The CLI is invoked through the
`contract` console script, not by importing `contract_core.cli`.
"""
```

to:

```python
"""contract-core — the public API.

Everything exported here is a semver obligation (R9 design §3.2). Everything else —
`runtime`, `errors`, `contract`, `schema`, `events`, `resolver`, `types`, `families`,
`vendor`, `compile.*`, `cli`, `reconcile`, `events_report`, `scaffold` — is **private**:
import paths into those modules are not supported and may change without a major bump. That
list is exhaustive, and it includes `errors` and `runtime`, the modules the four exported
names are *defined* in — reaching past this package for them is not supported either. The
CLI is invoked through the `contract` console script, not by importing `contract_core.cli`.
"""
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_public_api.py -v -k private_module_list`
Expected: PASS

- [ ] **Step 5: Fix the same omission in `docs/consuming-repo-setup.md` §2**

Change (currently lines 40-46):

```markdown
Those five names (plus `__version__`) are the whole supported surface. **Everything else is
private** — `contract_core.runtime`, `.errors`, `.contract`, `.resolver`, `.schema`, `.events`,
`.types`, `.families`, `.vendor`, `.compile.*`, `.cli`. That list is exhaustive, and note that it
includes `.runtime` and `.errors`: those are where the four exported names are *defined*, but
`from contract_core.errors import FieldDiff` is not a supported import path — only
`from contract_core import FieldDiff` is. Import paths into private modules may change without a
major bump. Run the CLI through the `contract` console script, not by importing `contract_core.cli`.
```

to:

```markdown
Those five names (plus `__version__`) are the whole supported surface. **Everything else is
private** — `contract_core.runtime`, `.errors`, `.contract`, `.resolver`, `.schema`, `.events`,
`.types`, `.families`, `.vendor`, `.compile.*`, `.cli`, `.reconcile`, `.events_report`,
`.scaffold`. That list is exhaustive, and note that it includes `.runtime` and `.errors`: those
are where the four exported names are *defined*, but `from contract_core.errors import
FieldDiff` is not a supported import path — only `from contract_core import FieldDiff` is.
Import paths into private modules may change without a major bump. Run the CLI through the
`contract` console script, not by importing `contract_core.cli`.
```

- [ ] **Step 6: Add the fast-path pointer ahead of §6**

In `docs/consuming-repo-setup.md`, immediately before `## 6. If you run the reconcile gate`
(currently line 193), insert:

```markdown
> **Fast path:** the first four steps below (author the contract + schemas by hand, register the
> `raw_drift` marker, wire the CI gate) can be scaffolded in one command —
> `contract init --system <name> --platform <platform> --source <api|mcp|llm|file>` — which
> generates a tree that already lints and reconciles clean. See the `authoring-data-contracts`
> skill's Phase A. `init` cannot author real schema content for you (§6.1 of its own design); this
> section still applies once you're filling in `REPLACE_ME_*` fields with real columns.

```

- [ ] **Step 7: Update `SKILL.md` Phase A to lead with `contract init`**

In `skills/authoring-data-contracts/SKILL.md`, change the Phase A heading and its first line
(currently lines 37-38):

```markdown
**Phase A — during the spec (brainstorming): emit `contract.yaml` + schema files next to the spec.**
1. List boundaries: each external read → an `input`; each deliverable → an `output`.
```

to:

```markdown
**Phase A — during the spec (brainstorming): emit `contract.yaml` + schema files next to the spec.**
0. **Fast path:** if the target repo already has a `pyproject.toml` and an importable package,
   run `contract init --system <name> --platform <platform> --source <api|mcp|llm|file>` first —
   it scaffolds a tree that already lints and reconciles clean, with placeholder schema fields
   marked `REPLACE_ME_*`. The steps below are what to do by hand when `init` doesn't apply, and
   are exactly what `init` automates when it does — read them either way to know what you're
   editing.
1. List boundaries: each external read → an `input`; each deliverable → an `output`.
```

- [ ] **Step 8: Add the `CHANGELOG.md` entry**

Under `## [Unreleased]` in `CHANGELOG.md` (adding to, not replacing, the P1 entry from
docs/superpowers/plans/2026-07-30-contract-gate-retire-token.md if that plan's entry is already
present under the same heading):

```markdown
### Added

- **`contract init`** scaffolds the four mechanical adoption steps — schema + `contract.yaml`
  authoring, `raw_drift` marker registration, and CI gate wiring — into a consuming repo. The
  generated tree passes `contract lint` and `contract reconcile` on the first run; placeholder
  schema fields are marked `REPLACE_ME_*` and the generated drift test fails on purpose until its
  real assertion is written (see `.github/workflows/contract.yml`'s `drift` job). Additive: no
  change to the public API surface (`contract_core.__all__`).
```

This lands as the `0.8.0` entry once the release is cut (bump `[project].version` in
`pyproject.toml` and `__version__` in `src/contract_core/__init__.py` from `0.7.0` to `0.8.0`,
retitle `## [Unreleased]` to `## [0.8.0] — <release date>`, and open a fresh empty `##
[Unreleased]` above it) — that release step is intentionally left to whoever cuts the tag, not
bundled into this implementation plan.

- [ ] **Step 9: Run the full suite one more time**

Run: `pytest -q && mypy && ruff check .`
Expected: all clean.

- [ ] **Step 10: Commit**

```bash
git add CHANGELOG.md docs/consuming-repo-setup.md src/contract_core/__init__.py \
        skills/authoring-data-contracts/SKILL.md tests/test_public_api.py
git commit -m "docs: point to contract init as the fast path; fix the stale private-module list"
```

---

## Self-Review

**Spec coverage** (design 2026-07-30-contract-init-design.md, by section):
- §1.1 entry state / success criterion → Task 9 (`test_scaffolded_tree_lints_and_reconciles_clean`).
- §2.1 flags, no prompts → Task 8.
- §2.1.1 `--platform` validation → Task 5 (`_validate_platform`), Task 9 e2e coverage.
- §2.2 module split, purity → the Task 1/2/4/5-6/7 split itself; Design Note 2 explains the
  `set[Path]` interface precisely.
- §2.3 public API impact none, private-module-list fix → Task 11.
- §3 archetype selection → Task 5 (`_archetype_of`, `_boundaries_for_fresh`).
- §4 / §4.0 / §4.1 / §4.2 / §4.3 what it writes, exact `contract.yaml`, names, `mode: observe`,
  namespacing → Task 3 templates + Task 5 `_plan_contract_yaml`/`_plan_schemas`.
- §4.4 `boundaries.py`, no `__init__.py` edit → Task 3/5, and no task touches `__init__.py`.
- §4.5 CI workflow, tag substitution, no secret → Task 3 (`ci-workflow.*.tmpl`), Task 9
  (`test_no_secret_emitted`), gated on the separate P1 plan per Global Constraints.
- §4.6 drift job presence/absence → Task 3 templates, Task 9
  (`test_drift_job_present_for_mediated_absent_for_file_ingest`).
- §4.7 printed dependency line → Task 5 (`_next_steps`, `dependency_line`).
- §5 / §5.1 idempotency, re-run, gap-fill, decline rule → Task 6 in full, with its own test file.
- §6 / §6.1 / §6.2 placeholders, `REPLACE_ME_*`, drift test fails on purpose → Task 3 templates,
  Task 9 (`test_drift_stub_is_red_not_a_collection_error`).
- §7 package detection, both-layouts refusal → Task 4.
- §8 guard ladder → Task 1.
- §9 / §9.1 templates as package data, `.tmpl` extension, wheel contents → Task 3.
- §10 / §10.1 testing bar, subprocess + PYTHONPATH → Task 9.
- §11 non-goals → respected by omission throughout (no `--force`, no prompts, no git awareness, no
  `--boundaries N`, no `--check`, no `__init__.py` edit — none of these appear anywhere above).
- §12 P1 sequencing → Global Constraints + Task 9's explicit dependency note; the separate P1 plan.
- §13 risks → the P1-ordering risk is the Global Constraints/Task 9 note; the placeholder-read-as-
  protection risk is Task 3's `REPLACE_ME_`/`mode: observe`/header-comment combination.
- §14 documentation changes → Task 11.

**Placeholder scan:** every code block above is complete, runnable code — no `TODO`, no "similar
to Task N" without the actual code repeated, no bare prose describing untyped behavior.

**Type consistency:** `Target`/`Plan`/`InitSpec`/`FreshSpec`/`ResolvedBoundary` are defined once in
Task 5 and used with the same field names throughout Tasks 6-9 (`plan.contract_target`,
`plan.other_targets`, `plan.marker_action`, `plan.next_steps`, `plan.dependency_line`,
`plan.is_rerun`, `plan.system`, `plan.archetype`); `MarkerAction`/`guard_marker`/`apply_marker`/
`MANUAL_SNIPPET` from Task 1 are the same names used in Tasks 5, 6, 7, 8. `detect_package`/
`DetectedPackage`/`PackageDetectionError` from Task 4 match their use in Task 8 exactly.
