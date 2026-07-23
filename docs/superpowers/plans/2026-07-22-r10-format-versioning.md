# R10 Format Versioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the authored schema/contract YAML format strict and self-versioning, so a `contract-core` that meets a file it does not fully understand refuses loudly instead of silently validating a weaker form.

**Architecture:** Two controls plus one error type, per the spec. **Control A** — `extra="forbid"` on the four authored-format pydantic models (`Schema`, `Field`, `Contract`, `BoundarySpec`) turns a silently-dropped key into a hard failure. **Control B** — an optional `format_version` key on `Schema` and `Contract`, governed by two constants (`READABLE_FORMAT_VERSIONS` for the `from_yaml` dispatcher, `CURRENT_FORMAT_VERSION` for the model), refuses a version this reader cannot carry forward. Both surface through **`ContractFormatError`**, raised only at the `from_yaml` boundary, carrying an attribute surface (`.path` / `.errors` / `.hint`) so the CLI renders per-key diagnostics an operator can act on.

**Tech Stack:** Python 3.13, pydantic 2.13, click, pyyaml, pytest. mypy `strict`, ruff (`E,F,I,UP,B`), line-length 100.

## Global Constraints

Every task's requirements implicitly include these. Values copied verbatim from the spec.

- **Release `0.3.0`** — minor under 0.x semantics; a 0.x minor may carry breaking changes to the authored format (spec §11).
- **`READABLE_FORMAT_VERSIONS = frozenset({"v1"})`**, **`CURRENT_FORMAT_VERSION = "v1"`** — both `"v1"` today; separate names because they diverge the moment `v2` exists (spec §4.5). Major-only versions (`v1`, `v2` — no minor component).
- **`from_yaml` is the ONLY wrapping boundary** (spec §5.1). Direct model construction (`Field(name=..., type=...)`, `Schema(format_version="v2")`) keeps raising `pydantic.ValidationError`, unwrapped.
- **`ContractFormatError` subclasses `ValueError`**, is **NOT** a `ContractViolation`, and does **NOT** wrap `OSError` (spec §5.1, §5.3).
- **Frozen public surface is exactly six names** (spec §5.3): `ContractFormatError`, `ContractRuntime`, `ContractViolation`, `FieldDiff`, `__version__`, `load_runtime`.
- **No `_v1_to_v2`, no migration tool, no upcast chain** — `v1` is the only version, so there is nothing to migrate between (spec §10). The dispatcher rewrites the key to current (identity today) to keep the "model only sees the current format" invariant structural.
- **`format_version` is NOT exported to ODCS** (spec §4.3, criterion 13).
- **Branch flow:** work on a `feat/*` branch off `dev`; never push to `main` (CLAUDE.md workflow rule 1).
- **Verify before claiming done:** run `pytest -q`, `ruff check .`, `mypy` and read the output (CLAUDE.md workflow rule 3).

## File Structure

**Modified:**
- `src/contract_core/errors.py` — add `ContractFormatError` (class + `.path`/`.errors`/`.hint` + two builder classmethods + `_render`). Leaf module; gains `importlib.metadata` for the reader version, nothing else.
- `src/contract_core/types.py` — add the two format-version constants and `normalize_format_version()` (the raw-dict dispatcher). Imports `ContractFormatError` from `errors` (one-way edge, no cycle).
- `src/contract_core/schema.py` — `extra="forbid"`; `format_version` field + validator; rewrite `from_yaml` to dispatch + wrap.
- `src/contract_core/contract.py` — `extra="forbid"` on `Contract` + `BoundarySpec`; `format_version` field + validator on `Contract` only; rewrite `from_yaml` to dispatch + wrap.
- `src/contract_core/cli.py` — `_load_failure` returns rendered lines from `ContractFormatError`; new `Contract.from_yaml` arm in `lint`.
- `src/contract_core/__init__.py` — export `ContractFormatError`; bump `__version__` to `0.3.0`.
- `pyproject.toml` — bump `version` to `0.3.0`.
- Docs: `CHANGELOG.md`, `docs/consuming-repo-setup.md`, `docs/superpowers/specs/2026-07-16-data-contract-system-design.md`.

**Test files:**
- `tests/test_errors.py` (modify) — `ContractFormatError` unit tests.
- `tests/test_format_version.py` (**create**) — Control A + Control B behavior through `from_yaml`; the ODCS non-leak check.
- `tests/test_cli.py` (modify) — per-key rendering; malformed-contract arm.
- `tests/test_public_api.py` (modify) — `FROZEN_SURFACE` 5 → 6.
- `tests/test_distribution.py` (modify) — `PUBLIC_NAMES` gains `ContractFormatError` (see **Deviation D2** below).
- `tests/fixtures/contract_malformed.yaml` (**create**) — a contract with an unknown top-level key.

