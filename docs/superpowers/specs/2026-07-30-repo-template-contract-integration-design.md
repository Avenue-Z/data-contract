# Integrating data contracts into `Avenue-Z/repo-template`

**Status:** ready to execute once `contract init` ships. Not blocked on specification.

**Depends on:** `docs/superpowers/specs/2026-07-30-contract-init-design.md` (branch
`docs/contract-init-spec` @ `82f8399`, status *Draft — in review*), and on the `data-contract`
visibility decision (§1.3).

**The design in one sentence:** `repo-template` ships **documentation and one inert beacon, and
scaffolds nothing**. `contract init` owns the entire scaffold, run by the adopter in the finished
repo once the package has its real name.

---

## 1. Dependencies

### 1.1 `contract init` — specified, not yet built

An earlier revision of this document blocked on `contract init` being unspecified. That is no longer
true: the design exists and answers every question this plan needed.

| Question | Answer |
| --- | --- |
| Which artifacts it emits | init §4 — `contract.yaml`, three schemas, `boundaries.py`, drift test, `.github/workflows/contract.yml`, a `pyproject.toml` edit. Schema **content** stays placeholder (§6.1). |
| Net-new, retrofit, or both | init §1.1 — **retrofit only.** It requires a `pyproject.toml` with `[project].name` and that package's `__init__.py` on disk, and refuses otherwise with no degraded mode. |
| Behaviour on an existing `contract.yaml` | init §5 — the file becomes the source of truth; gap-fill only, never overwrite, no `--force`. |
| Exit codes / non-interactive | init §2.1 — "No prompts, ever." Exit 0 whether it wrote eight files or none. |
| `pyproject.toml` edits | init §8 — the `raw_drift` marker, behind a guard ladder. init §4.7 — the `contract-core` **dependency pin is printed, not written**. |
| CI workflow and tag | init §4.5 — emitted with `@v{contract_core.__version__}` substituted for the placeholder. |

**What remains open is "shipped," not "specified."** The command is unbuilt and its design is still in
review. This plan is therefore executable-when-unblocked, and its §6 test suite cannot run until the
command exists.

### 1.2 P1 — the gate stops requiring a read token

init §12 sequences a prerequisite ahead of itself: `contract-gate.yml` drops the mandatory
`contract-core-token`, and `consuming-repo-setup.md` §1/§7 lose the "private, so your CI needs read
access" prerequisite. Everything this plan writes assumes P1 has landed. If it has not, the
documentation in §5 would teach a token requirement that is about to disappear.

### 1.3 The visibility decision — now coupled across two specs

`Avenue-Z/data-contract` is currently **public** (`gh repo view` → `"visibility": "PUBLIC"`). Per the
brief, that state is under review.

This is no longer an independent question on the template's side. init §12 P1 *bets on public* — it
retires the token on exactly that ground — and init §10 adds a test asserting the generated workflow
contains **no `secrets:` block**. So a flip to private reverts P1, inverts that test, and puts a
per-repo secret back into the adoption path this plan documents as tokenless.

The template's own exposure is now small, because it scaffolds nothing: the change would be to a
paragraph of documentation, not to a generated file. That is a direct benefit of dropping the flag
(§3). But the paragraph is wrong until the decision lands, so **do not write §5.2's prose until it
does.**

Separately and independently fixable: `docs/consuming-repo-setup.md` §1 and §7 assert
"`data-contract` is private" as present-tense fact. That is already wrong today. P1 removes those
lines anyway; if P1 slips, they should be corrected on their own.

---

## 2. What `repo-template` actually changes

Three documentation surfaces and one inert file. No script changes.

| Path | Action |
| --- | --- |
| `templates/python/.github/workflows/contract.yml.example` | **added** — a discovery beacon; comments only (§5.1) |
| `README.repo.tmpl` | **changed** — a `## Data contracts` section (§5.2) |
| `CLAUDE.md` | **changed** — one durable workflow rule (§5.3) |
| `docs/ADOPTION.md` | **changed** — a subsection in the §1 net-new track (§5.4) |
| `template-tests/test_contracts_docs.sh` | **added** — new suite (§6) |
| `scripts/init-repo.sh` | **unchanged** (§5.5) |

---

## 3. Why there is no `--contracts` flag

The earlier decision was a middle path: docs always, real files on `--contracts`. Reading the init
design killed the scaffolding half. Four reasons, three of them discovered in that spec.

