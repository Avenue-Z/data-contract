# Using `contract-core` in another repo

## 1. Pin it by git tag

There is no package index and no wheel. A release **is** an annotated git tag `vX.Y.Z` on `main`.
Add this to the consuming repo's `pyproject.toml`:

```toml
dependencies = [
  "contract-core @ git+https://github.com/Avenue-Z/data-contract.git@vX.Y.Z",
]
```

Substitute `vX.Y.Z` with a concrete released tag ([`CHANGELOG.md`](../CHANGELOG.md) is the canonical
list). If you also wire the gate (§7), this pin and the workflow `@tag` **must be the same tag**, at
or above the release that introduced the gate — see the same-tag rule in §7.

Your lockfile captures the exact resolved commit — the same pin-by-tag / lock-the-exact-version
discipline we apply to contracts themselves.

**Keep the `.git` suffix.** The `reconcile` gate (§6–§7) scopes its read token to exactly this repo
by rewriting the `.git` clone URL; a bare `.../data-contract@<tag>` pin would clone unauthenticated
and fail. It is the canonical `pip` VCS form regardless, so use it everywhere.

**Prerequisite, not a footnote:** `data-contract` is private, so your CI needs read access to it —
a deploy key or a token with `contents: read` on `Avenue-Z/data-contract`. This is the one
operational cost of the git-tag approach. A missing token shows up as a `pip` clone failure at
install time, not as anything contract-shaped.

**Versioning:** `contract-core` is pre-1.0. Under 0.x semantics a **minor** bump may carry breaking
changes to the authored format or the API. Read the release notes — [`CHANGELOG.md`](../CHANGELOG.md),
the canonical record — before moving a pin.

## 2. Import only the public API

```python
from contract_core import load_runtime, ContractRuntime, ContractViolation, FieldDiff
```

Those five names (plus `__version__`) are the whole supported surface. **Everything else is
private** — `contract_core.runtime`, `.errors`, `.contract`, `.resolver`, `.schema`, `.events`,
`.types`, `.families`, `.vendor`, `.compile.*`, `.cli`. That list is exhaustive, and note that it
includes `.runtime` and `.errors`: those are where the four exported names are *defined*, but
`from contract_core.errors import FieldDiff` is not a supported import path — only
`from contract_core import FieldDiff` is. Import paths into private modules may change without a
major bump. Run the CLI through the `contract` console script, not by importing `contract_core.cli`.

```python
runtime = load_runtime("contract.yaml", schema_paths=["schemas"])

@runtime.input("prompts")
def load_prompts():
    ...
```

`load_runtime`'s `schema_paths` default (`("schemas",)`) is signature-stable, but if the central
`avenue-z-schemas` path is later prepended to that default, a different schema may resolve. That
will be called out as a **behavior** change in [`CHANGELOG.md`](../CHANGELOG.md) — a stable signature
is not a promise of stable resolved bytes.

### Format version and strict keys

Authored files are strict: a key `contract-core` does not recognise is a hard error at
load, not a silently-ignored line. A typo (`requird:`) fails loudly. Add only keys this
version documents.

Files may carry an optional `format_version: v1` at the top level of a schema or contract.
It is optional — a file with no stamp is read as `v1`. It bumps only when the *meaning* of
an existing key changes, never when a key is added. A `format_version` this reader cannot
read is refused with an upgrade hint, rather than mis-parsed.

### Value constraints

A schema field may declare `enum`, `minimum`, `maximum`, or `min_length`. They are enforced at the
boundary alongside presence and type, and a violation raises `ContractViolation` under `enforce`:

```python
except ContractViolation as exc:
    for d in exc.diffs:
        if d.problem == "value":
            print(d.field, d.constraint, d.violating_rows, d.samples)
```

Constraints apply only to non-null values — `nullable` is the only null gate. Adding one to a schema
is a **breaking** change and requires a major version bump.

Constraints are checked for *satisfiability* when the schema loads, not only for applicability. These
are rejected outright, because each one fails or admits every row while reading as a real constraint:

| Authored | Why it is rejected |
| --- | --- |
| `enum: []` | admits nothing |
| `minimum: 5, maximum: 1` | empty interval — admits nothing |
| `enum: [0, 1]` with `minimum: 5` | enum disjoint from its bounds — admits nothing |
| `min_length: 0` or negative | admits everything; a no-op that reads as a constraint |
| `minimum: true` | Python treats `True` as `1`; a bound meaning `1` should say `1` |
| `minimum: 0.5` on an `int` field | means `1` on an integer column, but does not say so |

A *partial* overlap between an `enum` and its bounds (`enum: [1, 5, 9]` with `minimum: 5`) is
legitimate narrowing and is accepted. The list above is exhaustive — there is no general
satisfiability solver behind it.

### If you consume the ODCS export

Two things changed in `0.2.0` **for every schema, including ones that did not change**:

