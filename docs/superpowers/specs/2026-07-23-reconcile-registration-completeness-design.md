# `reconcile` — boundary registration-completeness gate (R3 + R2)

**Date:** 2026-07-23
**Status:** Approved for planning
**Owner:** Paul Ramirez / Engineering
**Closes:** R3 (reconcile registration completeness), R2 (adapter absorbs vendor drift — the
drift-test-presence half). Advances §15 item 5 (the `REGISTRY` global-state defect).
**Parent spec:** [`2026-07-16-data-contract-system-design.md`](2026-07-16-data-contract-system-design.md)
— §5.4, §6, §7, §12 criterion 3, and the R2/R3 rows of §14.

## 1. Purpose

`reconcile` is the CI-blocking gate that catches **incident #2 (spec rot)**: the automation's
code drifts away from the boundaries its contract declares, and nobody notices. It diffs the
boundaries a contract *declares* against the boundaries actually *registered* at import time,
and fails CI on any gap. In the same command it enforces R2: a declared raw boundary must have
a companion drift test.

**A false negative — reconcile passing while a real boundary drifted — is the failure mode to
fear.** Everything below is shaped by that: where the design must choose, it chooses the
over-strict direction (a false *positive* is an annoyance; a false *negative* defeats the gate).

This is the incident-#2 replay named in the parent spec §12 criterion 3: *"Swap an input from
API to CSV in the code without touching the contract. `contract reconcile` must fail in CI and
name the boundary that drifted."*

## 2. The structural insight that shapes the diff

The parent spec (§6) frames reconciliation as a symmetric set XOR:
`set(registered) ^ set(declared)`. In the current code it is **asymmetric**, and this matters.