**3.1 It would scaffold against the placeholder package.** init §1.1's entry state is satisfied
inside `init-repo.sh` — `templates/python` ships `name = "app"` (`pyproject.toml:6`) and
`src/app/__init__.py` — so `contract init` would run, and wire everything to `app`. `boundaries.py`
would land at `src/app/boundaries.py`, and the gate's `package:` input would be `app`. Every adopter
renames that package; this repo did precisely that (`docs/superpowers/plans/2026-07-16-data-contract-phase-0.md`
Task 1: "delete the `app` placeholder"). The flag would produce wiring that breaks on the adopter's
first real act.

**3.2 It would make a brand-new repo red on its first push.** init §4.6 emits a `drift` job over
§6.2's deliberate `pytest.fail("GENERATED PLACEHOLDER — assert the adapter REJECTS a drifted
payload")`. That red is correct *inside `contract init`'s frame* — the scaffold is incomplete by
construction and the red names the one remaining action. But `ensure_branches`
(`init-repo.sh:254-267`) pushes `dev`, `staging` and `main` immediately, so `--contracts` would hand
someone a repo that is red before they have written a line, against a template whose pitch is "one
click plus one script."

**3.3 It would drag pip into a bash script.** init §4.5 needs `contract_core.__version__` to write the
workflow tag, so the flag requires contract-core installed at init time. `init-repo.sh` today needs
`git`, `gh` and `jq`; `template-tests.yml:34-40` asserts exactly that tool list. And init §13 carries
the matching risk: run from an unreleased checkout, it writes a tag that does not exist.

**3.4 The flag is offered at the wrong moment anyway.** `init-repo.sh` runs once, on the day the repo
is created, before anyone knows whether it will read external data. The first vendor export lands
weeks later. `contract init` is designed for exactly that later moment — init §1.1's entry state and
§5's gap-fill re-run describe a command meant to be run in a repo that already exists and already has
a name. Leaving the scaffold to it is not a compromise; it is putting the work where its own design
puts it.

**What drops out with the flag:** the node/next refusal logic (nothing to refuse), the
`requires-python`/matrix rewrites, the `Dockerfile` base-image bump those rewrites would have forced,
and any need for `template-tests` to install contract-core. The remaining change is documentation.

---

## 4. `node` and `next` get nothing — stated out loud

There is no path for a node or next repo that needs a data contract, and none is proposed here.

`contract-core` is Python: pandera and pandas do the validation, the artifact is a Python package,
`reconcile --package` (`cli.py:101`) requires an **importable Python package** to scan for registered
boundaries, and `contract-gate.yml` sets up Python and runs the `contract` console script. There is no
TypeScript port and none planned. There is not even a partial path — the CI gate alone is unusable
without a Python package to point `--package` at.

What such a repo does instead is a real question with a real answer: move the external read into a
Python job that owns the contract, and let the node/next app consume already-validated data. That is
an architecture decision for the team that hits it, not something `repo-template` can scaffold. §5.2's
prose says so in one sentence, so the reader who needs it gets the answer rather than silence.

Because nothing is scaffolded, there is no flag to refuse and no failure mode to guard. The only
obligation is that the beacon file (§5.1) ships to python repos and **not** to node/next ones, which
falls out of its living under `templates/python/` and is asserted in §6.

---

## 5. Exact changes

### 5.1 Added — `templates/python/.github/workflows/contract.yml.example`

**Why `.example` and not `.yml`.** GitHub parses every file under `.github/workflows/`. A file with no
valid `on:` trigger surfaces as a workflow error in the Actions tab of every generated repo. A
commented-out `contract.yml` is therefore not an option; the extension must not be `.yml` or `.yaml`.

**Why it carries no tag and no `uses:` line.** `contract init` writes the real workflow with the
correct tag (init §4.5). A second copy carrying a literal `@vX.Y.Z` would be a competing source of
truth that goes stale — the exact rot `Avenue-Z/data-contract` PR #58 fixed by removing a literal tag
from the teaching template. There is also an audit gap: `template-tests/test_action_pins.sh:40` globs
`templates/*/.github/workflows/*.yml`, so a `.example` escapes the SHA-pin check. A file with no
`uses:` line closes that gap by construction rather than by exception.

So the beacon is a pointer, not a template:

