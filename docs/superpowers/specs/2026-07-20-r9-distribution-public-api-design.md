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
4. **Graceful degradation is explicit, loud, and "off always wins"** — preserves the parent spec's
   decision #3 ("hard-fail by default, fail loud"). Validation is on unless someone deliberately turns
   it off; and turning it off is *itself* loud (§3.3) — a disabled runtime announces itself once at
   construction, so "why is nothing validating?" is diagnosable from a signal, not inferred from the
   absence of failures. The kill switch is **un-overridable by application code**: anything that says
   "off" wins, so an ops kill switch can never be defeated by a module that hardcodes "on."

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
consumers must not import deep module paths. Every name in `__all__` is a semver obligation, so the
surface is the **minimum a consumer actually needs** — one line of justified consumer need per name,
not test convenience (test convenience is served by importing the private path).

| Public name | Kind | Why a *consumer* (not the test suite) needs it |
| --- | --- | --- |
| `load_runtime` | function (**new**) | The primary entry point. One call builds a configured `ContractRuntime` from a contract file. |
| `ContractRuntime` | class | The return type of `load_runtime` (consumers annotate/hold it) and the home of `.disabled()`. |
| `ContractViolation` | exception | The exception a boundary raises on hard failure; consumers catch/expect it. |
| `FieldDiff` | class | Consumers introspect `ContractViolation.diffs` (a `list[FieldDiff]`) to build custom handling/messages. |
| `__version__` | str | Already present. |

`FieldDiff`'s four attributes — `field`, `expected`, `observed`, `problem` — are themselves part of the
frozen surface (a consumer reads them; renaming one is a breaking change), and T5 pins them, not just
the class's export.

**Considered and rejected (kept private):** `Contract`, `Schema`, `EventLog`. A consumer using
`load_runtime(path)` never constructs a `Contract` or a `Schema` — those are resolution internals — and
a custom `EventLog` sink is not a real capability yet (the sink abstraction is §15 item 5, unbuilt and
out of scope), so exporting `EventLog` would promise a hook that doesn't exist. Exporting any of these
now would be adding a frozen compatibility obligation to serve our own tests; tests import the private
path instead. They can be promoted additively later if a genuine consumer need appears.

**Private (documented as such, not re-exported):** `contract` (`Contract`, `BoundarySpec`), `schema`
(`Schema`), `events` (`EventLog`), `resolver` (`Resolver`, `SchemaNotFound`), `types` (`Field`,
`JSON_SCHEMA_TYPE`, `PANDAS_DTYPE`), `families`, `compile.*` (`to_pandera`, `to_json_schema`,
`to_odcs`, …), and `cli`. These are internals or tooling-only; the `contract` console-script entry
point (already declared in `pyproject.toml`) is how the CLI is invoked, not a Python import target.

**The import path is the contract.** `from contract_core import load_runtime` is the promised surface;
where `load_runtime` is *defined* (`runtime.py`, or a small `api.py`) is an implementation detail, but
that module is **not** itself exposed — no `contract_core.api` import path is offered or supported. T2
(§5) freezes exactly the top-level names, so an accidental "helpful" re-export elsewhere is not part of
the contract.

**The factory:**

```python
def load_runtime(
    contract_path: str | Path = "contract.yaml",
    *,
    schema_paths: Sequence[str | Path] = ("schemas",),
    enabled: bool = True,
) -> ContractRuntime:
    """Build a runtime from a contract file, or a disabled no-op runtime.

    Returns a disabled runtime — no validation, no file I/O, one loud warning at
    construction (§3.3) — when CONTRACT_DISABLED is *on* in the environment OR when
    enabled=False. CONTRACT_DISABLED is on iff present and not in
    {"", "0", "false", "no"} (case-insensitive); so =0 / =false leave validation ON.
    "Off wins": there is no way to force validation on over the env kill switch.
    Otherwise loads the contract and resolver and returns an enforcing runtime.
    """
```

No `event_log` parameter: a custom event sink is not a supported capability yet (§15 item 5), so the
factory uses the default `EventLog`. The param is added — with `EventLog` promoted to the public
surface — when the sink abstraction lands, not before (YAGNI).

Internally it is a thin wrapper over the primitives that already exist: `Contract.from_yaml(path)` and
`Resolver(list(schema_paths))`. `schema_paths` defaulting to `("schemas",)` is **signature-stable but
behavior-affecting** if the central `avenue-z-schemas` path is later prepended to the default (§5.1 of
the parent spec): a consumer relying on today's resolution order could see a different schema resolve.
So that later change is a *behavior* change to call out in a changelog, **not** a free "no API change"
— the signature stays put, the resolved bytes may not.

