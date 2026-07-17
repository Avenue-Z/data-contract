# Avenue-Z Repo Template — Design

**Date:** 2026-07-13
**Status:** Approved for planning
**Author:** Paul Ramirez (with Claude)

## Problem

Every new Avenue-Z repo is started from scratch. A survey of six LTS repos
(`avenue-z-reporting-v2`, `aivx-reports`, `ad-spend-pacing`, `claude-marketplace`,
`drive-api-client`, `glean-chat-api-client`) shows real conventions have emerged, but
they are unwritten and unevenly applied:

- `docs/superpowers/{plans,specs}/` exists in 5 of 6 repos — the strongest de facto convention.
- Branch naming (`feat/`, `fix/`, `docs/`, `chore/`, `ci/`) is obeyed by every repo but
  written down in only one (`aivx-reports/CLAUDE.md` §8).
- The three Python repos are near-copies of each other: `src/` layout, `pyproject.toml`,
  pytest with `pythonpath=["src"]`, `tests/conftest.py` + `fakes.py`.
- Every `.gitignore` blocks credential JSON — but each blocks a *different subset*.

And there are real gaps:

- **CI exists in 1 of 6 repos** (`drive-api-client/.github/workflows/ci.yml`).
- **Zero repos lint.** No ruff, black, mypy, eslint config, or pre-commit anywhere in the org.
- **Zero repos** have LICENSE, CONTRIBUTING.md, SECURITY.md, a PR template, CODEOWNERS, or dependabot.
- **`.env.example` exists in 2 of 6.** Elsewhere env vars are documented in 500-line CLAUDE.md prose.
- **`glean-chat-api-client/.gitignore` ignores neither `.env` nor `.env.local`**, while a live
  `.env.local` sits in its working tree. `claude-marketplace` has no `.gitignore` at all.
- **No repo has branch protection** — because, as established below, it has not been possible.

## Goal

A GitHub template repository, `Avenue-Z/repo-template`, that a new project is created from in
one click plus one script, and that starts life with the org's conventions already in place.

## Key constraint discovered: the GitHub plan

Avenue-Z is on the **GitHub Free** plan (8 seats, 60 private repos). Verified against the API:

| Call | Result |
|---|---|
| `GET repos/Avenue-Z/canary-data-contracts/branches/main/protection` (private) | `403 Upgrade to GitHub Pro or make this repository public to enable this feature.` |
| `GET repos/Avenue-Z/canary-data-contracts/rulesets` (private) | `403` — same |
| `GET repos/Avenue-Z/avenue-z-reporting-v2/branches/main/protection` (public) | `404 Branch not protected` — feature available, simply unused |

Consequences:

1. **Branch protection and rulesets are unavailable on private repos on Free** — for everyone,
   including org owners. This is why no repo in the org has protection today.
2. **Branch protection is governed by the Admin *repository role*, not org ownership.** GitHub's
   repository-roles table lists "Manage branch protection rules and repository rulesets" under
   Admin only (not Read/Triage/Write/Maintain). Permissions were never the blocker; the plan is.
   *Not yet verified:* whether a repo creator in this org actually receives Admin, and how that
   interacts with Team-plan org rulesets (an org ruleset deliberately outranks a repo admin).
   Confirm on Team before writing any promise about non-owner capability into `CONTRIBUTING.md`.
3. **Org-level rulesets require GitHub Team.** Only they deliver "every repo shares the same
   rules automatically." Public-repo protection on Free is per-repo and must be applied each time.

### Decision

- `Avenue-Z/repo-template` itself is **public** (it contains no secrets by construction) and gets
  real branch protection, which proves the config works.
- Repos created from it stay **private** by default and rely on the layered enforcement below.
- **Existing private repos are not touched.** Making them public would expose full git history.
  `ad-spend-pacing` has `sa-key.json` and `client_secrets.json` in its working tree;
  `glean-chat-api-client`'s `.gitignore` does not block `.env*`; `zpress` is marked CONFIDENTIAL.
  Any future move to public requires a git-history secret audit (gitleaks/trufflehog) and
  credential rotation first. Out of scope here.
- The org ruleset is **committed as code but not applied**, ready for the day the org moves to Team.

## Branch model

```
feat/* | fix/* | docs/* | chore/* | ci/*  →  dev  →  staging  →  main
```