```
# This repo has NO data-contract wiring. This file is a signpost, not a workflow — the
# .example suffix is load-bearing (GitHub parses every .yml under .github/workflows/, and a
# file with no `on:` trigger reports as a workflow error).
#
# If this repo reads external data — a vendor API, an MCP tool, a CSV drop, LLM output — it
# should have a data contract: one artifact giving you runtime validation (did the vendor
# change the data under us?) and static reconciliation (did the code drift from the design?).
#
# DO NOT hand-write the workflow, and do not copy a version tag into this file. Run:
#
#     pip install "contract-core @ git+https://github.com/Avenue-Z/data-contract.git@<tag>"
#     contract init --system <name> --platform <platform> --source <api|mcp|llm|file>
#
# That writes .github/workflows/contract.yml with the correct pinned tag, plus contract.yaml,
# the schemas, the boundary wiring and a drift test. Delete this file once it has.
#
# Read first: Avenue-Z/data-contract docs/consuming-repo-setup.md, and the
# `authoring-data-contracts` Claude Code skill.
#
# PYTHON ONLY. contract-core is pandera/pandas and the gate needs an importable Python
# package. There is no node/next path — see README.md.
#
# NOTE: contract-core requires Python 3.13. This template's stack ships
# requires-python = ">=3.11" and a 3.11/3.12/3.13 CI matrix; adopting contracts means
# narrowing both to 3.13. See README.md.
```

### 5.2 Changed — `README.repo.tmpl`

A new `## Data contracts` section after `## Docs`. Stack-agnostic placement matches existing
convention: `README.repo.tmpl:72` documents `link-vercel.sh` as "(`next` stack)" in a file that also
ships to python repos.

> ## Data contracts
>
> **Python only.** If this repo reads external data — a vendor API, an MCP tool, a CSV drop, LLM
> output — or emits a deliverable, it should declare a data contract. One artifact buys two checks:
> runtime validation at the boundary, and static reconciliation that the code still matches the
> declared design.
>
> Do not hand-author it. From the repo root:
>
>     pip install "contract-core @ git+https://github.com/Avenue-Z/data-contract.git@<tag>"
>     contract init --system <name> --platform <platform> --source <api|mcp|llm|file>
>
> `contract init` writes `contract.yaml`, the schema tree, the boundary wiring, a drift test and the
> CI workflow. It is a **retrofit** command — run it once this repo's package has its real name, not
> on day one. Re-running it fills gaps and never overwrites.
>
> Two things it deliberately leaves you: the schema **fields** are `REPLACE_ME_` placeholders until
> you author them from the real columns, and the generated drift test fails on purpose until you
> write the assertion. Both are named in its output.
>
> **`contract-core` requires Python 3.13.** This repo ships `requires-python = ">=3.11"` and a
> 3.11/3.12/3.13 CI matrix; adopting contracts means narrowing both to 3.13 — otherwise the pin fails
> to install on the two older legs.
>
> **There is no node/next path.** `contract-core` is pandera/pandas and the CI gate needs an
> importable Python package. A non-Python repo that needs a contract should move the external read
> into a Python job that owns it, and consume already-validated data.
>
> Reference: `Avenue-Z/data-contract` `docs/consuming-repo-setup.md`, and the
> `authoring-data-contracts` Claude Code skill.

### 5.3 Changed — `CLAUDE.md`

One item appended to `## Workflow rules` (currently items 1–4, `CLAUDE.md:28-36`). This file is
explicitly durable-context-only, which a contracts rule satisfies:

> 5. **Python repos:** if this repo reads external data or emits a deliverable, it needs a data
>    contract. Do not hand-author one — run `contract init` (see `README.md`). `contract lint` and
>    `contract reconcile` are the gate; a boundary starts at `mode: observe` and is promoted only
>    once `contract events` reports it clean.

### 5.4 Changed — `docs/ADOPTION.md`

`docs/ADOPTION.md:11-66` is the §1 net-new track. Contracts are **not** a repo-creation step (§3.4),
so this is a labelled subsection after step 6 and before the "Claude Code skills" block — deliberately
not a numbered step, because numbering it would imply a day-one action.