### 3.3 Graceful degradation (§15 item 7)

Two failure modes, handled distinctly:

**(A) Library installed, validation wanted OFF** (kill switch, test environment):

- `ContractRuntime.disabled()` — a classmethod returning a runtime whose `raw()`, `input()`, and
  `output()` return **pass-through no-op decorators**: the decorated function runs and returns its
  value unchanged, with **no schema resolution, no file I/O, and no per-boundary validation or events**.
- **One loud signal at construction (closes the silent-disable gap).** The warning lives in
  **`ContractRuntime.disabled()` itself**, not in `load_runtime` — so it fires regardless of entry
  point: a consumer calling the public `disabled()` classmethod directly gets the same signal as one
  going through the factory. Constructing a disabled runtime emits exactly one `logging.warning` to
  **stderr**, naming the trigger and a best-available label — e.g.
  `contract validation DISABLED (CONTRACT_DISABLED set) [contract.yaml]`. Because a disabled runtime
  does **no file I/O**, it cannot read the contract to learn the `system` name, so it names what it
  actually has: `disabled(label: str | None = None)` takes an optional identifier, `load_runtime`
  passes `str(contract_path)` as that label (it knows the path without parsing it), and a bare
  `disabled()` call with no label reads `unspecified`. The message never depends on loading a file.
  This is what makes
  "off" *loud* per decision #4: the diagnostic is a positive signal, not the inference-from-silence a
  reviewer would (rightly) call a foot-gun. It is deliberately a **stderr warning, not an event-log
  write** — an event write is file I/O that can itself fail, reintroducing exactly the import-time
  crash item 7 exists to prevent; stderr has no such dependency and cannot crash an unrelated import.
- **Trigger, and precedence — "off always wins":** the runtime is disabled if `CONTRACT_DISABLED` is
  **on** in the environment **OR** `enabled=False` is passed. It is enabled only when `CONTRACT_DISABLED`
  is off *and* `enabled` is `True` (the default). There is deliberately **no way for application code to
  force validation on over the env kill switch** — that is what makes `CONTRACT_DISABLED` a real ops
  kill switch (a module that hardcodes `enabled=True` still cannot defeat it). A per-call opt-*out* is
  `enabled=False`; there is intentionally no per-call opt-*in* that overrides ops.
- **What "on" means for `CONTRACT_DISABLED` — pinned, because an ambiguous kill switch is an incident
  risk.** It is **not** "any truthy value / merely present." The var is **on** iff it is *present and
  its value, lowercased and stripped, is not in `{"", "0", "false", "no"}`*. So `CONTRACT_DISABLED=1`,
  `=true`, `=yes`, `=on` all disable; `CONTRACT_DISABLED=0`, `=false`, `=no`, `=` (empty), and *unset*
  all leave validation **enabled**. This is the direction an operator intends: typing `0`/`false` turns
  the switch *off*, it does not accidentally disable every contract. The single rule lives in one
  private helper (`_env_disabled()`), so the factory and any other caller share identical semantics.

**(B) Library not installed at all:** `contract-core` cannot catch its own missing import, so this is
solved by a **consumer pattern**, documented in the §5.5 authoring skill, not by library code:

```python
try:
    from contract_core import load_runtime
    runtime = load_runtime("contract.yaml")
except ImportError:
    runtime = _NoOpRuntime()  # standalone; must NOT import from the absent library
```

**On the `_NoOpRuntime` duplication (raised in review):** the no-op logic exists in two places — the
library's `disabled()` and this consumer snippet — and that duplication is **irreducible, not an
oversight**. Case B's entire premise is that `contract-core` is *not installed*, so the fallback cannot
`import` anything from it — an "importable guarded helper" shipped by the library is unreachable in
exactly the situation it would serve. The snippet is a handful of pass-through methods and drifts only
if the *decorator signature* (`raw`/`input`/`output` taking a name, returning a decorator) changes —
which T2's frozen surface already guards. Accepted, with eyes open.