**Deviations from the spec's §11 edit-site table (both surfaced, neither silent):**
- **D1 — `pyproject.toml` version bump.** The table lists only `__init__.py` for `__version__`; `pyproject.toml:7` is also `0.2.0` and must move to `0.3.0` in the same release commit, or the built artifact's metadata disagrees with `__version__`. Folded into Task 5.
- **D2 — `tests/test_distribution.py::PUBLIC_NAMES`.** Criterion 12 says "exactly one pre-existing test is edited" (`FROZEN_SURFACE`). Planning found a second by-hand tracker of the surface: `PUBLIC_NAMES` at `test_distribution.py:16`, whose in-code comment reads *"Kept in step with `tests/test_public_api.py::FROZEN_SURFACE` by hand."* Leaving it stale would falsify that comment and skip exercising the new name over a real install. This plan updates it, and classifies the edit as **additive coverage** (the subset-import test does not go red without it), consistent with criterion 12's spirit ("nothing rewritten to stay green") though not its literal count. **If you prefer criterion 12 read literally, veto this step in review and it is dropped.**

---

### Task 1: `ContractFormatError` — the error type and its surface

**Files:**
- Modify: `src/contract_core/errors.py`
- Modify: `src/contract_core/__init__.py` (export only; version bump is Task 5)
- Modify: `tests/test_public_api.py:14-20` (`FROZEN_SURFACE`)
- Modify: `tests/test_distribution.py:16` (`PUBLIC_NAMES` — Deviation D2)
- Test: `tests/test_errors.py`

**Interfaces:**
- Produces:
  - `ContractFormatError(*, path: str, errors: list[tuple[str, str]], hint: str | None)` — subclasses `ValueError`. Attributes `.path: str`, `.errors: list[tuple[str, str]]`, `.hint: str | None`.
  - `ContractFormatError.from_validation_error(path: str, exc: ValidationError) -> ContractFormatError` — hint present iff any error is `extra_forbidden`.
  - `ContractFormatError.unreadable_version(path: str, found: object, supported: frozenset[str]) -> ContractFormatError` — always hinted.
  - `str(err)` renders `f"{path}:\n"` + one `  {loc}: {msg}` line per error + optional `\n\n{hint}`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_errors.py`:

```python
from pydantic import ValidationError

import contract_core
from contract_core.errors import ContractFormatError, ContractViolation
from contract_core.schema import Schema  # only to produce a real ValidationError


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
    err = ContractFormatError(path="s.yaml", errors=[("k", "m")], hint="Upgrade the pin. See CHANGELOG.md.")
    assert str(err).endswith("Upgrade the pin. See CHANGELOG.md.")


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_errors.py -q`
Expected: FAIL — `ImportError: cannot import name 'ContractFormatError'`.

> Note: this task depends on `Schema` being strict (`extra="forbid"`) for `test_from_validation_error_hints_only_on_extra_forbidden` to raise on the `surprise` key. That model change lands in Task 2. Run this test file's version-independent cases now; the two `from_validation_error` cases go green once Task 2 makes `Schema` strict. **If executing strictly task-by-task, mark those two tests `@pytest.mark.xfail(reason="Schema strict lands in Task 2", strict=True)` here and remove the marker in Task 2 Step 8.** The other five tests do not depend on Task 2 and must pass at the end of Task 1.

- [ ] **Step 3: Implement `ContractFormatError` in `errors.py`**

Add these imports at the top of `src/contract_core/errors.py` (alongside the existing `from typing import Literal` / `from pydantic import ...`):

```python
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

from pydantic import ValidationError
```

Append to `src/contract_core/errors.py`:

```python
_UPGRADE_HINT = (
    "The file was likely authored against a newer contract-core. Upgrade the pin, or "
    "author the file against {ver}. See CHANGELOG.md."
)


def _reader_version() -> str:
    try:
        return _pkg_version("contract-core")
    except PackageNotFoundError:  # a source checkout with no install
        return "unknown"


class ContractFormatError(ValueError):
    """An authored file cannot be read as the current format (design R10, §5).

    Raised ONLY at the `from_yaml` boundary (§5.1). Subclasses ValueError so a consumer
    catching ValueError around `load_runtime` keeps working; is deliberately NOT a
    `ContractViolation`, which signals bad *data*, not a malformed *artifact* (§5.3).

    `.path` / `.errors` / `.hint` are a frozen attribute surface (§5.2.1): consumers read
    them to build custom handling, so renaming one is a breaking change.
    """

    def __init__(self, *, path: str, errors: list[tuple[str, str]], hint: str | None) -> None:
        self.path = path
        self.errors = errors
        self.hint = hint
        super().__init__(self._render())

    @classmethod
    def from_validation_error(cls, path: str, exc: ValidationError) -> "ContractFormatError":
        # Every error, not just the first (§5.2.1). `msg`'s "Value error, " prefix is
        # pydantic presentation over a raised ValueError; strip it, as `cli` already did.
        errors = [
            (".".join(str(p) for p in e["loc"]),
             str(e["msg"]).removeprefix("Value error, "))
            for e in exc.errors()
        ]
        unknown_keys = any(e["type"] == "extra_forbidden" for e in exc.errors())
        hint = _UPGRADE_HINT.format(ver=_reader_version()) if unknown_keys else None
        return cls(path=path, errors=errors, hint=hint)

    @classmethod
    def unreadable_version(
        cls, path: str, found: object, supported: frozenset[str]
    ) -> "ContractFormatError":
        msg = f"unknown format version {found!r}; this reader supports {sorted(supported)}"
        return cls(path=path, errors=[("format_version", msg)],
                   hint=_UPGRADE_HINT.format(ver=_reader_version()))

    def _render(self) -> str:
        lines = "\n".join(f"  {loc}: {msg}" for loc, msg in self.errors)
        body = f"{self.path}:\n{lines}"
        if self.hint is not None:
            body += f"\n\n{self.hint}"
        return body