- `required` is no longer emitted. ODCS documents that key as null semantics ("may contain Null
  values"), not presence, so this project's presence flag did not belong in it.
- Every non-nullable field grows a `quality` rule: `{"metric": "nullValues", "mustBe": 0}`.

The consequence worth planning for: **presence is not representable in the exported ODCS document.**
A field that is `required: true, nullable: true` exports only its name and logical type. Read
presence from the authored schema, not from exported ODCS. Regenerating ODCS for an untouched schema
will produce a different document than `0.1.0` did.

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

Read those as statements about *the switch*, not about validation: `=on` turns the kill switch on
(validation off), `=off` turns it off (validation on). Anything the list does not name — `=maybe`,
`=disabled`, a stray `=x` — disables. The switch fails toward "not validating", so a value that is
not clearly an off-value is treated as an operator asking for it.

There is deliberately **no per-call opt-*in*** that overrides the env var — that is what makes
`CONTRACT_DISABLED` a real ops kill switch. A module hardcoding `enabled=True` cannot defeat it.

A disabled runtime does no validation, no schema resolution and **no file I/O**, and it announces
itself once on stderr at construction:

```
contract validation DISABLED (CONTRACT_DISABLED set) [contract.yaml]
```

If you ever wonder "why is nothing validating?", that line is the answer, and its absence means
validation is on. It is written straight to `sys.stderr`, deliberately not through `logging` — a
`basicConfig` or `dictConfig` call in your app could delete a log record, and then the line's
absence would prove nothing. Nothing you configure can silence it. There is **no auto-degrade**: a
missing or malformed contract file raises.

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
  "contract-core @ git+https://github.com/Avenue-Z/data-contract.git@vX.Y.Z"
/tmp/smoke/bin/python -c "from contract_core import load_runtime; print('ok')"
```

Expected: `ok`. A failure here is an auth/tag problem, not a library problem.

## 6. If you run the `reconcile` gate

`contract reconcile` enforces R2: every declared `raw` boundary must have a drift test, which it
finds by looking for the marker `@pytest.mark.raw_drift("<name>")` (decorator position, attribute
form, one string-literal argument — the `"<name>"` must match the raw boundary's name). A declared
raw boundary with no such marker is a category-D failure.

reconcile finds the marker by **AST scan** — it never imports or runs your tests — so from
reconcile's side nothing needs registering. But if you write those drift tests as real collected
tests (files matching `test_*.py`) and run pytest with `--strict-markers`, pytest rejects the
unregistered `raw_drift` marker at collection, before reconcile is ever involved. Register it once
in the consuming repo's `pyproject.toml`:

```toml
[tool.pytest.ini_options]
markers = [
    "raw_drift: a drift test guarding a raw boundary (read by `contract reconcile`)",
]
```

This is *your* pytest configuration, not something the library ships — `contract-core`'s own suite
side-steps it by naming its reconcile fixtures `drift_*.py` (never collected), which a consuming
repo running real drift tests cannot do.

## 7. Wiring the gate into CI

`contract lint` + `contract reconcile` only protect you if CI runs them on every PR. This repo ships
a reusable workflow that does exactly that.

**Prerequisite, not a footnote:** `data-contract` is private, so a reusable workflow it hosts is
invisible to your repo until an admin enables, once, **Settings → Actions → General → Access →
"Accessible from repositories in the 'Avenue-Z' organization"** on `data-contract`. A `workflow was not
found` error means *that setting is off* — it is **not** the `contract-core-token`, which only clones
the dependency. If the setting cannot be enabled, use the inline alternative below; it calls nothing
cross-repo.

**Pin the same tag you pin contract-core to.** The workflow ships the CLI flag names at its tag,
while your `pyproject.toml` (§1) pins the CLI it drives, and a 0.x minor may change that surface (read
[`CHANGELOG.md`](../CHANGELOG.md)). So the workflow `@tag` and your contract-core pin **must be the
same tag** — a mismatch is silent CLI breakage, not a warning — and at or above the release that
introduced the gate.

### Call the reusable workflow

```yaml
# .github/workflows/contract.yml in YOUR repo
name: contract
on:
  pull_request:
  push:
    branches: [main]   # your protected branches

jobs:
  gate:
    # Same tag as your contract-core pin (§1) — see the same-tag rule below.
    uses: Avenue-Z/data-contract/.github/workflows/contract-gate.yml@vX.Y.Z
    with:
      contract: contract.yaml
      package: my_pkg              # importable — reconcile imports it to find registered boundaries
      schemas: |                   # one dir per line
        schemas
      tests: |                     # one path per line
        tests
    secrets:
      # A token/deploy key with contents:read on Avenue-Z/data-contract (§1).
      contract-core-token: ${{ secrets.CONTRACT_CORE_READ_TOKEN }}
```

`schemas` and `tests` are **newline-delimited** — one path per line under a `|` block. Blank and
whitespace-only lines *between or after* real entries are ignored, so a stray newline will not fail
the gate. But `schemas` and `tests` are each **required**: a block with *no* real entry expands to
zero flags and the gate fails closed with `Missing option '--schemas'` (or `--tests`). Every path
you list must exist in the checkout — a non-existent or misspelled path fails the same way.

### Exit-code semantics

The gate **is** the exit code; nothing parses output. `lint` exits non-zero on a malformed contract,
malformed schema, or unresolved schema ref. `reconcile` exits non-zero on any gating finding
(categories P/A/B/C/D — see the reconcile design) and on a malformed contract. Any non-zero fails the
check. The `raw_drift` marker is read by AST and needs no registration on reconcile's side — but if
you run your drift tests as collected pytest tests under `--strict-markers`, register the marker as
§6 shows, or pytest rejects it at collection.

### Inline alternative (no cross-repo call)

If you would rather not depend on the reusable workflow — or cannot enable the Actions-access setting
above — run the two commands directly. Pin the marketplace actions to your repo's policy.

```yaml
jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - name: Install and run the gate
        env:
          CONTRACT_CORE_TOKEN: ${{ secrets.CONTRACT_CORE_READ_TOKEN }}
        run: |
          set -euo pipefail
          [ -n "${CONTRACT_CORE_TOKEN:-}" ] || { echo "::error::CONTRACT_CORE_READ_TOKEN is empty"; exit 1; }
          git config --global \
            url."https://x-access-token:${CONTRACT_CORE_TOKEN}@github.com/Avenue-Z/data-contract.git".insteadOf \
            "https://github.com/Avenue-Z/data-contract.git"
          pip install .
          contract lint --contract contract.yaml --schemas schemas
          contract reconcile --contract contract.yaml --package my_pkg --tests tests
```

## 8. Where the evidence goes, and who is meant to look

Two different questions hide behind "how do I find out a contract failed", and they have two
different answers. Getting them mixed up is why observe-mode adoption stalls.

### Under `enforce`, nothing in this library notifies you — by design

A violation raises `ContractViolation`, which stops the job. **Delivery is your platform's job**, not
the library's: a failed GitHub Actions run emails and shows a red check, a failed Cloud Run job
surfaces in Cloud Logging and whatever alerting you point at it. That is deliberate. An event write
is I/O that can itself fail, and a library that opens a network connection to announce a validation
failure can take down the job it was meant to protect. If you want a Slack ping, hang it off the
platform's job-failure signal, where it belongs.

### Under `observe`, nothing fails — so you must go and read

`observe` validates, logs, and never raises. The run stays green whether or not the shape drifted,
which is exactly the point (it cannot break a working job) and exactly the trap: **no one finds out
unless something reads the log.** That reader is `contract events`, and the evidence has to survive
the run for it to have anything to read.

The runtime appends JSON Lines to `$CONTRACT_EVENT_LOG`, defaulting to `./contract-events.jsonl`.
Where to point it depends on where you run:

| Where you run | Where the evidence should go |
| --- | --- |
| Local / a persistent host | The default is fine. The file accumulates across runs; `contract events` reads it in place. |
| GitHub Actions | A path inside the workspace, then upload it as a build artifact — the runner's disk is destroyed when the job ends. |
| A container (e.g. Cloud Run) | **Not yet answered.** The container filesystem is ephemeral, so the default writes evidence nobody can ever read. See the note below before adopting `observe` there. |

In CI this needs no library support — the log path and the reader are both already parameters:

```yaml
      - name: Run the pipeline in observe mode
        env:
          CONTRACT_EVENT_LOG: ${{ github.workspace }}/contract-events.jsonl
        run: python -m my_pkg.main

      - name: Summarize what the boundaries observed
        run: contract events --log contract-events.jsonl --contract contract.yaml --json > events.json

      - uses: actions/upload-artifact@v4     # the evidence outlives the runner
        with:
          name: contract-events
          path: |
            contract-events.jsonl
            events.json
```

`contract events --json` carries `summary.ready`, which **fails closed** — an empty or absent log
reads `ready: false`, never a green light on zero evidence. So promotion to `enforce` can be gated on
observed evidence rather than on someone remembering to look. That is the intended watcher.

### Containers: an open decision, not an oversight

There is no sink abstraction — the event log writes to a filesystem path and nothing else. On an
ephemeral container that means observe-mode evidence dies with the container.

This is deliberately unbuilt rather than overlooked, because the hard part is not the writer, it is
what the writer does when the destination is down. A sink that **raises** turns contract validation
into a source of production outages; a sink that **swallows** creates silent evidence loss, which is
worse than no sink at all, because people promote boundaries on evidence they wrongly believe
arrived. Choosing between those needs a real deployment with real failure modes, not a guess.

**Trigger for revisiting: the first container deploy that runs a boundary in `observe`.** At that
point, work the question in this order, and stop at the first answer that holds:

1. Can the log path point at durable storage (a mounted bucket, a volume)? If so, nothing needs
   building.
2. Can the job ship the file on exit as an explicit step, the way CI uploads an artifact?
3. Only if neither holds does a sink abstraction earn its place — and it must answer the
   raise-vs-swallow question **before** any interface is published.

Until then, run `observe` where the evidence survives: locally and in CI.

---

*When the §5.5 authoring skill lands in Phase 1, it must carry §1 (the pin + deploy token), §3 (the
kill switch) and §4 (the absent-library pattern) — that skill is the eventual home for all three.*
