# R9 — Distribution & Public API Surface — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `contract-core` installable from another repo by a pinned git tag, expose a curated
five-name public API that a frozen-surface test guards, and add an explicit, loud, un-overridable
kill switch so a consumer can keep the decorators in place with validation off.

**Architecture:** Three thin additions to code that already exists. (1) `runtime.py` gains a private
`_env_disabled()` helper, a `ContractRuntime.disabled()` classmethod returning a no-op runtime
(`_DisabledRuntime`, whose `raw`/`input`/`output` are the identity decorator), and a module-level
`load_runtime()` factory wrapping `Contract.from_yaml` + `Resolver`. (2) `__init__.py` re-exports
exactly five names and declares `__all__`; every other module stays private-by-convention with its
filename unchanged. (3) Distribution is a version bump plus process/docs — an annotated `vX.Y.Z` tag
is the artifact; there is no wheel and no index.

**Tech Stack:** Python 3.13, Pydantic v2, Pandera, `jsonschema`, PyYAML, `click`, `pytest`,
`ruff`, `mypy --strict`, hatchling.

**Source spec:** [2026-07-20-r9-distribution-public-api-design.md](../specs/2026-07-20-r9-distribution-public-api-design.md).
Read §3 and §5 before starting. Section references below (§3.2, §5 T1…T5) point into that document.

**Branch:** work on the current `docs/r9-distribution-public-api` branch or cut a `feat/r9-*` branch
from it. PR base is `dev` (see `CONTRIBUTING.md` — **never push to `main`**).

## Superseded — read this before executing any task