- **`main`** — production. Receives PRs from `staging` only.
- **`staging`** — pre-prod soak / QA. Receives PRs from `dev` only.
- **`dev`** — integration branch, and the **default branch**, so work branches and PRs target it
  without anyone having to think about it.

Note: GitHub's "Use this template" copies **only the default branch** unless "Include all
branches" is ticked, and repos created via the API omit them unless explicitly requested.
Therefore `scripts/init-repo.sh` creates and pushes `staging` and `main` itself rather than
trusting the checkbox. This makes the init script load-bearing, not a convenience.

## Enforcement layers

| Layer | Enforces | Limit |
|---|---|---|
| `.github/workflows/guard-base-branch.yml` | The full base-branch matrix (below) | Cannot stop a direct `git push origin main`. **And a PR that edits the workflow file itself can pass its own guard** — see below |
| `.pre-commit-config.yaml` + `secret-scan` CI job | gitleaks — no credential reaches a commit or a PR | Hook is local; the CI job is the enforced one |
| `CONTRIBUTING.md` + `CLAUDE.md` Workflow Rules | The flow, commit conventions, the `git fetch --all --prune` + `git log origin/dev..HEAD` sync check | Convention only |
| `.github/rulesets/repo-ruleset.json` | Per-repo protection, incl. required checks | Needs a public repo, or Team |
| `.github/rulesets/org-ruleset.json` | Org-wide, inherited by every repo: no deletion, no force-push, PR required | Needs Team. **Carries no required status checks** — see below |

**The guard is not fully self-protecting, and this doc will not pretend it is.** `guard-base-branch`
runs on `pull_request`, and Actions reads the workflow file **from the PR's head**. The workflow
therefore checks out `github.base_ref` to fetch `scripts/check-base-branch.sh`, so a PR cannot
supply the decision logic that judges it — a PR from `wip/x` → `main` that rewrites
`check-base-branch.sh` to `exit 0` no longer passes. But a PR that rewrites
`.github/workflows/guard-base-branch.yml` **itself** still can, and with
`required_approving_review_count: 0` nobody is forced to look. That residual hole is closed by
review, not by CI: **`.github/` must be code-owned**, which is what makes `--team` load-bearing.

**The org ruleset must NOT require status checks.** It targets `repository_name: ~ALL` — every repo
in Avenue-Z, ~64 of them, none generated from this template and none carrying
`guard-base-branch.yml` or `secret-scan.yml`. A required check that never reports does not fail a
PR; it hangs it **pending forever**. With `enforcement: active` and `bypass_actors: []`, a single
org-wide apply on Team-upgrade day would take direct push **and** merge away from every
repo in the org at once — while the script printed success. (This risk is now defended twice over:
the org apply lives in its own script, `apply-org-ruleset.sh`, which **refuses** to apply a ruleset
declaring required status checks at all.) It would also contradict this spec's own
"out of scope: retrofitting the six reference repos (or the other 54)". So `org-ruleset.json` ships
only what is safe on a repo with **no CI at all** — `deletion`, `non_fast_forward`, and
`pull_request` with `required_approving_review_count: 0` — and required checks stay in
`repo-ruleset.json`, applied per repo, to repos that actually have the workflows. `--org` additionally
lists every repo it would touch and requires an explicit `--yes`. A test asserts `org-ruleset.json`
declares zero `required_status_checks` rules.

### Base-branch matrix (`guard-base-branch.yml`)

| Head branch | Allowed base | Anything else |
|---|---|---|
| `feat/*`, `fix/*`, `docs/*`, `chore/*`, `ci/*` | `dev` | fail |
| `dependabot/*` | `dev` | fail |
| `dev` | `staging` | fail |
| `staging` | `main` | fail |
| **any other prefix** | — | **fail closed** |

Fail-closed on an unmatched prefix is deliberate. The guard is already the weaker of the two
enforcement mechanisms — it cannot stop a direct push — so a pass-through for unrecognized branch
names would leave it enforcing nothing. A contributor who needs a new prefix adds it to the matrix
in a PR, which is the point.

**`dependabot/*` is in the matrix because otherwise the template's two features fight each other.**
Dependabot opens PRs from branches named `dependabot/<ecosystem>/<dep>-<version>` — an unmatched
prefix, which fail-closed would red-X. A fresh repo with three ecosystems enabled and no baseline can
open a dozen PRs on day one, and every one of them would fail the guard. A repo that greets its owner
with a wall of red on day one has not "started life with the conventions already working." So the row
is added **and** `dependabot.yml` sets `target-branch: dev`, which keeps dependabot inside the same
`… → dev → staging → main` promotion path as everything else rather than side-loading updates.