> **If this repo will read external data — later, not now.**
>
> A repo that reads a vendor API, an MCP tool, a CSV drop or LLM output should declare a data
> contract. This is **not** an init-time step and there is no `init-repo.sh` flag for it, on purpose:
> on the day you create a repo you usually do not yet know whether it reads external data, and the
> scaffolder needs your package to have its real name — not the `app` placeholder the template ships.
>
> When that day comes, from the repo root:
>
>     pip install "contract-core @ git+https://github.com/Avenue-Z/data-contract.git@<tag>"
>     contract init --system <name> --platform <platform> --source <api|mcp|llm|file>
>
> It writes `contract.yaml`, the schema tree, `boundaries.py`, a drift test and the CI workflow, and
> registers the `raw_drift` pytest marker. It prints — rather than writes — the `contract-core`
> dependency pin; add that line to `pyproject.toml` yourself.
>
> **Python only.** `contract-core` is pandera/pandas and the gate needs an importable Python package.
> There is no node or next path; a non-Python repo that needs a contract should move the external read
> into a Python job that owns it.
>
> **Adopting contracts makes this a 3.13 repo.** `contract-core` declares `requires-python = ">=3.13"`
> while the python stack ships `>=3.11` and a 3.11/3.12/3.13 matrix. Narrow `requires-python`,
> `[tool.ruff] target-version`, `[tool.mypy] python_version`, the `ci.yml` matrix **and the
> `Dockerfile` base image** together — leaving the Dockerfile behind reproduces
> Avenue-Z/data-contract#53.
>
> Expect a red check on the first run. The generated drift test fails by design until you write its
> assertion, and the generated schema fields are `REPLACE_ME_` placeholders until you author them from
> the real export. That red is the remaining work, not a broken scaffold.
>
> Full detail: `Avenue-Z/data-contract` `docs/consuming-repo-setup.md`; the
> `authoring-data-contracts` Claude Code skill carries the authoring workflow.

`docs/ADOPTION.md` is deleted by `init-repo.sh:376` and does not ship, which is correct — it is the
adoption playbook, and the equivalent pointer for the generated repo is §5.2's README section.

The template's own front-door `README.md` is **out of scope**: per the brief, ADOPTION.md §1 is the
surface a new adopter reads.

### 5.5 `scripts/init-repo.sh` — no diff

The requested "diff shape" is empty, and that is the result rather than an omission.

The beacon lives under `templates/python/`, so `cp -R "templates/${STACK}/." .` (`init-repo.sh:287`)
copies it for python and not for node or next. `README.repo.tmpl` is already swapped to `README.md`
at `init-repo.sh:373`. `CLAUDE.md` already ships untouched. `docs/ADOPTION.md` is already deleted at
`init-repo.sh:376`. Every surface this plan touches is carried by machinery that exists.

**Rejected:** stripping the README's contracts section for node/next with a `sed` on the generated
file. It adds a mutation to a script whose every branch is currently load-bearing and hand-verified,
to remove four lines that correctly tell a node/next reader why there is no path for them (§4). The
`link-vercel.sh` "(`next` stack)" precedent at `README.repo.tmpl:72` already ships stack-specific
prose to every stack.

---

## 6. `template-tests/` coverage

New file `template-tests/test_contracts_docs.sh`. `.github/workflows/template-tests.yml:64` globs
`template-tests/test_*.sh`, so no workflow edit is needed.

### 6.1 What this suite can prove

Fixture: the clone-and-init pattern from `test_init_repo.sh:6-14` — `git clone` the repo root into a
`mktemp -d`, `git checkout -b dev`, run `./scripts/init-repo.sh <stack> --no-push`.

```bash
# --- python: the beacon ships, inert ---
assert_file    "beacon copied into the python repo" .github/workflows/contract.yml.example
assert_no_file "no LIVE contract workflow was scaffolded" .github/workflows/contract.yml
beacon="$(cat .github/workflows/contract.yml.example)"
# The .example suffix is load-bearing: a .yml with no `on:` trigger reports as a workflow
# error in the Actions tab of every generated repo.
assert_nomatch "beacon declares no workflow triggers" '^on:'    "$beacon"
assert_nomatch "beacon declares no jobs"              '^jobs:'  "$beacon"
# test_action_pins.sh globs templates/*/.github/workflows/*.yml, so a .example escapes the
# SHA-pin audit. No `uses:` line means there is nothing for it to have missed.
assert_nomatch "beacon references no actions (closes the pin-audit gap)" 'uses:' "$beacon"
# A literal tag here would be a second source of truth that goes stale — the rot
# Avenue-Z/data-contract PR #58 removed from the teaching template.
assert_nomatch "beacon pins no version tag" '@v[0-9]' "$beacon"
assert_match   "beacon names contract init as the way in" 'contract init' "$beacon"

# --- python: the README pointer survived init ---
readme="$(cat README.md)"
assert_match "README documents data contracts"        '## Data contracts' "$readme"
assert_match "README routes to contract init"         'contract init'     "$readme"
assert_match "README states the python-only limit"    'Python only'       "$readme"
assert_match "README names the 3.13 requirement"      '3\.13'             "$readme"
assert_match "CLAUDE.md carries the contracts rule"   'contract init'     "$(cat CLAUDE.md)"

# --- node: the beacon must NOT ship ---
#   (re-clone, init as node)
assert_no_file "node repo carries no contract beacon" .github/workflows/contract.yml.example
assert_no_file "node repo carries no contract workflow" .github/workflows/contract.yml
# The README pointer DOES ship to node — it is how a node reader learns there is no path.
assert_match "node README explains there is no node path" 'no node/next path' "$(cat README.md)"

# --- the docs the adopter needs must not have shipped, and must exist upstream ---
assert_no_file "adoption playbook still stripped" docs/ADOPTION.md
```

