# `reconcile` — boundary registration-completeness gate (R3 + R2)

**Date:** 2026-07-23
**Status:** Approved for planning
**Owner:** Paul Ramirez / Engineering
**Closes:** R3 (reconcile registration completeness), R2 (adapter absorbs vendor drift — the
drift-test-presence half). Advances §15 item 5 (the `REGISTRY` global-state defect).
**Parent spec:** [`2026-07-16-data-contract-system-design.md`](2026-07-16-data-contract-system-design.md)
— §2 decision #6, §5.4, §7, §12 criterion 3, and the R2/R3 rows of §14.

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

The parent spec (§2, decision #6) frames reconciliation as a symmetric set XOR:
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

- **`registered − declared` is structurally near-impossible — and where it *does* arise, it is a
  crash, not a silent registration.** Decorating with a name the contract does not declare raises
  at import time from `_spec`, before the append. So this half of the XOR never becomes a stray
  registration; it becomes an import-time exception reconcile must catch and classify. To classify
  it *reliably* (not by parsing a message — §15 item 5 damns that), `_spec` raises a typed
  `UndeclaredBoundary(KeyError)` (internal, in `errors.py`, subclassing `KeyError` for
  back-compat), which force-import turns into a **gating** finding (category B, §5).
- **`declared − registered` is the load-bearing half.** A contract boundary that no decorator
  ever wired up (or wired up in code that force-import never reached) is the real drift, and the
  real false-pass risk.
- **Force-import completeness (R3) is therefore the whole ballgame.** If reconcile fails to
  import a module, it under-counts registrations and produces a *false pass*. And a decorator
  with a typo'd/undeclared name becomes an *import crash* that reconcile must catch and render as
  a finding rather than letting it abort the run.

reconcile still computes `registered − declared` and reports it defensively (near-zero cost), but
categories P/A/B/C/D below are the real gates.

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
2. **Reset** the registry (`_reset_registry()`, §4).
3. **Force-import** every module under `--package` (§6): evict-then-import so decorators re-run
   (§6.2), classifying each module's import failure — `UndeclaredBoundary` ⇒ gating category B,
   anything else ⇒ a non-gating diagnostic (§5.1) — rather than aborting. A failure of the
   *top-level* package import is the exception: category P, exit 1 (§6.2).
4. **Snapshot** the registry, filtered to `system` → the registered set `{(direction, name)}`.
5. **AST-scan** `--package`'s source files for misplaced boundary decorators → category C.
6. **AST-scan** `--tests` paths for `raw_drift` markers → the drift-covered raw set → category D.
7. **Emit findings.** Any finding ⇒ `exit 1`. Clean ⇒
   `OK: <system>@<version> — N boundaries reconciled` and `exit 0`.

### 3.1 Why `--schemas` is deliberately absent

reconcile never resolves schemas itself. The declared set is just boundary *names and
directions* — no resolution needed. The repo's own module-level `load_runtime(...)` resolves
schemas during force-import, using the repo's own `schema_paths`; a resolution failure there
surfaces as a non-gating import diagnostic, with category A gating on any declared boundary it
prevented from registering (§5.1). Giving reconcile its own `--schemas` would make it
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
- **Add a reset API — module-level and private.** A new `_reset_registry()` *function* in the
  `runtime` module (`def _reset_registry() -> None: ContractRuntime.REGISTRY.clear()`), **not** a
  public method on the exported `ContractRuntime` class. This is deliberate: `__all__` freezes the
  six *import-`*` names*, but it does not govern methods on an exported class — a no-underscore
  `ContractRuntime.reset_registry()` *would* enlarge the class's reachable surface, so the earlier
  "surface stays at 6" framing was wrong. The honest framing: `runtime` is already declared private
  in the package docstring (import paths into it are unsupported), so an underscore-prefixed
  module-level helper there is internal by both the R9 module-privacy rule and the naming
  convention. reconcile and the pytest fixture import it as an internal, not across the public
  surface. The `REGISTRY` arity change (2→3) is likewise an internal change to an
  already-private-module attribute.
  - **Reset alone is not enough in-process** — see §6.2. `_reset_registry()` clears the list, but
    Python caches modules in `sys.modules`, so re-importing an already-imported boundary module
    does *not* re-run its decorators. Force-import must evict-then-import to actually re-register.
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

Findings split into **gating** (any non-empty ⇒ `exit 1`) and **non-gating diagnostics**
(reported, but never block on their own). The split is the resolution of the import-blast-radius
problem (§5.1): a registration-completeness gate must not be brought down by an unrelated module's
optional-dependency import error, because *an annoying gate gets disabled, and a disabled gate is a
100% false negative*. Output follows `lint`'s human-readable, bulleted style.

**Gating findings:**

| Cat | Finding | Source & purpose |
| --- | --- | --- |
| **P** | `package '<pkg>' could not be imported` (pkg, error) | The top-level `--package` import failed (not installed, error in `__init__`). reconcile verified *nothing*, so it must never report a pass. Loud, explicit — §6.2. |
| **A** | `declared but no decorator registered it` (direction, name) | The R3 diff, `declared − registered`. The load-bearing false-pass guard; the incident-#2 replay. **Also the sound backstop that lets generic import errors be non-gating** (§5.1). |
| **B** | `decorator names an undeclared boundary '<name>'` (module, name) | A boundary decorator referenced a name the contract does not declare — the `registered − declared` guard (§2), classified by the typed `UndeclaredBoundary` (not by message-parsing). This is contract drift and gates. |
| **C** | `boundary decorator not at module top level` (file:line, name) | Placement AST scan. Enforces the "defined at import time" precondition force-import relies on (R3). |
| **D** | `raw boundary declared but no drift test found` (name) | R2. See §7. |

**Non-gating diagnostics:**

| Diag | Finding | Behavior |
| --- | --- | --- |
| import diagnostic | `module '<m>' failed to import: <error summary>` (non-`UndeclaredBoundary` cause) | Reported so it is visible and can *explain* a category-A finding, but does **not** by itself `exit 1`. |

### 5.1 Why non-gating import diagnostics stay sound (no false negative)

The instinct for a false-negative-fearing gate is to block on *any* import error. That instinct is
wrong here, and the reason is category A. If a module that fails to import held a **declared**
boundary, that boundary is now unregistered → it lands in `declared − registered` → **category A
gates on it, by name.** So the actual drift — a declared boundary silently going missing — is
caught by A regardless of how the import error itself is treated. Blocking on the raw import error
would only add false *positives* (an unrelated optional-dep module blocking the merge), which get
the gate disabled. Therefore: generic import errors are diagnostics; category A is the gate. The
one exception is a decorator that names an *undeclared* boundary — that has no declared name for A
to catch, so it is classified (`UndeclaredBoundary`) and gates directly as category B.

### 5.2 Determinism & the diagnostic/A overlap

- **Deterministic order (pinned for golden CLI tests and stable CI diffs):** findings render in a
  fixed category order — P, A, B, C, D, then diagnostics — and within each category sorted by their
  identifying tuple (name, or `file:line`).
- **The diagnostic/A overlap is intended, not emergent.** A module that fails to import can produce
  *both* a non-gating import diagnostic *and* a gating category-A finding (for each declared
  boundary it would have registered). This is complementary: A is the gate; the diagnostic is the
  likely cause, printed alongside so the fix is obvious. reconcile does not attempt to suppress
  either.

## 6. Force-import & AST mechanics; module layout

### 6.1 Module layout — pure core, impure shell

- **New module `contract_core/reconcile.py`** holds the **pure** functions (parent spec §11:
  "reconciliation … pure functions, structure in, findings out"), each unit-tested with no I/O:
  - `diff_boundaries(declared, registered) -> list[Finding]` — category A (`declared − registered`).
    The reverse (`registered − declared`) is computed too but is structurally empty (§2): a
    registered entry can only carry a declared name, since an undeclared one raises
    `UndeclaredBoundary` before the append. It is reported only if it ever somehow occurs.
  - `scan_decorator_placement(source_files) -> list[Finding]` — category C, over parsed ASTs.
  - `scan_drift_markers(test_files) -> set[str]` — the covered raw set for category D.
  - A small `Finding` value type (category + human message + identifying fields) with a total
    ordering, so the CLI shell can sort deterministically (§5.2).

  Categories P and B, and the import diagnostics, are produced by the **impure** force-import shell
  (§6.2), not these pure functions — they are outcomes of *running* imports, not of diffing
  structure. `classify_import_error(exc) -> Finding` (pure: exception in, category B-or-diagnostic
  out) is the one seam between them and is unit-tested directly.
- **The CLI subcommand** in [`cli.py`](../../../src/contract_core/cli.py) is the **impure shell**:
  force-import, file reads, registry snapshot, rendering, exit codes. It follows `lint`'s exact
  pattern (`click.Path` option types, `ContractFormatError` via `_echo_format_error`, `sys.exit`).

### 6.2 Force-import — the execution model

Three corners a registration-completeness gate lives or dies in: module caching, import blast
radius, and the top-level import itself.

**Evict, then import (module caching).** Python caches modules in `sys.modules`;
`import_module(m)` on an already-imported module returns the cached object *without re-running
module-level code*, so `REGISTRY.append` never fires again. A naïve `_reset_registry()` +
`import_module` therefore yields an empty registry and reports every declared boundary as a false
category A — and it lands exactly on the in-process path §4.1 relies on (reconcile's own test
suite; any repo that already imported its package before calling reconcile). So force-import first
**evicts the `--package` namespace** — every `sys.modules` key equal to `pkg_name` or starting
`pkg_name + "."` — and *then* imports, guaranteeing module-level code (and its decorators) re-runs
and re-registers. Only the target namespace is evicted; `contract_core` itself and third-party
modules stay loaded. Caveat (acceptable): after eviction+reimport, any previously held reference to
an old module object is stale — reconcile owns its process and the test fixtures do not hold module
references across a reconcile call, so no live object observes the swap.

**Top-level import gates; submodule imports are best-effort (blast radius).** The top-level
`import_module(pkg_name)` is wrapped: if it raises (package not installed, error in `__init__`),
reconcile emits a **category P** finding and exits 1 — it verified nothing and must not pass; no
walk is attempted. On success, `pkgutil.walk_packages(pkg.__path__, pkg.__name__ + ".")` imports
each submodule, each wrapped in `try/except`. The exception is **classified**, not blanket-gated:
- `UndeclaredBoundary` → **category B** (gating): a decorator named a boundary the contract does
  not declare.
- any other exception → a **non-gating import diagnostic** (§5.1): reported with a one-line
  summary (never a raw traceback), and walking continues so one broken module does not mask the
  rest. Category A remains the sound backstop for any *declared* boundary that module would have
  registered.

**`__path__`-absent (single-module / namespace packages).** `walk_packages(pkg.__path__, …)`
assumes a regular package. If the imported `--package` has no `__path__` (it is a single module),
reconcile scans just that one module. If `__path__` is a namespace-package path (a possibly-empty
list spanning locations), `walk_packages` handles it as given; reconcile does not special-case
namespace packages beyond not assuming a non-empty `__path__`. The placement scan (§6.3) takes its
source files from whatever `__path__`/`__file__` the import yielded.

### 6.3 Decorator-placement scan

The scan inspects **only decorator positions** (`node.decorator_list`), which already excludes
ordinary `.input()`/`.output()` *method calls*. Within those, a decorator is flagged when **all**:
1. it is an `ast.Call` whose `.func` is an `ast.Attribute` with `.attr ∈ {"raw", "input",
   "output"}` (the `@runtime.raw("x")` / `.input` / `.output` shape),
2. its single positional argument is a string literal (`ast.Constant` str) — the boundary name;
   this further narrows away decorator factories that happen to be named `input`/`output` but take
   other arguments, and
3. the decorated `FunctionDef` is **not** a direct child of the module body (it is nested in a
   function, method, `if`, `try`, etc.), so its decorator would run only when that code is
   *called*, not at import.

**Over-match, measured not asserted.** The residual false match is an unrelated
`@x.input("literal")` *decorator* whose receiver `x` is not a runtime. Measured against real code:
in this repo, **20 of 20** decorator-position `.raw/.input/.output` matches are genuine boundary
decorators (0 false); the pilot (`aivx-reports`) currently has none. Implementation **Task 1**
reports an over-match count against the pilot and this repo in the PR, replacing this estimate with
a number. If a repo ever proves noisy, the fallback narrowing is to require the receiver name to
match the module's runtime variable — deferred unless measurement demands it. Whatever the count,
the match fails in the **safe (over-strict) direction** — an over-match is a false *positive*
(annoying), never a false pass; but per §5.1's own logic an annoying gate gets disabled, which is
why the count must be small and measured, not waved at.

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
- **B1 — sys.modules eviction / in-process reuse:** two reconcile runs against the **same** fixture
  package in one process both produce correct results — the second run does not report a false
  category A because the module was already cached. This pins the evict-then-import model (§6.2);
  its absence is the exact bug the reviewer caught. A companion test asserts a boundary module is
  re-executed (its decorator re-registers) after `_reset_registry()` + force-import.
- **B2 — non-gating import diagnostic:** a fixture package with an unrelated submodule that raises
  on import (e.g. a missing optional dependency) but whose *declared* boundaries all register ⇒
  reconcile **passes** (exit 0) while *reporting* the import diagnostic. And the sound-backstop
  case: a submodule that fails to import *and* holds a declared boundary ⇒ category A FAILS naming
  the boundary, with the diagnostic printed as the likely cause. Together these pin §5.1.
- **P — package won't import (§6.2):** `--package` names a package whose top-level import raises ⇒
  reconcile emits a category-P finding and exits 1, never a traceback and never a pass.
- **B — undeclared-boundary decorator:** a top-level `@runtime.input("typo")` naming a boundary the
  contract does not declare ⇒ `UndeclaredBoundary` is classified as a gating category-B finding;
  force-import continues past it (other modules still scanned).
- **C:** a decorator nested inside a function body ⇒ FAILS. Without the placement scan this is a
  silent false pass (the decorator never runs at import, so A would not catch it either). Plus a
  negative: a normal top-level boundary decorator ⇒ no category-C finding (guards the over-match).
- **D — R2 true-positive *and* true-negative** (§12's "a checker that always says one thing passes
  half of any single-direction test"): a declared raw boundary with **no** `raw_drift` marker ⇒
  FAILS; the same boundary **with** the marker ⇒ passes.
- **Registry attribution:** two runtimes with different `system` values registering the same
  `(direction, name)` ⇒ reconcile-for-one does not count the other's registration;
  `_reset_registry` makes the tests order-independent.
- **Determinism:** a multi-finding run renders in the pinned order (§5.2), so the CLI golden test
  is stable.
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
- **§15 item 5 (registry only)** — `(system, direction, name)` + `_reset_registry`. The other
  item-5 entries (event-log sink/reader, error-classification fragility, `schema` field shadowing)
  are **out of scope** and stay open.