```

> **Render note:** the spec's §5.2 example messages carry a prose header ("declares keys this contract-core … does not understand"). §5.2 flags those two messages as *specified, not observed* — illustrative targets, not criteria. This uniform `loc: msg` render satisfies the actual criteria: it names every offending key path (criterion 14), and the hint is conditional (criterion 8). It drops two divergent header branches for one render path — a deliberate simplification.

- [ ] **Step 4: Export it from `__init__.py`**

Edit `src/contract_core/__init__.py`. Change the import line and `__all__` (leave `__version__ = "0.2.0"` for now — Task 5 bumps it):

```python
from contract_core.errors import ContractFormatError, ContractViolation, FieldDiff
from contract_core.runtime import ContractRuntime, load_runtime

__version__ = "0.2.0"

__all__ = [
    "ContractFormatError",
    "ContractRuntime",
    "ContractViolation",
    "FieldDiff",
    "__version__",
    "load_runtime",
]
```

Update the module docstring's private-modules sentence is not required; the exported list is what the frozen-surface test checks.

- [ ] **Step 5: Update the frozen-surface test**

Edit `tests/test_public_api.py`, the `FROZEN_SURFACE` set (currently 5 names):

```python
FROZEN_SURFACE = {
    "ContractFormatError",
    "ContractRuntime",
    "ContractViolation",
    "FieldDiff",
    "__version__",
    "load_runtime",
}
```

- [ ] **Step 6: Update the distribution import list (Deviation D2 — droppable)**

Edit `tests/test_distribution.py:16`:

```python
PUBLIC_NAMES = ["ContractFormatError", "ContractRuntime", "ContractViolation", "FieldDiff", "load_runtime"]
```

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_errors.py tests/test_public_api.py -q`
Expected: PASS (the two Task-2-dependent cases xfail-strict per Step 2, or pass if Task 2 already landed).

- [ ] **Step 8: Lint, type-check, commit**

Run: `.venv/bin/ruff check . && .venv/bin/mypy`
Expected: clean.

```bash
git add src/contract_core/errors.py src/contract_core/__init__.py tests/test_errors.py tests/test_public_api.py tests/test_distribution.py
git commit -m "feat(R10): add ContractFormatError and export it on the public surface"
```

---

### Task 2: Strict, versioned `from_yaml`

This is the core behavioral change and cannot be split: adding `extra="forbid"` without wrapping would leak `ValidationError` and force new tests to assert a type Task 3 then rewrites; wrapping without strict keys has nothing to reject. The `cli._load_failure` rework rides along because `from_yaml` no longer raises the `ValidationError`/`yaml.YAMLError` that `_load_failure` currently catches — omitting it would turn the existing malformed-schema lint tests red.

**Files:**
- Modify: `src/contract_core/types.py` (constants + `normalize_format_version`)
- Modify: `src/contract_core/schema.py` (`extra="forbid"`, `format_version` field + validator, `from_yaml`)
- Modify: `src/contract_core/contract.py` (`extra="forbid"` ×2, `format_version` on `Contract`, `from_yaml`)
- Modify: `src/contract_core/cli.py` (`_load_failure`)
- Test: `tests/test_format_version.py` (create), `tests/test_cli.py` (unchanged, must stay green)

**Interfaces:**
- Consumes: `ContractFormatError`, `.from_validation_error`, `.unreadable_version` (Task 1).
- Produces:
  - `contract_core.types.READABLE_FORMAT_VERSIONS: frozenset[str]`, `CURRENT_FORMAT_VERSION: str`.
  - `contract_core.types.normalize_format_version(data: dict[str, Any], path: str) -> dict[str, Any]` — defaults a missing key to `"v1"`, raises `ContractFormatError.unreadable_version` for an unreadable version, returns a copy with the key rewritten to `CURRENT_FORMAT_VERSION`.
  - `Schema.from_yaml` / `Contract.from_yaml` raise only `ContractFormatError` (or `OSError`); never `ValidationError` / `yaml.YAMLError`.
  - `cli._load_failure(path: Path) -> list[str] | None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_format_version.py`:

```python
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from contract_core.compile.odcs import validate_odcs
from contract_core.contract import Contract
from contract_core.errors import ContractFormatError
from contract_core.schema import Schema
from contract_core.types import CURRENT_FORMAT_VERSION, READABLE_FORMAT_VERSIONS

VALID_SCHEMA = {
    "schema": "peec.prompts_export", "version": "2.0.0", "kind": "tabular",
    "fields": [{"name": "sentiment", "type": "float", "minimum": -1.0, "maximum": 1.0}],
}


def _write(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "s.yaml"
    p.write_text(yaml.safe_dump(data))
    return p


# ---- Control A: strict keys (criteria 1, 2, 3, 4) ----

def test_unknown_key_on_a_schema_is_refused_not_dropped(tmp_path):
    # Criterion 1: §1 as a literal test — a future-format key does NOT validate a weaker form.
    p = _write(tmp_path, {**VALID_SCHEMA, "fields": [
        {"name": "x", "type": "int", "future_key": 42}]})
    with pytest.raises(ContractFormatError):
        Schema.from_yaml(p)


def test_a_realistic_typo_is_rejected(tmp_path):
    # Criterion 3: `requird` no longer silently defaults `required`.
    p = _write(tmp_path, {**VALID_SCHEMA, "fields": [
        {"name": "x", "type": "int", "requird": True}]})
    with pytest.raises(ContractFormatError):
        Schema.from_yaml(p)


def test_every_extra_key_is_reported_not_just_the_first(tmp_path):
    # Criterion 4: two unknown keys -> two entries in `.errors`.
    p = _write(tmp_path, {**VALID_SCHEMA, "fields": [
        {"name": "x", "type": "int", "a1": 1, "a2": 2}]})
    with pytest.raises(ContractFormatError) as ei:
        Schema.from_yaml(p)
    locs = {loc for loc, _ in ei.value.errors}
    assert any("a1" in loc for loc in locs)
    assert any("a2" in loc for loc in locs)


def test_each_model_rejects_an_unknown_key_at_its_own_level(tmp_path):
    # Criterion 2: top-level Schema, and BoundarySpec inside a Contract.
    ps = _write(tmp_path, {**VALID_SCHEMA, "surprise": 1})
    with pytest.raises(ContractFormatError):
        Schema.from_yaml(ps)
    pc = tmp_path / "c.yaml"
    pc.write_text(yaml.safe_dump({
        "system": "x", "version": "1.0.0",
        "inputs": [{"name": "b", "schema": "a.b@1", "surprise": 1}]}))
    with pytest.raises(ContractFormatError):
        Contract.from_yaml(pc)


# ---- Control B: format_version (criteria 5, 6) ----

def test_missing_format_version_defaults_to_v1(tmp_path):
    p = _write(tmp_path, VALID_SCHEMA)  # no format_version key
    s = Schema.from_yaml(p)
    assert s.format_version == CURRENT_FORMAT_VERSION


def test_explicit_v1_parses(tmp_path):
    p = _write(tmp_path, {"format_version": "v1", **VALID_SCHEMA})
    assert Schema.from_yaml(p).format_version == "v1"


def test_unreadable_version_through_from_yaml_is_refused_naming_found_and_supported(tmp_path):
    # Criterion 5 (dispatcher half): v2 is not in READABLE today.
    assert "v2" not in READABLE_FORMAT_VERSIONS
    p = _write(tmp_path, {"format_version": "v2", **VALID_SCHEMA})
    with pytest.raises(ContractFormatError) as ei:
        Schema.from_yaml(p)
    text = str(ei.value)
    assert "v2" in text and "v1" in text


def test_direct_construction_of_a_non_current_version_raises_plain_validationerror():
    # Criterion 5 (model half) / criterion 9: direct construction is NOT wrapped.
    with pytest.raises(ValidationError):
        Schema(schema="a.b", version="1.0.0", kind="tabular",
               fields=[{"name": "x", "type": "int"}], format_version="v2")


def test_from_yaml_never_leaks_a_yaml_error(tmp_path):
    # Criterion 6: a syntax error becomes ContractFormatError, not yaml.YAMLError.
    p = tmp_path / "s.yaml"
    p.write_text("kind: tabular\n  bad: indent")
    with pytest.raises(ContractFormatError):
        Schema.from_yaml(p)
    # And it is catchable as ValueError (criterion 7, boundary side).
    try:
        Schema.from_yaml(p)
    except ValueError:
        pass


# ---- criterion 9: applicability errors stay unwrapped on direct construction ----

def test_applicability_error_on_direct_field_construction_is_unwrapped():
    from contract_core.types import Field
    with pytest.raises(ValidationError):
        Field(name="brand", type="string", minimum=1)


# ---- criterion 13: format_version never reaches the ODCS export ----

def test_format_version_is_not_a_valid_odcs_key():
    # The vendored ODCS schema forbids extra top-level keys; a leak fails validation.
    doc = {"apiVersion": "v3.1.0", "kind": "DataContract", "id": "x", "name": "x",
           "version": "1.0.0", "status": "active", "schema": []}
    validate_odcs(doc)  # clean
    import jsonschema
    with pytest.raises(jsonschema.ValidationError):
        validate_odcs(doc | {"format_version": "v1"})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_format_version.py -q`
Expected: FAIL — `ImportError` on `CURRENT_FORMAT_VERSION` / `READABLE_FORMAT_VERSIONS`, and `AttributeError` on `s.format_version`.

- [ ] **Step 3: Add the constants and dispatcher to `types.py`**

At the top of `src/contract_core/types.py`, add to the imports:

```python
from pathlib import Path

from contract_core.errors import ContractFormatError
```

(The existing `from typing import Any, Literal` stays.) After the `FieldType` / `_BOUND_TYPES` / `_ENUM_TYPES` block, add:

```python
# Design §4.5. Two names, two jobs. Both "v1" today; they diverge the moment v2 exists.
READABLE_FORMAT_VERSIONS: frozenset[str] = frozenset({"v1"})  # the dispatcher's input set
CURRENT_FORMAT_VERSION: str = "v1"                            # the model's only legal value


def normalize_format_version(data: dict[str, Any], path: str) -> dict[str, Any]:
    """Carry a raw authored dict forward to the current format, or refuse it (§4.5).

    A missing stamp means v1: a file with no version predates versioning. An unreadable
    version is refused here, on the raw dict, before the model — the dispatcher half of the
    two rejecting sites in §4.5. There is no upcast chain today (§10); the key is rewritten
    to current so the "model only sees the current format" invariant is structural, not a
    coincidence of v1 == current.
    """
    found = data.get("format_version", "v1")
    if found not in READABLE_FORMAT_VERSIONS:
        raise ContractFormatError.unreadable_version(
            path=path, found=found, supported=READABLE_FORMAT_VERSIONS)
    return {**data, "format_version": CURRENT_FORMAT_VERSION}
```

> `Path` is imported because the signature and future call sites deal in paths; if ruff flags it unused (the helper takes `path: str`), drop the `from pathlib import Path` line. Confirm with `ruff check`.

- [ ] **Step 4: Make `Schema` strict and versioned**

Edit `src/contract_core/schema.py`. Update imports (add `ConfigDict`, `field_validator`, `ValidationError`, the two model helpers, and `ContractFormatError`):

```python
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from contract_core.errors import ContractFormatError
from contract_core.types import CURRENT_FORMAT_VERSION, Field, normalize_format_version
```

Add the config and field to the `Schema` class body (top of the class, before `schema`):

```python
class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format_version: str = CURRENT_FORMAT_VERSION
    # `schema` intentionally matches the YAML key; it shadows BaseModel.schema (deprecated).
    schema: str  # type: ignore[assignment]
    ...
```

Add a validator (anywhere among the class methods) rejecting a non-current version on direct construction:

```python
    @field_validator("format_version")
    @classmethod
    def _only_current_format(cls, v: str) -> str:
        # Through from_yaml the dispatcher has already normalized to current; this fires on
        # direct construction (§4.5 pt 2) and catches an upcast that forgot to rewrite the key.
        if v != CURRENT_FORMAT_VERSION:
            raise ValueError(
                f"format_version {v!r} is not the current format {CURRENT_FORMAT_VERSION!r}")
        return v
```

Replace `from_yaml`:

```python
    @classmethod
    def from_yaml(cls, path: str | Path) -> "Schema":
        p = Path(path)
        text = p.read_text()  # OSError leaks intentionally — not a malformed file (§5.1)
        try:
            raw = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ContractFormatError(
                path=str(p),
                errors=[("<file>", f"invalid YAML — {' '.join(str(exc).split())}")],
                hint=None,
            ) from exc
        data = normalize_format_version(raw, str(p)) if isinstance(raw, dict) else raw
        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            raise ContractFormatError.from_validation_error(str(p), exc) from exc
```

- [ ] **Step 5: Make `Contract` and `BoundarySpec` strict; version `Contract`**

Edit `src/contract_core/contract.py`. Update imports:

```python
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from contract_core.errors import ContractFormatError
from contract_core.types import CURRENT_FORMAT_VERSION, normalize_format_version
```

Add `model_config` to `BoundarySpec` (no `format_version` — it versions with its file):

```python
class BoundarySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    ...
```

Add `model_config`, `format_version`, the validator, and the new `from_yaml` to `Contract`:

```python
class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format_version: str = CURRENT_FORMAT_VERSION
    system: str
    version: str
    raw: list[BoundarySpec] = []
    inputs: list[BoundarySpec] = []
    outputs: list[BoundarySpec] = []

    @field_validator("format_version")
    @classmethod
    def _only_current_format(cls, v: str) -> str:
        if v != CURRENT_FORMAT_VERSION:
            raise ValueError(
                f"format_version {v!r} is not the current format {CURRENT_FORMAT_VERSION!r}")
        return v

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Contract":
        p = Path(path)
        text = p.read_text()  # OSError leaks intentionally (§5.1)
        try:
            raw = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ContractFormatError(
                path=str(p),
                errors=[("<file>", f"invalid YAML — {' '.join(str(exc).split())}")],
                hint=None,
            ) from exc
        data = normalize_format_version(raw, str(p)) if isinstance(raw, dict) else raw
        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            raise ContractFormatError.from_validation_error(str(p), exc) from exc
```

- [ ] **Step 6: Rework `cli._load_failure` to render per-error**

Edit `src/contract_core/cli.py`. Remove the now-unused imports `import yaml` and `from pydantic import ValidationError`; add `from contract_core.errors import ContractFormatError`. Replace `_load_failure` (lines 31-52):

```python
def _load_failure(path: Path) -> list[str] | None:
    """Rendered diagnostic lines for why `path` is not loadable, or None if it loads.

    `Schema.from_yaml` now wraps both the pydantic and the YAML failure into one
    `ContractFormatError` (design §5.1), so lint renders its `.errors` — one line per
    offending key path (§5.2.1) — plus its `.hint` when present. `OSError` still leaks
    from `from_yaml` and is caught here; an unreadable file is not a malformed one.
    """
    try:
        Schema.from_yaml(path)
    except ContractFormatError as exc:
        lines = [f"{loc}: {msg}" for loc, msg in exc.errors]
        if exc.hint:
            lines.append(exc.hint)
        return lines
    except OSError as exc:
        return [f"unreadable — {exc.strerror or exc}"]
    return None
```