Plus one assertion in the template's own tree, not a generated one — the beacon must stay python-only
at source:

```bash
assert_no_file "beacon is not in the node stack" templates/node/.github/workflows/contract.yml.example
assert_no_file "beacon is not in the next stack" templates/next/.github/workflows/contract.yml.example
```

### 6.2 What it cannot prove — and where that proof lives

The original brief asked for coverage proving **"a scaffolded repo's contract wiring actually
lints."** Under this design `repo-template` scaffolds no contract wiring, so that test cannot exist
here. Saying otherwise would be the failure the template is built to prevent: a suite that looks like
it verifies something it does not touch.

That proof exists, and it belongs to `contract-core`. init §1.1 states the success criterion —
"`contract init` into a repo in that state produces a tree where `contract lint` and `contract
reconcile` both exit 0" — and init §10 is the test: scaffold each archetype into a `tmp_path` repo,
subprocess the console script, assert both exit 0, with `PYTHONPATH` set to the directory containing
the package (init §10.1).

That is the right home. The scaffolder owns proving its output lints; the template owns proving it
routes people to the scaffolder and ships nothing live. Duplicating init §10 in a bash suite would
mean installing contract-core on the `template-tests` runner — which today receives only a
repo-scoped `GITHUB_TOKEN` (`template-tests.yml:54-60`) — to re-prove another repo's guarantee.

**Residual gap, named rather than papered over:** nothing in either suite proves the *documented
commands* work end to end — that following §5.4 verbatim in a template-derived repo yields a green
`lint`. That is a docs-accuracy risk, and the honest mitigation is the one-off manual check in §7.2,
not a fake automated assertion.

---

## 7. Two cross-repo findings

### 7.1 `contract init` in a template-derived repo produces a CI failure neither spec owns

`templates/python/pyproject.toml:9` declares `requires-python = ">=3.11"` and
`templates/python/.github/workflows/ci.yml:25` runs a `["3.11", "3.12", "3.13"]` matrix.
`contract-core` declares `requires-python = ">=3.13"` (`pyproject.toml:9`).

init §4.7 prints the dependency pin for the adopter to add by hand. The moment they add it, the
generated repo's `ci` check fails on the 3.11 and 3.12 legs at `pip install -e ".[dev]"`
(`ci.yml:31`) — before a single test runs. Nothing in `contract init` warns about this, because
nothing in it knows the repo came from this template; and until this plan lands, nothing in
`repo-template` mentions contracts at all.

§5.2 and §5.4 close it from the template side. **It is worth closing from the other side too:** since
`init` already reads `pyproject.toml` (init §7, §8), it could check `requires-python` and warn when
the declared floor is below 3.13. Recorded here as feedback for the init spec, not as a requirement
of this plan.

**Why an optional extra is not the answer** — recorded because it is the obvious alternative. Pinning
contract-core under a `contracts` extra keeps the matrix green, and that green is a lie:
`consuming-repo-setup.md` §4's consumer pattern catches `ImportError` and substitutes a no-op runtime
(necessarily — the library cannot catch its own absent import), so the 3.11 and 3.12 legs would run
the suite with every boundary decorator silently a pass-through. Two of three legs green over
unexercised wiring is precisely "a failure to verify is not a verified pass."

### 7.2 The one-off manual verification

Once `contract init` ships and this plan lands, run §5.4's documented sequence verbatim, once, in a
freshly scaffolded template repo, and confirm `contract lint` and `contract reconcile` exit 0. This is
the same class of check as `consuming-repo-setup.md` §5's per-release smoke test: it covers the seam
between two repos that neither repo's suite can reach. Skipping it means the documented adoption path
is unverified prose.

---

## 8. Rejected alternatives

| Alternative | Why not |
| --- | --- |
| `--contracts` flag on `init-repo.sh` | §3 — wires to the `app` placeholder, reds a new repo on first push, adds pip to the toolchain, and is offered before the answer is known. |
| Default-on contract skeleton for every python repo | An unwired `contract.yaml` is an inert control, the failure `resolve_codeowners` (`init-repo.sh:77-216`) exists to prevent. It also declares boundaries no decorator registers, so turning the gate on later yields category-A/B findings against a contract that was never real. |
| Commented-out `contract.yml` (not `.example`) | GitHub parses every file under `.github/workflows/`; a missing `on:` trigger reports as a workflow error in every generated repo. |
| Ship a full gate-call example with a pinned tag | A competing source of truth that goes stale, and it escapes `test_action_pins.sh:40`'s SHA-pin glob. |
| No beacon at all — README pointer only | Defensible, and close to being right. The beacon earns its place only as a zero-maintenance signpost in the directory where someone looks when they think "where would the contract check live?" It carries no tag, no `uses:`, and nothing that can rot. |
| `sed` the contracts section out of node/next READMEs | §5.5 — a mutation to a hand-verified script to remove prose that correctly answers a node reader's question. |
| Reproduce init §10's lint/reconcile test in `template-tests/` | §6.2 — requires installing contract-core on a runner holding only a repo-scoped `GITHUB_TOKEN`, to re-prove another repo's guarantee. |

---

## 9. Execution order

1. **Wait on** `contract init` leaving review, P1 landing (§1.2), and the visibility decision (§1.3).
2. `docs/*` branch off `dev` in `Avenue-Z/repo-template`. Add the beacon; edit `README.repo.tmpl`,
   `CLAUDE.md`, `docs/ADOPTION.md`; add `template-tests/test_contracts_docs.sh`.
3. Run the full suite locally — `for t in template-tests/test_*.sh; do bash "$t"; done` — and read the
   output. Existing suites must stay green; `test_init_repo.sh`'s zero-cruft assertions are the ones
   most likely to be disturbed.
4. PR into `dev`. Branch flow is `docs/* → dev → staging → main`; never push to `main`.
5. After merge, do §7.2's one-off manual verification and record the result.

---

## Appendix — evidence index

Claims below were verified directly. `repo-template` citations are against `6df4f21`; `data-contract`
citations against `dev` (`53c77a4`) except the init spec, which is `docs/contract-init-spec` @
`82f8399`.

| Claim | Source |
| --- | --- |
| CLI has `lint`/`reconcile`/`events`, no `init` | `src/contract_core/cli.py:43-169` |
| `reconcile` needs an importable package | `src/contract_core/cli.py:101` |
| `contract-core` requires 3.13 | `pyproject.toml:9` |
| init entry state / success criterion | init spec §1.1 |
| init is retrofit, gap-fill, no `--force` | init spec §5 |
| init emits the workflow with `@v{__version__}` | init spec §4.5 |
| init prints, not writes, the dependency pin | init spec §4.7 |
| init's drift job is red by design | init spec §4.6, §6.2 |
| init §10 is the lint/reconcile proof | init spec §1.1, §10, §10.1 |
| P1 retires the token, bets on public | init spec §12 |
| init spec status is *Draft — in review* | init spec line 4 (commit and working tree) |
| `data-contract` is public | `gh repo view Avenue-Z/data-contract --json visibility` → `PUBLIC` |
| Docs still assert it is private | `docs/consuming-repo-setup.md` §1, §7 |
| python stack is `>=3.11`, name `app` | `templates/python/pyproject.toml:6,9` |
| python CI matrix is 3.11–3.13 | `templates/python/.github/workflows/ci.yml:19-34` |
| Install step that breaks on the pin | `templates/python/.github/workflows/ci.yml:31` |
| Stack copy is a whole-directory `cp -R` | `scripts/init-repo.sh:287` |
| README seed swap; ADOPTION.md deleted | `scripts/init-repo.sh:373,376` |
| Branches pushed immediately on init | `scripts/init-repo.sh:254-267` |
| Inert-control posture | `scripts/init-repo.sh:77-216` |
| Stack-specific prose already ships to all stacks | `README.repo.tmpl:72` |
| `CLAUDE.md` workflow rules are items 1–4 | `CLAUDE.md:28-36` |
| Pin audit globs `*.yml` only | `template-tests/test_action_pins.sh:40` |
| Clone-and-init fixture pattern | `template-tests/test_init_repo.sh:6-14` |
| Suite auto-globs `test_*.sh` | `.github/workflows/template-tests.yml:64` |
| Runner tool list; repo-scoped token only | `.github/workflows/template-tests.yml:34-40,54-60` |
