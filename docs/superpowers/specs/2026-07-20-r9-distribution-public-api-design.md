# R9 — Distribution & Public API Surface — Design

**Date:** 2026-07-20
**Status:** Approved for planning
**Owner:** Paul Ramirez / Engineering
**Parent spec:** [Data Contract System — Design](2026-07-16-data-contract-system-design.md) §14 R9, §15 items 2 & 7
**Phase:** 1 (prerequisite to onboarding repo #2)

## 1. Problem

`contract-core` today is invisible-from-the-pilot but a hard blocker for its Phase 1 goal —
being "the first thing in every new repo." Concretely, as it stands in this repo:

- **Not installable elsewhere.** `pyproject.toml` pins `version = "0.0.1"` with no publish target; the
  only way to install it is an editable local path. CI on a fresh machine in a *consuming* repo cannot
  install it.
- **No public API.** `__init__.py` exports only `__version__`. Every consumer (the tests, and by
  extension the pilot) reaches into deep module paths — `contract_core.runtime`, `.contract`,
  `.resolver`, `.errors`, `.events`, `.schema`, `.types`, `.families`, `.compile.*`, `.cli`. Any
  internal refactor breaks every consuming repo at once.
- **Awkward construction.** Building a runtime requires the consumer to assemble `Contract` +
  `Resolver` by hand (`ContractRuntime(contract, resolver, ...)`), so "the public API" is more than
  re-exporting classes — it needs an ergonomic entry point.
- **Import-time fragility (§15 item 7, which the parent spec says "ties to R9").** A module that builds
  its runtime at import time takes a hard `contract-core` dependency *and* does file I/O at import, so
  anything importing that module hard-crashes when the library is absent or the contract file is
  missing. There is no supported way to keep the decorators in place but turn validation off.

This design covers **R9 proper** (installable versioned artifact + curated public API) **and §15
item 7** (graceful degradation), because the three together are what make `contract-core` safe to drop
into a new repo. §15 items 4 (enrichment hook) and 5 (library hygiene) are deliberately **out of
scope** (§6).

## 2. Guiding decisions (settled during brainstorming)

1. **Distribution = pinned git-tag ref, no index infra.** Consumers pin
   `contract-core @ git+https://github.com/Avenue-Z/data-contract@vX.Y.Z`. Uses the GitHub org that
   already exists; a private package index is a future drop-in, not a Phase 1 dependency.
2. **Curate a real public API in `__init__.py`; treat deep module paths as private** (parent spec R9
   mitigation, verbatim).
3. **Enforce the boundary with machinery, not discipline** — a frozen public-surface test — consistent
   with the project's R2/R3 "machinery over discipline" standard. Module *filenames* are unchanged (no
   underscore-rename churn); privacy is by convention **plus** the test that guards the promised
   surface.
4. **Graceful degradation is explicit, never automatic** — preserves the parent spec's decision #3
   ("hard-fail by default, fail loud"). Validation is on unless someone deliberately turns it off.

## 3. Design

### 3.1 Distribution (R9 half 1)

- Bump `version` `0.0.1 → 0.1.0` in `pyproject.toml`. Staying pre-1.0 is honest: the authored format
  and API may still break (see the parent spec's R10). Under 0.x semantics a **minor** bump may carry
  breaking changes.
- A release is an **annotated git tag** `vX.Y.Z` cut on `main`. No wheels, no index, no new
  infrastructure. The tag *is* the version.
- Consuming repos pin the dependency in their own `pyproject.toml`:

  ```toml
  dependencies = [
    "contract-core @ git+https://github.com/Avenue-Z/data-contract@v0.1.0",
  ]
  ```

  The exact resolved commit is captured in the **consumer's** lockfile — the same pin-by-tag /
  lock-the-exact-version discipline the parent spec §4.2 applies to contracts.
- **Prerequisite (documented, not hidden):** a consumer's CI needs read access to this repo (a deploy
  token / key). This is the one operational cost of the git-tag approach and is called out in the
  consuming-repo setup docs and the §5.5 authoring skill.

### 3.2 Public API surface (R9 half 2)

`__init__.py` re-exports a curated set and declares `__all__`. Everything not listed is private —
consumers must not import deep module paths.

| Public name | Kind | Purpose |
| --- | --- | --- |
| `load_runtime` | function (**new**) | The primary entry point. One call builds a configured `ContractRuntime` from a contract file. |
| `ContractRuntime` | class | The runtime; exposes `.raw()`, `.input()`, `.output()` decorators and `.disabled()`. |
| `ContractViolation` | exception | What a boundary raises on hard failure; what consumers catch/expect. |
| `FieldDiff` | class | The structural expected-vs-observed diff carried by `ContractViolation`. |
| `Contract` | class | Explicit/advanced construction; `Contract.from_yaml(path)`. |
| `Schema` | class | Advanced use and tests. |
| `EventLog` | class | Lets a consumer pass a custom event sink to `load_runtime`. |
| `__version__` | str | Already present. |

**Private (documented as such, not re-exported):** `resolver` (`Resolver`, `SchemaNotFound`),
`contract.BoundarySpec`, `types` (`Field`, `JSON_SCHEMA_TYPE`, `PANDAS_DTYPE`), `families`,
`compile.*` (`to_pandera`, `to_json_schema`, `to_odcs`, …), and `cli`. These are internals or
tooling-only; the `contract` console-script entry point (already declared in `pyproject.toml`) is how
the CLI is invoked, not a Python import target.