Update the `lint` loop (lines 69-72) to flatten the list:

```python
    for path in _lintable_schema_files(schema_dirs):
        reasons = _load_failure(path)
        if reasons is not None:
            for reason in reasons:
                malformed.append(f"{path}: {reason}")
```

- [ ] **Step 7: Run the new and existing suites**

Run: `.venv/bin/python -m pytest tests/test_format_version.py tests/test_cli.py tests/test_schema.py tests/test_contract.py -q`
Expected: PASS. The existing `test_cli` malformed-schema tests still pass because `_load_failure` now catches `ContractFormatError` and renders the same `min_length applies to string` / `invalid YAML` text it caught before.

- [ ] **Step 8: Remove the Task-1 xfail markers (if used)**

If Step 2 of Task 1 marked two `test_errors.py` cases `xfail(strict=True)`, remove the markers now — `Schema` is strict, so they pass. Run: `.venv/bin/python -m pytest tests/test_errors.py -q` → PASS.

- [ ] **Step 9: Run the full suite, lint, type-check**

Run: `.venv/bin/python -m pytest -q && .venv/bin/ruff check . && .venv/bin/mypy`
Expected: all green. Note the new total (was 186 at 0.2.0; re-baseline per criterion 12).

- [ ] **Step 10: Commit**

```bash
git add src/contract_core/types.py src/contract_core/schema.py src/contract_core/contract.py src/contract_core/cli.py tests/test_format_version.py tests/test_errors.py
git commit -m "feat(R10): strict, versioned from_yaml raising ContractFormatError"
```

---

### Task 3: `lint` handles a malformed contract file

`cli.py:66` calls `Contract.from_yaml(contract_path)` with no handler. After Task 2 it raises `ContractFormatError` for a malformed contract, which would traceback out of `lint` — the one command whose job is a readable diagnostic (criterion 15). No existing test loads a malformed contract, so this is a clean follow-on.

**Files:**
- Modify: `src/contract_core/cli.py:66`
- Create: `tests/fixtures/contract_malformed.yaml`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `ContractFormatError` (Task 1), `Contract.from_yaml` raising it (Task 2).

- [ ] **Step 1: Create the malformed-contract fixture**

Create `tests/fixtures/contract_malformed.yaml`:

```yaml
# DELIBERATELY INVALID: an unknown top-level key. Strict keys (design §3) reject it, and
# `lint` must report it as a diagnostic rather than tracebacking (criterion 15).
system: aivx-reports
version: 1.0.0
systemm: typo-of-system
inputs:
  - name: peec_prompts
    schema: peec.prompts_export@1
```

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_cli.py`:

```python
def test_lint_reports_a_malformed_contract_without_a_traceback():
    runner = CliRunner()
    res = runner.invoke(main, ["lint", "--contract", str(FIX / "contract_malformed.yaml"),
                               "--schemas", str(FIX / "schemas")])
    assert res.exit_code == 1
    assert res.exception is None or isinstance(res.exception, SystemExit)
    assert "LINT FAILED" in res.output
    assert "systemm" in res.output  # names the offending key path


def test_lint_names_every_unknown_key_and_prints_the_hint():
    # Criterion 14: the operator's STDOUT, not the exception. Two unknown keys -> two lines,
    # plus the upgrade hint, from a schema authored for a newer format.
    import tempfile
    import textwrap
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "peec" / "prompts_export"
        root.mkdir(parents=True)
        (root / "9.0.0.yaml").write_text(textwrap.dedent("""\
            schema: peec.prompts_export
            version: 9.0.0
            kind: tabular
            fields:
              - name: prompt
                type: string
                pattern: "^x$"
                max_length: 5
        """))
        res = CliRunner().invoke(main, [
            "lint", "--contract", str(FIX / "contract_lintable.yaml"),
            "--schemas", str(FIX / "schemas"), "--schemas", d])
    assert res.exit_code == 1
    assert "pattern" in res.output
    assert "max_length" in res.output
    assert "Upgrade the pin" in res.output
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_cli.py -q -k "malformed_contract or unknown_key"`
Expected: FAIL — `test_lint_reports_a_malformed_contract...` raises `ContractFormatError` as `res.exception` (not `SystemExit`).

- [ ] **Step 4: Add the `Contract.from_yaml` arm in `lint`**

Edit `src/contract_core/cli.py`, the `lint` function. Replace `contract = Contract.from_yaml(contract_path)` (line 66) with:

```python
    try:
        contract = Contract.from_yaml(contract_path)
    except ContractFormatError as exc:
        click.echo("LINT FAILED — malformed contract:")
        for loc, msg in exc.errors:
            click.echo(f"  - {loc}: {msg}")
        if exc.hint:
            click.echo(f"  {exc.hint}")
        sys.exit(1)
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_cli.py -q`
Expected: PASS (both new tests and the four pre-existing lint tests).

- [ ] **Step 6: Lint, type-check, commit**

Run: `.venv/bin/ruff check . && .venv/bin/mypy`
Expected: clean.

```bash
git add src/contract_core/cli.py tests/fixtures/contract_malformed.yaml tests/test_cli.py
git commit -m "feat(R10): lint reports a malformed contract file instead of tracebacking"
```

---

### Task 4: Confirm the propagation paths and the full criteria set

A verification-only task — no production code. It confirms the §11.1 call sites behave as the table claims (criteria 6, 7, 10 end-to-end through `load_runtime` and `resolver`), and re-runs the whole suite as the criterion-12 baseline.

**Files:**
- Test: `tests/test_format_version.py` (add)

- [ ] **Step 1: Write the propagation tests**

Add to `tests/test_format_version.py`:

```python
def test_load_runtime_surfaces_a_malformed_contract_as_a_valueerror(tmp_path, monkeypatch):
    # §11.1: Contract.from_yaml is on load_runtime's path (runtime.py:325). Criterion 7:
    # catchable as ValueError, and NOT a ContractViolation.
    # delenv CONTRACT_DISABLED: with it set, load_runtime returns a disabled no-op that
    # never calls from_yaml — so the assertion below would never fire (as the existing
    # test_public_api tests also guard).
    monkeypatch.delenv("CONTRACT_DISABLED", raising=False)
    from contract_core import ContractViolation, load_runtime
    p = tmp_path / "c.yaml"
    p.write_text("system: x\nversion: 1.0.0\nsurprise: 1\n")
    with pytest.raises(ContractFormatError) as ei:
        load_runtime(p, schema_paths=[tmp_path])
    assert isinstance(ei.value, ValueError)
    assert not isinstance(ei.value, ContractViolation)