### Secret scanning

`gitleaks` runs as a **pre-commit hook and a required CI job**, in the template core — not deferred
to a future move to public. The credential block in `.gitignore` is a denylist, and denylists leak;
it is a convenience, not a control. The survey found real credentials sitting in working trees
(`ad-spend-pacing`: `sa-key.json`, `client_secrets.json`) precisely because a denylist only catches
the filenames someone thought of.

This matters most on the **private** repos, which is where the daily commits happen: GitHub's own
server-side push protection is free only on **public** repositories, so private repos on Free have
no server-side net at all. The hook plus the CI job are the only backstop they get.

**What this control does *not* do — state it plainly.** Its protection boundary is **merge, not push**:

- The pre-commit hook is **local and skippable** — `git commit --no-verify` bypasses it entirely.
- Private repos on Free have **no server-side push protection**, so nothing rejects the push itself.
- Therefore a credential can be committed, pushed to a feature branch, and **live in the remote's
  object store** — reachable, and surviving even if the PR is closed unmerged.
- The `secret-scan` CI job catches it before it reaches `dev`/`staging`/`main`. That is the real,
  and only, guarantee.

The doc says this out loud because a control whose whole justification is "denylists leak" must not
itself be sold as something it isn't. A leaked key that reached the remote is **burned and must be
rotated**, even if the PR was never merged.

`scripts/apply-rulesets.sh` detects org plan and repo visibility, applies whatever is actually
possible, and **prints exactly what it skipped and why** — so nobody believes `main` is protected
when it is not. On upgrade to Team, an owner runs it once with `--org` and every repo inherits the
ruleset, with no template change and no per-repo work.

Applying an org ruleset requires the `admin:org` token scope
(`gh auth refresh -h github.com -s admin:org`); the current token has only
`gist, read:org, repo, workflow`.

**Ruleset contents must not lock out the maintainer.** Two distinct ways a ruleset bricks a repo,
and the template must dodge both:

1. **Required review with nobody to review.** A ruleset requiring one approving review on a repo whose
   sole collaborator is its creator makes every PR unmergeable — an author cannot approve their own PR.
   So the shipped ruleset sets **`required_approving_review_count: 0`**: a PR is still mandatory, and CI
   must still pass, but a solo maintainer can merge. Teams with two or more reviewers raise the count in
   their own repo. The template must not default to a config that bricks a one-person repo.

2. **A required status check that never reports.** This is the subtler trap. A required check that does
   not exist does *not* fail the PR — it stays **pending forever**, and the PR can never be merged.
   The stack-agnostic core has **no `ci.yml`**; the language `ci.yml` lives in `templates/` and only
   lands when `init-repo.sh` runs. So a ruleset requiring a check named `ci` would make the template
   repo itself permanently unmergeable, and success criterion #5 unachievable.

   Therefore `repo-ruleset.json` requires **only the two checks that exist in the stack-agnostic core
   and therefore actually run on the template repo**:

   | Required check | Source | Exists in core? |
   |---|---|---|
   | `guard-base-branch` | `.github/workflows/guard-base-branch.yml` | yes |
   | `secret-scan` | gitleaks CI job | yes |
   | `ci` | `templates/{python,node}/.github/workflows/ci.yml` | **no — added post-init only** |

   **`ci` is added by `scripts/apply-rulesets.sh`, not by `init-repo.sh`.** (An earlier draft of this
   spec said the init script does it; it does not, and never did.) `apply-rulesets.sh` adds
   `{"context":"ci"}` to the required-checks payload **if and only if `.github/workflows/ci.yml`
   exists in the working copy** — which is true in a generated repo, and false in the template core.
   The decision is therefore made at apply time, by the human running the script, against the tree in
   front of it. `init-repo.sh` copies `ci.yml` into place and prints `apply-rulesets.sh` as the next
   step; the required check appears only once someone runs it.

   The check names in the ruleset must match the **job** names in the workflow files exactly, or they
   will hang pending under a different alias. `templates/python/ci.yml` runs its matrix in a job
   called `test` and adds a non-matrix aggregate job named `ci` for exactly this reason — GitHub
   names a matrix job's contexts `test (3.11)`, so a context named plainly `test` never reports.

