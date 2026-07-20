# Data Contract System — Phase 0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the contract loop on one pilot (`aivx-reports`): author named/versioned schemas + a contract, compile them to runtime validators (Pandera for tabular, JSON Schema for payload) and an ODCS interop document, validate real data at boundaries with `observe`/`warn`/`enforce` modes and the two-boundary raw/normalized model, and hard-fail on a vendor-shaped type change and a field removal.

**Architecture:** A small Python library `contract_core` with four seams — *load* (Schema/Contract models from YAML), *resolve* (`platform.name@version` → Schema), *compile* (Schema → Pandera / JSON Schema; Contract → ODCS), and *runtime* (boundary decorators that validate a function's data and emit an event). The pilot lives in the separate `aivx-reports` repo and depends on `contract_core` as an installed package.

**Tech Stack:** Python 3.13, Pydantic v2 (our own models + payload validation), Pandera (tabular validation), `jsonschema` (payload + ODCS-document validation), PyYAML, `click` (CLI), `pytest`.

**Repo state (READ FIRST — the repo is NOT blank):** `data-contract` was initialized from `Avenue-Z/repo-template`. It already contains a placeholder `app` package (`src/app/main.py` with `greet()`), a smoke test for it (`tests/test_smoke.py`), `tests/conftest.py`, and a real `pyproject.toml` carrying the template's tooling — `ruff`, `mypy` (`strict = true`), `bandit`, and pytest `addopts = "--strict-config --strict-markers"` — plus dev deps including `pre-commit` (the gitleaks secret-scan hook). **Task 1 therefore MERGES `contract_core` into this scaffold — it does not overwrite.** Keep the tooling config; retarget it from `app` to `contract_core`; delete the `app` placeholder. `.gitignore` already lists `.venv/`, `__pycache__/`, `*.egg-info/`, `.pytest_cache/`, `dist/` — no new entries needed except the runtime event-log artifact.

**Execution scope for this pass:** Tasks 1–12 (the `contract_core` library, entirely within this repo). Tasks 13–16 (the `aivx-reports` pilot) are deferred to a later, deliberate pass and are left in this document unchanged as future work — do NOT execute them now.

## Global Constraints

Copied verbatim from the spec (`docs/superpowers/specs/2026-07-16-data-contract-system-design.md`); every task inherits these.

- **Dependency pins (floors):** `pandera ~=0.32.1`, `pydantic ~=2.13`, `datacontract-cli ~=1.0.12` (NOT used in Phase 0 — see note), `jsonschema` (Draft 2020-12 validator). Authoritative pins live in the lockfile.
- **Pandera import is namespaced:** `import pandera.pandas as pa` — never `import pandera as pa` (raises `FutureWarning`).
- **ODCS target:** v3.1.0. Validate emitted ODCS against the **dated** JSON Schema (`odcs-json-schema-v3.1.0-20260505.json`), pinned/vendored — never `-latest`.
- **Postel's law strictness (the 2×2, decision #2 / §5.2):**
  | | Declared field missing / retyped | Extra undeclared field |
  | --- | --- | --- |
  | **Input / Raw** | hard-fail (`enforce`) | pass silently (open) |
  | **Output** | hard-fail (`enforce`) | **`warn`** (never blocks) |
- **Modes:** `observe` (validate, never fail, log observed shape) → `warn` (log violation, continue) → `enforce` (hard-fail; the default). No `retry` in v1.
- **Two boundaries for mediated sources (§7):** raw-call-site contract *before* the adapter (catches vendor drift), normalized-schema contract *after* it. File-ingest sources have only the normalized boundary.
- **Portable Core principle (decision #1):** the compiled JSON Schema carries only the structural core — presence, type, nullability, enums. Value/cross-field checks are Python-side (Pandera) enrichment only.
- **Error quality (§8):** a violation raises `ContractViolation` carrying boundary, schema, version, and a *structural diff* (expected-vs-observed) — not a raw Pandera stack trace.
- **Event log (§4.4):** one record per crossing — `{system, boundary, schema, version, result, observed_shape, timestamp}`.
- **TDD, DRY, YAGNI, frequent commits.** Each task ends green.

**Phase 0 scope note (YAGNI, from the spec + plan args):**
- **In:** schema/contract YAML formats (6 scalar types + a `json_schema:` passthrough for complex payloads), resolver (local search paths only — central package deferred), compiler (→ Pandera, → JSON Schema, → ODCS), runtime decorators + modes + 2×2 + `ContractViolation` + event log, `contract lint`, the `aivx-reports` pilot through `observe`→`enforce`, and R2 drift-test *convention* groundwork.
- **Deferred (do NOT build):** `reconcile` (Phase 1), `compat` + Karapace + semver-bump CI (Phase 2), JS SDK (Phase 3), the authoring skill (Phase 1), version GC, the canary, `datacontract-cli` runtime integration. The decorator *registers* boundaries (a module-level list) so Phase 1's `reconcile` has data, but Phase 0 does not consume the registry.
- **Why ODCS emit is in Phase 0 despite no Phase-0 consumer:** it de-risks "does our format map cleanly onto ODCS given its reuse gap?" early, while the format is still cheap to change — not for spec-compliance alone.

**Type vocabulary (single source of truth; Tasks 2/6/7 all use this):**

| our `type` | pandas dtype (Pandera) | JSON Schema |
| --- | --- | --- |
| `string` | `str` (object) | `{"type": "string"}` |
| `int` | `Int64` (nullable int) | `{"type": "integer"}` |
| `float` | `float64` | `{"type": "number"}` |
| `bool` | `boolean` | `{"type": "boolean"}` |
| `date` | `datetime64[ns]` | `{"type": "string", "format": "date"}` |
| `datetime` | `datetime64[ns]` | `{"type": "string", "format": "date-time"}` |

`nullable: true` → Pandera `nullable=True` / JSON Schema `{"type": [T, "null"]}`. `required: true` → Pandera column present + `required=True` / JSON Schema `required` list membership.

---

### Task 1: Reframe the template scaffold as the `contract_core` package

The repo already has the `Avenue-Z/repo-template` scaffold (see **Repo state** above). This task **merges** `contract_core` into it: retarget `pyproject.toml` (keeping ruff/mypy/bandit/pytest-strict config), create the new package, delete the `app` placeholder, and swap the smoke test. It does **not** create a fresh `pyproject.toml` or `.gitignore` from scratch.

**Files:**
- Modify: `pyproject.toml` (rename project `app` → `contract-core`; add runtime deps + `contract` script; retarget wheel/mypy from `src/app` → `src/contract_core`; keep all tooling)
- Create: `src/contract_core/__init__.py`
- Modify: `tests/test_smoke.py` (replace the `greet` smoke test with the `contract_core` import test)
- Delete: `src/app/__init__.py`, `src/app/main.py` (placeholder demo — no longer referenced once the smoke test is swapped)
- Modify: `.gitignore` (append the one runtime artifact; the rest already exist)
- Keep unchanged: `tests/conftest.py`

**Interfaces:**
- Consumes: nothing.
- Produces: an installed, importable `contract_core` package (`import contract_core; contract_core.__version__`).

- [ ] **Step 1: Replace the smoke test with the failing `contract_core` test**

Overwrite `tests/test_smoke.py` (it currently imports `app.main.greet`) with:

```python
# tests/test_smoke.py
import contract_core


def test_package_imports_and_has_version():
    assert isinstance(contract_core.__version__, str)
    assert contract_core.__version__ != ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'contract_core'`.

- [ ] **Step 3: Retarget `pyproject.toml` (merge — do NOT replace the whole file)**

Apply these edits to the existing file, leaving `[tool.ruff]`, `[tool.ruff.lint]`, and `[tool.bandit]` untouched. The result should read:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "contract-core"
version = "0.0.1"
description = "Data contract core library — schemas, contracts, compilers, runtime validation."
requires-python = ">=3.13"
dependencies = [
    "pydantic~=2.13",
    "pandera~=0.32.1",
    "pandas>=2.0.0",
    "jsonschema>=4.20",
    "pyyaml>=6.0",
    "click>=8.1",
]

[project.optional-dependencies]
# pre-commit stays: it installs the gitleaks hook (the one local secret-scan control).
dev = ["pytest>=8", "ruff>=0.6", "mypy>=1.11", "pre-commit>=3.8"]

[project.scripts]
contract = "contract_core.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["src/contract_core"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
addopts = "--strict-config --strict-markers"

[tool.ruff]
line-length = 100
target-version = "py313"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.mypy]
python_version = "3.13"
strict = true
files = ["src"]

[tool.bandit]
exclude_dirs = ["tests"]
```

Concretely, the diff from the template is: `name` `app`→`contract-core`; add `version`/`description`/`requires-python`/`dependencies`; add `[project.scripts]`; wheel `packages` `src/app`→`src/contract_core`; `ruff`/`mypy` versions `py311`/`3.11`→`py313`/`3.13`. (`[project.scripts]` points at `contract_core.cli:main`, created in Task 12 — declaring it now is fine; install does not import it.)

- [ ] **Step 4: Write the package init**

```python
# src/contract_core/__init__.py
__version__ = "0.0.1"
```

- [ ] **Step 5: Delete the `app` placeholder**

Run:
```bash
git rm src/app/__init__.py src/app/main.py
```
Nothing references `app` after Step 1 swapped the smoke test. (`mypy files = ["src"]` now sees only `src/contract_core`.)

- [ ] **Step 6: Append the runtime artifact to `.gitignore`**

The event log (Task 10) defaults to `./contract-events.jsonl` on manual runs. Append under the Python section:

```
contract-events.jsonl
```
Everything else the package needs (`.venv/`, `__pycache__/`, `*.egg-info/`, `.pytest_cache/`, `dist/`) is already present — do not duplicate it.

- [ ] **Step 7: Set up the environment and install**

Run:
```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```
Expected: installs cleanly, `Successfully installed contract-core-0.0.1 ...`.

- [ ] **Step 8: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_smoke.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml src/contract_core/__init__.py tests/test_smoke.py .gitignore src/app
git commit -m "feat: reframe template scaffold as contract_core package"
```

---

### Task 2: Field model + type vocabulary

**Files:**
- Create: `src/contract_core/types.py`
- Test: `tests/test_types.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `FieldType = Literal["string","int","float","bool","date","datetime"]`
  - `class Field(pydantic.BaseModel)`: `name: str`, `type: FieldType`, `required: bool = True`, `nullable: bool = False`
  - `PANDAS_DTYPE: dict[str, str]` and `JSON_SCHEMA_TYPE: dict[str, dict]` mapping each `FieldType` per the Global Constraints table.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_types.py
import pytest
from contract_core.types import Field, PANDAS_DTYPE, JSON_SCHEMA_TYPE


def test_field_defaults_required_not_nullable():
    f = Field(name="order_id", type="string")
    assert f.required is True
    assert f.nullable is False


def test_field_rejects_unknown_type():
    with pytest.raises(ValueError):
        Field(name="x", type="decimal")


def test_type_maps_cover_all_field_types():
    kinds = {"string", "int", "float", "bool", "date", "datetime"}
    assert set(PANDAS_DTYPE) == kinds
    assert set(JSON_SCHEMA_TYPE) == kinds
    assert JSON_SCHEMA_TYPE["datetime"] == {"type": "string", "format": "date-time"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_types.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'contract_core.types'`.

- [ ] **Step 3: Write the implementation**

```python
# src/contract_core/types.py
from typing import Literal

from pydantic import BaseModel

FieldType = Literal["string", "int", "float", "bool", "date", "datetime"]


class Field(BaseModel):
    name: str
    type: FieldType
    required: bool = True
    nullable: bool = False


PANDAS_DTYPE: dict[str, str] = {
    "string": "str",
    "int": "Int64",
    "float": "float64",
    "bool": "boolean",
    "date": "datetime64[ns]",
    "datetime": "datetime64[ns]",
}

JSON_SCHEMA_TYPE: dict[str, dict] = {
    "string": {"type": "string"},
    "int": {"type": "integer"},
    "float": {"type": "number"},
    "bool": {"type": "boolean"},
    "date": {"type": "string", "format": "date"},
    "datetime": {"type": "string", "format": "date-time"},
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_types.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/contract_core/types.py tests/test_types.py
git commit -m "feat: field model and type vocabulary"
```

---

### Task 3: Schema model + YAML loader

**Files:**
- Create: `src/contract_core/schema.py`
- Create: `tests/fixtures/schemas/peec/prompts_export/1.0.0.yaml`
- Test: `tests/test_schema.py`

**Interfaces:**
- Consumes: `contract_core.types.Field`.
- Produces:
  - `class Schema(pydantic.BaseModel)`: `schema: str` (dotted name, e.g. `peec.prompts_export`), `version: str` (semver), `kind: Literal["tabular","payload"]`, `fields: list[Field] | None = None`, `json_schema: dict | None = None`.
  - property `ref -> str` returns `f"{self.schema}@{self.version}"`.
  - validator: exactly one of `fields` / `json_schema` is set; `json_schema` only allowed when `kind == "payload"`.
  - classmethod `from_yaml(path: str | Path) -> Schema`.

- [ ] **Step 1: Write the fixture**

```yaml
# tests/fixtures/schemas/peec/prompts_export/1.0.0.yaml
schema: peec.prompts_export
version: 1.0.0
kind: tabular
fields:
  - name: prompt
    type: string
    required: true
  - name: sentiment
    type: float
    required: true
    nullable: true
  - name: position
    type: int
    required: true
    nullable: true
  - name: share_of_voice
    type: float
    required: true
    nullable: true
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_schema.py
from pathlib import Path

import pytest
from contract_core.schema import Schema

FIX = Path(__file__).parent / "fixtures" / "schemas"


def test_load_tabular_schema_and_ref():
    s = Schema.from_yaml(FIX / "peec" / "prompts_export" / "1.0.0.yaml")
    assert s.ref == "peec.prompts_export@1.0.0"
    assert s.kind == "tabular"
    assert [f.name for f in s.fields] == ["prompt", "sentiment", "position", "share_of_voice"]


def test_rejects_both_fields_and_json_schema():
    with pytest.raises(ValueError):
        Schema(schema="x.y", version="1.0.0", kind="payload",
               fields=[{"name": "a", "type": "string"}], json_schema={"type": "object"})


def test_json_schema_requires_payload_kind():
    with pytest.raises(ValueError):
        Schema(schema="x.y", version="1.0.0", kind="tabular", json_schema={"type": "object"})
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'contract_core.schema'`.

- [ ] **Step 4: Write the implementation**

```python
# src/contract_core/schema.py
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, model_validator

from contract_core.types import Field


class Schema(BaseModel):
    schema: str
    version: str
    kind: Literal["tabular", "payload"]
    fields: list[Field] | None = None
    json_schema: dict | None = None

    @property
    def ref(self) -> str:
        return f"{self.schema}@{self.version}"

    @model_validator(mode="after")
    def _exactly_one_body(self) -> "Schema":
        if (self.fields is None) == (self.json_schema is None):
            raise ValueError("schema must set exactly one of `fields` or `json_schema`")
        if self.json_schema is not None and self.kind != "payload":
            raise ValueError("`json_schema` is only allowed when kind == 'payload'")
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Schema":
        data = yaml.safe_load(Path(path).read_text())
        return cls.model_validate(data)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_schema.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add src/contract_core/schema.py tests/test_schema.py tests/fixtures/schemas/peec/prompts_export/1.0.0.yaml
git commit -m "feat: schema model and YAML loader"
```

---

### Task 4: Contract model + YAML loader

**Files:**
- Create: `src/contract_core/contract.py`
- Create: `tests/fixtures/contract.yaml`
- Test: `tests/test_contract.py`

**Interfaces:**
- Consumes: nothing (references are strings at this layer).
- Produces:
  - `Mode = Literal["observe","warn","enforce"]`
  - `Direction = Literal["raw","input","output"]`
  - `class BoundarySpec(pydantic.BaseModel)`: `name: str`, `schema: str` (a ref like `peec.prompts_export@1`), `mode: Mode = "enforce"`, `source: dict | None = None`, `sink: dict | None = None`.
  - `class Contract(pydantic.BaseModel)`: `system: str`, `version: str`, `inputs: list[BoundarySpec] = []`, `outputs: list[BoundarySpec] = []`, `raw: list[BoundarySpec] = []`.
  - classmethod `from_yaml(path) -> Contract`.

- [ ] **Step 1: Write the fixture**

```yaml
# tests/fixtures/contract.yaml
system: aivx-reports
version: 1.0.0
raw:
  - name: peec_prompts_raw
    schema: peec.prompts_raw@1
    source: {kind: file, format: csv}
    mode: enforce
inputs:
  - name: peec_prompts
    schema: peec.prompts_export@1
    source: {kind: file, format: csv}
    mode: enforce
outputs:
  - name: report_payload
    schema: aivx.report@1
    sink: {kind: file, format: json}
    mode: enforce
```

- [ ] **Step 2: Write the failing test**

```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_contract.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'contract_core.contract'`.

- [ ] **Step 4: Write the implementation**

```python
# src/contract_core/contract.py
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

Mode = Literal["observe", "warn", "enforce"]
Direction = Literal["raw", "input", "output"]


class BoundarySpec(BaseModel):
    name: str
    schema: str  # a ref: "platform.name@version"
    mode: Mode = "enforce"
    source: dict | None = None
    sink: dict | None = None


class Contract(BaseModel):
    system: str
    version: str
    raw: list[BoundarySpec] = []
    inputs: list[BoundarySpec] = []
    outputs: list[BoundarySpec] = []

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Contract":
        data = yaml.safe_load(Path(path).read_text())
        return cls.model_validate(data)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_contract.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add src/contract_core/contract.py tests/test_contract.py tests/fixtures/contract.yaml
git commit -m "feat: contract model and YAML loader"
```

---

### Task 5: Resolver (local search paths, `name@version` and `name@major`)

**Files:**
- Create: `src/contract_core/resolver.py`
- Create: `tests/fixtures/schemas/peec/prompts_export/1.1.0.yaml`
- Test: `tests/test_resolver.py`

**Interfaces:**
- Consumes: `contract_core.schema.Schema`.
- Produces:
  - `class Resolver`: `__init__(self, search_paths: list[str | Path])`.
  - `resolve(self, ref: str) -> Schema` — `ref` is `dotted.name@version`. If `version` is a full semver (`1.1.0`) → exact match. If it is a major only (`1`) → newest available version with that major. Raises `SchemaNotFound` (subclass of `KeyError`) if nothing matches.
  - Layout convention: a schema `peec.prompts_export@1.1.0` lives at `<search_path>/peec/prompts_export/1.1.0.yaml` (dotted name → path with `.`→`/`).

- [ ] **Step 1: Write the second fixture (a newer minor of the same schema)**

```yaml
# tests/fixtures/schemas/peec/prompts_export/1.1.0.yaml
schema: peec.prompts_export
version: 1.1.0
kind: tabular
fields:
  - name: prompt
    type: string
    required: true
  - name: sentiment
    type: float
    required: true
    nullable: true
  - name: position
    type: int
    required: true
    nullable: true
  - name: share_of_voice
    type: float
    required: true
    nullable: true
  - name: mentions
    type: int
    required: false
    nullable: true
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_resolver.py
from pathlib import Path

import pytest
from contract_core.resolver import Resolver, SchemaNotFound

FIX = Path(__file__).parent / "fixtures" / "schemas"


def test_exact_version_resolves():
    r = Resolver([FIX])
    s = r.resolve("peec.prompts_export@1.0.0")
    assert s.version == "1.0.0"


def test_major_pin_resolves_to_newest_matching():
    r = Resolver([FIX])
    s = r.resolve("peec.prompts_export@1")
    assert s.version == "1.1.0"  # newest with major 1


def test_missing_schema_raises():
    r = Resolver([FIX])
    with pytest.raises(SchemaNotFound):
        r.resolve("peec.nonexistent@1")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_resolver.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'contract_core.resolver'`.

- [ ] **Step 4: Write the implementation**

```python
# src/contract_core/resolver.py
from pathlib import Path

from contract_core.schema import Schema


class SchemaNotFound(KeyError):
    pass


def _parse_semver(v: str) -> tuple[int, int, int]:
    parts = [int(p) for p in v.split(".")]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])  # type: ignore[return-value]


class Resolver:
    def __init__(self, search_paths: list[str | Path]) -> None:
        self.search_paths = [Path(p) for p in search_paths]

    def resolve(self, ref: str) -> Schema:
        name, _, version = ref.partition("@")
        rel = Path(*name.split("."))
        exact = "." in version  # "1.1.0" has dots; "1" does not
        for base in self.search_paths:
            schema_dir = base / rel
            if not schema_dir.is_dir():
                continue
            if exact:
                path = schema_dir / f"{version}.yaml"
                if path.is_file():
                    return Schema.from_yaml(path)
            else:
                major = int(version)
                candidates = [
                    (p, _parse_semver(p.stem))
                    for p in schema_dir.glob("*.yaml")
                    if _parse_semver(p.stem)[0] == major
                ]
                if candidates:
                    best = max(candidates, key=lambda c: c[1])[0]
                    return Schema.from_yaml(best)
        raise SchemaNotFound(ref)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_resolver.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add src/contract_core/resolver.py tests/test_resolver.py tests/fixtures/schemas/peec/prompts_export/1.1.0.yaml
git commit -m "feat: schema resolver with exact and major-pin resolution"
```

---

### Task 6: Compile Schema → Pandera DataFrameSchema (tabular)

**Files:**
- Create: `src/contract_core/compile/__init__.py`
- Create: `src/contract_core/compile/pandera_compile.py`
- Test: `tests/test_compile_pandera.py`

**Interfaces:**
- Consumes: `contract_core.schema.Schema`, `contract_core.types.PANDAS_DTYPE`.
- Produces:
  - `to_pandera(schema: Schema, *, strict: bool) -> pandera.pandas.DataFrameSchema`.
  - `strict=False` (open — inputs): unknown columns pass. Required fields become `required=True` columns; `nullable` maps through.
  - **`coerce=False` — this is load-bearing.** With `coerce=True`, Pandera would silently convert a vendor's stringified `"1"` into `Int64` and *pass*, defeating success criterion #1 (type-change detection), which is the whole point of the system. Columns must be checked at their incoming dtype so a type change is a hard failure.
  - Raises `ValueError` if `schema.kind != "tabular"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_compile_pandera.py
import pandas as pd
import pandera.pandas as pa
import pytest
from contract_core.compile.pandera_compile import to_pandera
from contract_core.schema import Schema


def _schema():
    return Schema.model_validate({
        "schema": "peec.prompts_export", "version": "1.0.0", "kind": "tabular",
        "fields": [
            {"name": "prompt", "type": "string", "required": True},
            {"name": "position", "type": "int", "required": True, "nullable": True},
        ],
    })


def _good_df():
    return pd.DataFrame({"prompt": ["a"], "position": pd.array([1], dtype="Int64")})


def test_good_data_passes():
    ps = to_pandera(_schema(), strict=False)
    ps.validate(_good_df())  # must not raise


def test_open_schema_allows_extra_columns():
    ps = to_pandera(_schema(), strict=False)
    df = _good_df()
    df["extra"] = [9]
    ps.validate(df)  # must not raise — extra column allowed when open


def test_missing_required_column_fails():
    ps = to_pandera(_schema(), strict=False)
    df = _good_df().drop(columns=["position"])  # missing `position`
    with pytest.raises(pa.errors.SchemaError):
        ps.validate(df)


def test_wrong_dtype_fails_not_coerced():
    # criterion #1 lives or dies here: a stringified int MUST fail, not coerce.
    ps = to_pandera(_schema(), strict=False)
    df = _good_df()
    df["position"] = df["position"].astype(str)  # object, not Int64
    with pytest.raises(pa.errors.SchemaError):
        ps.validate(df)


def test_rejects_non_tabular():
    s = Schema.model_validate({"schema": "x.y", "version": "1.0.0", "kind": "payload",
                               "json_schema": {"type": "object"}})
    with pytest.raises(ValueError):
        to_pandera(s, strict=False)
```

**String-dtype note for the engineer:** `test_good_data_passes` also settles how `string` fields validate. If Pandera's `str` check rejects a plain `object`-dtype column of Python strings under `coerce=False`, adjust the `string` entry in `PANDAS_DTYPE` (Task 2) — e.g. to pandas `"string"` with a read-time cast, or keep object-str — until `test_good_data_passes` is green. Settle it *here*, not in Task 15. `date`/`datetime` fields would need parsing under `coerce=False`; the pilot uses none, so that rough edge is deferred (note it, don't solve it).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_compile_pandera.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'contract_core.compile'`.

- [ ] **Step 3: Write `compile/__init__.py` (empty package marker)**

```python
# src/contract_core/compile/__init__.py
```

- [ ] **Step 4: Write the implementation**

```python
# src/contract_core/compile/pandera_compile.py
import pandera.pandas as pa

