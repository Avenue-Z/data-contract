# `contract-gate` — wiring the reconcile/lint gate into consuming-repo CI

**Date:** 2026-07-23
**Status:** Approved for planning
**Owner:** Paul Ramirez / Engineering
**Closes:** Phase 1 "CI wiring" (the middle third of "make it stick" = reconcile + CI wiring +
authoring skill). `reconcile` itself shipped as v0.4.0; this makes it a real, merge-blocking gate
in the repos that consume it.
**Parent specs:**
[`2026-07-16-data-contract-system-design.md`](2026-07-16-data-contract-system-design.md) — §13
(phased rollout; Phase 1), §14 R3 (the gate), §15 (the "value is in the library, the gate runs in
consumers" through-line).
[`2026-07-23-reconcile-registration-completeness-design.md`](2026-07-23-reconcile-registration-completeness-design.md)
— §3 (command surface & exit codes), §5 (gating vs non-gating findings), §7 (R2 drift-test
detection). Authority on gate semantics.

## 1. Purpose

`contract reconcile` and `contract lint` exist as CLI commands, but nothing in CI runs them, so the
gate gates nothing. This spec makes it a merge-blocking gate **in consuming repos** — the repos that
actually have a first-party contract to reconcile against their code.

The key placement fact (parent spec §15): **this repo is the library, not a consumer.** It has no
first-party contract — the only contract/schema YAML here are test fixtures. So "wire reconcile into
CI" is about consuming repos, and the deliverable is a *reusable* mechanism plus the docs a consumer
needs to adopt it.

## 2. Scope

**In scope:**
1. A reusable GitHub Actions workflow (`on: workflow_call`) shipped in *this* repo that a consuming
   repo calls to install its project (which brings in pinned contract-core), then run `lint` +
   `reconcile` and fail CI on any nonzero exit — plus a small, unit-tested `scripts/expand-flags.sh`
   it relies on for the newline→repeated-flags expansion (§4.3.1).
2. Consumer documentation: a new section in [`docs/consuming-repo-setup.md`](../../consuming-repo-setup.md)
   with a copy-pasteable `uses:` snippet, a plain inline alternative, exit-code semantics, and a
   cross-reference to the existing §6 `raw_drift`-marker note.
3. A `CHANGELOG.md` `[Unreleased]` note recording the new consumer-facing surface.

**Out of scope (YAGNI — decided during brainstorming):**
- **No self-test job in this repo's CI.** The incident-#2 exit-code contract is already
  regression-guarded by [`tests/test_cli.py`](../../../tests/test_cli.py) —
  `test_reconcile_clean_exits_zero` (clean → exit 0) and `test_reconcile_incident_2_replay_exits_one`
  (broken → exit 1), which run inside the gating `test` matrix job. A self-test job would either
  duplicate that (by materializing a fixture consumer package that does not exist on disk today) or
  test reusable-workflow plumbing that cannot faithfully run against *unreleased* PR code, since the
  workflow installs contract-core by released tag.
- **No `contract-core-version` workflow input.** The pin lives in the consumer's `pyproject.toml`
  (§1 of the setup guide) — a single source of truth for the *installed version*. A second pin in
  the workflow could silently disagree with the pyproject pin.
  **But note the residual coupling this does NOT close:** the workflow's own `@vX.Y.Z` tag ships the
  hardcoded CLI flag strings (`--contract`/`--schemas`/`--package`/`--tests`), which are themselves a
  version contract with the CLI the consumer installs. Those two tags — the workflow `@tag` and the
  pyproject contract-core pin — live in different files and nothing at runtime forces them equal, yet
  §7 states a 0.x minor bump may break the CLI surface. This coupling is closed by a **hard
  same-tag requirement in the §6 docs** (not the soft cross-reference §3 gives), rather than by a
  runtime assertion: extracting the workflow's own tag to diff against `contract_core.__version__` is
  brittle and still cannot tell a compatible minor from a breaking one. See §6.
- **No skip-lint / skip-reconcile knobs, no deploy-key/SSH auth variant.** Not requested.
- **No changes to [`ci.yml`](../../../.github/workflows/ci.yml) or
  [`ci-aggregate-gate.sh`](../../../scripts/ci-aggregate-gate.sh).** See §5.

## 3. Placement decision (raised and settled)

The reusable workflow lives **here, in `data-contract`**, not in `Avenue-Z/repo-template`.

- The workflow is intrinsically coupled to contract-core's CLI surface and version. It should be
  released in lockstep with the CLI it wraps, and referenced by the **same** `@vX.Y.Z` tag consumers
  already pin contract-core to. This "same tag" is design intent here but a **hard requirement**
  where it's enforceable — in the §6 docs — because nothing at runtime forces it (§2).
- `repo-template`'s workflows get copied into *every* generated repo. A reconcile gate is opt-in —
  only repos that consume contract-core need it — so baking it into the template would ship a dead
  gate into unrelated repos.

## 4. The reusable workflow — `.github/workflows/contract-gate.yml`

`on: workflow_call` **only**. Consequence worth stating: it never runs on this repo's own
`pull_request`/`push`, creates **no new check context here**, and therefore cannot touch or hang the
existing required `ci` aggregate context.

### 4.1 Interface

| Kind | Name | Required | Default | Purpose |
|---|---|---|---|---|
| input | `contract` | yes | — | path to the contract file (shared by lint + reconcile) |
| input | `package` | yes | — | importable package name for `reconcile --package` |
| input | `schemas` | yes | — | schema dirs for `lint --schemas`, **newline-delimited** |
| input | `tests` | yes | — | test paths for `reconcile --tests`, **newline-delimited** |
| input | `python-version` | no | `"3.13"` | matches the library's 3.13 target (`requires-python`) |
| input | `install-command` | no | `pip install .` | installs the consumer project + its pinned contract-core |
| secret | `contract-core-token` | yes | — | read access to the private `Avenue-Z/data-contract` for pip |

**Why the multi-value inputs are strings.** `workflow_call` inputs are typed `string`/`number`/
`boolean` only — no arrays. `--schemas` and `--tests` are both repeatable CLI options, so they arrive
as **newline-delimited** strings, and the job expands each into repeated flags via the tested
`scripts/expand-flags.sh` (§4.3.1) — not an inline loop — because this is the workflow's most
false-red-prone logic and the repo's convention is to put such logic in a unit-tested script.

**Why `install-command` and not a version input.** For `reconcile --package NAME` to work, the
consumer's package must be **importable** in the CI env (reconcile imports it to discover registered
boundaries). That forces installing the consumer's project. `pip install .` does exactly that *and*
pulls contract-core via the consumer's `pyproject.toml` pin — one install, single source of truth.
The input exists only so a consumer who needs extras (`pip install ".[ci]"`) can override the default.