**No bypass actors. Verified live, 2026-07-13.** The design originally listed the org-admin role as a
`bypass_actor` (`bypass_mode: always`) "for emergencies." Applied to the live repo, a direct
`git push origin main` by an org owner **succeeded** — the ruleset reported `enforcement: active`
while protecting nothing against exactly the people most likely to push to `main`. The bypass also
bought nothing: an org owner can already disable or edit a ruleset in settings, which is *visible and
deliberate* rather than silent. `bypass_actors` is therefore **empty**: everyone, including org
owners, goes through a PR. This closes the open question about repo-vs-org bypass precedence by
removing the bypass entirely.

## Repository layout

The template core is **stack-agnostic**. The org is genuinely two-stack (Python: `ad-spend-pacing`,
`drive-api-client`, `glean-chat-api-client`; TypeScript/Vercel: `avenue-z-reporting-v2`,
`aivx-reports`), so language-specific files live in `templates/` and are copied into place by the
init script, which then deletes `templates/`. A generated repo therefore carries **zero dead files**.

**"Zero dead files" includes the template's tests and the template's own spec/plan.** These are
about `repo-template`, not about the repo you generated, and two of the tests actively *fail* in a
generated repo — `test_rulesets.sh` and `test_apply_rulesets.sh` both assert "the core has no
`ci.yml`", a premise that inverts the instant `init-repo.sh` copies one in. So the template's own
suite lives in **`template-tests/`**, not `tests/`: `init-repo.sh` deletes that directory wholesale,
which leaves the generated repo's `tests/` (the stack skeleton it just copied) untouched. The init
script also deletes this spec and its plan from the generated tree. The empty
`docs/superpowers/{specs,plans}/` directories stay — that is where the new repo's *own* specs go.

```
repo-template/
├── .github/
│   ├── workflows/{guard-base-branch.yml, secret-scan.yml}
│   ├── rulesets/{org-ruleset.json, repo-ruleset.json}
│   ├── PULL_REQUEST_TEMPLATE.md
│   ├── CODEOWNERS.tmpl                 # NOT live; init-repo.sh substitutes a real team or drops it
│   └── dependabot.yml                  # pip + npm + github-actions
├── docs/
│   ├── superpowers/{plans,specs,handoffs}/   # de facto standard, 5 of 6 repos
│   └── notes/                                # dated session notes; today they get dumped at docs/ root
├── .pre-commit-config.yaml             # gitleaks
├── scripts/
│   ├── init-repo.sh                    # <python|node> [--team <slug>]: select stack, push branches
│   ├── check-base-branch.sh            # the guard's decision logic; run from the BASE branch
│   └── apply-rulesets.sh               # apply what the plan allows; report what it skipped
├── template-tests/                     # the TEMPLATE's own suite. DELETED by init-repo.sh — it
│                                       #   tests repo-template's premises, not the generated repo's,
│                                       #   and it is not in tests/ so that deleting it cannot take
│                                       #   the generated repo's tests/ skeleton with it.
├── templates/
│   ├── python/                         # pyproject.toml (hatchling, src/, ruff, mypy, pytest),
│   │                                   #   ci.yml (matrix), Dockerfile + .dockerignore (Cloud Run Job),
│   │                                   #   src/ + tests/conftest.py skeleton
│   └── node/                           # package.json (type: module, vitest, eslint),
│                                       #   tsconfig.json, ci.yml (npm ci → lint → typecheck → test)
├── .gitignore
├── .env.example
├── README.md
├── CLAUDE.md
├── CONTRIBUTING.md
├── SECURITY.md
└── LICENSE
```

Each `docs/` subdirectory gets a `.gitkeep` and a one-line `README.md` stating what belongs in it.

## Root files

**`.gitignore`** — union of the org's real patterns, closing the gaps found in the survey:
OS (`.DS_Store`); Python (`__pycache__/`, `.venv/`, `.pytest_cache/`, `dist/`, `build/`, `*.egg-info/`);
Node (`node_modules/`, `.next/`, `.vercel/`, `*.tsbuildinfo`); `.claude/`; env (see below); and a
**credential block** — `*service-account*.json`, `sa-key*.json`, `client_secrets.json`, `token.json`,
`google-credentials.json`.

**Env-block ordering is load-bearing and must be exactly this:**