def test_resolver_surfaces_a_malformed_schema_as_contract_format_error(tmp_path):
    # §11.1: resolver.py calls Schema.from_yaml at two sites. A malformed resolved schema
    # propagates as ContractFormatError, not a bare pydantic/yaml error (criterion 6).
    from contract_core.resolver import Resolver
    d = tmp_path / "peec" / "prompts_export"
    d.mkdir(parents=True)
    (d / "1.0.0.yaml").write_text(
        "schema: peec.prompts_export\nversion: 1.0.0\nkind: tabular\n"
        "fields:\n  - name: x\n    type: int\n    bogus: 1\n")
    with pytest.raises(ContractFormatError):
        Resolver([tmp_path]).resolve("peec.prompts_export@1")
```

- [ ] **Step 2: Run them**

Run: `.venv/bin/python -m pytest tests/test_format_version.py -q -k "load_runtime or resolver"`
Expected: PASS. (If `load_runtime`'s signature is `load_runtime(path, schema_paths=...)`, confirm the keyword against `runtime.py`; adjust the call to match the real signature — do not guess.)

- [ ] **Step 3: Full suite + criteria audit**

Run: `.venv/bin/python -m pytest -q`
Expected: all green. Confirm by eye against the spec §9 list that criteria 1-15 each map to a passing test (1,2,3,4→test_format_version strict cases; 5,6→version + leak cases; 7→errors + load_runtime; 8→errors hint cases; 9→direct-construction cases; 10→existing test_cli malformed; 11→test_public_api; 12→this run vs baseline + one edited test [two with D2]; 13→test_format_version ODCS; 14,15→test_cli).

- [ ] **Step 4: Commit**

```bash
git add tests/test_format_version.py
git commit -m "test(R10): confirm ContractFormatError propagation through resolver and load_runtime"
```

---

### Task 5: Release `0.3.0` — version bump and docs

No code. Bumps the version in both files (Deviation D1), writes the CHANGELOG entry with the breaking-change line the spec mandates, updates the author-facing format doc, and closes the R10 row.

**Files:**
- Modify: `src/contract_core/__init__.py` (`__version__`)
- Modify: `pyproject.toml:7` (`version`)
- Modify: `CHANGELOG.md`
- Modify: `docs/consuming-repo-setup.md`
- Modify: `docs/superpowers/specs/2026-07-16-data-contract-system-design.md` (R10 row + §15 item 3)

- [ ] **Step 1: Bump the version in both places**

`src/contract_core/__init__.py`: `__version__ = "0.3.0"`.
`pyproject.toml` line 7: `version = "0.3.0"`.

- [ ] **Step 2: Write the CHANGELOG entry**

In `CHANGELOG.md`, under `## [Unreleased]`, add a new dated section above `## [0.2.0]`:

```markdown
## [0.3.0] — 2026-07-22

### Added

- **`format_version` on schema and contract files** — an optional, major-only format
  stamp (`v1`). A missing stamp means `v1`. A version this reader cannot carry forward is
  refused loudly at load. `format_version` is not exported to the ODCS document.
- **`ContractFormatError`** is now part of the public API (surface 5 → 6). It is raised
  only at the `from_yaml` boundary, subclasses `ValueError`, and carries `.path`,
  `.errors`, and `.hint` so tooling can render per-key diagnostics.

### Changed

- **BREAKING — unknown keys in authored files now fail; previously they were silently
  ignored.** A schema or contract carrying a key `contract-core` does not recognise — a
  typo, a hand-added annotation, or a key from a newer `contract-core` — now raises
  `ContractFormatError` at load instead of being dropped. This is the fix for the silent
  weakening described in the R10 design: a reader that dropped a key it did not understand
  validated a weaker form than the file it read. Any consuming repo with a stray key in an
  authored file must remove it or move to the reader that understands it.
- `Schema.from_yaml` and `Contract.from_yaml` now raise `ContractFormatError` rather than
  letting `pydantic.ValidationError` or `yaml.YAMLError` escape. Direct model construction
  is unchanged and still raises `ValidationError`.

### Minimum supported reader

Consuming repos should pin **`contract-core >= 0.3.0`**. Earlier readers silently ignore
keys they do not understand (including the `0.2.0` value constraints), so a file authored
against a newer format is validated as a weaker form with no error. `0.3.0` is the first
reader that refuses rather than under-validates.
```