The boundary decorator resolves its spec from the contract *before* it registers
([`runtime.py:122-125`](../../../src/contract_core/runtime.py#L122-L125)):

```python
def _decorator(self, direction: str, name: str) -> Decorator:
    spec = self._spec(direction, name)          # raises KeyError if name not declared
    resolved = self.resolver.resolve(spec.schema)
    ContractRuntime.REGISTRY.append((direction, name))   # only reached if declared
```

Consequences:

- **`registered − declared` is structurally near-impossible.** Decorating with a name the
  contract does not declare raises `KeyError` at import time — a *crash*, not a registration.
  So this half of the XOR does not arise through the normal decorator path.
- **`declared − registered` is the load-bearing half.** A contract boundary that no decorator
  ever wired up (or wired up in code that force-import never reached) is the real drift, and the
  real false-pass risk.
- **Force-import completeness (R3) is therefore the whole ballgame.** If reconcile fails to
  import a module, it under-counts registrations and produces a *false pass*. And a decorator
  with a typo'd/undeclared name becomes an *import crash* that reconcile must catch and render as
  a finding rather than letting it abort the run.

reconcile still computes `registered − declared` and reports it defensively (near-zero cost), but
A/B/C/D below are the real gates.

## 3. Command surface & flow

```
contract reconcile --contract contract.yaml --package my_automation --tests tests/
```

| Option | Meaning |
| --- | --- |
| `--contract` | Path to the contract YAML (the declared set). Required. `click.Path(exists=True)`. |
| `--package` | The importable package name to force-import and AST-scan for placement. Required. |
| `--tests` | One or more paths to AST-scan for `raw_drift` markers (R2). Required; `multiple=True`. |

Flow, in order:

1. **Load** the contract via `Contract.from_yaml` → the declared set `{(direction, name)}` and
   the `system`. A `ContractFormatError` is rendered exactly as `lint` renders it
   (`_echo_format_error`) and exits 1.
2. **Reset** the registry (`ContractRuntime.reset_registry()`, §4).
3. **Force-import** every module under `--package` (§6), catching each module's import crash as a
   category-B finding rather than aborting.
4. **Snapshot** the registry, filtered to `system` → the registered set `{(direction, name)}`.
5. **AST-scan** `--package`'s source files for misplaced boundary decorators → category C.
6. **AST-scan** `--tests` paths for `raw_drift` markers → the drift-covered raw set → category D.
7. **Emit findings.** Any finding ⇒ `exit 1`. Clean ⇒
   `OK: <system>@<version> — N boundaries reconciled` and `exit 0`.

### 3.1 Why `--schemas` is deliberately absent

reconcile never resolves schemas itself. The declared set is just boundary *names and
directions* — no resolution needed. The repo's own module-level `load_runtime(...)` resolves
schemas during force-import, using the repo's own `schema_paths`; a resolution failure there
surfaces as a category-B import-error finding. Giving reconcile its own `--schemas` would make it
duplicate — and risk disagreeing with — the repo's resolver configuration. It stays out.

## 4. Registry evolution

The registered set comes from `ContractRuntime.REGISTRY`, which §15 item 5 flags as
"process-global mutable class state (leaks across contracts/tests — the pilot's registry
assertion is already order-dependent)." The defect is not that it is global — a module-level
registry is the *correct* decoupling mechanism, because reconcile discovers registrations by
force-importing arbitrary modules and observing side effects, never by holding a handle to the
repo's runtime instance. The defect is that entries are **unattributed** and the registry is
**never reset**.

Changes:

- **Attribute each entry.** `REGISTRY` entries become `(system, direction, name)`. The append
  site at [`runtime.py:125`](../../../src/contract_core/runtime.py#L125) gains
  `self.contract.system`. reconcile filters the snapshot to `system == contract.system`.
- **Add a reset API.** A new **internal** `ContractRuntime.reset_registry()` classmethod. It is
  *not* added to `__init__.__all__` — the frozen public surface (R9) stays at 6 names. reconcile
  calls it before force-import; a pytest fixture calls it between tests.
- **Update the existing assertion.** [`test_runtime.py:149`](../../../tests/test_runtime.py#L149)
  (`("input", "prompts") in ContractRuntime.REGISTRY`) updates to the 3-tuple. Deliberate,
  in-scope.

### 4.1 What attribution buys — the cross-contract false-attribution it prevents

Without attribution, two contracts live in one process share one unlabelled list. If contract A
(`system: aivx-reports`) registers `("input", "metrics")` and contract B (`system: peec-sync`)
declares `"metrics"` but *forgets the decorator*, reconcile-for-B finds A's entry, believes B's
boundary is registered, and **passes** — the precise false-pass a blocking gate must not have.
With `(system, direction, name)`, reconcile-for-B filters to `peec-sync`, sees nothing, and
correctly flags `"metrics"` as declared-but-unregistered.

Most consuming repos have one contract, where both options behave identically. Where attribution
*always* matters is reconcile's own test suite, which builds many runtimes with many `system`
names into that one global list — the exact order-dependence §15 item 5 reports. Attribution +
reset make those tests correct and independent.

## 5. Finding taxonomy

Four gating categories; **any** non-empty ⇒ `exit 1`. Each finding names the boundary and enough
to fix it. Output follows `lint`'s human-readable, bulleted style.

| Cat | Finding | Source & purpose |
| --- | --- | --- |
| **A** | `declared but no decorator registered it` (direction, name) | The R3 diff, `declared − registered`. The load-bearing false-pass guard; the incident-#2 replay. |
| **B** | `boundary module failed to import` (module, exception summary) | Force-import crash. Includes the `KeyError` a typo'd/undeclared decorator name raises — turning a would-be abort into a clean finding. |
| **C** | `boundary decorator not at module top level` (file:line, name) | Placement AST scan. Enforces the "defined at import time" precondition force-import relies on (R3). |
| **D** | `raw boundary declared but no drift test found` (name) | R2. See §7. |

Defensive fifth line (non-gating unless it appears): `registered − declared` — structurally
near-impossible (§2), reported if it ever occurs so the anomaly is visible rather than swallowed.

## 6. Force-import & AST mechanics; module layout

### 6.1 Module layout — pure core, impure shell

- **New module `contract_core/reconcile.py`** holds the **pure** functions (parent spec §11:
  "reconciliation … pure functions, structure in, findings out"), each unit-tested with no I/O:
  - `diff_boundaries(declared, registered) -> list[Finding]` — categories A and the defensive
    reverse.
  - `scan_decorator_placement(source_files) -> list[Finding]` — category C, over parsed ASTs.
  - `scan_drift_markers(test_files) -> set[str]` — the covered raw set for category D.
  - A small `Finding` value type (category + human message + fields).
- **The CLI subcommand** in [`cli.py`](../../../src/contract_core/cli.py) is the **impure shell**:
  force-import, file reads, registry snapshot, rendering, exit codes. It follows `lint`'s exact
  pattern (`click.Path` option types, `ContractFormatError` via `_echo_format_error`, `sys.exit`).

### 6.2 Force-import

`importlib.import_module(pkg_name)`, then
`pkgutil.walk_packages(pkg.__path__, pkg.__name__ + ".")`, importing each submodule. Each import
is wrapped in `try/except Exception` → category B (module name + a one-line exception summary, not
a raw traceback). Walking continues past a failure so one broken module does not mask the rest.
Source paths for the placement scan (§6.3) are taken from the imported package's `__path__`.

### 6.3 Decorator-placement scan

Over each source file's AST, a decorator is flagged when **both**:
1. it is an `ast.Call` whose `.func` is an `ast.Attribute` with `.attr ∈ {"raw", "input",
   "output"}` (the `@runtime.raw("x")` / `.input` / `.output` shape), and
2. the decorated `FunctionDef` is **not** a direct child of the module body (it is nested in a
   function, method, `if`, `try`, etc.), so its decorator would run only when that code is
   *called*, not at import.

Accepted, documented residual: an unrelated `@x.input(...)` decorator whose receiver is not a
runtime would be flagged. This fails in the **safe (over-strict) direction** — never a false
pass — and is rare. It is documented as the matched pattern rather than guessed away.

Accepted residual (unchanged from parent §5.4): genuinely dynamic, factory-created boundaries
remain undetectable by any of this machinery. The authoring skill steers away from that pattern.

## 7. R2 — drift-test detection

### 7.1 The mechanism

Convention: each raw-boundary drift test carries `@pytest.mark.raw_drift("<raw_boundary_name>")`.
`scan_drift_markers` AST-parses (never imports) every `.py` under `--tests`, collecting every
string argument to a `raw_drift` marker into the covered set. For every `name` in `contract.raw`:
`name ∉ covered` ⇒ a category-D finding.

`pytest.mark.raw_drift` is idiomatic pytest and requires **no new importable API** — a marker is
attribute access, not an import, so the frozen surface stays at 6. Consuming repos register the
marker in `pytest.ini`/`pyproject.toml` to silence the unknown-mark warning; this is documented,
not enforced by reconcile.

### 7.2 The honest ceiling — stated, not hidden

reconcile is a **static** gate. `raw_drift` detection verifies a drift test **exists and is
linked** to the raw boundary; it does **not** verify the test genuinely exercises an unknown-shape
rejection — that would require running the suite, which breaks the pure-function model and couples
the gate to the repo's whole test environment.

This is the same disciplined scope the rest of the system takes: R3's diff is sound but only as
complete as import execution; R8's families match logical not physical dtype. It satisfies the
parent spec's R2 bar precisely — *"turning 'we wrote the test' from a hope into a gate"* —
by converting **silent absence** of a drift test into a **hard failure**. A hollow marked test
still passes, but that is now a **visible, reviewable act naming the boundary**, not a silent gap.
This is the R2 residual, stated where R2 is enforced.

## 8. Testing (TDD — false negatives are the target)

Every category gets a **failing test first**, then the implementation. Pure functions are tested
directly; the CLI shell is tested end-to-end against fixture packages.

Critical pins (each is a false-*negative* the gate must not have):

- **A — incident-#2 replay (§12 criterion 3):** a fixture package that *declares* a boundary
  whose decorated function lives in a module force-import must reach, but the decoration is absent
  or the module is only conditionally imported ⇒ reconcile FAILS naming the boundary. This is the
  core R3 test.
- **C:** a decorator nested inside a function body ⇒ FAILS. Without the placement scan this is a
  silent false pass (the decorator never runs at import, so A would not catch it either).
- **D — R2 true-positive *and* true-negative** (§12's "a checker that always says one thing passes
  half of any single-direction test"): a declared raw boundary with **no** `raw_drift` marker ⇒
  FAILS; the same boundary **with** the marker ⇒ passes.
- **B:** a top-level decorator with a typo'd name ⇒ reported as a category-B finding, not an
  uncaught traceback; force-import continues past it.
- **Registry attribution:** two runtimes with different `system` values registering the same
  `(direction, name)` ⇒ reconcile-for-one does not count the other's registration; `reset_registry`
  makes the tests order-independent.
- **Clean case:** a fully-wired fixture package ⇒ `exit 0` with the `OK:` summary.

Baseline 212 tests stay green; `ruff check .` and `mypy` stay clean. New tests live in
`tests/test_reconcile.py` (pure functions) and extend the CLI tests for the subcommand.

## 9. Non-goals

- **No static I/O scanner.** reconcile is a sound registry diff, not an AST discovery of
  boundaries nobody declared (parent spec §1 non-goals, §2 decision #6). The placement scan is a
  *placement* check on already-declared decorators, not boundary discovery.
- **No test execution.** reconcile does not run pytest (§7.2).
- **No dynamic-factory boundary detection.** Accepted residual (§6.3, parent §5.4).
- **No changes to the runtime validation path** beyond the registry tuple + reset API. The
  decorator's validate/emit behavior is untouched.

## 10. Risk-row closures (to land in the same PR as the code)

Per the parent spec's "close a row in the same PR that lands its mitigation" rule, this work
closes, with date + commit + option taken:

- **R3** — force-import + placement scan as a single `reconcile` gate; dynamic-factory residual
  accepted.
- **R2** — the `raw_drift` marker finding (category D); static existence+linkage, ceiling stated
  (§7.2).
- **§15 item 5 (registry only)** — `(system, direction, name)` + `reset_registry`. The other
  item-5 entries (event-log sink/reader, error-classification fragility, `schema` field shadowing)
  are **out of scope** and stay open.