```gitignore
.env
.env.local
.env.*
!.env.example      # negation MUST come after .env.* or it silently does nothing
```

`.env.*` matches `.env.example`, so the negation must follow the broader pattern. Verified with
`git check-ignore`:

| Order | `.env` | `.env.local` | `.env.production` | `.env.example` |
|---|---|---|---|---|
| negation **last** (correct) | ignored | ignored | ignored | **trackable** ✅ |
| negation **before** `.env.*` | ignored | ignored | ignored | **ignored** ❌ |

The wrong order does not error — it silently ignores `.env.example`, the one env file the template
exists to ship. A test asserts `git check-ignore .env.example` exits non-zero.

**`.env.example`** — the only committed env file. Every var declared, commented, values blank.
Modeled on `ad-spend-pacing/.env.example`, the best-annotated in the org. README setup step is
`cp .env.example .env.local`. No `.env.local` is ever tracked.

**`README.md`** — skeleton in the org's stable order (consistent across all six repos even as depth
varies from 27 to 413 lines): one-line what-this-is → Stack → Setup → Run → Tests → Deploy → Docs.
`<!-- TODO -->` markers throughout.

**`CLAUDE.md`** — short and stable: What This Is / Stack / Layout / Commands / Env / Workflow Rules /
Project Rules. Carries an explicit banner that **volatile state does not belong here** — the fix for
`aivx-reports/CLAUDE.md` §9 "Open Branches (as of 2026-06-24)" and §13 "Recent History", both already
stale, and for the 500+ line CLAUDE.md files in the two largest repos.

**`CONTRIBUTING.md`** — the branch flow, commit conventions, and the mandatory
`git fetch --all --prune` + `git log origin/dev..HEAD` sync check, lifted from `aivx-reports/CLAUDE.md` §8
(the clearest written convention in the org).

**`SECURITY.md`** — vulnerability reporting, and the never-commit-credentials rule.

**`LICENSE`** — proprietary / UNLICENSED. These are private org repos, not OSS.

**No CHANGELOG.** A changelog only pays off if maintained; `aivx-reports` keeps one inline in its README.

## CODEOWNERS: no placeholder

A CODEOWNERS entry naming a team that does not exist — or that exists but lacks **write access to
this repo** — is **silently ignored**. Per GitHub's docs: *"If you specify a user or team that
doesn't exist or has insufficient access, a code owner will not be assigned."* No error, no warning.
A `@Avenue-Z/<team>` placeholder would therefore ship a file that *looks* like enforced review and
enforces nothing — the same class of lie as the stale CLAUDE.md state this template exists to kill.

So the template ships **`.github/CODEOWNERS.tmpl`**, never a live `CODEOWNERS`. `init-repo.sh` takes
`--team <slug>`, verifies via `gh api orgs/Avenue-Z/teams/<slug>` that the team exists, and only then
writes `.github/CODEOWNERS`. Without `--team`, it **deletes the template and prints a warning** that
the repo has no code-owner review. A repo either has a real, verified owning team or is honest about
having none.

Note that team existence is necessary but not sufficient — the team must also be granted write access
to the new repo, because that is the exact silent-failure case.

**`init-repo.sh` GRANTS write access; it does not merely warn.** (An earlier draft of this spec said
it warns. Warning was the wrong call, and the shipped script does not do it.) A warning nobody actions
leaves an inert `CODEOWNERS` — a file that looks like enforced review and enforces nothing, which is
the precise failure this section exists to prevent. So when the team exists but lacks write, the
script issues `PUT orgs/Avenue-Z/teams/<slug>/repos/<owner>/<repo>` with `permission=push`, re-reads
the permission to confirm the grant actually took, and only then writes `CODEOWNERS`.

**This means `--team` mutates GitHub permissions.** An "init" script that changes org access control
is surprising, so it is documented in the script's header, in `README.md`, and in `CONTRIBUTING.md` —
not only in the code. It requires repo-admin or org-owner rights; a 403 is fatal and no `CODEOWNERS`
is written. Omit `--team` and no permission is touched.