- [ ] **Step 3: Update the author-facing format doc**

In `docs/consuming-repo-setup.md`: update the pin guidance to `>= 0.3.0` (§1), and add, under the format documentation (near the "Value constraints" section at line 53), a short subsection:

```markdown
### Format version and strict keys

Authored files are strict: a key `contract-core` does not recognise is a hard error at
load, not a silently-ignored line. A typo (`requird:`) fails loudly. Add only keys this
version documents.

Files may carry an optional `format_version: v1` at the top level of a schema or contract.
It is optional — a file with no stamp is read as `v1`. It bumps only when the *meaning* of
an existing key changes, never when a key is added. A `format_version` this reader cannot
read is refused with an upgrade hint, rather than mis-parsed.
```

- [ ] **Step 4: Close the R10 row in the system design**

In `docs/superpowers/specs/2026-07-16-data-contract-system-design.md`:
- The R10 row (line ~455): append a **CLOSED** note matching the style of the R8/R9 rows, stating what shipped (strict keys + `format_version` + `ContractFormatError`, released `0.3.0`) **and** naming the residual verbatim — that `0.1.0`/`0.2.0` readers are unreachable, so R10 buys the next format break, not the last one (spec §6). Do not imply the `0.1.0`→`0.2.0` gap is sealed.
- §15 item 3 ("The authored format is unversioned → R10", line ~489): mark it closed with a pointer to the R10 row and CHANGELOG `0.3.0`.

- [ ] **Step 5: Full verification**

Run: `.venv/bin/python -m pytest -q && .venv/bin/ruff check . && .venv/bin/mypy`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/contract_core/__init__.py pyproject.toml CHANGELOG.md docs/consuming-repo-setup.md docs/superpowers/specs/2026-07-16-data-contract-system-design.md
git commit -m "chore(R10): release 0.3.0 — format versioning, closing R10 with a stated residual"
```

---

## Self-Review

**1. Spec coverage** — every §9 criterion maps to a task:

| Criterion | Task | Test |
|---|---|---|
| 1 (future key refused, not weakened) | 2 | `test_unknown_key_on_a_schema_is_refused_not_dropped` |
| 2 (each model rejects at its level) | 2 | `test_each_model_rejects_an_unknown_key_at_its_own_level` |
| 3 (typo rejected) | 2 | `test_a_realistic_typo_is_rejected` |
| 4 (every extra key reported) | 2 | `test_every_extra_key_is_reported_not_just_the_first` |
| 5 (format_version via from_yaml; direct raises ValidationError) | 2 | `test_unreadable_version...`, `test_direct_construction...` |
| 6 (no leaked ValidationError/YAMLError) | 2, 4 | `test_from_yaml_never_leaks...`, `test_resolver_surfaces...` |
| 7 (ValueError, not ContractViolation) | 1, 4 | `test_format_error_is_a_valueerror...`, `test_load_runtime_surfaces...` |
| 8 (hint conditional) | 1 | `test_from_validation_error_hints_only_on_extra_forbidden`, `..._no_hint_on_an_applicability_error` |
| 9 (direct construction unwrapped) | 2 | `test_applicability_error_on_direct_field_construction_is_unwrapped` |
| 10 (malformed fixtures still diagnostics) | 2 | pre-existing `test_cli` malformed-schema tests stay green |
| 11 (surface = 6 names) | 1 | `test_public_surface_is_frozen` (updated) |
| 12 (one edited test; re-baseline) | 1, 4 | FROZEN_SURFACE edit + full-suite run; D2 noted |
| 13 (no ODCS leak) | 2 | `test_format_version_is_not_a_valid_odcs_key` |
| 14 (lint names keys + hint) | 3 | `test_lint_names_every_unknown_key_and_prints_the_hint` |
| 15 (malformed contract → diagnostic) | 3 | `test_lint_reports_a_malformed_contract_without_a_traceback` |

Out-of-scope items (§7, §10) have no task, correctly. §11.1 propagation confirmed in Task 4.

**2. Placeholder scan** — no "TBD"/"handle appropriately"/"write tests for the above"; every code step carries full code; every test step carries the assertion.

**3. Type consistency** — `normalize_format_version(data: dict[str, Any], path: str) -> dict[str, Any]` is defined in Task 2 Step 3 and called with the same signature in `schema.py`/`contract.py` Steps 4-5. `ContractFormatError(*, path, errors, hint)` and both classmethods (Task 1) are used unchanged in Task 2. `_load_failure` return type moves `str | None → list[str] | None` in one task (2), and the `lint` loop consuming it is updated in the same step. `CURRENT_FORMAT_VERSION` / `READABLE_FORMAT_VERSIONS` names are identical across types.py, schema.py, contract.py, and the tests.

**Two carried deviations (D1 version bump, D2 distribution-test edit) are documented in the File Structure section, not buried in steps.**
