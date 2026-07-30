# Integrating data contracts into `Avenue-Z/repo-template`

**Status: BLOCKED — not a plan to execute.**

The template work depends on `contract init`, which does not exist and is not specified. This
document does the part that does not depend on it: it records the decisions already taken, the
findings that hold regardless, and the exact preconditions that unblock the work. The four
deliverables originally asked for — exact files added/changed, the `init-repo.sh` diff shape, the
`ADOPTION.md` section, and the `template-tests/` coverage — are **deliberately not designed here**.
See §6.

---

## 1. Why this is blocked

### 1.1 `contract init` does not exist

`src/contract_core/cli.py` registers exactly three commands:

| Command | Definition |
| --- | --- |
| `contract lint` | `cli.py:52` |
| `contract reconcile` | `cli.py:104` |
| `contract events` | `cli.py:129` |

There is no `init`. Verified beyond the working tree: `git grep -i "contract init\|scaffold"` across
every commit on every branch returns nothing, no spec exists under `docs/superpowers/specs/`, and the
open issue list (#55, #53, #22) contains no scaffolding work.

### 1.2 What adoption costs without it

Standing up contracts in a consuming repo today means hand-authoring, per
`skills/authoring-data-contracts/SKILL.md` and `docs/consuming-repo-setup.md`:

1. `contract.yaml` — `system`/`version` plus `raw`/`inputs`/`outputs` boundary sets
2. one or more `schemas/<platform>/<name>/<X.Y.Z>.yaml` files, authored from the **real** columns
3. runtime wiring — `load_runtime` plus `@runtime.raw` / `.input` / `.output` decorators
   (`references/templates/runtime_wiring.py`)
4. a `@pytest.mark.raw_drift("<name>")` test per `raw` boundary, or `reconcile` fails category-D
5. `.github/workflows/contract.yml` calling the reusable gate at a pinned tag
   (`references/templates/ci-gate.yml`)

...plus two `pyproject.toml` edits: the `contract-core @ git+...@vX.Y.Z` pin (`consuming-repo-setup.md`
§1) and the `raw_drift` marker registration (§6).

The authored format is strict and explicitly "not guessable" — an unrecognised key is a hard load
error. That is the correct design for the format and precisely why a scaffolder is load-bearing.

### 1.3 The retrofit path is the one that matters, and it is the one `contract init` owns

This is the core of the block, and it is not just "hand-authoring is tedious."

`init-repo.sh` runs **once, by one person, on the day the repo is created** — the README says as much
about plugin installation, and the same logic applies here. On that day, nobody knows whether the repo
will read external data. The first TikTok export lands weeks later. So an init-time flag is offered at
exactly the moment the answer is unknown, and the path that actually gets used is *"I now need a
contract in a repo that already exists."*

`repo-template` cannot serve that path. It has no presence in a generated repo — `init-repo.sh:359`
deletes `templates/`, `template-tests/` and `template-docs/` wholesale, and the script's own
idempotency short-circuit (`init-repo.sh:276`) exits early on any re-run. Retrofit belongs to a command
you run *inside* the finished repo. That command is `contract init`.

Wiring the template before it exists would ship a `--contracts` flag serving the minority case and a
docs pointer whose only follow-through is a five-artifact manual checklist.

---

## 2. Decisions taken — do not re-litigate

These were settled and hold whenever the work unblocks.

### 2.1 Middle: docs always, real files only on `--contracts`

**Decision.** Every `templates/python` repo ships a docs pointer (`README.repo.tmpl`, `CLAUDE.md`) and
an inert example workflow. `contract.yaml`, `schemas/`, the drift test and the `pyproject.toml` edits
are scaffolded **only** under `./scripts/init-repo.sh python --contracts`.

**Against pure opt-in.** A flag is discoverable only to someone who already knows it exists. That is
the discovery problem restated, not solved — and it is asked on day one (§1.3), when the answer is
unknown.

**Against default-on.** The template's governing posture is that an inert control is worse than no
control: `resolve_codeowners` (`init-repo.sh:77-216`) will *grant* a team write access or ship no
`CODEOWNERS` at all, rather than write a file GitHub silently ignores. A `contract.yaml` nobody wired
is that same file in a different costume. It declares boundaries no decorator registers, so the moment
someone does turn on the gate, `reconcile` reports category-A/B findings against a contract that was
never real. And a live gate on a repo with no external reads teaches people that contract checks are
noise to be deleted — the most expensive outcome available.

**Why the middle is not a fudge.** Discovery is a documentation problem with a documentation fix. The
reader needs to find out contracts exist at the moment they add their first external read. A line in
`README.md` and `CLAUDE.md` is present at that moment; a flag consumed weeks earlier is not.

**Constraint on "commented-out workflow" — it cannot be a `.yml`.** GitHub parses *every* file under
`.github/workflows/`, and a file with no valid `on:` trigger surfaces as a workflow error in the
Actions tab of every generated repo. The inert artifact must therefore ship as
`.github/workflows/contract.yml.example` (or under `docs/`), never as a commented-out `contract.yml`.
This is a hard requirement, not a preference, and needs a `template-tests/` assertion.

### 2.2 `--contracts` narrows the python stack to 3.13

**The collision.** `templates/python/pyproject.toml:9` declares `requires-python = ">=3.11"` and
`templates/python/.github/workflows/ci.yml:25` runs a `["3.11", "3.12", "3.13"]` matrix. `contract-core`
declares `requires-python = ">=3.13"`. A scaffolded repo pinning contract-core in `dependencies` fails
the 3.11 and 3.12 legs at `pip install -e ".[dev]"` (`ci.yml:31`) — before a single test runs.

**Decision.** `--contracts` rewrites, in the copied stack only: `requires-python` to `>=3.13`,
`[tool.ruff] target-version` to `py313`, `[tool.mypy] python_version` to `3.13`, and the `ci.yml`
matrix to `["3.13"]`. A repo scaffolded **without** the flag keeps the full matrix, untouched.

**Why not an optional extra.** Pinning contract-core under a `contracts` extra keeps the matrix green,
and that green is a lie. The consuming pattern in `consuming-repo-setup.md` §4 catches `ImportError`
and substitutes a no-op runtime — by design, since the library cannot catch its own absent import. So
on 3.11 and 3.12 the decorators would silently become pass-throughs and the suite would pass with
validation disabled. Two of three legs reporting green on unexercised boundary wiring is exactly the
"a failure to verify is not a verified pass" violation this template is built around. Secondary
problems: `mypy --strict` against contract-core types under `python_version = "3.11"`, and a repo
testing on versions the gate (`contract-gate.yml:29`, default `3.13`) never exercises.

**Why not raise the whole template.** Dropping 3.11/3.12 from `templates/python` for every repo is a
breaking change to a surface unrelated to contracts. It may be right on its own merits; it is not this
change's call to make.

### 2.3 `node` and `next` get nothing — and `--contracts` must be refused, loudly

**Stated out loud: the answer is nothing.** There is no path for a node or next repo that needs a data
contract, and none is proposed here.

`contract-core` is Python — pandera and pandas do the validation, the distributed artifact is a Python
package, and `reconcile --package` (`cli.py:101`) requires an **importable Python package** to scan for
registered boundaries. `contract-gate.yml` sets up Python and runs the `contract` console script. There
is no TypeScript port, no port planned, and no partial path: even the CI gate alone is unusable without
a Python package to point `--package` at.

What such a repo does instead is a real question with a real answer — move the external read into a
Python job that owns the contract, and let the node/next app consume already-validated data — but that
is an architecture decision for the team that hits it, not something `repo-template` can scaffold.

**Requirement.** `./scripts/init-repo.sh node --contracts` (and `next`) must `die` with a message
naming the reason, before mutating anything. Silently ignoring the flag would hand someone a repo they
believe is contract-wired and is not — the same silent-inert failure as an ignored `CODEOWNERS`. This
gets a `template-tests/` assertion.

---

## 3. Findings that hold regardless of `contract init`

### 3.1 The ground truth checks out

Verified against `Avenue-Z/repo-template` at `6df4f21`: zero mention of contracts anywhere —
`CLAUDE.md`, `README.md`, `README.repo.tmpl`, `CONTRIBUTING.md`, `scripts/init-repo.sh`,
`docs/ADOPTION.md`, and all three starters. `git ls-files` is 90 files; none reference contracts.

### 3.2 The visibility fork is a *second* dependency, and it is not `contract init`

`Avenue-Z/data-contract` is currently **public** (`gh repo view` → `"visibility": "PUBLIC"`,
`"isPrivate": false`), and per the brief that state is under review and undecided.

The template work has to know the answer, because the two branches produce different scaffolds:

| If public | If private |
| --- | --- |
| No `contract-core-token` secret. `contract-gate.yml` steps 0/2/4 (the token guard, the authenticated `.contract-core` checkout, the `insteadOf` rewrite) are all inert or removable. | The scaffolded workflow needs `secrets: contract-core-token`, and someone must provision `CONTRACT_CORE_READ_TOKEN` per repo. |
| The Actions org-access prerequisite (`consuming-repo-setup.md` §7) drops — a public repo's reusable workflow is callable. | An admin must enable Actions access on `data-contract` once, or every scaffolded gate fails `workflow was not found`. |
| `init-repo.sh` scaffolds a workflow that works on first push. | `init-repo.sh` scaffolds a workflow that **fails until a human does something it cannot do** — the script has no path to set a repo secret. |

That last row is the sharp edge. Under the private branch, the honest options are to ship the gate
disabled with a documented enablement step, or to have `init-repo.sh` provision the secret via `gh`
(new permission surface, new failure modes, and the `resolve_codeowners` precedent says it must then
verify rather than assume). Both are real design work. **Do not begin the template work until the
visibility decision lands** — it changes what gets written, not just a comment.

Note also that `consuming-repo-setup.md` §1 and §7 both assert "`data-contract` is private" as
present-tense fact. That is already wrong today and should be corrected independently of this work.

### 3.3 `templates/python/Dockerfile` is not touched

Confirmed internally coherent and left alone: `name = "app"`, `src/app/main.py` exists,
`requires-python = ">=3.11"` matches `FROM python:3.11-slim`, `ENTRYPOINT python -m app.main`
resolves. The broken Dockerfile in `data-contract` is this repo's own adaptation failure
(Avenue-Z/data-contract#53), not inherited.

**But §2.2 puts it in scope.** Narrowing `requires-python` to `>=3.13` under `--contracts` desynchronises
it from `FROM python:3.11-slim` — reproducing #53 in the template, by hand, on purpose. The
`--contracts` path must bump the base image with the rest of the stack. This is a consequence of the
version decision, not a "fix" to a working file.

---

## 4. Preconditions — what unblocks this

**A. `contract init` is specified and shipped**, and its spec answers at minimum:

1. Which of the five artifacts in §1.2 it emits, and which remain hand-authored. (A scaffolder that
   cannot produce schemas from real data still leaves the highest-effort artifact manual — that is a
   legitimate answer, but the plan needs to know it.)
2. Whether it is a net-new-repo command, an in-place retrofit command, or both. §1.3 says the retrofit
   mode is the one that matters.
3. What it does in a repo that already has a `contract.yaml` — refuse, merge, or overwrite.
4. Its exit codes, and whether it is safe to run non-interactively from a script.
5. Whether it edits `pyproject.toml` (the pin and the `raw_drift` marker) or only prints instructions.
6. Whether it emits the CI workflow, and if so how it resolves the pinned tag — `ci-gate.yml` currently
   ships a `@vX.Y.Z` placeholder, and the same-tag rule (`consuming-repo-setup.md` §7) means the
   workflow tag and the `pyproject.toml` pin must match exactly.

**B. The `data-contract` visibility decision lands** (§3.2).

Both are external to `repo-template`. Neither can be resolved by designing harder here.

---

## 5. Scope inventory for the eventual plan

Not a design — an inventory of surfaces, recorded so the work is not re-scoped from scratch. Every item
is contingent on §4.

**In `Avenue-Z/repo-template`:**

- `scripts/init-repo.sh` — a `--contracts` flag (python-only, `die` on node/next per §2.3), the
  stack-narrowing rewrites of §2.2, and the scaffold invocation, placed relative to the existing
  copy → verify → `resolve_codeowners` → `add_dependabot_ecosystem` → strip → commit sequence.
- `templates/python/` — the inert `.github/workflows/contract.yml.example` (§2.1), and whatever
  `--contracts` mutates.
- `README.repo.tmpl` and `templates/python`'s `CLAUDE.md` surface — the always-on docs pointer.
- `docs/ADOPTION.md` §1 — a step in the net-new track, and the "add contracts later" pointer that §1.3
  says is the path people actually take.
- `template-tests/` — a new suite. `template-tests.yml:64` globs `template-tests/test_*.sh`, so a new
  file is picked up automatically; no workflow edit needed.

**What the tests must prove** (assertion targets, not assertions):

- Without `--contracts`: no `contract.yaml`, no `schemas/`, and the python matrix is still
  `["3.11", "3.12", "3.13"]` — the flag's absence must cost nothing.
- With `--contracts`: the scaffolded contract **actually lints**. `contract lint --contract contract.yaml
  --schemas schemas` exits 0 against the generated tree. This is the assertion that matters; every other
  one is file-presence theater without it. It implies the suite installs `contract-core`, which the
  visibility decision (§3.2) governs — a private dependency needs a token the template-tests runner
  does not have today (`template-tests.yml:60` passes only a repo-scoped `GITHUB_TOKEN`).
- With `--contracts`: `contract reconcile` exits 0 — i.e. the scaffolded decorators and the scaffolded
  `raw_drift` test are consistent with the scaffolded `contract.yaml`.
- The example workflow is inert: no `.github/workflows/contract.yml` in a non-`--contracts` repo, and
  the `.example` file is not valid-workflow-shaped in a way GitHub would parse (§2.1).
- `node --contracts` and `next --contracts` exit non-zero, name the reason, and leave `templates/`
  intact — the existing `assert_dir "died BEFORE mutating the tree"` pattern
  (`test_init_repo.sh:237`).
- The existing zero-dead-files guarantees still hold: nothing contract-related leaks into a repo
  scaffolded without the flag, on any of `dev`/`staging`/`main`.

---

## 6. Explicitly not delivered

Per the decision to block:

- Exact files added/changed, with content.
- The `init-repo.sh` diff.
- `ADOPTION.md` prose.
- Written `template-tests/` assertions.

All four depend on what `contract init` emits (§4.A) and on the visibility decision (§4.B). Writing
them now would mean designing against an invented CLI surface, which is the failure mode the block
exists to avoid.

---

## Appendix — evidence index

| Claim | Source |
| --- | --- |
| CLI has no `init` | `src/contract_core/cli.py:43-169` |
| Five hand-authored artifacts | `skills/authoring-data-contracts/SKILL.md`; `docs/consuming-repo-setup.md` §1, §6, §7 |
| Template strips itself on init | `scripts/init-repo.sh:276-280`, `:359-377` |
| Inert-control posture | `scripts/init-repo.sh:77-216`; `template-tests/test_init_repo.sh:124-141` |
| Python matrix 3.11–3.13 | `templates/python/.github/workflows/ci.yml:19-34` |
| `requires-python >= 3.11` | `templates/python/pyproject.toml:9` |
| `contract-core` needs 3.13 | `pyproject.toml:8` |
| Absent-library no-op fallback | `docs/consuming-repo-setup.md` §4 |
| Gate is Python-only | `.github/workflows/contract-gate.yml:82-138`; `cli.py:101` |
| `data-contract` is public | `gh repo view Avenue-Z/data-contract --json visibility` → `PUBLIC` |
| Docs assert it is private | `docs/consuming-repo-setup.md` §1, §7 |
| Test suite auto-globs | `.github/workflows/template-tests.yml:64` |
| Runner has only `GITHUB_TOKEN` | `.github/workflows/template-tests.yml:54-60` |
