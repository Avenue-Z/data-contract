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
of `""`, `"0"`, `"false"`, `"no"`. So:

- disables: `CONTRACT_DISABLED=1`, `=true`, `=yes`, `=on`
- leaves validation **enabled**: `CONTRACT_DISABLED=0`, `=false`, `=no`, `=` (empty), and unset

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