### 4.2 Permissions & pinning

- `permissions: contents: read` at the workflow level — least privilege, matching house style
  ([`ci.yml`](../../../.github/workflows/ci.yml#L10-L11), `sca.yml`, `secret-scan.yml`). The
  reusable workflow's checkout of the caller repo uses the automatic `GITHUB_TOKEN`.
- Actions SHA-pinned to the **same** SHAs `ci.yml` already uses:
  `actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0` and
  `actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6.3.0`.

### 4.3 The single `gate` job

1. **checkout (caller)** — `actions/checkout` checks out the *caller's* repository at the caller's
   ref (default `workflow_call` behavior; uses the auto `GITHUB_TOKEN`, no extra secret). This is the
   workspace `lint`/`reconcile` run against (the caller's contract + package).
2. **checkout (this repo's scripts)** — see §4.3.1: resolve the workflow's own tag from
   `github.workflow_ref` and check out `Avenue-Z/data-contract` at that tag into `./.contract-core/`
   (authed with `contract-core-token`), so the **tested** `scripts/expand-flags.sh` is present on the
   runner. This is what lets step 5/6 run tested logic rather than an inline copy.
3. **setup-python** — `actions/setup-python` with `inputs.python-version`.
4. **configure git auth** — `set -euo pipefail` (deliberately **no `set -x`**, so the token cannot
   leak to logs). Token supplied via `env:` from `secrets.contract-core-token`, never interpolated
   into the script body. **Two hardening rules the prose depends on:**
   - **Guard the empty token explicitly.** `set -u` catches an *unset* variable but not a
     *set-but-empty* one — the classic misconfigured-or-absent-secret case (including any fork PR,
     which receives no secrets — see §6). Without a guard, an empty token writes a broken
     `https://x-access-token:@github.com/…` rewrite and pip fails many steps later with an opaque
     auth error — the very "shows up as a pip clone failure, not as anything contract-shaped" mode
     [`consuming-repo-setup.md`](../../consuming-repo-setup.md#L19) warns about. So the step MUST
     begin: `[ -n "${CONTRACT_CORE_TOKEN:-}" ] || { echo "::error::contract-core-token is empty"; exit 1; }`
     — note the `:-` default: without it a *genuinely unset* var (possible on the §6 inline path,
     where the `env:` mapping isn't guaranteed) trips `set -u` with a raw `unbound variable` *before*
     the clear `::error::` can fire, resurrecting the opaque failure the guard exists to kill. With
     `:-`, the clear message wins on both the reusable-workflow and inline paths.
   - **Scope the rewrite to exactly the one private repo**, not all of `github.com` — otherwise the
     credential rides *every* `github.com` HTTPS clone during install (transitive git deps,
     submodules, a setuptools-scm tag fetch), which contradicts the least-privilege posture of §4.2:
   ```bash
   git config --global \
     url."https://x-access-token:${CONTRACT_CORE_TOKEN}@github.com/Avenue-Z/data-contract".insteadOf \
     "https://github.com/Avenue-Z/data-contract"
   ```
   This authenticates pip's HTTPS clone of the private contract-core dependency and nothing else.
5. **install** — run `inputs.install-command`.
6. **lint** — `set -euo pipefail`; build the repeated `--schemas` flags by piping `inputs.schemas`
   through `./.contract-core/scripts/expand-flags.sh --schemas` (§4.3.1), then run
   `contract lint --contract <contract> <expanded --schemas flags>`.
7. **reconcile** — `set -euo pipefail`; same expansion for `inputs.tests` via `expand-flags.sh
   --tests`, then run `contract reconcile --contract <contract> --package <package> <expanded --tests flags>`.

**The gate is the exit code — nothing parses output.** Per the reconcile design §3: `lint` exits 1
on a malformed contract, malformed schema, or unresolved ref; `reconcile` exits 1 on any gating
finding (categories P/A/B/C/D) and on a malformed contract. A nonzero exit fails the step → fails
the `gate` job → fails the caller's required check. Fail-fast (lint before reconcile), no `|| true`
anywhere.

### 4.3.1 The riskiest logic lives in a tested script, per house convention

The newline→repeated-flags expansion is the one piece of non-trivial, easy-to-botch logic in the
workflow, and its worst failure is a **false red**: a stray trailing empty line becomes
`--schemas ""`, which trips `click.Path(exists=True)` ([`cli.py`](../../../src/contract_core/cli.py#L50))
and fails the gate on a *valid* contract. The repo already has a written rule for exactly this
([`ci-aggregate-gate.sh`](../../../scripts/ci-aggregate-gate.sh#L10): logic goes in a script so
tests exercise the *same* logic the workflow runs — the `check-base-branch.sh` pattern). So:

- **`scripts/expand-flags.sh <flag>`** — reads a newline-delimited value list on **stdin**, **skips
  empty/blank lines** (killing the trailing-newline false-red), and emits the `<flag> <value>` pairs
  in a **NUL-delimited** form the caller consumes with `mapfile -d ''` — NUL-safe so a value can
  contain anything a path legally can. It lives in `data-contract` and is **unit-tested in this
  repo's own CI** (a `tests/`-level test, the same "template-tests exercise the script" posture as
  `ci-aggregate-gate.sh`). Empty input → zero flags → the CLI's own `required=True` reports the
  missing option, not a spurious `""`.
- **Why the step-2 self-checkout exists.** A `workflow_call` workflow's `actions/checkout` gets the
  **caller's** repo, so `data-contract/scripts/` is not on the runner. To run the *tested* script
  (not a drift-prone inline copy — the exact thing the convention forbids), step 2 checks out
  `Avenue-Z/data-contract` at the workflow's **own** resolved tag into `./.contract-core/`. The tag
  is read from `github.workflow_ref` (format `owner/repo/path@ref`; take `${GITHUB_WORKFLOW_REF##*@}`,
  yielding e.g. `refs/tags/v0.5.0`, which `actions/checkout`'s `ref:` accepts), and the private
  checkout is authed with `contract-core-token`. This guarantees the script version matches the
  workflow version — no third pin to drift.

### 4.4 One-time producer-side prerequisite — Actions access sharing (BLOCKER)

`data-contract` is **private**, and GitHub refuses to resolve a reusable workflow from a private repo
into a *different* repo unless that repo explicitly shares its Actions:
**Settings → Actions → General → Access → "Accessible from repositories in the `Avenue-Z`
organization."** This must be enabled **once** on `data-contract` by an org/repo admin. It is not a
code change and cannot be done in this PR — it is an operational step the rollout depends on.

**This is a distinct credential from `contract-core-token`, and conflating them is the trap.**

| Concern | Governed by | Failure symptom if missing |
|---|---|---|
| Resolving `uses: Avenue-Z/data-contract/.github/workflows/contract-gate.yml@tag` | the caller's automatic `GITHUB_TOKEN` **+ the Actions access-sharing setting above** | `error: workflow was not found` before any step runs |
| pip cloning the private contract-core dependency during install | `secrets.contract-core-token` (§4.1) | a `pip` clone failure at install time |

A consumer can provision `contract-core-token` perfectly and still be stopped cold at
workflow-resolution if the access setting is off. So the docs (§6) must name this prerequisite, and
the rollout is not "done" until it is enabled — see §9 criterion #3 and §10.

## 5. Why this does NOT touch this repo's `ci` gate

The existing required context is the non-matrix `ci` aggregate job. A gating job reaches the merge
gate only by being named in **both** the `ci` job's `needs:` list **and**
[`scripts/ci-aggregate-gate.sh`](../../../scripts/ci-aggregate-gate.sh) — a bare `needs:` under
`if: always()` does not gate. We add **no job to `ci.yml`**: the deliverable is an `on: workflow_call`
workflow that never executes on this repo's PRs. So there is no new context to wire, nothing to
extend in the aggregate script, and no risk of hanging the `ci` context PENDING.

## 6. Consumer documentation — new `§7` in `docs/consuming-repo-setup.md`

Inserted after the existing §6 (the `raw_drift` marker note), before the closing italic note, in the
same terse, caveat-forward tone as the rest of the guide. It covers:

- **The Actions-access prerequisite, stated first** — a short "Prerequisite, not a footnote"
  callout (matching §1's tone) that `data-contract` must have Actions access-sharing enabled
  (§4.4), and that a `workflow was not found` error means that setting, **not** the
  `contract-core-token`. This is the operational landmine that otherwise stops a correctly-wired
  consumer cold, so it leads the section.
- **Copy-pasteable `uses:` snippet** — a caller job that invokes
  `Avenue-Z/data-contract/.github/workflows/contract-gate.yml@vX.Y.Z` with the `with:` inputs and an
  explicit `secrets:\n  contract-core-token: ${{ secrets.CONTRACT_CORE_READ_TOKEN }}` block.
  Cross-reference §1 for provisioning that read token (deploy key or `contents: read` PAT).
- **Which tag to pin — a hard requirement, not a suggestion.** The workflow `@tag` **MUST** be the
  **same tag** as the contract-core pin in the consumer's `pyproject.toml`. Stated as an imperative
  with the failure named: the workflow ships hardcoded CLI flags at its tag, the CLI is installed at
  the pyproject tag, and §7 warns a 0.x minor may break that surface — so **a mismatch is silent CLI
  breakage** (an unknown-flag error masquerading as a gate failure), not a warning. And it must be at
  or above the release that first shipped the gate — you cannot reference the workflow at a tag older
  than the one that introduced it (the §5 chicken-and-egg: the release that ships the workflow is the
  first that can call it).
- **Fork-PR assumption, stated in one sentence.** A `pull_request` from a fork receives no secrets
  and no writable token, so `contract-core-token` arrives empty and the gate cannot pass — it fails
  fast with the §4.3 `::error::contract-core-token is empty` guard (a clear message, not an opaque
  pip error). This gate assumes the repo's same-repo private branch flow (the org norm); fork PRs are
  out of its scope by construction.
- **Plain inline alternative** — a hand-rolled job (checkout → setup-python 3.13 → install → run the
  two commands) for a repo that would rather see the mechanics than call the reusable workflow. This
  alternative also side-steps the Actions-access prerequisite entirely (nothing to resolve
  cross-repo), which is a legitimate reason to prefer it.
- **Exit-code semantics** — the "nonzero exit *is* the gate, nothing parses output" contract, with
  the category list from the reconcile design.
- **Cross-reference to §6** — register the `raw_drift` marker in the consumer's `pyproject.toml` so
  `pytest --strict-markers` does not reject it at collection; reconcile itself reads the marker via
  AST and needs no registration.
- A note that `schemas` and `tests` are **newline-delimited** in the `with:` block.

## 7. CHANGELOG

A short `[Unreleased]` entry under a `### Added` (or repo-convention) heading: a reusable
`contract-gate` CI workflow plus the consumer wiring docs. Rationale: the workflow is a **new
shipped, consumer-facing surface** — consumers reference it by the same tag they pin contract-core
to, so which release first carries it is information a consumer wiring `@vX.Y.Z` needs. This is a
CI/docs change, not a library-API change, so no code-behavior note is required.

## 8. Testing & verification

- **actionlint** (or equivalent) on the new workflow — must pass. Install it if absent; do not claim
  a pass without seeing the output.
- **`scripts/expand-flags.sh` gets a unit test in this repo's CI** (§4.3.1) — the one piece of
  workflow logic that *can* be tested without a runner is, following the `ci-aggregate-gate.sh`
  convention. Cases: multi-line input → repeated flags; **trailing/blank lines skipped** (the
  false-red guard); empty input → zero flags; a value with an awkward character survives the
  NUL-delimited round-trip. This test runs in the gating `test` job, so the expansion is **proven
  before a consumer's PR is the test case** — it is *not* in the residual-risk bucket below.
- **The incident-#2 exit-code contract** is already covered by `tests/test_cli.py` inside the gating
  `test` job; the existing suite must still pass (`ruff check .`, `mypy`, `pytest -q`). The only new
  Python-adjacent artifact is the shell script above and its test.
- **Accepted residual risk — stated, not hidden.** The expansion logic is now unit-tested (above),
  so it is *out* of this bucket. What remains: actionlint validates the workflow's *syntax*, not that
  the step **wiring** runs end-to-end — the self-checkout + ref-resolution, install, git-auth, and
  exit-code propagation to the gate are verified by **inspection**, not CI, because the workflow
  installs contract-core by released tag and so cannot be faithfully exercised against unreleased PR
  code (§2). So the **plumbing half of §9 criterion #1, and criterion #3, are first really proven by a
  consumer wiring it post-release** — the same posture as the existing §5 by-hand smoke test.
  Treat that plumbing as inspection-verified, not CI-proven.
- **Branch flow:** work on a `ci/*` branch, open the PR against `dev`. The chain
  `ci/* → dev → staging → main` is enforced by
  [`guard-base-branch.yml`](../../../.github/workflows/guard-base-branch.yml) /
  [`scripts/check-base-branch.sh`](../../../scripts/check-base-branch.sh) — **not** by code
  ownership. There is no `CODEOWNERS` file, and [`SECURITY.md`](../../../SECURITY.md) states plainly
  that `.github/CODEOWNERS` (were it present) "forces nothing" here: with
  `require_code_owner_review: false` and zero required approvals in the ruleset, code ownership only
  auto-*requests* a reviewer, it does not gate. So do not lean on code ownership as a control — the
  base-branch guard is the real one.

## 9. Success criteria

1. `.github/workflows/contract-gate.yml` exists, is valid per actionlint, is `on: workflow_call`
   only, pins actions by SHA, sets `permissions: contents: read`, guards an empty token, scopes the
   `insteadOf` rewrite to the one private repo, expands flags via the tested `scripts/expand-flags.sh`
   (not an inline loop), and runs `lint` then `reconcile` failing on any nonzero exit. *actionlint
   proves the shape and the flag-expansion is unit-tested (§8); the remaining step **wiring** (steps
   run, exit codes propagate) is verified by inspection here and first-consumer adoption — see §8's
   residual-risk note.*
2. `scripts/expand-flags.sh` exists and its unit test passes in the gating `test` job — multi-line →
   repeated flags, blank/trailing lines skipped, empty input → zero flags, awkward value survives.
3. A consumer can copy the `uses:` snippet from the docs and have a working merge-blocking gate,
   given (a) the read token from §1 **and** (b) the one-time Actions access-sharing setting on
   `data-contract` from §4.4/§10. Without (b), workflow resolution fails before any step runs, so
   this criterion is *not* satisfied by the PR alone — it requires the §10 operational step.
4. The existing `ci` required context and the matrix/aggregate split are unchanged and unbroken.
5. `CHANGELOG.md` records the new surface under `[Unreleased]`.

## 10. Rollout — the operational step outside this PR

This PR ships code and docs; it does not, by itself, make the gate callable. Before or at the release
that first carries the workflow, an `Avenue-Z` admin must enable **Settings → Actions → General →
Access → "Accessible from repositories in the organization"** on `data-contract` (§4.4). This is a
one-time repo setting, not a code change, and it is the difference between "the workflow exists" and
"a consumer can call it." The plan must surface this as an explicit hand-off item, not bury it.