from contract_core.schema import Schema
from contract_core.types import PANDAS_DTYPE


def to_pandera(schema: Schema, *, strict: bool) -> pa.DataFrameSchema:
    if schema.kind != "tabular":
        raise ValueError(f"to_pandera requires kind 'tabular', got {schema.kind!r}")
    columns = {
        f.name: pa.Column(
            PANDAS_DTYPE[f.type],
            nullable=f.nullable,
            required=f.required,
            coerce=False,  # load-bearing: coercion would hide type drift (criterion #1)
        )
        for f in schema.fields
    }
    return pa.DataFrameSchema(columns, strict=strict)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_compile_pandera.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add src/contract_core/compile/__init__.py src/contract_core/compile/pandera_compile.py tests/test_compile_pandera.py
git commit -m "feat: compile schema to pandera DataFrameSchema"
```

---

### Task 7: Compile Schema → JSON Schema (payload, structural core)

**Files:**
- Create: `src/contract_core/compile/jsonschema_compile.py`
- Test: `tests/test_compile_jsonschema.py`

**Interfaces:**
- Consumes: `contract_core.schema.Schema`, `contract_core.types.JSON_SCHEMA_TYPE`.
- Produces:
  - `to_json_schema(schema: Schema, *, open: bool) -> dict` — a Draft 2020-12 object schema (the structural core only).
  - For a `fields` schema: `properties` from field types; `required` list = required field names; `additionalProperties` = `True` when `open` else `False`; `nullable` fields get `{"type": [T, "null"]}`.
  - For a `json_schema` passthrough schema: return `schema.json_schema` unchanged (author owns it).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_compile_jsonschema.py
from contract_core.compile.jsonschema_compile import to_json_schema
from contract_core.schema import Schema


def _payload():
    return Schema.model_validate({
        "schema": "aivx.report", "version": "1.0.0", "kind": "payload",
        "fields": [
            {"name": "slug", "type": "string", "required": True},
            {"name": "score", "type": "float", "required": True, "nullable": True},
        ],
    })


def test_open_payload_allows_additional_properties():
    js = to_json_schema(_payload(), open=True)
    assert js["additionalProperties"] is True
    assert js["required"] == ["slug", "score"]
    assert js["properties"]["slug"] == {"type": "string"}
    assert js["properties"]["score"] == {"type": ["number", "null"]}


def test_closed_payload_forbids_additional_properties():
    js = to_json_schema(_payload(), open=False)
    assert js["additionalProperties"] is False


def test_passthrough_returns_authored_json_schema():
    s = Schema.model_validate({
        "schema": "x.y", "version": "1.0.0", "kind": "payload",
        "json_schema": {"type": "object", "properties": {"a": {"type": "string"}}},
    })
    assert to_json_schema(s, open=True) == {"type": "object", "properties": {"a": {"type": "string"}}}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_compile_jsonschema.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

```python
# src/contract_core/compile/jsonschema_compile.py
from contract_core.schema import Schema
from contract_core.types import JSON_SCHEMA_TYPE