**Fail-loud alignment (decision #3):** the default path is fully enabled and enforcing. There is **no
auto-degrade** — a missing/malformed contract file raises, it does not silently disable validation.
Disabling is always a deliberate act (env var or explicit flag) **and always announces itself** (the
construction warning above), so the system never silently ships zero validation.

## 4. Components changed

- `pyproject.toml` — version bump; (release tagging is a git/process step, not a file change).
- `src/contract_core/__init__.py` — curated re-exports + `__all__`.
- `src/contract_core/runtime.py` — add `ContractRuntime.disabled()` and the no-op decorator path;
  add the module-level `load_runtime` factory (may live in `runtime.py` or a small `api.py` — an
  implementation detail for the plan, not a design decision).
- Docs / §5.5 authoring skill — consumer pin syntax, the deploy-token prerequisite, and the
  absent-library try/except pattern.
- Tests — the five success-criteria tests (§5).

## 5. Success criteria (literal, falsifiable — matches parent spec §12 style)

1. **T1 — installability, over the *real* install path.** The distribution model ships no wheel
   (§3.1), so T1 must not test one. In a **clean** venv, install `contract-core` the way a consumer
   does — a PEP 508 git-ref that pip resolves and **builds from source** — then import the public API:
   `pip install "contract-core @ git+file://<repo-path>@<ref>"` into a fresh venv, then
   `python -c "from contract_core import load_runtime, ContractRuntime, ContractViolation, FieldDiff"`
   exits 0. Using a local `file://` remote at a committed `<ref>` exercises the exact git-ref
   resolve-and-build path consumers use, with **no network or deploy token**, so it runs on every CI
   push — closing the "T1 tests an artifact the model doesn't produce" gap. The **auth** layer (a real
   `git+https://…@vX.Y.Z` fetch with the deploy token) is a separate, thinner concern verified by a
   **first-release smoke test** (once per release, over https), since a tag cannot be installed before
   it is cut. Together they cover both halves of the R9 failure: the install *mechanics* (every push)
   and the *authenticated remote* (at release).
2. **T2 — stable surface (a change *tripwire*, not a stability guarantee).** A snapshot test asserts
   `set(contract_core.__all__)` equals the frozen expected set; removing or renaming any public name
   fails CI **here**, before it breaks a consumer. Note precisely what this does and does not promise:
   under the 0.x versioning policy (§3.1) a breaking surface change *is permitted* on a minor bump, so
   T2 enforces **"you must notice and do it deliberately"** (the change is blocked until someone updates
   the frozen set — and, by policy, bumps the minor and notes it), **not "you must never break."** It
   is the machinery that turns a silent break into a conscious, reviewed one — the guard against "any
   internal refactor breaks every consuming repo at once," not a compatibility guarantee the versioning
   policy would contradict.
3. **T3 — public API is sufficient.** A sample consumer module runs a full raw→input→output validation
   importing **only** `from contract_core import …` — no deep module paths. If the public surface is
   insufficient for a real boundary flow, this fails.
4. **T4 — degradation is a real toggle, with pinned activation semantics.** With `CONTRACT_DISABLED=1`
   (and, separately, `load_runtime(enabled=False)`, and a direct `ContractRuntime.disabled()` call), a
   decorated function whose data *would* hard-fail an enforcing boundary instead returns its data
   unchanged and performs no file I/O — **and** the construction emits the single stderr warning
   (§3.3), asserted present (including on the direct `disabled()` path, since that is where the warning
   lives). Conversely, with the env var unset **and** with `CONTRACT_DISABLED=0` (the foot-gun case: an
   operator typing `0` must *not* disable), and `enabled` at its default, the same function still
   hard-fails **and** emits no such warning. (True-positive *and* true-negative on the toggle, the
   `=0`/`=false` off-values, and the loud-signal — same rigor as parent spec criterion #4.)
5. **T5 — `FieldDiff` is reachable and usable off a caught violation.** Catching a `ContractViolation`
   from an enforced boundary yields a non-empty `list[FieldDiff]` (via its `diffs`), each with the
   `field`/`expected`/`observed`/`problem` fields a consumer needs for custom handling — using **only**
   the top-level import. This is what justifies `FieldDiff` on the frozen surface (review #4/#5): a
   public name with no consumer-facing test is a name we will break blind.

## 6. Out of scope (explicit boundaries)

- **§15 item 4 — value-check enrichment hook.** Separate Phase 1 design.
- **§15 item 5 — library hygiene:** process-global `ContractRuntime.REGISTRY`, empty-frame reporting,
  fragile runtime error-classification, the `schema` field `UserWarning`, event-log sink abstraction.
  Not touched here. Note the interaction: `REGISTRY` being process-global class state is unaffected by
  curating the public API — flagged so the item-5 design owns it, not this one.
- **Central `avenue-z-schemas` resolver default.** `load_runtime`'s `schema_paths` keeps the
  *signature* stable when the registry path is later prepended, but that later change is
  behavior-affecting (§3.2), not free; wiring the registry in is not part of R9.
- **Private package index.** Deferred; the git-tag approach is designed so an index is an additive
  drop-in.