**Three outcomes when identifying the repo, and they are not interchangeable.** The write-access check
needs to know which repo this is. `gh repo view` succeeding is one case; a working copy with **no
GitHub remote yet** is a second (an answer: there is nothing to check against — write `CODEOWNERS`,
but warn loudly that write access is UNVERIFIED and the file may be inert, and record that in the
file's own header rather than claiming a verification that never happened); an expired token, a
network blip, or a rate limit is a third (**not** an answer — `die`). Collapsing all three into "no
repo" and writing `CODEOWNERS` anyway is the same silent downgrade as the 404-vs-401 trap below.

## Init script: idempotent, single-commit, git-rollback

`init-repo.sh` must be safe to re-run. Between "Use this template" and the first run, a new repo has
only `dev` — no `main`, no `staging` — so a script that fails halfway or is never run leaves the repo
in a half-configured state.

**Ordering: branch `staging` and `main` from `dev` *after* the init commit.** This is load-bearing and
was previously unstated. Immediately after "Use this template," `dev` still contains `templates/` — the
script's own commit is what removes it. So if `staging` and `main` are cut from `dev` *before* that
commit, all three heads permanently carry `templates/` and the dead stack files the design promises
zero of, and every future promotion drags that cruft along until someone cleans it by hand. The order
is therefore fixed:

1. Copy the chosen stack into place; verify the copy.
2. Remove `templates/`; commit **once**; push `dev`.
3. **Then** create `staging` and `main` from the *post-cleanup* `dev`, so all three heads share one
   clean tree.

- **Idempotent branch creation.** Create-if-absent for `staging` and `main` (check `git rev-parse
  --verify`), never force-push.
- **`set -euo pipefail`,** so a failure stops rather than continuing into a partial config.
- **Copy is verified before `templates/` is removed,** and the whole change lands as **one commit**.
- **Rollback is git.** The script runs inside a git working tree, so a failed run is undone with
  `git checkout -- . && git clean -fd`, and `templates/` remains in HEAD until the commit lands.
  A stage-to-temp-dir-then-atomically-move layer was considered and rejected: it protects against a
  failure mode git already covers, at the cost of real moving parts. On failure the script prints the
  recovery command.

**Re-run repairs *absence*, not *drift*.** This bounds the idempotency claim honestly. Create-if-absent
means a second run sees `staging`/`main` exist and does nothing. If `dev` has advanced since the first
run, those branches are now *stale* relative to the intended lineage, and re-running **will not
reconcile them** — by design, because silently fast-forwarding `main` is exactly the unreviewed
promotion the branch model exists to prevent. So:

- Re-run is safe and correct for: *the script died partway; a branch was never pushed.*
- Re-run is **not** a reconciliation tool. Drift between `dev`, `staging`, and `main` is resolved the
  normal way — by opening a PR.

**`set -e` will kill the graceful paths unless they are guarded.** `gh api orgs/Avenue-Z/teams/<slug>`
exits **non-zero on 404** — and a 404 is the *expected input* to the warn-and-continue branch, not an
error. Under `set -e`, a bare `gh api ... | jq ...` aborts the script on precisely the case the feature
was written to handle. Both the team-existence check and the team-write-access check must therefore use
an explicit guard:

**But the guard must distinguish "absent" from "couldn't tell."** `set -e` is disabled inside an `if`
condition — which is *why* the guard works, and also its trap: a bare `if ! gh api ...` treats **every**
non-zero exit as "team not found." A network blip, an expired token, or a rate limit would then
silently delete `CODEOWNERS.tmpl` and leave the repo with no code-owner review — the exact quiet
downgrade this section exists to prevent. Honest enforcement means a failure to *verify* is not the
same as a verified *absence*:

```bash
if out=$(gh api "orgs/Avenue-Z/teams/${team}" 2>&1); then
  :                                          # team exists → continue to the write-access check
elif grep -qE '"status": *"404"|HTTP 404' <<<"$out"; then
  warn "team '${team}' does not exist — dropping CODEOWNERS (no code-owner review)"
  rm -f .github/CODEOWNERS.tmpl
else
  die "cannot verify team '${team}' (not a 404): ${out}"   # auth/network/rate-limit → STOP
fi
```

- **404** → a real answer. Warn, drop the file, continue.
- **Any other non-zero** → we do not know. **Stop and say why.** Never downgrade silently.

Same pattern for the write-access check, and for any `gh api` call whose failure is a decision rather
than a fault.

## New: linting

`templates/python/pyproject.toml` ships **ruff + mypy**, and `templates/node/` ships **eslint +
`tsc --noEmit`**. No repo in the org lints today, so this is a genuine change to the day-to-day, not
just a new file: every new repo starts with a lint gate that no existing repo would pass. Accepted
deliberately. Existing repos are not retrofitted as part of this work.

## Testing / success criteria

1. `scripts/init-repo.sh python` in a scratch clone produces a repo whose `pytest -q` and `ruff check`
   pass on the skeleton, with no `templates/` directory left behind.
2. `scripts/init-repo.sh node` likewise for `npm test`, `npm run lint`, `tsc --noEmit`.
3. Both leave `main`, `staging`, `dev` pushed to origin, with `dev` as the default branch.
4. `guard-base-branch.yml` fails a PR from `feat/x` → `main`, passes `feat/x` → `dev`, passes
   `dev` → `staging`, and **fails an unmatched prefix** (`wip/x` → `dev`) — the fail-closed case.
5. `apply-rulesets.sh` on the public template repo results in `main` reporting protected via
   `gh api repos/Avenue-Z/repo-template/branches/main/protection` — **and then the maintainer can
   still open and merge a PR into it.** Protection that bricks the repo is a failed criterion, not a
   passed one.
6. `apply-rulesets.sh` against a private repo on Free exits 0 and prints a clear explanation that
   protection was skipped and why — it does not fail silently or claim success.
7. Re-running `init-repo.sh` on an already-initialized repo is a no-op that exits 0 — it does not
   duplicate, reset, or force-push branches.
8. `init-repo.sh --team <nonexistent>` refuses to write a live `CODEOWNERS`; with no `--team` it
   removes `CODEOWNERS.tmpl` and warns. No generated repo ever ships an inert CODEOWNERS.
9. Committing a fake AWS/Google credential to the skeleton is blocked by the gitleaks pre-commit hook,
   and — the guarantee that actually matters — the `secret-scan` CI job fails the PR when the hook is
   bypassed with `--no-verify`.
10. `git check-ignore .env.example` exits **non-zero** (i.e. the file is trackable) while
    `git check-ignore .env.local` exits zero. Guards the negation-ordering trap. Note this asserts the
    **repo-local** rule; a developer's global gitignore or a parent `.gitignore` in a nested checkout
    could shadow it, and that is out of the template's control.
11. `init-repo.sh --team <nonexistent>` **warns and exits 0** — it does not abort with a `set -e`
    crash. Proves the `gh api` 404 path is guarded rather than fatal.
12. **(template repo)** The template's own ruleset requires only `guard-base-branch` and `secret-scan`;
    a PR into its `main` reaches a mergeable state rather than hanging pending on a `ci` check that does
    not exist. *This can only be tested on the template, which by definition never has `ci` — hence #13.*
13. **(generated repo — the case #12 structurally cannot cover)** After `init-repo.sh python`, a PR into
    the **generated** repo's `main` reaches mergeable **and the `ci` check reports a result rather than
    hanging pending**. This is the one that proves the required-check name `init-repo.sh` adds actually
    matches the **job name** inside the copied `ci.yml`. Without it, the hang-pending trap is merely
    relocated from the template — where it cannot occur — into every repo the template produces, and
    template testing would never reveal it. Repeat for `node`.
14. `dependabot/*` PRs pass `guard-base-branch` and target `dev`. A fresh repo does not greet its owner
    with a wall of failing dependabot PRs.
15. On all three of `dev`, `staging`, `main` in a generated repo, `test -d templates` fails — the
    post-cleanup branch-lineage ordering held, and no head carries dead stack files.

## Out of scope

- Retrofitting the six reference repos (or the other 54) with any of this.
- The git-history secret audit and credential rotation that a future move to public would require.
  (Note: gitleaks in the template prevents *new* leaks. It does not clean *existing* history.)
- Upgrading the org to GitHub Team. The design is ready for it; the decision is Paul's.

## Review log — 2026-07-13

Spec revised after review. Accepted: full base-branch matrix + fail-closed on unmatched prefix;
idempotent re-runnable `init-repo.sh`; gitleaks moved into the template core rather than deferred;
`CODEOWNERS.tmpl` with verified-team substitution instead of an inert placeholder; ruleset configured
so it cannot lock out a sole maintainer.

Rejected: staging-directory + atomic-move for the `templates/` copy. The script runs in a git working
tree, which already provides the rollback (`git checkout -- . && git clean -fd`); the added machinery
would guard a failure mode git covers. Mitigated instead with `set -euo pipefail`, verify-before-delete,
a single commit, and a printed recovery command.

Verified against GitHub docs, not assumed: CODEOWNERS silently ignores nonexistent or
insufficient-access owners; "Manage branch protection rules and repository rulesets" is an Admin-role
permission, not org-owner-exclusive.

## Review log — 2026-07-13 (round 2)

Second review round. All six items accepted; two were blocking and are now resolved in the design.

- **(blocking) Required-check trap.** A required status check that never reports hangs **pending**
  rather than failing, so a ruleset requiring `ci` — which lives in `templates/` and does not exist in
  the stack-agnostic core — would have made the template repo permanently unmergeable and criterion #5
  unachievable. Ruleset now requires only `guard-base-branch` and `secret-scan` (both in core);
  `init-repo.sh` adds `ci` to a generated repo only after `ci.yml` is in place. New criterion #12.
- **(blocking) `set -e` kills the graceful paths.** `gh api .../teams/<slug>` exits non-zero on 404,
  which is the expected input to the warn-and-continue branch. Both `gh api` checks now use explicit
  `if ! gh api ...` guards. New criterion #11.
- **Idempotency bounded.** "Safe to re-run" now states that re-run repairs *absence*, not *drift*;
  stale `staging`/`main` are reconciled by PR, not by the script — silently fast-forwarding `main` is
  the exact unreviewed promotion the branch model prevents.
- **Secret-scanning boundary stated honestly.** `--no-verify` skips the hook and private repos on Free
  have no push protection, so the boundary is **merge, not push**: a credential can reach the remote's
  object store on a feature branch and survive an unmerged PR. Such a key is burned and must be rotated.
- **`.gitignore` negation ordering pinned,** and verified with `git check-ignore`: `!.env.example` must
  follow `.env.*`, or `.env.example` is *silently* ignored — the one file the template exists to ship.
  New criterion #10.
- **Unverified item promoted to a Team-path blocker.** Whether a repo-level bypass actor survives an
  org-level ruleset determines whether the emergency-bypass design works at all. It blocks validation of
  the Team path, not merely the wording of `CONTRIBUTING.md`.

## Review log — 2026-07-13 (round 3 — approved)

Approved for planning and build. Four items folded in; the rest were notes for the build engineer.

- **`dependabot/*` vs. fail-closed — the two features were fighting.** Dependabot branches
  (`dependabot/<ecosystem>/<dep>`) are an unmatched prefix, so the guard would have red-X'd every one of
  them, and a fresh repo with three ecosystems can open a dozen PRs on day one. Added the
  `dependabot/*` → `dev` row **and** `target-branch: dev` in `dependabot.yml`. A template whose first
  impression is a wall of red has not "started life with the conventions working." New criterion #14.
- **Branch lineage pinned to *post-cleanup* `dev`.** Previously unstated: `dev` still contains
  `templates/` until the script's own commit removes it, so cutting `staging`/`main` before that commit
  would leave all three heads permanently carrying the dead files the design promises zero of. Order is
  now fixed — copy, verify, remove, commit, push `dev`, *then* branch. New criterion #15.
- **The required-check-name invariant is now tested where it can actually fail.** #12 only exercises the
  template repo, which by construction never has `ci` — so it proves the trap is avoided in the one place
  it cannot occur. New criterion #13 tests a **generated** repo: the `ci` check must *report*, not hang
  pending, proving the name `init-repo.sh` adds matches the job name in the copied `ci.yml`.
- **`gh api` guard now separates "absent" from "couldn't tell."** `set -e` is disabled inside an `if`
  condition, so a bare `if ! gh api` treats an expired token or a network blip identically to a 404 and
  would silently drop `CODEOWNERS`. Now: 404 → warn and drop; any other non-zero → **stop and say why**.
  A failure to verify is not a verified absence.

Noted, not changed: #5 and #12 overlap but test different repos and both stay; the `check-ignore` test
asserts the repo-local rule only, which a global gitignore could shadow.

### Open, blocking the Team-upgrade path only

1. Does a repo creator in Avenue-Z actually receive the Admin role on the repo they create?
2. Does a repo-level bypass actor survive an org-level ruleset, or does the org ruleset outrank it?

Both are unanswerable on Free. Confirm on Team before the org-wide rollout, and before either claim
lands in `CONTRIBUTING.md`. Neither blocks building the template itself.