def _field_schema(field_type: str, nullable: bool) -> dict:
    base = dict(JSON_SCHEMA_TYPE[field_type])
    if nullable:
        t = base["type"]
        base["type"] = [t, "null"]
    return base


def to_json_schema(schema: Schema, *, open: bool) -> dict:
    if schema.json_schema is not None:
        return schema.json_schema
    props = {f.name: _field_schema(f.type, f.nullable) for f in schema.fields}
    required = [f.name for f in schema.fields if f.required]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": props,
        "required": required,
        "additionalProperties": bool(open),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_compile_jsonschema.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/contract_core/compile/jsonschema_compile.py tests/test_compile_jsonschema.py
git commit -m "feat: compile schema to structural-core JSON Schema"
```

---

### Task 8: Compile Contract → ODCS document + validate against pinned ODCS JSON Schema

**Files:**
- Create: `src/contract_core/compile/odcs.py`
- Create: `src/contract_core/vendor/odcs-json-schema-v3.1.0-20260505.json` (fetched, vendored)
- Test: `tests/test_compile_odcs.py`

**Interfaces:**
- Consumes: `contract_core.contract.Contract`, `contract_core.resolver.Resolver`, `contract_core.schema.Schema`.
- Produces:
  - `to_odcs(contract: Contract, resolver: Resolver) -> dict` — resolves every boundary's schema ref and inlines it as an ODCS `schema` list entry; emits a spec-valid ODCS v3.1.0 document. Deterministic field order.
  - `validate_odcs(doc: dict) -> None` — validates `doc` against the vendored dated ODCS JSON Schema; raises `jsonschema.ValidationError` on failure.

**Note on the vendored schema:** fetch the *dated* file from the Bitol repo. Confirm the exact path/filename in `bitol-io/open-data-contract-standard` under `schema/` before committing (the research noted the 3.1.0 schema was edited in place on 2026-05-05; the dated snapshot is the reproducible one). If the exact dated filename differs, vendor the 3.1.0 schema you actually fetched and rename the local copy to match `-20260505` only if that is genuinely the dated artifact.

- [ ] **Step 1: Fetch and vendor the ODCS JSON Schema**

Run:
```bash
mkdir -p src/contract_core/vendor
curl -fsSL "https://raw.githubusercontent.com/bitol-io/open-data-contract-standard/main/schema/odcs-json-schema-latest.json" \
  -o src/contract_core/vendor/odcs-json-schema-v3.1.0-20260505.json