**The factory:**

```python
def load_runtime(
    contract_path: str | Path = "contract.yaml",
    *,
    schema_paths: Sequence[str | Path] = ("schemas",),
    enabled: bool | None = None,
    event_log: EventLog | None = None,
) -> ContractRuntime:
    """Build a runtime from a contract file, or a disabled no-op runtime.

    Disabled (no validation, no file I/O) when CONTRACT_DISABLED is set in the
    environment, or when enabled=False. Otherwise loads the contract and resolver
    and returns an enforcing runtime. enabled=True forces enabled even if the env
    var is set (explicit code beats ambient config).
    """
```

Internally it is a thin wrapper over the primitives that already exist: `Contract.from_yaml(path)` and
`Resolver(list(schema_paths))`. `schema_paths` defaulting to `("schemas",)` leaves room to prepend the
central `avenue-z-schemas` registry path later (§5.1 of the parent spec) without an API change.

### 3.3 Graceful degradation (§15 item 7)

Two failure modes, handled distinctly:

**(A) Library installed, validation wanted OFF** (kill switch, test environment):

- `ContractRuntime.disabled()` — a classmethod returning a runtime whose `raw()`, `input()`, and
  `output()` return **pass-through no-op decorators**: the decorated function runs and returns its
  value unchanged, with **no schema resolution, no file I/O, and no validation**. It emits no events.
- Triggered by either:
  - `CONTRACT_DISABLED=1` in the environment — an ops kill switch requiring no code change; checked
    inside `load_runtime`.
  - `load_runtime(..., enabled=False)` — an explicit in-code toggle (e.g. a test fixture).
  - Precedence: an explicit `enabled=True` beats the env var (explicit code wins over ambient config);
    `enabled=None` (default) defers to the env var; `enabled=False` always disables.

**(B) Library not installed at all:** `contract-core` cannot catch its own missing import, so this is
solved by a **consumer pattern**, documented in the §5.5 authoring skill, not by library code:

```python
try:
    from contract_core import load_runtime
    runtime = load_runtime("contract.yaml")
except ImportError:
    runtime = _NoOpRuntime()  # decorators pass through; contract absent, degrade to a warning
```

**Fail-loud alignment (decision #3):** the default path is fully enabled and enforcing. There is **no
auto-degrade** — a missing/malformed contract file raises, it does not silently disable validation.
Disabling is always a deliberate act (env var or explicit flag), so the system never silently ships
zero validation.

## 4. Components changed

- `pyproject.toml` — version bump; (release tagging is a git/process step, not a file change).
- `src/contract_core/__init__.py` — curated re-exports + `__all__`.
- `src/contract_core/runtime.py` — add `ContractRuntime.disabled()` and the no-op decorator path;
  add the module-level `load_runtime` factory (may live in `runtime.py` or a small `api.py` — an
  implementation detail for the plan, not a design decision).
- Docs / §5.5 authoring skill — consumer pin syntax, the deploy-token prerequisite, and the
  absent-library try/except pattern.
- Tests — the four success-criteria tests (§5).

## 5. Success criteria (literal, falsifiable — matches parent spec §12 style)

1. **T1 — installability.** From a **clean** environment, the built artifact installs and the public
   API imports:
   `pip install <built wheel/sdist>` into a fresh venv, then
   `python -c "from contract_core import load_runtime, ContractRuntime, ContractViolation"` exits 0.
   This is the literal inverse of the R9 failure "CI on another machine cannot install it." (Runs
   against the built artifact in CI; a git-tag end-to-end install is exercised once at first release.)
2. **T2 — stable surface.** A snapshot test asserts `set(contract_core.__all__)` equals the frozen
   expected set. Removing or renaming any public name fails CI **here**, before it breaks a consumer —
   the guard against "any internal refactor breaks every consuming repo at once."
3. **T3 — public API is sufficient.** A sample consumer module runs a full raw→input→output validation
   importing **only** `from contract_core import …` — no deep module paths. If the public surface is
   insufficient for a real boundary flow, this fails.
4. **T4 — degradation is a real toggle.** With `CONTRACT_DISABLED=1` (and, separately,
   `load_runtime(enabled=False)`), a decorated function whose data *would* hard-fail an enforcing
   boundary instead returns its data unchanged and performs no file I/O. With the env var unset and
   `enabled` at its default, the same function still hard-fails. (A true-positive *and* true-negative,
   so an always-off bug can't pass — same rigor as parent spec criterion #4.)

## 6. Out of scope (explicit boundaries)

- **§15 item 4 — value-check enrichment hook.** Separate Phase 1 design.
- **§15 item 5 — library hygiene:** process-global `ContractRuntime.REGISTRY`, empty-frame reporting,
  fragile runtime error-classification, the `schema` field `UserWarning`, event-log sink abstraction.
  Not touched here. Note the interaction: `REGISTRY` being process-global class state is unaffected by
  curating the public API — flagged so the item-5 design owns it, not this one.
- **Central `avenue-z-schemas` resolver default.** `load_runtime`'s `schema_paths` is designed to
  accommodate it later without an API change; wiring the registry in is not part of R9.
- **Private package index.** Deferred; the git-tag approach is designed so an index is an additive
  drop-in.