**This plan has been executed** (PR #10). It is kept as the record of what was intended, **not** as
instructions to follow verbatim. Five things diverged, and in each case **the shipped code is
canonical** — copying the snippet below it reintroduces a defect that review already caught.

| Where | The plan says | What shipped, and why |
|---|---|---|
| Task 1 | Two tests: `test_version_is_0_1_0` asserting the literal, plus a check against `importlib.metadata` | One test, `test_version_matches_pyproject`, reading `pyproject.toml` with `tomllib`. The literal put the version in a *third* place while the release procedure names two, so the next release started red. The metadata comparison is a snapshot taken at install time — on a dev machine with a stale editable install it compares `__init__.py` against a version nobody ships and passes on a real skew. |
| Task 2 | `_ENV_OFF_VALUES = frozenset({"", "0", "false", "no"})` | `{"", "0", "false", "no", "off"}`. As planned, `CONTRACT_DISABLED=off` **disabled** validation — the exact foot-gun the pinned table exists to prevent, and worse because the docs listed `=on` under "disables" and so taught the `on`/`off` vocabulary. |
| Task 3 | The announcement is a `logging.warning` | A bare `print(..., file=sys.stderr)`. A log record reaches stderr only via `logging.lastResort`; one `basicConfig` call in the consuming app deletes it, which would falsify the consumer doc's guarantee that the line's absence means validation is on. |
| Task 7 | `venv --system-site-packages` + `--no-deps` | A `.pth` naming the running interpreter's `purelib`, plus `--no-build-isolation` and `REPO.as_uri()`. See the note in Task 7 — the planned recipe **cannot work**. |
| — | No `CHANGELOG.md` task | `CHANGELOG.md` was added. Task 8's consumer doc tells readers to "read the release notes before moving a pin" while no such artifact existed; it is now the canonical record, linked from both referencing sites, and the release procedure requires moving its entry when a version is cut. |

The design spec has been amended for the Task 2 and Task 3 divergences, so §3.3 there is current.

## Global Constraints

Every task inherits these. Values are copied verbatim from the design and the repo's existing config.

- **Public surface is exactly five names** (§3.2): `load_runtime`, `ContractRuntime`,
  `ContractViolation`, `FieldDiff`, `__version__`. Nothing else. `Contract`, `Schema`, `EventLog`,
  `Resolver`, `Field`, `to_pandera`, `to_json_schema`, `to_odcs`, `cli` stay **private** — tests for
  internals import the deep path on purpose.
- **No `contract_core.api` import path.** Where `load_runtime` is *defined* is an implementation
  detail; this plan defines it in `runtime.py` and exposes it **only** as `contract_core.load_runtime`.
- **"Off always wins" (§3.3).** Disabled iff `CONTRACT_DISABLED` is on **OR** `enabled=False`. There
  is deliberately **no** way for application code to force validation on over the env var.
- **`CONTRACT_DISABLED` is on iff present and its value, stripped and lowercased, is not in
  `{"", "0", "false", "no", "off"}`.** So `=1`, `=true`, `=yes`, `=on` disable; `=0`, `=false`,
  `=no`, `=off`, `=` (empty), and *unset* leave validation **enabled**. This rule lives in exactly
  one helper, `_env_disabled()`. *(Corrected in place: the set originally omitted `"off"` — see the
  superseded table. These constraints are stated as inherited by every task, so leaving the wrong
  set here and flagging it only at the snippet would be the same defect one level up.)*
- **A disabled runtime does no file I/O** — no contract read, no schema resolution, no event write.
- **Disabling is loud**: exactly one line written to `sys.stderr` at construction, emitted from
  `ContractRuntime.disabled()` itself (not from `load_runtime`), naming the trigger and a best-available
  label. Never an event-log write (an event write is file I/O that can itself fail — the exact
  import-time crash §15 item 7 exists to prevent), and never a `logging` record (a consumer's logging
  config can delete one). *(Corrected in place; originally a `logging.warning`.)*
- **No auto-degrade.** A missing or malformed contract file **raises**; it never silently disables.
- **Version 0.1.0**, pre-1.0. Under 0.x a **minor** bump may carry breaking changes.
- **Pandera import is namespaced:** `import pandera.pandas as pa` — never `import pandera as pa`.
- **Tooling gates that must stay green:** `ruff check .`, `mypy` (strict, `files = ["src"]`),
  `pytest -q` (with `--strict-config --strict-markers`).
- **TDD, DRY, YAGNI, frequent commits.** Each task ends green on all three gates.

## File Structure

| File | Status | Responsibility |
| --- | --- | --- |
| `pyproject.toml` | modify | version `0.0.1` → `0.1.0` |
| `src/contract_core/__init__.py` | modify | the curated public surface + `__all__` + `__version__` |
| `src/contract_core/runtime.py` | modify | `_env_disabled()`, `ContractRuntime.disabled()`, `_DisabledRuntime`, `load_runtime()` |
| `tests/conftest.py` | modify | one shared `event_log_path` fixture (keeps the default `EventLog` out of the repo root) |
| `tests/test_smoke.py` | modify | version value + metadata/`__version__` skew guard |
| `tests/test_degradation.py` | create | T4 — env truth table, all three disable paths, true-negatives |
| `tests/test_public_api.py` | create | T2 (frozen surface), T3 (sufficiency), T5 (`FieldDiff` reachable) |
| `tests/test_distribution.py` | create | T1 — git-ref install into a clean venv |
| `tests/fixtures/consumer/contract.yaml` | create | a raw+input+output contract for T3/T4/T5 |
| `docs/consuming-repo-setup.md` | create | pin syntax, deploy token, absent-library pattern, kill switch |
| `CONTRIBUTING.md` | modify | the release (tag-cutting) procedure |
| `README.md` | modify | one link to the new consumer doc |

Existing fixture schemas are reused as-is — **no new schema files.** `tests/fixtures/schemas/` already
contains `peec/prompts_export/1.0.0.yaml` (tabular: `prompt` str, `sentiment` float, `position` int,
`share_of_voice` float) and `aivx/report/1.0.0.yaml` (payload: `slug` str, `score` float).

---

### Task 1: Bump to 0.1.0 and guard the two version strings against skew

> **Superseded — see the table at the top.** Applies to every step below. What shipped is one test,
> `test_version_matches_pyproject`, reading `pyproject.toml` with `tomllib`. Both tests written
> below are gone: the literal put the version in a third place the release procedure does not name,
> and `importlib.metadata` only agrees while the editable install is current.

The version string lives in **two** places — `pyproject.toml` and `__init__.py:__version__` — and
nothing keeps them in step. `__version__` is on the frozen public surface (§3.2), so a skew ships a
lie to consumers. Bump both and add the guard that makes a future skew fail CI.

**Files:**
- Modify: `pyproject.toml:6`
- Modify: `src/contract_core/__init__.py:2`
- Modify: `tests/test_smoke.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `contract_core.__version__ == "0.1.0"`, equal to the installed distribution metadata.

- [ ] **Step 1: Write the failing tests**

Replace the whole of `tests/test_smoke.py` with:

```python
# tests/test_smoke.py
from importlib.metadata import version

import contract_core


def test_package_imports_and_has_version():
    assert isinstance(contract_core.__version__, str)
    assert contract_core.__version__ != ""


def test_version_is_0_1_0():
    assert contract_core.__version__ == "0.1.0"


def test_version_matches_distribution_metadata():
    # `__version__` is on the frozen public surface (R9 design §3.2) but is hand-written in
    # __init__.py, while pip/consumers see pyproject's. A skew publishes a lie; fail here instead.
    assert contract_core.__version__ == version("contract-core")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_smoke.py -q`
Expected: FAIL — `assert '0.0.1' == '0.1.0'` in `test_version_is_0_1_0`.
(`test_version_matches_distribution_metadata` passes today — both sides are `0.0.1`. That is fine;
it is the *regression* guard, and Step 4 proves it still holds after the bump.)

> **Superseded — see the table at the top.** That parenthetical only holds while the editable install
> is current: `importlib.metadata` reports what was recorded at install time, which is why Step 4
> below has to exist at all. What shipped drops both of these tests for one that reads
> `pyproject.toml` directly, so it is a real guard on a dev machine and not only in CI, and the
> version stays in the two files the release procedure names.

- [ ] **Step 3: Bump both version strings**

In `pyproject.toml`, line 6:

```toml
version = "0.1.0"
```

In `src/contract_core/__init__.py`:

```python
# src/contract_core/__init__.py
__version__ = "0.1.0"
```

- [ ] **Step 4: Reinstall so distribution metadata is refreshed, then run the tests**

The editable install caches the old version in its `.dist-info`, so `importlib.metadata` keeps
reporting `0.0.1` until you reinstall.

Run: `pip install -e ".[dev]" --quiet && pytest tests/test_smoke.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the full gate**

Run: `ruff check . && mypy && pytest -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/contract_core/__init__.py tests/test_smoke.py
git commit -m "chore(R9): bump to 0.1.0 and guard __version__ against metadata skew"
```

---

### Task 2: `_env_disabled()` — pin the kill-switch activation semantics

> **Superseded — see the table at the top.** Applies to every step below, tests included. `"off"` is
> missing from both `_ENV_OFF_VALUES` and the `OFF_VALUES` fixture, so as written this task *and its
> test* agree that `CONTRACT_DISABLED=off` disables validation. A test that shares the omission
> cannot catch it — which is how this reached review. What shipped adds `"off"`, `"OFF"` and
> `"  off  "` to `OFF_VALUES`.

An ambiguous kill switch is an incident risk (§3.3). One private helper owns the rule so the factory
and any other caller cannot drift apart.

**Files:**
- Modify: `src/contract_core/runtime.py`
- Create: `tests/test_degradation.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `contract_core.runtime._env_disabled() -> bool` — reads `os.environ["CONTRACT_DISABLED"]`,
  returns `True` iff present and `value.strip().lower() not in {"", "0", "false", "no", "off"}`.
  *(Corrected in place; `"off"` was missing — see the superseded table.)*

- [ ] **Step 1: Write the failing test**

Create `tests/test_degradation.py`:

```python
# tests/test_degradation.py
import pytest

from contract_core.runtime import _env_disabled

# The pinned truth table (R9 design §3.3). An operator typing `0` or `false` must NOT
# accidentally disable every contract in the fleet, so those are OFF values, not "truthy".
ON_VALUES = ["1", "true", "TRUE", "yes", "on", "  1  ", "disabled", "please"]
OFF_VALUES = ["", "0", "false", "FALSE", "no", "No", "  0  "]


@pytest.mark.parametrize("value", ON_VALUES)
def test_env_disabled_is_on_for(value, monkeypatch):
    monkeypatch.setenv("CONTRACT_DISABLED", value)
    assert _env_disabled() is True


@pytest.mark.parametrize("value", OFF_VALUES)
def test_env_disabled_is_off_for(value, monkeypatch):
    monkeypatch.setenv("CONTRACT_DISABLED", value)
    assert _env_disabled() is False


def test_env_disabled_is_off_when_unset(monkeypatch):
    monkeypatch.delenv("CONTRACT_DISABLED", raising=False)
    assert _env_disabled() is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_degradation.py -q`
Expected: collection error — `ImportError: cannot import name '_env_disabled' from 'contract_core.runtime'`.

- [ ] **Step 3: Write the implementation**

In `src/contract_core/runtime.py`, extend the stdlib imports at the top of the file (currently
`import functools` on line 2) to:

```python
import functools
import logging
import os
```

Then, immediately after the `Problem = Literal[...]` line (currently line 19), insert:

> **Superseded — see the table at the top.** The off-set below is missing `"off"`, so
> `CONTRACT_DISABLED=off` disables validation. Use `{"", "0", "false", "no", "off"}`. The `_LOG`
> logger is gone too — see the Task 3 note.

```python
_LOG = logging.getLogger("contract_core")

# `CONTRACT_DISABLED` is an ops kill switch, so its activation rule is pinned, not "truthy"
# (R9 design §3.3): typing `0`/`false` must turn the switch OFF, not disable every contract.
_ENV_OFF_VALUES = frozenset({"", "0", "false", "no"})


def _env_disabled() -> bool:
    """Is the `CONTRACT_DISABLED` kill switch on? Present and not an off-value."""
    raw = os.environ.get("CONTRACT_DISABLED")
    if raw is None:
        return False
    return raw.strip().lower() not in _ENV_OFF_VALUES
```

(`_LOG` is unused until Task 3; it is placed here because it belongs with the other module-level
constants and ruff's `F401`/`F841` do not flag an assigned module global.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_degradation.py -q`
Expected: PASS (16 passed).

- [ ] **Step 5: Run the full gate**

Run: `ruff check . && mypy && pytest -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/contract_core/runtime.py tests/test_degradation.py
git commit -m "feat(R9): pin CONTRACT_DISABLED activation semantics in _env_disabled()"
```

---

### Task 3: `ContractRuntime.disabled()` — no-op boundaries plus one loud warning

> **Superseded — see the table at the top.** Applies to every step below, tests included. The
> announcement that shipped is `print(..., file=sys.stderr)`, not `_LOG.warning`, so every `caplog`
> assertion written below is a `capsys` assertion in `tests/test_degradation.py`, and `disabled()`
> is a `@staticmethod`. Step 5 below — the manual stderr check — became a real test
> (`test_disabled_announces_even_when_logging_is_configured_away`) rather than a one-off command.

The warning lives **here**, not in `load_runtime`, so a consumer calling `disabled()` directly gets
the same signal as one going through the factory (§3.3).

**Files:**
- Modify: `src/contract_core/runtime.py`
- Modify: `tests/test_degradation.py`

**Interfaces:**
- Consumes: `_env_disabled()` from Task 2.
- Produces:
  - `ContractRuntime.disabled(label: str | None = None) -> ContractRuntime` (classmethod).
  - The warning text: `contract validation DISABLED (<trigger>) [<label>]`, where `<trigger>` is
    `CONTRACT_DISABLED set` when `_env_disabled()` is true and `explicitly disabled` otherwise, and
    `<label>` is the argument or the literal `unspecified`.

- [ ] **Step 1: Write the failing tests**

First widen the import block at the **top** of `tests/test_degradation.py` — ruff enforces `E402`
(no module-level import below code) and `I001` (sorted import block), so imports never get appended
at the bottom:

```python
# tests/test_degradation.py
import pandas as pd
import pytest

from contract_core.runtime import ContractRuntime, _env_disabled
```

Then append the tests to the end of the file:

```python
def _bad_df():
    """Data that WOULD hard-fail `peec.prompts_export@1.0.0` — `position` is missing."""
    return pd.DataFrame({"prompt": ["a"], "sentiment": [0.5], "share_of_voice": [0.3]})


def test_disabled_runtime_passes_data_through_untouched(monkeypatch):
    monkeypatch.delenv("CONTRACT_DISABLED", raising=False)
    rt = ContractRuntime.disabled()

    @rt.input("a-boundary-that-is-not-in-any-contract")
    def load():
        return _bad_df()

    out = load()
    assert list(out.columns) == ["prompt", "sentiment", "share_of_voice"]


def test_disabled_runtime_decorates_all_three_directions(monkeypatch):
    monkeypatch.delenv("CONTRACT_DISABLED", raising=False)
    rt = ContractRuntime.disabled()
    for deco in (rt.raw("x"), rt.input("x"), rt.output("x")):

        @deco
        def fn():
            return {"anything": 1}

        assert fn() == {"anything": 1}


def test_disabled_runtime_does_no_file_io(monkeypatch, tmp_path):
    # No contract read, no schema resolution, no event write (R9 design §3.3).
    events = tmp_path / "events.jsonl"
    monkeypatch.setenv("CONTRACT_EVENT_LOG", str(events))
    monkeypatch.delenv("CONTRACT_DISABLED", raising=False)
    rt = ContractRuntime.disabled()

    @rt.output("report")
    def emit():
        return {"nope": True}

    emit()
    assert not events.exists()


def test_disabled_warns_once_naming_trigger_and_label(monkeypatch, caplog):
    monkeypatch.delenv("CONTRACT_DISABLED", raising=False)
    with caplog.at_level("WARNING", logger="contract_core"):
        ContractRuntime.disabled("contract.yaml")
    warnings = [r for r in caplog.records if "DISABLED" in r.getMessage()]
    assert len(warnings) == 1
    assert warnings[0].getMessage() == "contract validation DISABLED (explicitly disabled) [contract.yaml]"


def test_disabled_names_the_env_var_when_it_is_the_trigger(monkeypatch, caplog):
    monkeypatch.setenv("CONTRACT_DISABLED", "1")
    with caplog.at_level("WARNING", logger="contract_core"):
        ContractRuntime.disabled("contract.yaml")
    msg = caplog.records[-1].getMessage()
    assert msg == "contract validation DISABLED (CONTRACT_DISABLED set) [contract.yaml]"


def test_disabled_with_no_label_reads_unspecified(monkeypatch, caplog):
    # A disabled runtime does no file I/O, so it cannot read the contract to learn the
    # system name. It names what it actually has.
    monkeypatch.delenv("CONTRACT_DISABLED", raising=False)
    with caplog.at_level("WARNING", logger="contract_core"):
        ContractRuntime.disabled()
    assert "[unspecified]" in caplog.records[-1].getMessage()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_degradation.py -q`
Expected: FAIL — `AttributeError: type object 'ContractRuntime' has no attribute 'disabled'`.

- [ ] **Step 3: Write the implementation**

In `src/contract_core/runtime.py`, add the `disabled` classmethod to `ContractRuntime`, immediately
after `__init__` and before `_spec`:

> **Superseded — see the table at the top.** Two changes to what shipped: the announcement is a
> bare `print(..., file=sys.stderr)`, not `_LOG.warning` (a consumer's logging config can delete a
> record, which would falsify "its absence means validation is on"), and it is a `@staticmethod` —
> it never uses `cls`, so as written a subclass calling `.disabled()` silently gets a base-class
> no-op. The tests that follow assert on `capsys`, not `caplog`.

```python
    @classmethod
    def disabled(cls, label: str | None = None) -> "ContractRuntime":
        """Return a no-op runtime and announce it once, loudly, on stderr.

        Turning validation off is itself a loud act (R9 design §3.3): "why is nothing
        validating?" must be diagnosable from a positive signal, not inferred from the
        absence of failures. Deliberately a log warning and NOT an event-log write — an
        event write is file I/O that can itself fail, reintroducing exactly the import-time
        crash graceful degradation exists to prevent.

        `label` is a best-available identifier (the factory passes the contract path). A
        disabled runtime reads no files, so it can never learn the contract's `system` name.
        """
        trigger = "CONTRACT_DISABLED set" if _env_disabled() else "explicitly disabled"
        _LOG.warning("contract validation DISABLED (%s) [%s]", trigger, label or "unspecified")
        return _DisabledRuntime()
```

Then append to the **end** of the module:

```python
def _passthrough(fn: Callable[..., Any]) -> Callable[..., Any]:
    """The identity decorator: no wrapper, no validation, no events, no overhead."""
    return fn


class _DisabledRuntime(ContractRuntime):
    """Every boundary is a pass-through. Reachable only via `ContractRuntime.disabled()`.

    It deliberately does not call `ContractRuntime.__init__`: a disabled runtime has no
    contract and no resolver, and *acquiring* them is the file I/O this class exists to
    avoid. Touching `.contract` or `.resolver` on one is an error, by construction.
    """

    def __init__(self) -> None:
        pass

    def raw(self, name: str) -> Decorator:
        return _passthrough

    def input(self, name: str) -> Decorator:
        return _passthrough

    def output(self, name: str) -> Decorator:
        return _passthrough
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_degradation.py -q`
Expected: PASS (22 passed).

- [ ] **Step 5: Confirm the warning really reaches stderr, not just caplog**

`caplog` proves a record was emitted; this proves the default (no handler configured) routing
sends it to stderr via `logging.lastResort`.

> **Superseded.** This step had the right instinct and the wrong conclusion. `logging.lastResort`
> *is* why the record reaches stderr with no handler configured — which means this check passes
> while a consumer who calls `basicConfig` gets nothing, and the consumer doc guarantees that the
> line's absence means validation is on. What shipped writes to `sys.stderr` directly and asserts it
> under `logging.disable(logging.CRITICAL)`, so the check is a test rather than a manual command.

Run:
```bash
python -c "from contract_core.runtime import ContractRuntime; ContractRuntime.disabled('x')" 2>/dev/null
python -c "from contract_core.runtime import ContractRuntime; ContractRuntime.disabled('x')" 2>&1 >/dev/null
```
Expected: the first prints nothing; the second prints
`contract validation DISABLED (explicitly disabled) [x]`.

- [ ] **Step 6: Run the full gate**

Run: `ruff check . && mypy && pytest -q`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/contract_core/runtime.py tests/test_degradation.py
git commit -m "feat(R9): add ContractRuntime.disabled() with a loud one-shot warning"
```

---

### Task 4: `load_runtime()` — the factory, with "off always wins" precedence

> **Superseded — see the table at the top.** Applies to every step below. The `caplog` assertions
> are `capsys` assertions in what shipped (Task 3's note says why),
> `test_env_var_set_to_zero_does_not_disable` is parametrized over `["0", "off"]`, and the
> `event_log_path` fixture is `autouse`.

**Files:**
- Modify: `src/contract_core/runtime.py`
- Modify: `tests/conftest.py`
- Create: `tests/fixtures/consumer/contract.yaml`
- Modify: `tests/test_degradation.py`

**Interfaces:**
- Consumes: `_env_disabled()` (Task 2), `ContractRuntime.disabled()` (Task 3),
  `Contract.from_yaml`, `Resolver` (existing).
- Produces:
  `load_runtime(contract_path: str | Path = "contract.yaml", *, schema_paths: Sequence[str | Path] = ("schemas",), enabled: bool = True) -> ContractRuntime`

- [ ] **Step 1: Add the shared event-log fixture**

The default `EventLog` writes `./contract-events.jsonl` in the process CWD — the repo root when
pytest runs. `load_runtime` takes no `event_log` parameter by design (§3.2), so tests steer it with
the env var instead. Replace `tests/conftest.py` with:

```python
"""Shared fixtures. Prefer hand-rolled fakes over mock — the org's convention."""
import pytest


@pytest.fixture
def event_log_path(tmp_path, monkeypatch):
    """Point the default EventLog at tmp_path.

    `load_runtime` has no `event_log` parameter (a custom sink is not a supported capability
    yet — R9 design §3.2), so an enabled runtime built by the factory writes wherever
    CONTRACT_EVENT_LOG says, defaulting to ./contract-events.jsonl in the repo root.
    """
    path = tmp_path / "events.jsonl"
    monkeypatch.setenv("CONTRACT_EVENT_LOG", str(path))
    return path
```

(Deliberately **not** autouse — the existing tests construct their own `EventLog` and must stay
unaffected.)

- [ ] **Step 2: Add the consumer contract fixture**

Create `tests/fixtures/consumer/contract.yaml`. It exercises all three directions against schemas
that already exist in `tests/fixtures/schemas/`:

```yaml
# tests/fixtures/consumer/contract.yaml
# A raw -> input -> output contract used by the R9 public-API and degradation tests.
system: demo-consumer
version: 1.0.0
raw:
  - name: prompts_raw
    schema: peec.prompts_export@1.0.0
    source: {kind: file, format: csv}
    mode: enforce
inputs:
  - name: prompts
    schema: peec.prompts_export@1.0.0
    source: {kind: file, format: csv}
    mode: enforce
outputs:
  - name: report
    schema: aivx.report@1.0.0
    sink: {kind: file, format: json}
    mode: enforce
```

- [ ] **Step 3: Write the failing tests**

Again, imports go in the block at the **top** of `tests/test_degradation.py`, which now reads in
full:

```python
# tests/test_degradation.py
from pathlib import Path

import pandas as pd
import pytest

from contract_core.errors import ContractViolation
from contract_core.runtime import ContractRuntime, _env_disabled, load_runtime
```

Then append to the end of the file:

```python
FIX = Path(__file__).parent / "fixtures"
CONSUMER_CONTRACT = FIX / "consumer" / "contract.yaml"
SCHEMAS = FIX / "schemas"


def _enforcing_loader(rt):
    """A boundary whose data would hard-fail an enforcing runtime."""

    @rt.input("prompts")
    def load():
        return _bad_df()

    return load


def test_enabled_by_default_still_hard_fails_and_stays_quiet(
    monkeypatch, caplog, event_log_path
):
    # True negative: the toggle must not disable anything when nobody asked.
    monkeypatch.delenv("CONTRACT_DISABLED", raising=False)
    with caplog.at_level("WARNING", logger="contract_core"):
        rt = load_runtime(CONSUMER_CONTRACT, schema_paths=[SCHEMAS])
    with pytest.raises(ContractViolation):
        _enforcing_loader(rt)()
    assert not [r for r in caplog.records if "DISABLED" in r.getMessage()]


def test_env_var_set_to_zero_does_not_disable(monkeypatch, caplog, event_log_path):
    # The foot-gun case: an operator typing `0` must NOT disable the fleet.
    monkeypatch.setenv("CONTRACT_DISABLED", "0")
    with caplog.at_level("WARNING", logger="contract_core"):
        rt = load_runtime(CONSUMER_CONTRACT, schema_paths=[SCHEMAS])
    with pytest.raises(ContractViolation):
        _enforcing_loader(rt)()
    assert not [r for r in caplog.records if "DISABLED" in r.getMessage()]


def test_env_var_disables_and_warns(monkeypatch, caplog, event_log_path):
    monkeypatch.setenv("CONTRACT_DISABLED", "1")
    with caplog.at_level("WARNING", logger="contract_core"):
        rt = load_runtime(CONSUMER_CONTRACT, schema_paths=[SCHEMAS])
    assert _enforcing_loader(rt)() is not None  # returns its data, unchanged
    assert not event_log_path.exists()
    msg = caplog.records[-1].getMessage()
    assert msg == f"contract validation DISABLED (CONTRACT_DISABLED set) [{CONSUMER_CONTRACT}]"


def test_enabled_false_disables_and_warns(monkeypatch, caplog, event_log_path):
    monkeypatch.delenv("CONTRACT_DISABLED", raising=False)
    with caplog.at_level("WARNING", logger="contract_core"):
        rt = load_runtime(CONSUMER_CONTRACT, schema_paths=[SCHEMAS], enabled=False)
    assert _enforcing_loader(rt)() is not None
    assert not event_log_path.exists()
    assert "explicitly disabled" in caplog.records[-1].getMessage()


def test_off_always_wins_over_application_code(monkeypatch, caplog, event_log_path):
    # A module hardcoding enabled=True cannot defeat the ops kill switch (R9 design §3.3).
    monkeypatch.setenv("CONTRACT_DISABLED", "1")
    with caplog.at_level("WARNING", logger="contract_core"):
        rt = load_runtime(CONSUMER_CONTRACT, schema_paths=[SCHEMAS], enabled=True)
    assert _enforcing_loader(rt)() is not None
    assert "CONTRACT_DISABLED set" in caplog.records[-1].getMessage()


def test_disabled_factory_reads_no_contract_file(monkeypatch, tmp_path):
    # Proves "no file I/O": the path does not exist and construction still succeeds.
    monkeypatch.setenv("CONTRACT_DISABLED", "1")
    rt = load_runtime(tmp_path / "does-not-exist.yaml")
    assert rt.input("whatever")(lambda: 42)() == 42


def test_missing_contract_raises_when_enabled_no_auto_degrade(monkeypatch, tmp_path):
    # Fail-loud (design decision #3): a missing contract raises; it never silently disables.
    monkeypatch.delenv("CONTRACT_DISABLED", raising=False)
    with pytest.raises(FileNotFoundError):
        load_runtime(tmp_path / "does-not-exist.yaml")
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `pytest tests/test_degradation.py -q`
Expected: collection error — `ImportError: cannot import name 'load_runtime' from 'contract_core.runtime'`.

- [ ] **Step 5: Write the implementation**

In `src/contract_core/runtime.py`, widen the `collections.abc` import (currently line 3) to:

```python
from collections.abc import Callable, Sequence
```

and add `Path` to the stdlib imports:

```python
from pathlib import Path
```

Then append the factory to the end of the module, after `_DisabledRuntime`:

```python
def load_runtime(
    contract_path: str | Path = "contract.yaml",
    *,
    schema_paths: Sequence[str | Path] = ("schemas",),
    enabled: bool = True,
) -> ContractRuntime:
    """Build a runtime from a contract file, or a disabled no-op runtime.

    Returns a disabled runtime — no validation, no file I/O, one loud warning at
    construction — when CONTRACT_DISABLED is *on* in the environment OR when
    enabled=False. CONTRACT_DISABLED is on iff present and not in
    {"", "0", "false", "no", "off"} (case-insensitive); so =0 / =false / =off leave
    validation ON.
    "Off wins": there is no way to force validation on over the env kill switch.
    Otherwise loads the contract and resolver and returns an enforcing runtime.
    """
    if _env_disabled() or not enabled:
        # Pass the path as the label: the factory knows it without parsing the file.
        return ContractRuntime.disabled(str(contract_path))
    contract = Contract.from_yaml(contract_path)
    resolver = Resolver(list(schema_paths))
    return ContractRuntime(contract, resolver)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/test_degradation.py -q`
Expected: PASS (29 passed).

- [ ] **Step 7: Confirm no event log leaked into the repo root**

Run: `git status --porcelain && ls contract-events.jsonl 2>&1`
Expected: clean-but-for-your-edits, and `ls: contract-events.jsonl: No such file or directory`.
(If the file appeared, a test is missing the `event_log_path` fixture — fix that, do not gitignore it.)

- [ ] **Step 8: Run the full gate**

Run: `ruff check . && mypy && pytest -q`
Expected: all green.

- [ ] **Step 9: Commit**

```bash
git add src/contract_core/runtime.py tests/conftest.py tests/test_degradation.py tests/fixtures/consumer/contract.yaml
git commit -m "feat(R9): add load_runtime() factory with off-always-wins precedence"
```

---

### Task 5: The curated public surface and its frozen-surface tripwire (T2)

Note precisely what T2 promises: under the 0.x policy a breaking surface change **is permitted** on a
minor bump, so this test enforces *"you must notice and do it deliberately"* — not *"you must never
break."* It turns a silent break into a reviewed one.

**Files:**
- Modify: `src/contract_core/__init__.py`
- Create: `tests/test_public_api.py`

**Interfaces:**
- Consumes: `load_runtime`, `ContractRuntime` (Tasks 3–4), `ContractViolation`, `FieldDiff` (existing).
- Produces: `from contract_core import load_runtime, ContractRuntime, ContractViolation, FieldDiff`
  and `contract_core.__all__`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_public_api.py`:

```python
# tests/test_public_api.py
# Every import in this file is a TOP-LEVEL import on purpose. A deep-module import here
# (contract_core.runtime, .contract, .resolver, ...) defeats T3: the point is to prove the
# curated surface is sufficient for a real consumer. Do not add one.
import contract_core

# The frozen public surface (R9 design §3.2). Changing this set is a deliberate act:
# under 0.x a breaking change is allowed, but it must be conscious, reviewed, and carry a
# minor bump — this test is what makes "silent" impossible.
FROZEN_SURFACE = {
    "ContractRuntime",
    "ContractViolation",
    "FieldDiff",
    "__version__",
    "load_runtime",
}


def test_public_surface_is_frozen():
    assert set(contract_core.__all__) == FROZEN_SURFACE


def test_all_has_no_duplicates():
    assert len(contract_core.__all__) == len(set(contract_core.__all__))


def test_every_promised_name_is_actually_importable():
    # __all__ is a promise, not proof: a name can be listed and not exported.
    for name in FROZEN_SURFACE:
        assert hasattr(contract_core, name), f"{name} is in __all__ but not on the package"


def test_no_module_alias_leaks_onto_the_public_surface():
    # "The import path is the contract": where load_runtime is DEFINED is an implementation
    # detail, and no `contract_core.api`-style import path is offered or supported.
    assert not hasattr(contract_core, "api")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_public_api.py -q`
Expected: FAIL — `AttributeError: module 'contract_core' has no attribute '__all__'`.

- [ ] **Step 3: Write the public surface**

Replace `src/contract_core/__init__.py` entirely:

```python
# src/contract_core/__init__.py
"""contract-core — the public API.

Everything exported here is a semver obligation (R9 design §3.2). Everything else —
`contract`, `schema`, `events`, `resolver`, `types`, `families`, `compile.*`, `cli` — is
**private**: import paths into those modules are not supported and may change without a
major bump. The CLI is invoked through the `contract` console script, not by importing
`contract_core.cli`.
"""
from contract_core.errors import ContractViolation, FieldDiff
from contract_core.runtime import ContractRuntime, load_runtime

__version__ = "0.1.0"

__all__ = [
    "ContractRuntime",
    "ContractViolation",
    "FieldDiff",
    "__version__",
    "load_runtime",
]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_public_api.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Verify the promised import line works from a cold interpreter**

Run: `python -c "from contract_core import load_runtime, ContractRuntime, ContractViolation, FieldDiff; print('ok')"`
Expected: `ok` (no circular-import error — no module under `src/contract_core/` imports the
top-level package, which is what keeps this chain safe).

- [ ] **Step 6: Run the full gate**

Run: `ruff check . && mypy && pytest -q`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/contract_core/__init__.py tests/test_public_api.py
git commit -m "feat(R9): curate the public API surface and freeze it with a tripwire test"
```

---

### Task 6: Prove the surface is sufficient (T3) and `FieldDiff` is usable (T5)

A public name with no consumer-facing test is a name we will break blind. These two tests are what
justify `FieldDiff` and `load_runtime` on the frozen surface.

**Files:**
- Modify: `tests/test_public_api.py`

**Interfaces:**
- Consumes: the entire public surface from Task 5. Nothing new is produced.

- [ ] **Step 1: Write the failing tests**

Imports go in the block at the **top** of `tests/test_public_api.py` (ruff `E402`/`I001`), which now
reads in full — note every `contract_core` name comes from the top level, which is the whole point
of T3:

```python
# tests/test_public_api.py
# Every import in this file is a TOP-LEVEL import on purpose. A deep-module import here
# (contract_core.runtime, .contract, .resolver, ...) defeats T3: the point is to prove the
# curated surface is sufficient for a real consumer. Do not add one.
from pathlib import Path

import pandas as pd
import pytest

import contract_core
from contract_core import ContractViolation, FieldDiff, load_runtime
```

Then append to the end of the file:

```python
FIX = Path(__file__).parent / "fixtures"
CONSUMER_CONTRACT = FIX / "consumer" / "contract.yaml"
SCHEMAS = FIX / "schemas"


def _good_df():
    return pd.DataFrame({
        "prompt": ["a"], "sentiment": [0.5],
        "position": pd.array([1], dtype="Int64"),
        "share_of_voice": [0.3],
    })


def test_public_api_is_sufficient_for_a_full_raw_input_output_flow(monkeypatch, event_log_path):
    """T3: a real consumer module, importing ONLY the top-level names."""
    monkeypatch.delenv("CONTRACT_DISABLED", raising=False)
    runtime = load_runtime(CONSUMER_CONTRACT, schema_paths=[SCHEMAS])

    @runtime.raw("prompts_raw")
    def fetch_raw():
        return _good_df()

    @runtime.input("prompts")
    def normalize():
        return fetch_raw()

    @runtime.output("report")
    def build_report():
        df = normalize()
        return {"slug": "acme", "score": float(df["sentiment"].iloc[0])}

    assert build_report() == {"slug": "acme", "score": 0.5}
    results = [line for line in event_log_path.read_text().splitlines() if line.strip()]
    assert len(results) == 3  # one event per crossing: raw, input, output


def test_field_diff_is_reachable_and_usable_off_a_caught_violation(
    monkeypatch, event_log_path
):
    """T5: catching a violation yields a usable list[FieldDiff], top-level imports only."""
    monkeypatch.delenv("CONTRACT_DISABLED", raising=False)
    runtime = load_runtime(CONSUMER_CONTRACT, schema_paths=[SCHEMAS])

    @runtime.input("prompts")
    def load():
        return _good_df().drop(columns=["position"])

    with pytest.raises(ContractViolation) as ei:
        load()

    diffs = ei.value.diffs
    assert diffs and all(isinstance(d, FieldDiff) for d in diffs)
    # These four attribute names are themselves part of the frozen surface: a consumer
    # reads them to build custom handling, so renaming one is a breaking change.
    diff = next(d for d in diffs if d.field == "position")
    assert diff.expected == "int"
    assert diff.observed == "absent"
    assert diff.problem == "missing"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_public_api.py -q`
Expected: PASS if Tasks 4–5 are complete. **This is the one task whose tests are green on first
run** — they assert an integration that the prior tasks built. To prove they are not vacuous, do
Step 3 before accepting them.

- [ ] **Step 3: Prove the new tests can fail (anti-vacuity check)**

Temporarily change `assert len(results) == 3` to `== 99` and `diff.problem == "missing"` to
`== "retyped"`, then run:

Run: `pytest tests/test_public_api.py -q`
Expected: 2 failed — with real values in the diff output (`assert 3 == 99`,
`assert 'missing' == 'retyped'`). Revert both edits and re-run: PASS (6 passed).

- [ ] **Step 4: Prove the surface claim is real — no deep imports in this file**

Run: `grep -nE "^(from|import) contract_core\." tests/test_public_api.py`
Expected: **no output** (grep exits 1). Any hit is a deep-module import, and T3 stops proving what
it claims.

- [ ] **Step 5: Run the full gate**

Run: `ruff check . && mypy && pytest -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add tests/test_public_api.py
git commit -m "test(R9): prove the public surface is sufficient and FieldDiff is usable (T3, T5)"
```

---

### Task 7: T1 — install over the real git-ref path into a clean venv

> **Superseded — the venv recipe below is known not to work. Read `tests/test_distribution.py`
> instead; it is canonical.**
>
> `venv --system-site-packages` exposes the **base interpreter's** site-packages, not the outer
> venv's. When the suite itself runs inside a venv — the normal case, and always true in CI — the
> deps are invisible and the probe dies on `ModuleNotFoundError: No module named 'pandera'` before
> it can check anything.
>
> What shipped names the running interpreter's `purelib` through a `.pth`, and that difference is
> load-bearing beyond merely working: a `.pth` **appends** where `PYTHONPATH` **prepends**, and the
> outer env holds an editable-install `contract_core` shim that a prepend would have silently
> shadowed the package under test with. Two later changes from review: the URL is built with
> `REPO.as_uri()` (an f-string breaks on a checkout path containing a space or `#`), and the install
> passes `--no-build-isolation` against hatchling from the `dev` extra, so a cold pip cache no
> longer fetches the build backend from PyPI and a PyPI blip cannot redden CI. Verified passing with
> `PIP_NO_INDEX=1`.

The distribution model ships **no wheel**, so T1 must not test one. It installs the way a consumer
does — a PEP 508 git ref that pip resolves and **builds from source** — using a local `file://`
remote at a committed ref, so it needs no GitHub deploy token and runs on every push.

**Read before writing:** this test installs **`HEAD`, the committed tree** — not your working
directory. Tasks 1–6 must be committed before it can pass. That is the point: it verifies the
artifact a consumer would actually get.

**Files:**
- Create: `tests/test_distribution.py`

**Interfaces:**
- Consumes: the committed public surface from Task 5. Nothing new is produced.

- [ ] **Step 1: Write the test**

Create `tests/test_distribution.py`:

```python
# tests/test_distribution.py
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# Kept in step with tests/test_public_api.py::FROZEN_SURFACE by hand: this list is what a
# consumer's `from contract_core import ...` line looks like, and duplicating it here is
# deliberate — the whole point of the test is to prove that line works against a real install,
# so importing the expected names from the source tree would defeat it.
PUBLIC_NAMES = ["ContractRuntime", "ContractViolation", "FieldDiff", "load_runtime"]


def _run(*cmd: str, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([*cmd], capture_output=True, text=True, **kw)


def test_git_ref_install_exposes_the_public_api(tmp_path):
    """T1: `pip install "contract-core @ git+file://<repo>@<sha>"` then import the surface.

    A local file:// remote at a committed ref exercises the exact resolve-and-build-from-source
    path a consumer's `git+https://.../data-contract@vX.Y.Z` pin takes, with no deploy token.
    The *authenticated remote* half is verified once per release by the smoke test in
    docs/consuming-repo-setup.md — a tag cannot be installed before it is cut.
    """
    if shutil.which("git") is None:
        pytest.skip("git is not on PATH")

    head = _run("git", "-C", str(REPO), "rev-parse", "HEAD")
    assert head.returncode == 0, head.stderr
    sha = head.stdout.strip()

    # --system-site-packages + --no-deps: this test is about the git-ref resolve and the
    # source build, NOT about re-resolving pydantic/pandera/pandas from PyPI. The runtime
    # deps come from the outer (already installed) environment; the assertion below proves
    # contract_core itself came from the fresh install, not from that outer environment.
    venv = tmp_path / "venv"
    created = _run(sys.executable, "-m", "venv", "--system-site-packages", str(venv))
    assert created.returncode == 0, created.stderr
    py = venv / "bin" / "python"

    spec = f"contract-core @ git+file://{REPO}@{sha}"
    installed = _run(str(py), "-m", "pip", "install", "--quiet", "--no-deps",
                     "--ignore-installed", spec)
    assert installed.returncode == 0, installed.stderr

    probe = (
        f"from contract_core import {', '.join(PUBLIC_NAMES)}\n"
        "import contract_core\n"
        "print(contract_core.__file__)\n"
    )
    imported = _run(str(py), "-c", probe)
    assert imported.returncode == 0, imported.stderr
    # Guard against a false green: with --system-site-packages the outer editable install is
    # visible, so assert the import resolved to the copy we just built from the git ref.
    assert str(venv) in imported.stdout, imported.stdout
```

- [ ] **Step 2: Run the test to verify the harness detects failure (anti-vacuity)**

A subprocess test that swallows a nonzero exit passes vacuously. Prove it does not: temporarily add
`"nonexistent_symbol"` to `PUBLIC_NAMES`, then run:

Run: `pytest tests/test_distribution.py -q`
Expected: FAIL, with pip/python's real stderr in the assertion message —
`ImportError: cannot import name 'nonexistent_symbol' from 'contract_core'`.
Remove the bogus name before continuing.

- [ ] **Step 3: Commit the public API, then run the test for real**

The test installs `HEAD`. If Tasks 1–6 are committed, this passes now.

Run: `pytest tests/test_distribution.py -q`
Expected: PASS (1 passed), in roughly 10–30s.

If it fails with a pip network error, the build backend (`hatchling`) is being fetched under build
isolation — that needs PyPI reachability once (it is then cached). This test needs **no** GitHub
credentials; it does need to reach PyPI on a cold pip cache. Record that in the PR description
rather than working around it.

- [ ] **Step 4: Run the full gate**

Run: `ruff check . && mypy && pytest -q`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add tests/test_distribution.py
git commit -m "test(R9): verify the git-ref install path exposes the public API (T1)"
```

---

### Task 8: Consumer documentation and the release procedure

Three things a consuming repo cannot discover from the code: the pin syntax and its deploy-token
prerequisite, the absent-library `try/except` pattern, and the kill switch's exact semantics. The
§5.5 authoring skill that will eventually carry these does not exist yet (Phase 1), so the document
is the carrier today.

**Files:**
- Create: `docs/consuming-repo-setup.md`
- Modify: `CONTRIBUTING.md` (append a "Releasing" section)
- Modify: `README.md` (one line in the Docs list)

**Interfaces:** none — documentation only.

- [ ] **Step 1: Write the consumer setup doc**

Create `docs/consuming-repo-setup.md`:

````markdown
# Using `contract-core` in another repo

## 1. Pin it by git tag

There is no package index and no wheel. A release **is** an annotated git tag `vX.Y.Z` on `main`.
Add this to the consuming repo's `pyproject.toml`:

```toml
dependencies = [
  "contract-core @ git+https://github.com/Avenue-Z/data-contract@v0.1.0",
]
```

Your lockfile captures the exact resolved commit — the same pin-by-tag / lock-the-exact-version
discipline we apply to contracts themselves.

**Prerequisite, not a footnote:** `data-contract` is private, so your CI needs read access to it —
a deploy key or a token with `contents: read` on `Avenue-Z/data-contract`. This is the one
operational cost of the git-tag approach. A missing token shows up as a `pip` clone failure at
install time, not as anything contract-shaped.

**Versioning:** `contract-core` is pre-1.0. Under 0.x semantics a **minor** bump may carry breaking
changes to the authored format or the API. Read the release notes before moving a pin.

## 2. Import only the public API

```python
from contract_core import load_runtime, ContractRuntime, ContractViolation, FieldDiff
```

Those five names (plus `__version__`) are the whole supported surface. **Everything else is
private** — `contract_core.runtime`, `.contract`, `.resolver`, `.schema`, `.events`, `.types`,
`.families`, `.compile.*`, `.cli`. Import paths into those may change without a major bump. Run the
CLI through the `contract` console script, not by importing `contract_core.cli`.

```python
runtime = load_runtime("contract.yaml", schema_paths=["schemas"])

@runtime.input("prompts")
def load_prompts():
    ...
```

`load_runtime`'s `schema_paths` default (`("schemas",)`) is signature-stable, but if the central
`avenue-z-schemas` path is later prepended to that default, a different schema may resolve. That
will be called out as a **behavior** change in the release notes — a stable signature is not a
promise of stable resolved bytes.

## 3. Turning validation off

Two knobs, and **"off always wins"**:

| Situation | Result |
| --- | --- |
| `CONTRACT_DISABLED` on (see below) | **disabled** — even if the code passes `enabled=True` |
| `load_runtime(..., enabled=False)` | disabled |
| neither | **enabled** (the default) |

`CONTRACT_DISABLED` is **on** iff it is present *and* its value, stripped and lowercased, is not one
of `""`, `"0"`, `"false"`, `"no"`, `"off"`. So:

- disables: `CONTRACT_DISABLED=1`, `=true`, `=yes`, `=on`
- leaves validation **enabled**: `CONTRACT_DISABLED=0`, `=false`, `=no`, `=off`, `=` (empty), and
  unset

*(Corrected in place; `"off"` was missing — see the superseded table. The shipped
`docs/consuming-repo-setup.md` also spells out that these name the state of the switch, not of
validation, and that an unrecognised value disables.)*

There is deliberately **no per-call opt-*in*** that overrides the env var — that is what makes
`CONTRACT_DISABLED` a real ops kill switch. A module hardcoding `enabled=True` cannot defeat it.

A disabled runtime does no validation, no schema resolution and **no file I/O**, and it announces
itself once on stderr at construction:

```
contract validation DISABLED (CONTRACT_DISABLED set) [contract.yaml]
```

If you ever wonder "why is nothing validating?", that line is the answer, and its absence means
validation is on. There is **no auto-degrade**: a missing or malformed contract file raises.

## 4. If `contract-core` might not be installed

The library cannot catch its own missing import, so this is a consumer pattern. The fallback must
be standalone — it cannot import anything from the library whose absence it is handling:

```python
try:
    from contract_core import load_runtime
    runtime = load_runtime("contract.yaml")
except ImportError:
    class _NoOpRuntime:
        """Stand-in when contract-core is not installed. Must NOT import from it."""
        def _passthrough(self, name):
            return lambda fn: fn
        raw = input = output = _passthrough

    runtime = _NoOpRuntime()
```

Yes, this duplicates the library's own disabled runtime. That duplication is irreducible, not an
oversight: the entire premise here is that the library is absent, so a helper it ships would be
unreachable exactly when it is needed. It drifts only if the decorator signature
(`raw`/`input`/`output` taking a name and returning a decorator) changes — which the library's
frozen-surface test already guards.

## 5. First-release smoke test (once per release, by hand)

The automated `tests/test_distribution.py` covers the install *mechanics* over a local `file://`
remote. It cannot cover the **authenticated remote**, because a tag cannot be installed before it is
cut. After cutting a tag, once, from a machine holding only the CI credential:

```bash
python -m venv /tmp/smoke && /tmp/smoke/bin/pip install \
  "contract-core @ git+https://github.com/Avenue-Z/data-contract@v0.1.0"
/tmp/smoke/bin/python -c "from contract_core import load_runtime; print('ok')"
```

Expected: `ok`. A failure here is an auth/tag problem, not a library problem.

---

*When the §5.5 authoring skill lands in Phase 1, it must carry §1 (the pin + deploy token), §3 (the
kill switch) and §4 (the absent-library pattern) — that skill is the eventual home for all three.*
````

- [ ] **Step 2: Append the release procedure to `CONTRIBUTING.md`**

Add at the end of `CONTRIBUTING.md`:

```markdown
## Releasing `contract-core`

A release is an **annotated git tag `vX.Y.Z` cut on `main`**. There is no wheel, no package index,
and no publish step — the tag *is* the version, and consumers pin
`contract-core @ git+https://github.com/Avenue-Z/data-contract@vX.Y.Z`.

1. In a normal PR, bump `version` in `pyproject.toml` **and** `__version__` in
   `src/contract_core/__init__.py` (a test fails if they skew). `contract-core` is pre-1.0: under
   0.x semantics a **minor** bump may carry breaking changes — including a change to the public
   surface, which `tests/test_public_api.py` blocks until someone updates the frozen set
   deliberately.
2. Land it through the normal chain: `dev` → `staging` → `main`. **Never push to `main`.**
3. Tag the merge commit on `main`:

       git fetch --all --prune
       git tag -a v0.1.0 <sha-on-main> -m "contract-core v0.1.0"
       git push origin v0.1.0

4. Run the first-release smoke test in `docs/consuming-repo-setup.md` §5 — it is the only check
   that covers the authenticated `git+https` fetch, which no automated test can run before the tag
   exists.
```

- [ ] **Step 3: Link the doc from `README.md`**

In the `## Docs` list, add after the `docs/superpowers/handoffs/` bullet:

```markdown
- `docs/consuming-repo-setup.md` — installing and using `contract-core` from another repo
```

- [ ] **Step 4: Verify the docs are honest**

Every claim in the doc is asserted by a test. Confirm the mapping by hand:

Run: `pytest tests/test_degradation.py tests/test_public_api.py -q`
Expected: all pass. Then re-read §3's truth table against
`tests/test_degradation.py::ON_VALUES`/`OFF_VALUES` and the warning string against
`test_disabled_warns_once_naming_trigger_and_label`. If any line in the doc has no test behind it,
either write the test or delete the claim.

> **This step ran and passed while `CONTRACT_DISABLED=off` disabled validation.** That is the most
> useful thing in this plan to learn from. The check is "doc agrees with test", and both were
> derived from the same wrong list, so they agreed perfectly. Cross-checking two artifacts with a
> common ancestor proves consistency, not correctness. The check that would have caught it is
> adversarial — enumerate the values an operator might *plausibly type* and ask what each does —
> which is what the reviewer did.

- [ ] **Step 5: Run the full gate**

Run: `ruff check . && mypy && pytest -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add docs/consuming-repo-setup.md CONTRIBUTING.md README.md
git commit -m "docs(R9): consumer setup, kill-switch semantics, and the release procedure"
```

---

## Post-merge: cutting v0.1.0

**Not a task in this plan** — it happens after the PR chain lands, and it changes real GitHub state.
Follow `CONTRIBUTING.md` § "Releasing `contract-core`": tag `main`, push the tag, then run the
first-release smoke test from `docs/consuming-repo-setup.md` §5. Only then can a consuming repo pin
`@v0.1.0`.

## Deliberately not built (§6 of the design)

Do not add these while implementing — each is a separate, owned piece of work:

- **§15 item 4** — the value-check enrichment hook.
- **§15 item 5** — library hygiene: the process-global `ContractRuntime.REGISTRY`, empty-frame
  reporting, runtime error-classification, the `schema`-field `UserWarning`, and the **event-log sink
  abstraction**. This is why `load_runtime` has no `event_log` parameter and why `EventLog` is *not*
  on the public surface: exporting it would promise a hook that does not exist. Both are added
  together, later.
- **The central `avenue-z-schemas` resolver default** — `schema_paths` keeps the signature stable
  for it, but wiring the registry in is not part of R9.
- **A private package index** — the git-tag approach is designed so an index is an additive drop-in.
- **Renaming modules with a leading underscore** — privacy is by convention *plus* the frozen-surface
  test (design decision #3: no underscore-rename churn).