head -c 200 src/contract_core/vendor/odcs-json-schema-v3.1.0-20260505.json
```
Expected: a JSON document beginning with `{` and referencing `$schema`. **Verify** it declares ODCS v3.x; if the repo layout has changed, locate the dated 3.1.0 schema and vendor that instead. Record the source URL + retrieval date in a comment header is not possible in JSON — note it in the commit message.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_compile_odcs.py
from pathlib import Path

import jsonschema
import pytest
from contract_core.compile.odcs import to_odcs, validate_odcs
from contract_core.contract import Contract
from contract_core.resolver import Resolver

FIX = Path(__file__).parent / "fixtures"


def test_odcs_document_is_valid_and_inlines_schemas():
    contract = Contract(
        system="demo", version="1.0.0",
        inputs=[{"name": "prompts", "schema": "peec.prompts_export@1.0.0",
                 "source": {"kind": "file", "format": "csv"}}],
    )
    resolver = Resolver([FIX / "schemas"])
    doc = to_odcs(contract, resolver)
    assert doc["kind"] == "DataContract"
    assert doc["version"] == "1.0.0"
    # the resolved schema's fields are inlined as ODCS properties
    names = [p["name"] for s in doc["schema"] for p in s["properties"]]
    assert "prompt" in names
    validate_odcs(doc)  # must not raise


def test_validate_odcs_rejects_malformed():
    with pytest.raises(jsonschema.ValidationError):
        validate_odcs({"not": "an odcs document"})
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_compile_odcs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'contract_core.compile.odcs'`.

- [ ] **Step 4: Write the implementation**

```python
# src/contract_core/compile/odcs.py
import json
from importlib import resources

import jsonschema

from contract_core.contract import BoundarySpec, Contract
from contract_core.resolver import Resolver
from contract_core.schema import Schema

_ODCS_LOGICAL = {
    "string": "string", "int": "integer", "float": "number",
    "bool": "boolean", "date": "date", "datetime": "date",
}


def _schema_block(name: str, resolved: Schema) -> dict:
    props = []
    if resolved.fields is not None:
        for f in resolved.fields:
            props.append({
                "name": f.name,
                "logicalType": _ODCS_LOGICAL[f.type],
                "required": f.required,
            })
    return {"name": name, "physicalType": "table", "properties": props}


def to_odcs(contract: Contract, resolver: Resolver) -> dict:
    blocks = []
    for group in (contract.raw, contract.inputs, contract.outputs):
        for b in group:  # type: BoundarySpec
            resolved = resolver.resolve(b.schema)
            blocks.append(_schema_block(b.name, resolved))
    return {
        "apiVersion": "v3.1.0",
        "kind": "DataContract",
        "id": contract.system,
        "name": contract.system,
        "version": contract.version,
        "status": "active",
        "schema": blocks,
    }


def _load_odcs_schema() -> dict:
    text = (
        resources.files("contract_core.vendor")
        .joinpath("odcs-json-schema-v3.1.0-20260505.json")
        .read_text()
    )
    return json.loads(text)


def validate_odcs(doc: dict) -> None:
    jsonschema.validate(instance=doc, schema=_load_odcs_schema())
```

- [ ] **Step 5: Make the vendored JSON importable as package data**

Add to `pyproject.toml` under `[tool.hatch.build.targets.wheel]`:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/contract_core"]

[tool.hatch.build.targets.wheel.force-include]
"src/contract_core/vendor/odcs-json-schema-v3.1.0-20260505.json" = "contract_core/vendor/odcs-json-schema-v3.1.0-20260505.json"
```

Create `src/contract_core/vendor/__init__.py` (empty) so `resources.files("contract_core.vendor")` works. Reinstall: `.venv/bin/pip install -e ".[dev]"`.

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_compile_odcs.py -v`
Expected: PASS (2 tests). If ODCS validation fails on a required top-level key the schema demands, add that key to `to_odcs` (e.g. `description`, `tags`) until the document validates — the test is the arbiter.

- [ ] **Step 7: Commit**

```bash
git add src/contract_core/compile/odcs.py src/contract_core/vendor/ tests/test_compile_odcs.py pyproject.toml
git commit -m "feat: compile contract to validated ODCS v3.1.0 document

Vendored ODCS JSON Schema from bitol-io/open-data-contract-standard (retrieved 2026-07-16)."
```

---

### Task 9: `ContractViolation` error with structural diff

**Files:**
- Create: `src/contract_core/errors.py`
- Test: `tests/test_errors.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class FieldDiff(pydantic.BaseModel)`: `field: str`, `expected: str`, `observed: str`, `problem: Literal["missing","retyped","extra"]`.
  - `class ContractViolation(Exception)`: `__init__(self, *, boundary: str, schema_ref: str, direction: str, diffs: list[FieldDiff])`; `__str__` renders the §8 message format:
    `<schema_ref> at <direction> '<boundary>': <problem> field '<field>' expected <expected>, observed <observed>` (one line per diff).

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_errors.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

```python
# src/contract_core/errors.py
from typing import Literal

from pydantic import BaseModel


class FieldDiff(BaseModel):
    field: str
    expected: str
    observed: str
    problem: Literal["missing", "retyped", "extra"]


class ContractViolation(Exception):
    def __init__(self, *, boundary: str, schema_ref: str, direction: str,
                 diffs: list[FieldDiff]) -> None:
        self.boundary = boundary
        self.schema_ref = schema_ref
        self.direction = direction
        self.diffs = diffs
        super().__init__(self._render())

    def _render(self) -> str:
        lines = []
        for d in self.diffs:
            lines.append(
                f"{self.schema_ref} at {self.direction} '{self.boundary}': "
                f"{d.problem} field '{d.field}' expected {d.expected}, observed {d.observed}"
            )
        return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_errors.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/contract_core/errors.py tests/test_errors.py
git commit -m "feat: ContractViolation with structural diff message"
```

---

### Task 10: Validation event log

**Files:**
- Create: `src/contract_core/events.py`
- Test: `tests/test_events.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class EventLog`: `__init__(self, path: str | Path | None = None)` — defaults to env `CONTRACT_EVENT_LOG`, else `./contract-events.jsonl`.
  - `emit(self, *, system: str, boundary: str, schema: str, version: str, result: Literal["pass","warn","violation"], observed_shape: dict, timestamp: str)` — appends one JSON line.
  - `records(self) -> list[dict]` — reads back all emitted records (test/debug helper).
  - Timestamp is passed in by the caller (runtime passes `datetime.now(UTC).isoformat()`); `EventLog` does not call the clock, so it is trivially testable.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_events.py
from contract_core.events import EventLog


def test_emit_and_read_back(tmp_path):
    log = EventLog(tmp_path / "events.jsonl")
    log.emit(system="aivx-reports", boundary="peec_prompts",
             schema="peec.prompts_export", version="1.0.0",
             result="pass", observed_shape={"columns": ["prompt"]},
             timestamp="2026-07-16T00:00:00+00:00")
    recs = log.records()
    assert len(recs) == 1
    assert recs[0]["result"] == "pass"
    assert recs[0]["boundary"] == "peec_prompts"
    assert recs[0]["observed_shape"] == {"columns": ["prompt"]}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_events.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

```python
# src/contract_core/events.py
import json
import os
from pathlib import Path
from typing import Literal

Result = Literal["pass", "warn", "violation"]


class EventLog:
    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            path = os.environ.get("CONTRACT_EVENT_LOG", "./contract-events.jsonl")
        self.path = Path(path)

    def emit(self, *, system: str, boundary: str, schema: str, version: str,
             result: Result, observed_shape: dict, timestamp: str) -> None:
        record = {
            "system": system, "boundary": boundary, "schema": schema,
            "version": version, "result": result,
            "observed_shape": observed_shape, "timestamp": timestamp,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as fh:
            fh.write(json.dumps(record) + "\n")

    def records(self) -> list[dict]:
        if not self.path.is_file():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_events.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/contract_core/events.py tests/test_events.py
git commit -m "feat: JSONL validation event log"
```

---

### Task 11: Runtime decorators — modes, 2×2 strictness, two boundaries

This is the core task. It wires load → resolve → compile → validate → event, honoring the mode ladder and the strictness 2×2, for both tabular (Pandera) and payload (JSON Schema) boundaries.

**Files:**
- Create: `src/contract_core/runtime.py`
- Test: `tests/test_runtime.py`

**Interfaces:**
- Consumes: `Resolver`, `to_pandera`, `to_json_schema`, `ContractViolation`, `FieldDiff`, `EventLog`, `Contract`, `BoundarySpec`.
- Produces:
  - `class ContractRuntime`:
    - `__init__(self, contract: Contract, resolver: Resolver, event_log: EventLog | None = None, clock: Callable[[], str] | None = None)`.
    - decorator factories `raw(name)`, `input(name)`, `output(name)` — each looks up the `BoundarySpec` by `name` in the matching group, resolves its schema, and wraps the decorated function so its **return value** is validated before being handed back.
    - `REGISTRY: list[tuple[str, str]]` — module-level list of `(direction, name)` appended on decoration (Phase-1 `reconcile` consumes this; Phase 0 only populates it — a test asserts it is populated).
  - Validation semantics per the 2×2:
    - `raw`/`input`: open. Tabular → `to_pandera(strict=False)`; payload → `to_json_schema(open=True)`. A *missing/retyped* declared field is a hard violation; extra fields pass silently.
    - `output`: complete. *Missing* declared field → hard violation; *extra* field → `warn` (never raises), independent of mode.
    - Mode gates hard violations only: `observe` → never raise (log `result="violation"` but return data); `warn` → never raise (log); `enforce` → raise `ContractViolation`.
  - `observed_shape`: tabular → `{"columns": [...], "dtypes": {col: str(dtype)}}`; payload → `{"keys": [...]}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_runtime.py
import pandas as pd
import pytest
from contract_core.contract import Contract
from contract_core.errors import ContractViolation
from contract_core.events import EventLog
from contract_core.resolver import Resolver
from contract_core.runtime import ContractRuntime

from pathlib import Path
FIX = Path(__file__).parent / "fixtures"


def _runtime(tmp_path, mode="enforce"):
    contract = Contract.model_validate({
        "system": "demo", "version": "1.0.0",
        "inputs": [{"name": "prompts", "schema": "peec.prompts_export@1.0.0", "mode": mode}],
    })
    resolver = Resolver([FIX / "schemas"])
    log = EventLog(tmp_path / "events.jsonl")
    return ContractRuntime(contract, resolver, event_log=log,
                           clock=lambda: "2026-07-16T00:00:00+00:00"), log


def _good_df():
    return pd.DataFrame({
        "prompt": ["a"], "sentiment": [0.5],
        "position": pd.array([1], dtype="Int64"),
        "share_of_voice": [0.3],
    })


def test_enforce_passes_valid_data_and_logs(tmp_path):
    rt, log = _runtime(tmp_path)

    @rt.input("prompts")
    def load():
        return _good_df()

    out = load()
    assert list(out.columns) == ["prompt", "sentiment", "position", "share_of_voice"]
    assert log.records()[0]["result"] == "pass"


def test_enforce_extra_column_passes_open_input(tmp_path):
    rt, _ = _runtime(tmp_path)

    @rt.input("prompts")
    def load():
        df = _good_df()
        df["surprise_vendor_column"] = [1]
        return df

    load()  # must not raise — inputs are open


def test_enforce_missing_required_column_raises(tmp_path):
    rt, log = _runtime(tmp_path)

    @rt.input("prompts")
    def load():
        return _good_df().drop(columns=["position"])

    with pytest.raises(ContractViolation) as ei:
        load()
    assert "position" in str(ei.value)
    assert log.records()[-1]["result"] == "violation"


def test_observe_never_raises_but_logs_violation(tmp_path):
    rt, log = _runtime(tmp_path, mode="observe")

    @rt.input("prompts")
    def load():
        return _good_df().drop(columns=["position"])

    load()  # observe: no raise
    assert log.records()[-1]["result"] == "violation"


def test_registry_is_populated(tmp_path):
    from contract_core.runtime import ContractRuntime
    rt, _ = _runtime(tmp_path)

    @rt.input("prompts")
    def load():
        return _good_df()

    assert ("input", "prompts") in ContractRuntime.REGISTRY
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_runtime.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'contract_core.runtime'`.

- [ ] **Step 3: Write the implementation**

```python
# src/contract_core/runtime.py
import functools
from typing import Callable

import pandas as pd
import pandera.pandas as pa

from contract_core.compile.jsonschema_compile import to_json_schema
from contract_core.compile.pandera_compile import to_pandera
from contract_core.contract import BoundarySpec, Contract
from contract_core.errors import ContractViolation, FieldDiff
from contract_core.events import EventLog
from contract_core.resolver import Resolver
from contract_core.schema import Schema


def _default_clock() -> str:
    from datetime import UTC, datetime
    return datetime.now(UTC).isoformat()


class ContractRuntime:
    REGISTRY: list[tuple[str, str]] = []

    def __init__(self, contract: Contract, resolver: Resolver,
                 event_log: EventLog | None = None,
                 clock: Callable[[], str] | None = None) -> None:
        self.contract = contract
        self.resolver = resolver
        self.event_log = event_log or EventLog()
        self.clock = clock or _default_clock

    def _spec(self, direction: str, name: str) -> BoundarySpec:
        group = {"raw": self.contract.raw, "input": self.contract.inputs,
                 "output": self.contract.outputs}[direction]
        for b in group:
            if b.name == name:
                return b
        raise KeyError(f"no {direction} boundary named {name!r} in contract")

    def raw(self, name: str):
        return self._decorator("raw", name)

    def input(self, name: str):
        return self._decorator("input", name)

    def output(self, name: str):
        return self._decorator("output", name)

    def _decorator(self, direction: str, name: str):
        spec = self._spec(direction, name)
        resolved = self.resolver.resolve(spec.schema)
        ContractRuntime.REGISTRY.append((direction, name))

        def deco(fn):
            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                data = fn(*args, **kwargs)
                self._validate(direction, spec, resolved, data)
                return data
            return wrapper
        return deco

    # ---- validation ----

    def _validate(self, direction: str, spec: BoundarySpec, resolved: Schema, data) -> None:
        is_output = direction == "output"
        if resolved.kind == "tabular":
            diffs, observed = self._validate_tabular(resolved, data, is_output)
        else:
            diffs, observed = self._validate_payload(resolved, data, is_output)

        hard = [d for d in diffs if d.problem in ("missing", "retyped")]
        extra = [d for d in diffs if d.problem == "extra"]

        if hard:
            result = "violation"
        elif extra and is_output:
            result = "warn"
        else:
            result = "pass"

        self.event_log.emit(
            system=self.contract.system, boundary=spec.name,
            schema=resolved.schema, version=resolved.version,
            result=result, observed_shape=observed, timestamp=self.clock(),
        )

        if hard and spec.mode == "enforce":
            raise ContractViolation(boundary=spec.name, schema_ref=resolved.ref,
                                    direction=direction, diffs=hard)

    def _validate_tabular(self, resolved: Schema, df: pd.DataFrame, is_output: bool):
        observed = {"columns": list(df.columns),
                    "dtypes": {c: str(t) for c, t in df.dtypes.items()}}
        diffs: list[FieldDiff] = []
        ps = to_pandera(resolved, strict=False)
        try:
            ps.validate(df, lazy=True)
        except pa.errors.SchemaErrors as err:
            for _, row in err.failure_cases.iterrows():
                col = row.get("column")
                if col is None:
                    continue
                declared = next((f for f in resolved.fields if f.name == col), None)
                expected = declared.type if declared else "?"
                problem = "missing" if "column" in str(row.get("check", "")).lower() \
                    and col not in df.columns else "retyped"
                if col not in df.columns:
                    problem = "missing"
                diffs.append(FieldDiff(field=str(col), expected=str(expected),
                                       observed=str(df.dtypes.get(col, "absent")),
                                       problem=problem))
        # de-dup by field
        seen = {}
        for d in diffs:
            seen[d.field] = d
        diffs = list(seen.values())
        if is_output:
            declared_names = {f.name for f in resolved.fields}
            for c in df.columns:
                if c not in declared_names:
                    diffs.append(FieldDiff(field=str(c), expected="absent",
                                           observed=str(df.dtypes[c]), problem="extra"))
        return diffs, observed

    def _validate_payload(self, resolved: Schema, payload: dict, is_output: bool):
        import jsonschema
        observed = {"keys": list(payload.keys())}
        js = to_json_schema(resolved, open=not is_output)
        diffs: list[FieldDiff] = []
        validator = jsonschema.Draft202012Validator(js)
        for err in validator.iter_errors(payload):
            if err.validator == "required":
                # message: "'x' is a required property"
                missing = err.message.split("'")[1]
                diffs.append(FieldDiff(field=missing, expected="present",
                                       observed="absent", problem="missing"))
            elif err.validator == "type" and err.path:
                field = str(err.path[-1])
                diffs.append(FieldDiff(field=field, expected=str(err.validator_value),
                                       observed=type(err.instance).__name__, problem="retyped"))
            elif err.validator == "additionalProperties" and is_output:
                # closed output: name the extras
                declared = set((resolved.json_schema or {}).get("properties", {})) \
                    if resolved.json_schema else {f.name for f in resolved.fields}
                for k in payload:
                    if k not in declared:
                        diffs.append(FieldDiff(field=str(k), expected="absent",
                                               observed=type(payload[k]).__name__,
                                               problem="extra"))
        return diffs, observed
```

**Implementation note for the engineer:** the tabular missing-vs-retyped classification via Pandera's `failure_cases` is fiddly. The test suite (Step 1) is the contract — if a case misclassifies `missing` vs `retyped`, adjust `_validate_tabular` until `test_enforce_missing_required_column_raises` and Task 15's type-change test both pass. The *observable* requirement is: missing and retyped both produce a hard violation naming the field; the `problem` label is secondary.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_runtime.py -v`
Expected: PASS (5 tests). Iterate on `_validate_tabular` if the missing-column case misclassifies.

- [ ] **Step 5: Add a payload output test (extra field warns, missing fails)**

```python
# append to tests/test_runtime.py

def _payload_runtime(tmp_path, mode="enforce"):
    contract = Contract.model_validate({
        "system": "demo", "version": "1.0.0",
        "outputs": [{"name": "report", "schema": "aivx.report@1.0.0", "mode": mode}],
    })
    resolver = Resolver([FIX / "schemas"])
    log = EventLog(tmp_path / "e.jsonl")
    return ContractRuntime(contract, resolver, event_log=log,
                           clock=lambda: "2026-07-16T00:00:00+00:00"), log


def test_output_missing_field_raises(tmp_path):
    rt, _ = _payload_runtime(tmp_path)

    @rt.output("report")
    def produce():
        return {"slug": "digital-banks"}  # missing "score"

    with pytest.raises(ContractViolation):
        produce()


def test_output_extra_field_warns_not_raises(tmp_path):
    rt, log = _payload_runtime(tmp_path)

    @rt.output("report")
    def produce():
        return {"slug": "x", "score": 0.9, "debug_note": "hi"}

    produce()  # extra field must NOT raise
    assert log.records()[-1]["result"] == "warn"
```

This requires an `aivx.report@1.0.0` payload fixture:

```yaml
# tests/fixtures/schemas/aivx/report/1.0.0.yaml
schema: aivx.report
version: 1.0.0
kind: payload
fields:
  - name: slug
    type: string
    required: true
  - name: score
    type: float
    required: true
    nullable: true
```

- [ ] **Step 6: Run the payload tests**

Run: `.venv/bin/python -m pytest tests/test_runtime.py -v`
Expected: PASS (7 tests total).

- [ ] **Step 7: Commit**

```bash
git add src/contract_core/runtime.py tests/test_runtime.py tests/fixtures/schemas/aivx/report/1.0.0.yaml
git commit -m "feat: runtime boundary decorators with modes and 2x2 strictness"
```

---

### Task 12: `contract lint` CLI

**Files:**
- Create: `src/contract_core/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `Contract`, `Resolver`, `to_odcs`, `validate_odcs`.
- Produces:
  - `main` (click group) with subcommand `lint`:
    - `contract lint --contract PATH --schemas DIR [--schemas DIR ...]` — loads the contract, resolves every boundary's schema ref (fails on `SchemaNotFound`), compiles to ODCS, validates the ODCS document. Exit 0 on success with `OK: <system>@<version> — N boundaries resolved`; exit 1 with a readable error listing unresolved refs.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
from pathlib import Path

from click.testing import CliRunner
from contract_core.cli import main

FIX = Path(__file__).parent / "fixtures"


def test_lint_ok():
    runner = CliRunner()
    res = runner.invoke(main, ["lint", "--contract", str(FIX / "contract_lintable.yaml"),
                               "--schemas", str(FIX / "schemas")])
    assert res.exit_code == 0, res.output
    assert "OK" in res.output


def test_lint_unresolved_ref_fails():
    runner = CliRunner()
    res = runner.invoke(main, ["lint", "--contract", str(FIX / "contract_broken.yaml"),
                               "--schemas", str(FIX / "schemas")])
    assert res.exit_code == 1
    assert "peec.nonexistent@1" in res.output
```

Create the two fixtures:

```yaml
# tests/fixtures/contract_lintable.yaml
system: demo
version: 1.0.0
inputs:
  - name: prompts
    schema: peec.prompts_export@1.0.0
    source: {kind: file, format: csv}
```

```yaml
# tests/fixtures/contract_broken.yaml
system: demo
version: 1.0.0
inputs:
  - name: prompts
    schema: peec.nonexistent@1
    source: {kind: file, format: csv}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

```python
# src/contract_core/cli.py
import sys

import click

from contract_core.compile.odcs import to_odcs, validate_odcs
from contract_core.contract import Contract
from contract_core.resolver import Resolver, SchemaNotFound


@click.group()
def main() -> None:
    """contract — data contract tooling."""


@main.command()
@click.option("--contract", "contract_path", required=True, type=click.Path(exists=True))
@click.option("--schemas", "schema_dirs", multiple=True, required=True, type=click.Path(exists=True))
def lint(contract_path: str, schema_dirs: tuple[str, ...]) -> None:
    """Validate a contract: resolve every schema ref and compile to valid ODCS."""
    contract = Contract.from_yaml(contract_path)
    resolver = Resolver(list(schema_dirs))
    boundaries = [*contract.raw, *contract.inputs, *contract.outputs]
    unresolved = []
    for b in boundaries:
        try:
            resolver.resolve(b.schema)
        except SchemaNotFound:
            unresolved.append(b.schema)
    if unresolved:
        click.echo("LINT FAILED — unresolved schema refs:")
        for ref in unresolved:
            click.echo(f"  - {ref}")
        sys.exit(1)
    doc = to_odcs(contract, resolver)
    validate_odcs(doc)
    click.echo(f"OK: {contract.system}@{contract.version} — {len(boundaries)} boundaries resolved")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_cli.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Verify the installed entry point works**

Run: `.venv/bin/contract lint --contract tests/fixtures/contract_lintable.yaml --schemas tests/fixtures/schemas`
Expected: `OK: demo@1.0.0 — 1 boundaries resolved`.

- [ ] **Step 6: Commit**

```bash
git add src/contract_core/cli.py tests/test_cli.py tests/fixtures/contract_lintable.yaml tests/fixtures/contract_broken.yaml
git commit -m "feat: contract lint command"
```

---

### Task 13: Pilot — author PEEC raw + normalized schemas and the aivx-reports contract

From here, work in the `aivx-reports` repo (`/Users/paulramirez/Documents/Projects/aivx-reports`). The raw-boundary schema comes from the documented PEEC CSV columns in `agent/peec_mapper.py`'s docstring; the normalized schema is the mapper's output columns.

**Files (in `aivx-reports`):**
- Create: `contracts/schemas/peec/prompts_raw/1.0.0.yaml`
- Create: `contracts/schemas/peec/prompts_mapped/1.0.0.yaml`
- Create: `contracts/contract.yaml`

**Interfaces:**
- Consumes: `contract_core` (installed into the aivx-reports venv).
- Produces: the pilot's schemas + contract, lintable by `contract lint`.

- [ ] **Step 1: Install `contract_core` into the pilot's environment**

Run (in `aivx-reports`):
```bash
/Users/paulramirez/Documents/Projects/aivx-reports/.venv/bin/pip install -e /Users/paulramirez/Documents/Projects/data-contract
```
(If the pilot has no venv, create one and `pip install -r agent/requirements.txt` first.)
Expected: `Successfully installed contract-core-0.0.1`.

- [ ] **Step 2: Author the raw PEEC prompts schema (from the mapper docstring's Prompts CSV columns)**

```yaml
# contracts/schemas/peec/prompts_raw/1.0.0.yaml
# Raw PEEC "General > Prompts" CSV export. Per-call-site, NOT promoted (§7).
# Column list confirmed from agent/peec_mapper.py docstring (2026-05-20 export).
schema: peec.prompts_raw
version: 1.0.0
kind: tabular
fields:
  - name: status
    type: string
    required: true
  - name: prompt
    type: string
    required: true
  - name: sentiment
    type: float
    required: true
    nullable: true
  - name: position
    type: int
    required: true
    nullable: true
  - name: mentions
    type: int
    required: true
    nullable: true
  - name: share_of_voice
    type: float
    required: true
    nullable: true
```

- [ ] **Step 3: Author the normalized (mapped) schema (the mapper's OUTPUT columns)**

Inspect `agent/peec_mapper.py` to confirm the exact output column names it writes to `peec_mapped.csv`, then:

```yaml
# contracts/schemas/peec/prompts_mapped/1.0.0.yaml
# Normalized AIVx agent-format columns emitted by peec_mapper.py. Promotable.
schema: peec.prompts_mapped
version: 1.0.0
kind: tabular
fields:
  - name: brand
    type: string
    required: true
  - name: prompt
    type: string
    required: true
  - name: present
    type: bool
    required: true
  - name: share_of_voice
    type: float
    required: true
    nullable: true
```

**If the real mapped columns differ, use the real ones** — the test in Task 15 validates against the actual mapper output, so these must match reality.

- [ ] **Step 4: Author the contract**

```yaml
# contracts/contract.yaml
system: aivx-reports
version: 1.0.0
raw:
  - name: peec_prompts_raw
    schema: peec.prompts_raw@1
    source: {kind: file, format: csv}
    mode: observe        # start in observe; promote to enforce in Task 15
inputs:
  - name: peec_prompts_mapped
    schema: peec.prompts_mapped@1
    source: {kind: file, format: csv}
    mode: observe
```

- [ ] **Step 5: Lint the contract**

Run (in `aivx-reports`):
```bash
.venv/bin/contract lint --contract contracts/contract.yaml --schemas contracts/schemas
```
Expected: `OK: aivx-reports@1.0.0 — 2 boundaries resolved`.

- [ ] **Step 6: Commit (in aivx-reports)**

```bash
cd /Users/paulramirez/Documents/Projects/aivx-reports
git add contracts/
git commit -m "feat(contracts): PEEC raw + mapped schemas and aivx-reports contract"
```

---

### Task 14: Pilot — decorate the two boundaries, run in `observe`

**Files (in `aivx-reports`):**
- Modify: `agent/peec_mapper.py` — decorate the raw-CSV read and the mapped-CSV write.

**Interfaces:**
- Consumes: `contract_core.runtime.ContractRuntime`, the pilot contract + schemas.
- Produces: a decorated mapper whose two boundaries validate-and-log on every run (in `observe`, never failing).

- [ ] **Step 1: Add a runtime bootstrap to the mapper**

Locate the function in `agent/peec_mapper.py` that reads the raw prompts CSV into a DataFrame (returns a `pd.DataFrame`), and the function/section that produces the mapped DataFrame before it is written to `--output`. Add near the top of the module:

```python
from pathlib import Path
from contract_core.contract import Contract
from contract_core.resolver import Resolver
from contract_core.runtime import ContractRuntime

_CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"
_RT = ContractRuntime(
    Contract.from_yaml(_CONTRACTS / "contract.yaml"),
    Resolver([_CONTRACTS / "schemas"]),
)
```

- [ ] **Step 2: Decorate the raw read**

Wrap the raw-prompts loader so its returned DataFrame is validated at the `peec_prompts_raw` boundary. If the read is currently inline (e.g. `df = pd.read_csv(prompts_path)`), extract it into a small function:

```python
@_RT.raw("peec_prompts_raw")
def _load_raw_prompts(prompts_path: str) -> "pd.DataFrame":
    return pd.read_csv(prompts_path)
```

and replace the inline read with `df = _load_raw_prompts(prompts_path)`.

- [ ] **Step 3: Decorate the mapped output**

Wrap the function that returns the fully mapped DataFrame (the value written to `peec_mapped.csv`) at the `peec_prompts_mapped` boundary:

```python
@_RT.input("peec_prompts_mapped")
def _finalize_mapped(df: "pd.DataFrame") -> "pd.DataFrame":
    return df
```

Call `mapped = _finalize_mapped(mapped)` immediately before the CSV is written. (It is declared under `inputs` in the contract because it is an input to the downstream agent; the decorator name matches.)

- [ ] **Step 4: Run the mapper on real/mock data in observe**

Run (in `aivx-reports`, using a real Peec export or the repo's `agent/mock_data`):
```bash
CONTRACT_EVENT_LOG=contract-events.jsonl .venv/bin/python agent/peec_mapper.py \
  --prompts <peec_prompts.csv> --urls <peec_urls.csv> --domains <peec_domains.csv> \
  --owned-brand "Chime" --output /tmp/peec_mapped.csv
```
Expected: completes without error (observe never fails); `contract-events.jsonl` contains two records with `result` `pass` or `violation` and the observed shapes. Inspect it:
```bash
cat contract-events.jsonl
```

- [ ] **Step 5: Reconcile the observed shape with the schemas**

If the raw boundary logged `result: violation`, the authored `peec.prompts_raw@1.0.0` disagrees with the real export — update the schema fields to match the observed columns/dtypes (this is the point of `observe`). Re-run until both boundaries log `pass`.

- [ ] **Step 6: Commit (in aivx-reports)**

```bash
git add agent/peec_mapper.py contracts/
git commit -m "feat(contracts): decorate PEEC raw + mapped boundaries (observe mode)"
```

---

### Task 15: Pilot — success criteria #1 and #2, then promote to `enforce`

This task is the Phase 0 acceptance gate. It encodes spec success criteria #1 (type change) and #2 (field removal) as literal tests against the pilot, then flips the boundaries to `enforce`.

**Files (in `aivx-reports`):**
- Create: `tests/test_contract_pilot.py`
- Modify: `contracts/contract.yaml` (observe → enforce)

**Interfaces:**
- Consumes: the decorated mapper, `ContractViolation`.
- Produces: passing acceptance tests; boundaries in `enforce`.

- [ ] **Step 1: Write the acceptance tests (criteria #1 and #2)**

```python
# tests/test_contract_pilot.py
import pandas as pd
import pytest
from contract_core.contract import Contract
from contract_core.errors import ContractViolation
from contract_core.resolver import Resolver
from contract_core.runtime import ContractRuntime
from pathlib import Path

CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"


def _enforcing_runtime(tmp_path):
    contract = Contract.from_yaml(CONTRACTS / "contract.yaml")
    # force enforce regardless of file state, so the test is self-contained
    for b in contract.raw:
        b.mode = "enforce"
    from contract_core.events import EventLog
    return ContractRuntime(contract, Resolver([CONTRACTS / "schemas"]),
                           event_log=EventLog(tmp_path / "e.jsonl"),
                           clock=lambda: "2026-07-16T00:00:00+00:00")


def _valid_raw_prompts():
    return pd.DataFrame({
        "status": ["ok"], "prompt": ["best bank?"],
        "sentiment": [0.4], "position": pd.array([1], dtype="Int64"),
        "mentions": pd.array([3], dtype="Int64"), "share_of_voice": [0.25],
    })


def test_criterion_1_type_change_hard_fails(tmp_path):
    rt = _enforcing_runtime(tmp_path)

    @rt.raw("peec_prompts_raw")
    def load():
        df = _valid_raw_prompts()
        df["position"] = df["position"].astype(str)  # vendor sends string, not int
        return df

    with pytest.raises(ContractViolation) as ei:
        load()
    assert "position" in str(ei.value)
    assert "peec.prompts_raw@1.0.0" in str(ei.value)


def test_criterion_2_field_removal_hard_fails(tmp_path):
    rt = _enforcing_runtime(tmp_path)

    @rt.raw("peec_prompts_raw")
    def load():
        return _valid_raw_prompts().drop(columns=["share_of_voice"])

    with pytest.raises(ContractViolation) as ei:
        load()
    assert "share_of_voice" in str(ei.value)
```

- [ ] **Step 2: Run the acceptance tests**

Run (in `aivx-reports`):
```bash
.venv/bin/python -m pytest tests/test_contract_pilot.py -v
```
Expected: PASS (2 tests). Both hard-fail at the boundary with the field named — this is spec §12 #1 and #2 satisfied. If a test fails because the violation isn't raised or the field isn't named, fix `contract_core._validate_tabular` (Task 11) — the acceptance test is the arbiter.

- [ ] **Step 3: Promote the boundaries to `enforce`**

Edit `contracts/contract.yaml`: change both `mode: observe` to `mode: enforce` (do this only after Task 14 Step 5 confirmed clean `observe` runs, so enforce won't break a real run on already-correct data).

- [ ] **Step 4: Re-run the mapper end-to-end in enforce on good data**

Run the same command as Task 14 Step 4. Expected: completes successfully (data already matches the schema), event log shows `pass`.

- [ ] **Step 5: Commit (in aivx-reports)**

```bash
git add tests/test_contract_pilot.py contracts/contract.yaml
git commit -m "test(contracts): success criteria #1/#2; promote boundaries to enforce"
```

---

### Task 16: R2 groundwork — adapter drift-test convention

The R2 gate (a `reconcile` finding when a raw boundary has no drift-test) is Phase 1. Phase 0 establishes the *convention* the gate will check: every raw boundary has a companion test that fails on an unknown raw shape. This task writes that test for the pilot and documents the convention so Phase 1 has something concrete to enforce.

**Files (in `aivx-reports`):**
- Create: `tests/test_peec_adapter_drift.py`
- Create: `contracts/README.md` (the convention, for the authoring skill + Phase 1 gate)

**Interfaces:**
- Consumes: `peec_mapper` adapter, `ContractViolation`.
- Produces: a drift-test proving the adapter does NOT silently absorb an unknown raw shape (R2), plus the documented convention.

- [ ] **Step 1: Write the adapter drift-test**

The test asserts that when the raw PEEC CSV is missing a column the adapter depends on, the pipeline fails at the raw boundary rather than the adapter coercing it into a valid mapped frame (R2: "adapter must fail on unknown raw shape").

```python
# tests/test_peec_adapter_drift.py
import pandas as pd
import pytest
from contract_core.contract import Contract
from contract_core.errors import ContractViolation
from contract_core.events import EventLog
from contract_core.resolver import Resolver
from contract_core.runtime import ContractRuntime
from pathlib import Path

CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"


def test_adapter_does_not_absorb_missing_raw_column(tmp_path):
    """R2: a raw shape change must surface at the raw boundary, not be coerced away."""
    contract = Contract.from_yaml(CONTRACTS / "contract.yaml")
    for b in contract.raw:
        b.mode = "enforce"
    rt = ContractRuntime(contract, Resolver([CONTRACTS / "schemas"]),
                         event_log=EventLog(tmp_path / "e.jsonl"),
                         clock=lambda: "2026-07-16T00:00:00+00:00")

    @rt.raw("peec_prompts_raw")
    def load_drifted():
        # vendor dropped `mentions` — the column the mapper's presence logic needs
        return pd.DataFrame({
            "status": ["ok"], "prompt": ["q"], "sentiment": [0.1],
            "position": pd.array([1], dtype="Int64"), "share_of_voice": [0.2],
        })

    with pytest.raises(ContractViolation) as ei:
        load_drifted()
    assert "mentions" in str(ei.value)
```

- [ ] **Step 2: Run the drift-test**

Run (in `aivx-reports`):
```bash
.venv/bin/python -m pytest tests/test_peec_adapter_drift.py -v
```
Expected: PASS.

- [ ] **Step 3: Document the convention**

```markdown
<!-- contracts/README.md -->
# Contracts — conventions

## Every raw boundary has a drift-test (R2)

For each boundary declared under `raw:` in `contract.yaml`, there MUST be a test
that feeds the decorated raw loader a payload missing a depended-on column and
asserts it raises `ContractViolation` at the raw boundary. This proves the
adapter (e.g. `peec_mapper.py`) does not silently coerce a changed vendor shape
into a valid mapped frame — the failure mode R2 exists to prevent.

Phase 1's `contract reconcile` will enforce this automatically: a raw boundary
with no companion drift-test is a reconcile finding. Until then, it is a
reviewed convention. Pilot example: `tests/test_peec_adapter_drift.py`.
```

- [ ] **Step 4: Commit (in aivx-reports)**

```bash
git add tests/test_peec_adapter_drift.py contracts/README.md
git commit -m "test(contracts): R2 adapter drift-test + convention doc"
```

---

## Phase 0 Definition of Done

- [ ] `contract_core` installs and all `tests/` in `data-contract` pass: `.venv/bin/python -m pytest -v`.
- [ ] `contract lint` resolves the pilot contract and validates its ODCS output.
- [ ] The pilot (`aivx-reports`) runs its mapper with both boundaries decorated; the event log records each crossing with an observed shape.
- [ ] **Success criterion #1** (type change) and **#2** (field removal) pass as literal tests against the pilot and hard-fail at the boundary naming the field and schema version.
- [ ] Both boundaries are in `enforce`, verified not to break on already-correct data.
- [ ] The R2 drift-test convention exists, with a passing pilot example.
- [ ] **Gate question answered (spec §13):** was the onboarding loop pleasant? Record friction (schema authoring, decorator placement, observe→enforce promotion) before deciding whether Phase 1 needs format changes.

## Deferred to later phases (do NOT build in Phase 0)

`reconcile` + the R2 gate enforcement (Phase 1) · the authoring skill (Phase 1) · `compat` + Karapace + semver-bump CI + success criteria #4/#5 (Phase 2) · JS validate-only SDK (Phase 3) · version GC · the canary · `datacontract-cli` runtime integration.
