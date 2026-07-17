# Avenue-Z Repo Template Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `Avenue-Z/repo-template` — a public GitHub template repository with `main`/`staging`/`dev` branches whose stack-agnostic core carries the org's conventions, and whose `init-repo.sh` turns a fresh copy into a working Python or Node repo.

**Architecture:** The committed root is stack-agnostic (gitignore, env example, docs tree, governance files, base-branch guard, secret scan). Language-specific files live in `templates/{python,node}/` and are copied to the root by `scripts/init-repo.sh`, which then deletes `templates/`, commits once, pushes `dev`, and only then cuts `staging` and `main` from the cleaned tree. `scripts/apply-rulesets.sh` applies branch protection where the GitHub plan allows and prints what it skipped where it does not.

**Tech Stack:** Bash (`gh` CLI, git), GitHub Actions, gitleaks, pre-commit; `templates/python` = hatchling + pytest + ruff + mypy; `templates/node` = vitest + eslint + tsc.

**Spec:** `template-docs/specs/2026-07-13-avenue-z-repo-template-design.md` — read it before Task 1. Its 15 success criteria are the acceptance tests; each is mapped to a task below.

## Global Constraints

- **Org:** `Avenue-Z`. **Repo:** `repo-template`. **Visibility: public** (template only; generated repos are private).
- **Default branch: `dev`.** Branch model: `feat/* | fix/* | docs/* | chore/* | ci/* | dependabot/*` → `dev` → `staging` → `main`.
- **Every shell script:** `#!/usr/bin/env bash` + `set -euo pipefail`.
- **`gh api` failure handling:** HTTP 404 is an *answer* (warn, continue). Any other non-zero exit is *"could not verify"* → **stop and say why**. Never downgrade a control silently.
- **Required status-check names in rulesets must equal the `jobs.<id>` key in the workflow** — a mismatched name hangs *pending* forever and makes the PR unmergeable.
- **The stack-agnostic core has no `ci` check.** Only `guard-base-branch` and `secret-scan` may be required on the template repo itself. `ci` is added to a generated repo only *after* `ci.yml` is copied in.
- **`.gitignore` env block ordering is load-bearing:** `!.env.example` MUST come after `.env.*`.
- **No secrets, ever.** No real credential values in any committed file, including examples.
- Python floor: `>=3.11`. Node floor: `>=20`.
- Commit style: `feat:` / `fix:` / `docs:` / `chore:` / `ci:` / `test:`.

---

## File Structure

| File | Responsibility |
|---|---|
| `.gitignore` | Union denylist: OS, Python, Node, `.claude/`, env block, credential block |
| `.env.example` | The only committed env file; declares + comments every var |
| `README.md` | what-this-is → Stack → Setup → Run → Tests → Deploy → Docs |
| `CLAUDE.md` | Durable agent context; explicitly forbids volatile state |
| `CONTRIBUTING.md` | Branch flow, commit conventions, sync check |
| `SECURITY.md` | Vuln reporting + never-commit-credentials |
| `LICENSE` | Proprietary / UNLICENSED |
| `.pre-commit-config.yaml` | gitleaks hook (local, skippable — CI is the real gate) |
| `.github/workflows/guard-base-branch.yml` | Job id **`guard-base-branch`**. Enforces the base matrix; fails closed |
| `.github/workflows/secret-scan.yml` | Job id **`secret-scan`**. gitleaks on PRs — the enforced boundary |
| `.github/PULL_REQUEST_TEMPLATE.md` | Checklist |
| `.github/CODEOWNERS.tmpl` | NOT live. `init-repo.sh` writes a real `CODEOWNERS` or drops this |
| `.github/dependabot.yml` | pip + npm + actions, `target-branch: dev` |
| `.github/rulesets/repo-ruleset.json` | Per-repo protection; review count 0; core checks only |
| `.github/rulesets/org-ruleset.json` | Org-wide equivalent; committed, not applied (needs Team) |
| `scripts/init-repo.sh` | Stack select, CODEOWNERS resolve, cleanup, commit, branch lineage |
| `scripts/apply-rulesets.sh` | Apply what the plan allows; report what it skipped |
| `tests/test_gitignore.sh` | Criterion 10 |
| `tests/test_init_repo.sh` | Criteria 1, 2, 7, 11, 15 |
| `tests/test_apply_rulesets.sh` | Criterion 6 |
| `tests/lib.sh` | Shared `assert_*` helpers |
| `templates/python/**` | pyproject (hatchling, ruff, mypy, pytest), `ci.yml` (job id **`ci`**), Dockerfile, src/tests skeleton |
| `templates/node/**` | package.json, tsconfig, eslint, `ci.yml` (job id **`ci`**), src/tests skeleton |
| `docs/{superpowers/{plans,specs,handoffs},notes}/` | Each with `.gitkeep` + a one-line `README.md` |

**Criteria → task map:** 10→T1 · 6→T8 · 1,2,7,11,15→T7/T9/T10 · 4,14→T3 · 9→T4 · 8→T7 · 3→T7 · 5,12→T11 · 13→T12

---

### Task 1: Repo skeleton, `.gitignore`, `.env.example`

**Files:**
- Create: `.gitignore`, `.env.example`, `tests/lib.sh`, `tests/test_gitignore.sh`

**Interfaces:**
- Consumes: nothing.
- Produces: `tests/lib.sh` exporting `assert_eq <expected> <actual> <msg>`, `assert_ignored <path>`, `assert_trackable <path>`, `pass <msg>`, `fail <msg>`. Every later test file sources it.

- [ ] **Step 1: Write the failing test** — `tests/lib.sh`

```bash
#!/usr/bin/env bash
# Shared assertions for the repo-template test scripts.
set -euo pipefail

FAILURES=0

pass() { printf '  ok   %s\n' "$1"; }
fail() { printf '  FAIL %s\n' "$1"; FAILURES=$((FAILURES + 1)); }

assert_eq() { # <expected> <actual> <msg>
  if [ "$1" = "$2" ]; then pass "$3"; else fail "$3 (expected '$1', got '$2')"; fi
}

# git check-ignore exits 0 when the path IS ignored, 1 when it is not.
assert_ignored() {
  if git check-ignore -q "$1"; then pass "$1 is ignored"; else fail "$1 should be ignored"; fi
}

assert_trackable() {
  if git check-ignore -q "$1"; then fail "$1 should be trackable but is ignored"; else pass "$1 is trackable"; fi
}

finish() {
  if [ "$FAILURES" -eq 0 ]; then printf '\nALL PASS\n'; exit 0; fi
  printf '\n%d FAILURE(S)\n' "$FAILURES"; exit 1
}
```

Then `tests/test_gitignore.sh` — **criterion 10**:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=lib.sh
source tests/lib.sh

echo "gitignore: env block ordering"
touch .env .env.local .env.production .env.example

assert_ignored   .env
assert_ignored   .env.local
assert_ignored   .env.production
assert_trackable .env.example          # THE trap: a negation before .env.* silently ignores this

echo "gitignore: credential block"
touch sa-key.json client_secrets.json token.json google-credentials.json my-service-account.json
for f in sa-key.json client_secrets.json token.json google-credentials.json my-service-account.json; do
  assert_ignored "$f"
done

rm -f .env .env.local .env.production .env.example sa-key.json client_secrets.json \
      token.json google-credentials.json my-service-account.json
finish
```

- [ ] **Step 2: Run it and watch it fail**

```bash
chmod +x tests/lib.sh tests/test_gitignore.sh && ./tests/test_gitignore.sh
```
Expected: FAIL — no `.gitignore` exists yet, so every `assert_ignored` fails and `assert_trackable .env.example` passes vacuously.

- [ ] **Step 3: Write `.gitignore`**

```gitignore
# --- OS ---
.DS_Store
Thumbs.db

# --- Python ---
__pycache__/
*.py[cod]
*.egg-info/
.venv/
venv/
build/
dist/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/

# --- Node ---
node_modules/
.next/
.vercel/
*.tsbuildinfo

# --- Agent config (shared agent config lives in Avenue-Z/claude-marketplace) ---
.claude/

# --- Env. ORDER IS LOAD-BEARING: the negation MUST follow .env.* ---
# .env.* matches .env.example, so !.env.example placed earlier silently does nothing.
.env
.env.local
.env.*
!.env.example

# --- Credentials. A denylist, and denylists leak: gitleaks is the real control. ---
*service-account*.json
sa-key*.json
client_secrets.json
token.json
google-credentials.json
```

- [ ] **Step 4: Run the test — expect PASS**

```bash
./tests/test_gitignore.sh
```
Expected: `ALL PASS`. If `.env.example` reports ignored, the negation is misordered.

- [ ] **Step 5: Write `.env.example`**

```bash
# Copy to .env.local and fill in. NEVER commit .env.local.
#   cp .env.example .env.local
#
# Every variable this project reads must be declared here, commented, with a blank
# or dummy value. This file is the env contract; do not document vars in prose only.

# --- Core ---
# Deployment environment: local | staging | production
APP_ENV=local

# --- Google Cloud (service-account auth; see SECURITY.md) ---
# Absolute path to the service-account JSON. The file itself is gitignored.
GOOGLE_SERVICE_ACCOUNT_KEY=
# user = local OAuth flow; service_account = Cloud Run
AUTH_MODE=user

# --- Secrets (fill in .env.local; never here) ---
# API_KEY=
# SLACK_BOT_TOKEN=
# DATABASE_URL=
```

- [ ] **Step 6: Commit**

```bash
git add .gitignore .env.example tests/lib.sh tests/test_gitignore.sh
git commit -m "feat: gitignore with ordered env block, env example, test helpers"
```

---

### Task 2: Docs tree and governance files

**Files:**
- Create: `README.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `SECURITY.md`, `LICENSE`
- Create: `docs/superpowers/{plans,specs,handoffs}/{.gitkeep,README.md}`, `docs/notes/{.gitkeep,README.md}`

**Interfaces:**
- Consumes: nothing.
- Produces: `CONTRIBUTING.md` is the canonical statement of the branch flow. Task 3's workflow and Task 7's script must not contradict it.

- [ ] **Step 1: Create the docs tree**

```bash
mkdir -p docs/superpowers/plans docs/superpowers/specs docs/superpowers/handoffs docs/notes
touch docs/superpowers/plans/.gitkeep docs/superpowers/specs/.gitkeep \
      docs/superpowers/handoffs/.gitkeep docs/notes/.gitkeep
echo "Implementation plans. One per feature: YYYY-MM-DD-<feature>.md" > docs/superpowers/plans/README.md
echo "Design specs, written before the plan. YYYY-MM-DD-<topic>-design.md" > docs/superpowers/specs/README.md
echo "Session handoffs for picking up in-flight work. YYYY-MM-DD-<topic>.md" > docs/superpowers/handoffs/README.md
echo "Dated working notes. YYYY-MM-DD-<topic>.md — NOT a dumping ground for docs/ root." > docs/notes/README.md
```

- [ ] **Step 2: Write `CONTRIBUTING.md`**

```markdown
# Contributing

## Branch flow

    feat/* | fix/* | docs/* | chore/* | ci/* | dependabot/*  →  dev  →  staging  →  main

- **`dev`** — integration branch, and the default. Open your PR here.
- **`staging`** — pre-prod soak / QA. Receives PRs from `dev` only.
- **`main`** — production. Receives PRs from `staging` only.

`guard-base-branch` fails any PR whose base is wrong for its head, and **fails closed on an
unrecognized branch prefix**. Need a new prefix? Add it to the matrix in a PR.

## Never push directly to main

Every change reaches `main` through the chain above. No exceptions.

## Start every session by syncing

    git fetch --all --prune
    git log origin/dev..HEAD        # what you have that origin does not

## Commits

`feat:` `fix:` `docs:` `chore:` `ci:` `test:` — imperative mood, one logical change.

## Before you open a PR

- Tests pass.
- Lint passes (`ruff check` / `npm run lint`).
- No credentials. `secret-scan` will fail the PR; a key that reached the remote is **burned and
  must be rotated**, even if the PR is never merged. See SECURITY.md.
```

- [ ] **Step 3: Write `CLAUDE.md`**

```markdown
# CLAUDE.md

> **This file holds DURABLE context only.**
> Do NOT put volatile state here — open branches, recent history, "as of <date>" lists, in-flight
> work. It rots within days, and a stale CLAUDE.md is worse than none: an agent will act on it.
> Volatile state belongs in `docs/notes/` or `docs/superpowers/handoffs/`.

## What this is
<!-- TODO: one or two sentences. What does this project do, for whom? -->

## Stack
<!-- TODO: language, framework, datastore, deploy target -->

## Layout
<!-- TODO: the 3-6 directories that matter and what each holds -->

## Commands
| Task | Command |
|---|---|
| Install | <!-- TODO --> |
| Test | <!-- TODO --> |
| Lint | <!-- TODO --> |
| Run | <!-- TODO --> |

## Env
Declared in `.env.example`. Copy to `.env.local`. Never commit `.env.local`.

## Workflow rules
1. Branch flow is `feat/* → dev → staging → main`. **Never push directly to `main`.**
2. Sync before you start: `git fetch --all --prune && git log origin/dev..HEAD`.
3. Verify before claiming done — run the tests and read the output. Do not assert a pass you
   have not seen.
4. Never commit credentials. `.gitignore` is a denylist and denylists leak; `secret-scan` is the
   real control.

## Project rules
<!-- TODO: the rules specific to THIS repo. Keep them durable. -->
```

- [ ] **Step 4: Write `SECURITY.md`**

```markdown
# Security

## Reporting

Email **paul.ramirez@avenuez.com**. Do not open a public issue.

## Never commit credentials

Service-account JSON, API keys, tokens, `.env.local` — none of it belongs in git.

`.gitignore` blocks the credential filenames we have thought of. That is a **denylist, and
denylists leak** — it is a convenience, not a control. The controls are:

| Control | Boundary |
|---|---|
| gitleaks pre-commit hook | Local, and **skippable with `--no-verify`** |
| `secret-scan` CI job | **Merge** — it fails the PR |

Note what this means: nothing stops the *push*. Private repos on the Free plan have no server-side
push protection. A credential can be committed, pushed to a branch, and reach the remote's object
store — where it survives even if the PR is closed unmerged.

**A key that reached the remote is burned. Rotate it.** Removing the commit is not sufficient.
```

- [ ] **Step 5: Write `LICENSE`**

```
Copyright (c) 2026 Avenue Z, Inc. All rights reserved.

PROPRIETARY AND CONFIDENTIAL. This software is the confidential and proprietary
information of Avenue Z, Inc. It is not licensed for use, copying, modification,
or distribution outside Avenue Z, Inc. without prior written permission.
```

- [ ] **Step 6: Write `README.md`**

```markdown
# <!-- TODO: repo-name -->

<!-- TODO: one sentence. What is this and who is it for? -->

## Stack
<!-- TODO -->

## Setup

    git clone git@github.com:Avenue-Z/<repo>.git && cd <repo>
    cp .env.example .env.local    # then fill it in
    <!-- TODO: install command -->
    pre-commit install            # installs the gitleaks hook

## Run
<!-- TODO -->

## Tests
<!-- TODO -->

## Deploy
<!-- TODO -->

## Docs

- `docs/superpowers/specs/` — design specs
- `docs/superpowers/plans/` — implementation plans
- `docs/notes/` — dated working notes
- `CONTRIBUTING.md` — branch flow. **Never push directly to `main`.**
```

- [ ] **Step 7: Commit**

```bash
git add README.md CLAUDE.md CONTRIBUTING.md SECURITY.md LICENSE docs/
git commit -m "docs: README, CLAUDE, CONTRIBUTING, SECURITY, LICENSE, docs tree"
```

---

### Task 3: `guard-base-branch` workflow — criteria 4, 14

**Files:**
- Create: `.github/workflows/guard-base-branch.yml`

**Interfaces:**
- Consumes: the branch flow from `CONTRIBUTING.md` (Task 2).
- Produces: a status check whose name is exactly **`guard-base-branch`** (the `jobs.` key). Tasks 6 and 11 require this name verbatim in the rulesets — a mismatch hangs pending forever.

- [ ] **Step 1: Write the workflow**

The job id **must** be `guard-base-branch`.

```yaml
name: guard-base-branch

on:
  pull_request:
    types: [opened, edited, reopened, synchronize]

jobs:
  guard-base-branch:
    runs-on: ubuntu-latest
    steps:
      - name: Enforce the base-branch matrix
        env:
          HEAD_REF: ${{ github.head_ref }}
          BASE_REF: ${{ github.base_ref }}
        run: |
          set -euo pipefail
          echo "PR: ${HEAD_REF} -> ${BASE_REF}"

          case "${HEAD_REF}" in
            feat/*|fix/*|docs/*|chore/*|ci/*|dependabot/*) want=dev ;;
            dev)                                           want=staging ;;
            staging)                                       want=main ;;
            *)
              echo "::error::Unrecognized branch prefix '${HEAD_REF}'. This guard FAILS CLOSED."
              echo "Allowed: feat/ fix/ docs/ chore/ ci/ dependabot/ — or dev, staging."
              echo "Need a new prefix? Add it to the matrix in .github/workflows/guard-base-branch.yml."
              exit 1
              ;;
          esac

          if [ "${BASE_REF}" != "${want}" ]; then
            echo "::error::'${HEAD_REF}' must target '${want}', not '${BASE_REF}'. See CONTRIBUTING.md."
            exit 1
          fi
          echo "OK: '${HEAD_REF}' -> '${BASE_REF}'"
```

`dependabot/*` is in the matrix deliberately: without it, fail-closed would red-X every dependabot PR, and a fresh repo would greet its owner with a wall of red. Task 5's `dependabot.yml` sets `target-branch: dev` to match.

- [ ] **Step 2: Verify the job name matches what the rulesets will require**

```bash
grep -A1 '^jobs:' .github/workflows/guard-base-branch.yml
```
Expected: the next line is `  guard-base-branch:`. This exact string goes in the rulesets in Task 6.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/guard-base-branch.yml
git commit -m "ci: guard-base-branch — enforce base matrix, fail closed, allow dependabot"
```

Criteria 4 and 14 are verified live in Task 11 (real PRs against the template repo).

---

### Task 4: Secret scanning — criterion 9

**Files:**
- Create: `.pre-commit-config.yaml`, `.github/workflows/secret-scan.yml`

**Interfaces:**
- Produces: a status check named exactly **`secret-scan`** (the `jobs.` key), required by the rulesets in Task 6.

- [ ] **Step 1: Write `.pre-commit-config.yaml`**

```yaml
# Local hooks. SKIPPABLE with `git commit --no-verify` — the CI job is the real gate.
# Install once:  pre-commit install
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.21.2
    hooks:
      - id: gitleaks
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: check-merge-conflict
      - id: end-of-file-fixer
      - id: trailing-whitespace
```

- [ ] **Step 2: Write `.github/workflows/secret-scan.yml`**

Job id **must** be `secret-scan`.

```yaml
name: secret-scan

on:
  pull_request:
  push:
    branches: [dev, staging, main]

jobs:
  secret-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0          # gitleaks needs history to scan the PR's commits
      - name: gitleaks
        uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

- [ ] **Step 3: Verify the hook fires on a planted credential**

```bash
pre-commit install
PROBE="AKIAIOSFODNN7EXAMPL"X   # built at runtime: a literal here would trip our own secret-scan
printf 'AWS_SECRET_ACCESS_KEY=%s\n' "$PROBE" > /tmp/leak.env
cp /tmp/leak.env ./leak-test.env && git add -f leak-test.env
git commit -m "test: should be blocked" || echo "BLOCKED AS EXPECTED"
```
Expected: gitleaks blocks the commit. Then clean up:

```bash
git reset HEAD leak-test.env && rm -f leak-test.env
```

The bypass path (`--no-verify` → caught by `secret-scan` in CI) is verified live in Task 11. That is the guarantee that actually matters; the hook is a courtesy.

- [ ] **Step 4: Commit**

```bash
git add .pre-commit-config.yaml .github/workflows/secret-scan.yml
git commit -m "ci: gitleaks pre-commit hook and secret-scan job"
```

---

### Task 5: PR template, CODEOWNERS template, dependabot

**Files:**
- Create: `.github/PULL_REQUEST_TEMPLATE.md`, `.github/CODEOWNERS.tmpl`, `.github/dependabot.yml`

**Interfaces:**
- Produces: `.github/CODEOWNERS.tmpl` containing the literal token `@Avenue-Z/TEAM_SLUG`. Task 7's `init-repo.sh` substitutes that exact string, or deletes the file. It must never be named `CODEOWNERS` — a live file with an unresolvable team is **silently ignored** by GitHub and would ship enforcement theater.

- [ ] **Step 1: Write `.github/PULL_REQUEST_TEMPLATE.md`**

```markdown
## What

<!-- One sentence. What changes, and why? -->

## Base branch

<!-- feat/fix/docs/chore/ci -> dev  |  dev -> staging  |  staging -> main -->

## Checklist

- [ ] Tests pass, and I read the output.
- [ ] Lint passes.
- [ ] No credentials. (If one ever reached the remote: rotate it — removing the commit is not enough.)
- [ ] Docs updated if behavior changed.
- [ ] No volatile state added to `CLAUDE.md`.
```

- [ ] **Step 2: Write `.github/CODEOWNERS.tmpl`**

```
# TEMPLATE — not live. scripts/init-repo.sh writes .github/CODEOWNERS from this
# only after verifying the team exists AND has write access to the repo.
#
# Why the ceremony: GitHub SILENTLY IGNORES a CODEOWNERS entry naming a team that
# does not exist or lacks write access. No error, no warning. The file would look
# like enforced review while enforcing nothing.
*  @Avenue-Z/TEAM_SLUG
```

- [ ] **Step 3: Write `.github/dependabot.yml`**

`target-branch: dev` keeps dependabot inside the promotion chain, and pairs with the `dependabot/*` row in Task 3's matrix.

**Ship `github-actions` ONLY.** The stack-agnostic core has no `pyproject.toml` and no `package.json`, so declaring `pip` or `npm` here would make dependabot error with "manifest not found" on the template repo, and would leave a python repo carrying a dead npm block. `init-repo.sh` appends the block for the stack it selected (Task 7). Every repo then declares exactly the ecosystems it actually has.

```yaml
# Only github-actions here: it is the one ecosystem the stack-agnostic core actually has.
# scripts/init-repo.sh appends the pip OR npm block for the stack it selects.
version: 2
updates:
  - package-ecosystem: github-actions
    directory: "/"
    schedule: { interval: weekly }
    target-branch: dev
    open-pull-requests-limit: 5
```

- [ ] **Step 4: Commit**

```bash
git add .github/PULL_REQUEST_TEMPLATE.md .github/CODEOWNERS.tmpl .github/dependabot.yml
git commit -m "chore: PR template, CODEOWNERS template, dependabot targeting dev"
```

---

### Task 6: Rulesets as code

**Files:**
- Create: `.github/rulesets/repo-ruleset.json`, `.github/rulesets/org-ruleset.json`

**Interfaces:**
- Consumes: the job names `guard-base-branch` (Task 3) and `secret-scan` (Task 4).
- Produces: JSON consumed by `scripts/apply-rulesets.sh` (Task 8) via `gh api --input`.

Two traps this task exists to avoid, both of which brick a repo:
1. `required_approving_review_count: 1` on a solo repo → the author cannot approve their own PR → nothing is ever mergeable. **Use 0.**
2. A required check that does not exist does not fail — it hangs **pending forever**. The core has **no `ci`**, so `ci` must NOT appear here.

- [ ] **Step 1: Write `.github/rulesets/repo-ruleset.json`**

```json
{
  "name": "avenue-z-branch-protection",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "include": ["refs/heads/main", "refs/heads/staging", "refs/heads/dev"],
      "exclude": []
    }
  },
  "bypass_actors": [
    { "actor_id": 1, "actor_type": "OrganizationAdmin", "bypass_mode": "always" }
  ],
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": true,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": false,
        "required_status_checks": [
          { "context": "guard-base-branch" },
          { "context": "secret-scan" }
        ]
      }
    }
  ]
}
```

- [ ] **Step 2: Write `.github/rulesets/org-ruleset.json`**

Same rules, org-scoped, targeting every repo. **Committed, not applied** — org rulesets require GitHub Team, and Avenue-Z is on Free.

```json
{
  "name": "avenue-z-branch-protection-org",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "include": ["refs/heads/main", "refs/heads/staging", "refs/heads/dev"],
      "exclude": []
    },
    "repository_name": { "include": ["~ALL"], "exclude": [] }
  },
  "bypass_actors": [
    { "actor_id": 1, "actor_type": "OrganizationAdmin", "bypass_mode": "always" }
  ],
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": true,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": false,
        "required_status_checks": [
          { "context": "guard-base-branch" },
          { "context": "secret-scan" }
        ]
      }
    }
  ]
}
```

- [ ] **Step 3: Validate the JSON and assert `ci` is absent**

```bash
jq empty .github/rulesets/repo-ruleset.json && jq empty .github/rulesets/org-ruleset.json
! grep -q '"context": *"ci"' .github/rulesets/*.json && echo "OK: no 'ci' required (would hang pending)"
jq -r '.rules[] | select(.type=="pull_request") | .parameters.required_approving_review_count' \
  .github/rulesets/repo-ruleset.json
```
Expected: valid JSON, the `ci`-absent message, and `0`.

- [ ] **Step 4: Commit**

```bash
git add .github/rulesets/
git commit -m "chore: repo and org rulesets as code (org one is dormant until Team)"
```

---

### Task 7: `init-repo.sh` — criteria 1, 2, 3, 7, 8, 11, 15

**Files:**
- Create: `scripts/init-repo.sh`, `tests/test_init_repo.sh`

**Interfaces:**
- Consumes: `templates/<stack>/` (Tasks 9, 10), `.github/CODEOWNERS.tmpl` (Task 5).
- Produces: `init-repo.sh <python|node> [--team <slug>] [--no-push]`. `--no-push` exists so the tests can run without a remote.

Four invariants, each of which was a bug caught in review:

1. **Branch lineage.** `dev` still contains `templates/` until this script's commit removes it. Cut `staging` and `main` **after** that commit, or all three heads permanently carry dead files.
2. **`gh api`: 404 ≠ "couldn't tell."** `set -e` is disabled inside an `if` condition, so a bare `if ! gh api` treats an expired token exactly like a missing team and would silently drop CODEOWNERS. A 404 is an answer; anything else means **stop**.
3. **Idempotent on absence, not drift.** Create-if-absent, never force-push. Re-running does not reconcile a stale `main` — that is what a PR is for.
4. **`ci` is added to required checks only after `ci.yml` is in place.**

- [ ] **Step 1: Write the failing test** — `tests/test_init_repo.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "${REPO_ROOT}/tests/lib.sh"

# Build a throwaway clone so we never mutate the real template.
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT
git clone -q "${REPO_ROOT}" "${WORK}/repo"
cd "${WORK}/repo"
git checkout -qb dev 2>/dev/null || git checkout -q dev

echo "init-repo: python"
./scripts/init-repo.sh python --no-push

# Criterion 15 — no head carries templates/
[ ! -d templates ] && pass "templates/ removed from working tree" || fail "templates/ still present"
for b in dev staging main; do
  if git ls-tree -r --name-only "$b" | grep -q '^templates/'; then
    fail "branch $b still contains templates/"
  else
    pass "branch $b is free of templates/"
  fi
done

# Criterion 3 — all three branches exist
for b in dev staging main; do
  git rev-parse --verify -q "$b" >/dev/null && pass "branch $b exists" || fail "branch $b missing"
done

# Criterion 1 — the python skeleton is real
[ -f pyproject.toml ] && pass "pyproject.toml copied" || fail "pyproject.toml missing"
[ -f .github/workflows/ci.yml ] && pass "ci.yml copied" || fail "ci.yml missing"

# Criterion 8 — no --team means no inert CODEOWNERS
[ ! -f .github/CODEOWNERS ] && pass "no CODEOWNERS without --team" || fail "inert CODEOWNERS shipped"
[ ! -f .github/CODEOWNERS.tmpl ] && pass "CODEOWNERS.tmpl removed" || fail "CODEOWNERS.tmpl left behind"

# Criterion 7 — re-run is a no-op, exit 0
if ./scripts/init-repo.sh python --no-push; then pass "re-run exits 0"; else fail "re-run failed"; fi

# Criterion 11 — a bogus team WARNS and exits 0; it does not set -e crash
cd "${WORK}" && rm -rf repo2 && git clone -q "${REPO_ROOT}" repo2 && cd repo2
git checkout -qb dev 2>/dev/null || git checkout -q dev
if out=$(./scripts/init-repo.sh python --team definitely-not-a-real-team --no-push 2>&1); then
  pass "bogus --team exits 0 (guarded, not fatal)"
  grep -qi 'does not exist' <<<"$out" && pass "warned about the missing team" || fail "no warning emitted"
  [ ! -f .github/CODEOWNERS ] && pass "no CODEOWNERS written for a bogus team" || fail "wrote CODEOWNERS anyway"
else
  fail "bogus --team crashed instead of warning (set -e trap)"
fi

finish
```

- [ ] **Step 2: Run it, watch it fail**

```bash
chmod +x tests/test_init_repo.sh && ./tests/test_init_repo.sh
```
Expected: FAIL — `scripts/init-repo.sh` does not exist.

- [ ] **Step 3: Write `scripts/init-repo.sh`**

```bash
#!/usr/bin/env bash
#
# Turn a fresh copy of Avenue-Z/repo-template into a working repo.
#
#   ./scripts/init-repo.sh <python|node> [--team <slug>] [--no-push]
#
set -euo pipefail

ORG="Avenue-Z"
STACK=""
TEAM=""
PUSH=1

warn() { printf '\033[33mWARN\033[0m  %s\n' "$*" >&2; }
info() { printf '\033[32m--\033[0m    %s\n' "$*"; }
die()  { printf '\033[31mERROR\033[0m %s\n' "$*" >&2
         printf 'Recover with: git checkout -- . && git clean -fd\n' >&2
         exit 1; }

[ $# -ge 1 ] || die "usage: init-repo.sh <python|node> [--team <slug>] [--no-push]"
STACK="$1"; shift
case "${STACK}" in python|node) ;; *) die "stack must be 'python' or 'node', got '${STACK}'" ;; esac
while [ $# -gt 0 ]; do
  case "$1" in
    --team)    TEAM="${2:-}"; [ -n "${TEAM}" ] || die "--team needs a slug"; shift 2 ;;
    --no-push) PUSH=0; shift ;;
    *)         die "unknown flag '$1'" ;;
  esac
done

git rev-parse --git-dir >/dev/null 2>&1 || die "not a git repository"

# NOTE: every function is defined BEFORE it is called. Bash executes a script
# sequentially — a call placed above its definition dies with "command not found".
# The idempotency short-circuit calls ensure_branches, so it lives at the bottom.

# ------------------------------------------------------------------ CODEOWNERS
# GitHub SILENTLY IGNORES a CODEOWNERS entry whose team does not exist or lacks
# write access. So we verify, or we ship no file at all — never enforcement theater.
#
# The guard below distinguishes "team is absent" (404 — an answer) from "I could not
# tell" (auth, network, rate limit — NOT an answer). set -e is disabled inside an
# `if` condition, so a bare `if ! gh api` would treat an expired token as a missing
# team and silently drop the control. That is the exact failure this file prevents.
resolve_codeowners() {
  if [ -z "${TEAM}" ]; then
    warn "no --team given — this repo will have NO code-owner review."
    rm -f .github/CODEOWNERS.tmpl
    return 0
  fi

  local out
  if out=$(gh api "orgs/${ORG}/teams/${TEAM}" 2>&1); then
    :   # exists
  elif grep -qE '"status": *"404"|HTTP 404|Not Found' <<<"${out}"; then
    warn "team '${TEAM}' does not exist in ${ORG} — dropping CODEOWNERS (no code-owner review)."
    rm -f .github/CODEOWNERS.tmpl
    return 0
  else
    die "cannot verify team '${TEAM}' (not a 404 — auth? network? rate limit?): ${out}"
  fi

  # Existence is necessary but NOT sufficient: the team must also hold write access
  # on THIS repo, or the CODEOWNERS entry is silently ignored just the same.
  local repo perm
  repo="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || echo '')"
  if [ -n "${repo}" ]; then
    if perm=$(gh api "orgs/${ORG}/teams/${TEAM}/repos/${repo}" -q '.permissions.push' 2>&1); then
      [ "${perm}" = "true" ] || warn "team '${TEAM}' has no WRITE access to ${repo} — CODEOWNERS will be silently ignored until it does."
    else
      grep -qE '"status": *"404"|HTTP 404|Not Found' <<<"${perm}" \
        && warn "team '${TEAM}' is not attached to ${repo} — grant it write access or CODEOWNERS is inert." \
        || die "cannot check team write access (not a 404): ${perm}"
    fi
  fi

  sed "s|@${ORG}/TEAM_SLUG|@${ORG}/${TEAM}|" .github/CODEOWNERS.tmpl > .github/CODEOWNERS
  rm -f .github/CODEOWNERS.tmpl
  info "wrote .github/CODEOWNERS for @${ORG}/${TEAM}"
}

# -------------------------------------------------------------- branch lineage
# Cut staging and main from the POST-cleanup dev. Before the cleanup commit, dev
# still holds templates/ — branching early would leave all three heads carrying
# dead files forever. Create-if-absent; never force-push.
ensure_branches() {
  local head; head="$(git rev-parse --abbrev-ref HEAD)"
  for b in staging main; do
    if git rev-parse --verify -q "${b}" >/dev/null; then
      info "branch ${b} already exists — leaving it alone (re-run repairs absence, not drift)"
    else
      git branch "${b}" "${head}"
      info "created ${b} from ${head}"
    fi
  done
  if [ "${PUSH}" -eq 1 ]; then
    git push -u origin dev staging main
    info "pushed dev, staging, main"
  else
    info "--no-push: branches created locally only"
  fi
}

# ------------------------------------------------------------------------ main

# Idempotency short-circuit. Placed HERE, after ensure_branches is defined.
# Re-run repairs ABSENCE, not DRIFT: if templates/ is gone, the stack was selected on a
# previous run — do not re-copy, do not reset, do not force-push. A stale main is
# reconciled by opening a PR, not by re-running this script.
if [ ! -d templates ]; then
  info "templates/ already removed — this repo is initialized. Ensuring branches exist."
  ensure_branches
  exit 0
fi

info "initializing as a '${STACK}' repo"

[ -d "templates/${STACK}" ] || die "templates/${STACK} not found"

# 1. copy, 2. verify, 3. remove, 4. commit once, 5. push dev, 6. THEN branch.
cp -R "templates/${STACK}/." .
if [ "${STACK}" = python ]; then
  [ -f pyproject.toml ] || die "copy failed: pyproject.toml missing"
else
  [ -f package.json ] || die "copy failed: package.json missing"
fi
[ -f .github/workflows/ci.yml ] || die "copy failed: .github/workflows/ci.yml missing"
info "copied templates/${STACK} and verified"

resolve_codeowners

# Dependabot: the core declares only github-actions (the one ecosystem it actually has).
# Append the block for the stack we just selected, so this repo declares exactly what it has.
add_dependabot_ecosystem() {
  local eco
  case "${STACK}" in python) eco=pip ;; node) eco=npm ;; esac
  cat >> .github/dependabot.yml <<EOF
  - package-ecosystem: ${eco}
    directory: "/"
    schedule: { interval: weekly }
    target-branch: dev
    open-pull-requests-limit: 5
EOF
  info "added the '${eco}' ecosystem to .github/dependabot.yml"
}
add_dependabot_ecosystem

# Remove templates/ ONLY. init-repo.sh does NOT delete itself: criterion 7 requires a re-run
# to be a no-op exiting 0, and a self-deleting script cannot be re-run. The re-run IS the
# recovery path for a first run that died partway. scripts/ keeps apply-rulesets.sh regardless.
rm -rf templates
info "removed templates/"

git add -A
git commit -q -m "chore: initialize ${STACK} repo from Avenue-Z/repo-template"
info "committed the initialized tree"

if [ "${PUSH}" -eq 1 ]; then
  git push -u origin "$(git rev-parse --abbrev-ref HEAD)"
fi
ensure_branches

cat <<EOF

Done. Next:
  1. pre-commit install
  2. Fill in the TODOs in README.md and CLAUDE.md
  3. ./scripts/apply-rulesets.sh          # adds 'ci' to required checks now that ci.yml exists
EOF
```

- [ ] **Step 4: Run the test — expect PASS**

```bash
./tests/test_init_repo.sh
```
Expected: `ALL PASS`. This will only pass once Task 9 has created `templates/python/` — if you are executing in order, run Task 9 first and return here. (The plan lists this task before the templates because its interface defines what the templates must contain.)

- [ ] **Step 5: Commit**

```bash
git add scripts/init-repo.sh tests/test_init_repo.sh
git commit -m "feat: init-repo.sh — stack select, guarded CODEOWNERS, post-cleanup branch lineage"
```

---

### Task 8: `apply-rulesets.sh` — criterion 6

**Files:**
- Create: `scripts/apply-rulesets.sh`, `tests/test_apply_rulesets.sh`

**Interfaces:**
- Consumes: `.github/rulesets/*.json` (Task 6).
- Produces: `apply-rulesets.sh [--org]`. Exits **0** when protection is impossible, printing why — never a silent failure and never a false claim of success.

- [ ] **Step 1: Write the failing test**

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source tests/lib.sh

echo "apply-rulesets: honest reporting"
if out=$(./scripts/apply-rulesets.sh --dry-run 2>&1); then
  pass "exits 0"
else
  fail "should exit 0 even when protection is impossible"
fi
grep -qiE 'free|skip|cannot|unavailable|would apply' <<<"$out" \
  && pass "explains what it did or skipped" \
  || fail "silent — must say what it skipped and why"
finish
```

- [ ] **Step 2: Run it, watch it fail**

```bash
chmod +x tests/test_apply_rulesets.sh && ./tests/test_apply_rulesets.sh
```
Expected: FAIL — script does not exist.

- [ ] **Step 3: Write `scripts/apply-rulesets.sh`**

```bash
#!/usr/bin/env bash
#
# Apply branch protection where the GitHub plan allows it, and say plainly where it does not.
#
#   ./scripts/apply-rulesets.sh [--org] [--dry-run]
#
# Branch protection and rulesets are UNAVAILABLE on private repos on the Free plan — for
# everyone, including org owners. Org-level rulesets additionally require Team. This script
# never pretends otherwise: if it cannot protect a branch, it says so and exits 0.
#
set -euo pipefail

ORG="Avenue-Z"
DO_ORG=0
DRY=0

warn() { printf '\033[33mSKIP\033[0m  %s\n' "$*"; }
info() { printf '\033[32m--\033[0m    %s\n' "$*"; }
die()  { printf '\033[31mERROR\033[0m %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --org)     DO_ORG=1; shift ;;
    --dry-run) DRY=1; shift ;;
    *)         die "unknown flag '$1'" ;;
  esac
done

PLAN="$(gh api "orgs/${ORG}" -q .plan.name 2>/dev/null || echo unknown)"
info "org plan: ${PLAN}"

# ------------------------------------------------------------------ org ruleset
if [ "${DO_ORG}" -eq 1 ]; then
  if [ "${PLAN}" = free ]; then
    warn "org-level rulesets require GitHub Team. On Free they cannot be created."
    warn "  The ruleset is committed at .github/rulesets/org-ruleset.json, ready to apply on upgrade."
    exit 0
  fi
  if [ "${DRY}" -eq 1 ]; then
    info "[dry-run] would POST orgs/${ORG}/rulesets from .github/rulesets/org-ruleset.json"
    exit 0
  fi
  gh api -X POST "orgs/${ORG}/rulesets" --input .github/rulesets/org-ruleset.json \
    || die "org ruleset failed. Need the admin:org scope? gh auth refresh -h github.com -s admin:org"
  info "org ruleset applied — every repo in ${ORG} now inherits it."
  exit 0
fi

# ----------------------------------------------------------------- repo ruleset
REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
VIS="$(gh repo view --json visibility -q .visibility)"
info "repo: ${REPO} (${VIS})"

if [ "${VIS}" != "PUBLIC" ] && [ "${PLAN}" = free ]; then
  warn "${REPO} is PRIVATE and ${ORG} is on the Free plan."
  warn "  Branch protection and rulesets are UNAVAILABLE here. Nothing was applied."
  warn "  main/staging/dev are NOT protected. A direct push to main will succeed."
  warn "  Enforcement in this repo is: guard-base-branch + secret-scan on PRs, and convention."
  warn "  To get real protection: upgrade ${ORG} to GitHub Team, then run: $0 --org"
  exit 0                       # NOT an error — an honest report of a plan limit.
fi

# Add 'ci' to the required checks ONLY if ci.yml is actually present. A required check
# that never reports does not fail the PR — it hangs PENDING forever, and nothing merges.
PAYLOAD="$(mktemp)"; trap 'rm -f "${PAYLOAD}"' EXIT
if [ -f .github/workflows/ci.yml ]; then
  info "ci.yml present — adding 'ci' to required checks"
  jq '(.rules[] | select(.type=="required_status_checks") | .parameters.required_status_checks)
      += [{"context":"ci"}]' .github/rulesets/repo-ruleset.json > "${PAYLOAD}"
else
  info "no ci.yml (stack-agnostic core) — requiring only guard-base-branch + secret-scan"
  info "  A required 'ci' check would hang pending forever and make every PR unmergeable."
  cp .github/rulesets/repo-ruleset.json "${PAYLOAD}"
fi

if [ "${DRY}" -eq 1 ]; then
  info "[dry-run] would POST repos/${REPO}/rulesets with:"
  jq -r '.rules[] | select(.type=="required_status_checks")
         | .parameters.required_status_checks[].context' "${PAYLOAD}" | sed 's/^/        required: /'
  exit 0
fi

gh api -X POST "repos/${REPO}/rulesets" --input "${PAYLOAD}" >/dev/null \
  || die "ruleset POST failed for ${REPO}"
info "ruleset applied to ${REPO} on main, staging, dev."
info "Verify you can still merge:  gh api repos/${REPO}/branches/main/protection"
```

- [ ] **Step 4: Run the test — expect PASS**

```bash
chmod +x scripts/apply-rulesets.sh && ./tests/test_apply_rulesets.sh
```
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add scripts/apply-rulesets.sh tests/test_apply_rulesets.sh
git commit -m "feat: apply-rulesets.sh — apply what the plan allows, report what it skipped"
```

---

### Task 9: `templates/python/` — criterion 1

**Files:**
- Create: `templates/python/pyproject.toml`, `templates/python/.github/workflows/ci.yml`, `templates/python/Dockerfile`, `templates/python/.dockerignore`, `templates/python/src/app/__init__.py`, `templates/python/src/app/main.py`, `templates/python/tests/conftest.py`, `templates/python/tests/test_smoke.py`

**Interfaces:**
- Consumes: copied to the repo root by `init-repo.sh` (Task 7).
- Produces: a `ci.yml` whose job id is exactly **`ci`** — `apply-rulesets.sh` adds the context `"ci"`, and a mismatch hangs pending forever. This is criterion 13.

- [ ] **Step 1: Write the skeleton test first**

`templates/python/tests/conftest.py`:

```python
"""Shared fixtures. Prefer hand-rolled fakes over mock — the org's convention."""
```

`templates/python/tests/test_smoke.py`:

```python
from app.main import greet


def test_greet_returns_a_greeting():
    assert greet("world") == "hello, world"
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "app"
version = "0.1.0"
description = "TODO"
requires-python = ">=3.11"
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=8", "ruff>=0.6", "mypy>=1.11"]

[tool.hatch.build.targets.wheel]
packages = ["src/app"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.mypy]
python_version = "3.11"
strict = true
files = ["src"]
```

- [ ] **Step 3: Write the implementation**

`templates/python/src/app/__init__.py`: (empty file)

`templates/python/src/app/main.py`:

```python
def greet(name: str) -> str:
    return f"hello, {name}"
```

- [ ] **Step 4: Verify the skeleton passes its own gates**

```bash
cd templates/python
python -m venv .venv && . .venv/bin/activate
pip install -q -e ".[dev]"
pytest -q && ruff check . && mypy
deactivate && rm -rf .venv
cd ../..
```
Expected: 1 passed; ruff clean; mypy `Success`.

- [ ] **Step 5: Write `templates/python/.github/workflows/ci.yml`** — job id **must** be `ci`

```yaml
name: ci

on:
  pull_request:
  push:
    branches: [dev, staging, main]

jobs:
  ci:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install -e ".[dev]"
      - run: ruff check .
      - run: mypy
      - run: pytest -q
```

- [ ] **Step 6: Write the Dockerfile (Cloud Run Job)**

`templates/python/Dockerfile`:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir .
ENTRYPOINT ["python", "-m", "app.main"]
```

`templates/python/.dockerignore`:

```
.venv/
__pycache__/
.git/
tests/
docs/
```

- [ ] **Step 7: Commit**

```bash
git add templates/python
git commit -m "feat: python template — hatchling, ruff, mypy, pytest, ci job 'ci', Cloud Run Dockerfile"
```

---

### Task 10: `templates/node/` — criterion 2

**Files:**
- Create: `templates/node/package.json`, `templates/node/tsconfig.json`, `templates/node/eslint.config.mjs`, `templates/node/.github/workflows/ci.yml`, `templates/node/src/main.ts`, `templates/node/tests/smoke.test.ts`

**Interfaces:**
- Produces: a `ci.yml` whose job id is exactly **`ci`** — same contract as Task 9.

- [ ] **Step 1: Write the failing test** — `templates/node/tests/smoke.test.ts`

```typescript
import { describe, expect, it } from "vitest";
import { greet } from "../src/main.js";

describe("greet", () => {
  it("returns a greeting", () => {
    expect(greet("world")).toBe("hello, world");
  });
});
```

- [ ] **Step 2: Write `package.json`**

```json
{
  "name": "app",
  "version": "0.1.0",
  "type": "module",
  "engines": { "node": ">=20" },
  "scripts": {
    "test": "vitest run",
    "lint": "eslint .",
    "typecheck": "tsc --noEmit"
  },
  "devDependencies": {
    "@eslint/js": "^9.12.0",
    "eslint": "^9.12.0",
    "typescript": "^5.6.0",
    "typescript-eslint": "^8.8.0",
    "vitest": "^2.1.0"
  }
}
```

- [ ] **Step 3: Write `tsconfig.json` and `eslint.config.mjs`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "skipLibCheck": true
  },
  "include": ["src", "tests"]
}
```

```javascript
import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["node_modules/", "dist/"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
);
```

- [ ] **Step 4: Write the implementation** — `templates/node/src/main.ts`

```typescript
export function greet(name: string): string {
  return `hello, ${name}`;
}
```

- [ ] **Step 5: Verify the skeleton passes its own gates**

```bash
cd templates/node
npm install
npm test && npm run lint && npm run typecheck
rm -rf node_modules package-lock.json
cd ../..
```
Expected: 1 test passed; eslint clean; tsc clean.

- [ ] **Step 6: Write `templates/node/.github/workflows/ci.yml`** — job id **must** be `ci`

```yaml
name: ci

on:
  pull_request:
  push:
    branches: [dev, staging, main]

jobs:
  ci:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
      - run: npm ci
      - run: npm run lint
      - run: npm run typecheck
      - run: npm test
```

- [ ] **Step 7: Commit**

```bash
git add templates/node
git commit -m "feat: node template — vitest, eslint, tsc, ci job 'ci'"
```

---

### Task 11: Create the template repo and prove it works — criteria 3, 4, 5, 9, 12, 14

**Files:** none created — this is live verification against GitHub.

**Interfaces:**
- Consumes: everything above.

This is the task that proves the design rather than asserting it. **The template repo is public** — it holds no secrets by construction, and public is what makes branch protection available on the Free plan.

- [ ] **Step 1: Run the full local suite first**

```bash
./tests/test_gitignore.sh && ./tests/test_init_repo.sh && ./tests/test_apply_rulesets.sh
```
Expected: `ALL PASS` from each.

- [ ] **Step 2: Create the repo, public, default branch `dev`**

```bash
gh repo create Avenue-Z/repo-template --public \
  --description "Avenue Z repo template: main/staging/dev, conventions, CI, secret scanning" \
  --source . --remote origin --push
git branch -M dev 2>/dev/null || true
git push -u origin dev
gh api -X PATCH repos/Avenue-Z/repo-template -f default_branch=dev >/dev/null
gh api -X PATCH repos/Avenue-Z/repo-template -F is_template=true >/dev/null
gh repo view Avenue-Z/repo-template --json defaultBranchRef,isTemplate,visibility
```
Expected: `dev`, `true`, `PUBLIC`.

- [ ] **Step 3: Create `staging` and `main` from `dev`**

```bash
git branch staging dev && git branch main dev
git push -u origin staging main
gh api repos/Avenue-Z/repo-template/branches --jq '.[].name'
```
Expected: `dev`, `main`, `staging`.

- [ ] **Step 4: Verify the guard — criteria 4 and 14**

```bash
git checkout -b feat/guard-probe dev
echo "probe" >> docs/notes/.gitkeep && git commit -aqm "test: guard probe" && git push -u origin feat/guard-probe

gh pr create --base main --head feat/guard-probe --title "should FAIL" --body "feat/* must target dev"
sleep 45 && gh pr checks --watch || echo "FAILED AS EXPECTED (criterion 4)"
gh pr close --delete-branch=false "$(gh pr list --head feat/guard-probe --json number -q '.[0].number')"

gh pr create --base dev --head feat/guard-probe --title "should PASS" --body "feat/* -> dev"
sleep 45 && gh pr checks --watch && echo "PASSED AS EXPECTED"
```
Expected: base `main` → `guard-base-branch` **fails**. Base `dev` → **passes**.

Now the fail-closed case:

```bash
git checkout -b wip/unmatched dev && git push -u origin wip/unmatched
gh pr create --base dev --head wip/unmatched --title "should FAIL CLOSED" --body "unmatched prefix"
sleep 45 && gh pr checks --watch || echo "FAILED CLOSED AS EXPECTED (criterion 4)"
```
Expected: fails with "Unrecognized branch prefix".

- [ ] **Step 5: Verify `secret-scan` catches a `--no-verify` bypass — criterion 9**

This is the guarantee that matters: the hook is skippable, the CI job is not.

**Do not probe with AWS's published example key.** gitleaks' default AWS rule carries an allowlist
(`regexes = ['.+EXAMPLE$']`) that deliberately exempts any key ending in `EXAMPLE`. Probing with it
makes `secret-scan` **pass**, and you would wrongly conclude criterion 9 is satisfied while nothing
was caught. Change the trailing character so the allowlist does not match — the `PROBE=` line below
assembles the key at runtime, which also keeps a detectable literal out of this document (an earlier
draft embedded one, and the repo's own gitleaks hook correctly blocked the commit).

```bash
git checkout -b fix/leak-probe dev
PROBE="AKIAIOSFODNN7EXAMPL"X   # built at runtime: a literal here would trip our own secret-scan
printf 'AWS_SECRET_ACCESS_KEY=%s\n' "$PROBE" > leak.txt
git add leak.txt && git commit --no-verify -qm "test: planted credential, hook bypassed"
git push -u origin fix/leak-probe
gh pr create --base dev --head fix/leak-probe --title "should FAIL secret-scan" --body "planted key"
sleep 60 && gh pr checks --watch || echo "SECRET-SCAN FAILED THE PR AS EXPECTED (criterion 9)"
gh pr close --delete-branch "$(gh pr list --head fix/leak-probe --json number -q '.[0].number')"
git push origin --delete fix/leak-probe && git checkout dev
```
Expected: `secret-scan` fails the PR even though the hook was bypassed.

- [ ] **Step 6: Apply the ruleset and confirm the repo is still usable — criteria 5 and 12**

Protection that bricks the repo is a **failed** criterion, not a passed one.

```bash
./scripts/apply-rulesets.sh --dry-run       # confirm: guard-base-branch + secret-scan, NO ci
./scripts/apply-rulesets.sh
gh api repos/Avenue-Z/repo-template/branches/main/protection --jq '.required_status_checks.contexts'
```
Expected: `["guard-base-branch","secret-scan"]` — **`ci` absent**. If `ci` appears, every PR will hang pending and the repo is bricked.

Now prove a maintainer can still merge:

```bash
git checkout -b chore/protection-probe dev
echo "" >> README.md && git commit -aqm "chore: probe merge under protection" && git push -u origin chore/protection-probe
gh pr create --base dev --head chore/protection-probe --title "probe: mergeable under protection" --body "criterion 5"
sleep 60 && gh pr merge --squash --delete-branch
```
Expected: **merges**. A hang here means a required check never reported — check that the ruleset context strings equal the `jobs:` keys exactly.

- [ ] **Step 7: Clean up the probes and record the result**

```bash
git checkout dev && git pull
git push origin --delete feat/guard-probe wip/unmatched 2>/dev/null || true
gh pr list --state open
```
Expected: no open probe PRs.

---

### Task 12: End-to-end on a generated repo — criterion 13

**Files:** none — live verification of the case Task 11 structurally cannot cover.

**Why this task exists:** criterion 12 proves the required-check trap is avoided on the *template*, which by construction never has a `ci` check. That proves the trap is dodged in the one place it **cannot occur**. The trap actually lives in every *generated* repo, where `apply-rulesets.sh` adds a `ci` context that must match the `jobs.ci` key in the copied `ci.yml`. If it does not, every PR in every generated repo hangs pending forever — and template testing would never reveal it.

- [ ] **Step 1: Generate a throwaway repo from the template**

```bash
gh repo create Avenue-Z/tmpl-probe-python --private --template Avenue-Z/repo-template
sleep 5
git clone git@github.com:Avenue-Z/tmpl-probe-python.git /tmp/tmpl-probe && cd /tmp/tmpl-probe
git branch --show-current      # expect: dev  (Use-this-template copies the default branch only)
```

- [ ] **Step 2: Initialize it**

```bash
./scripts/init-repo.sh python
```
Expected: copies the stack, warns about no `--team`, removes `templates/`, commits once, pushes `dev`, then creates and pushes `staging` and `main`.

- [ ] **Step 3: Verify criteria 15, 3, 8, 1**

```bash
for b in dev staging main; do
  git ls-tree -r --name-only "origin/$b" | grep -q '^templates/' \
    && echo "FAIL: $b carries templates/" || echo "ok: $b clean"
done                                                   # criterion 15
gh api repos/Avenue-Z/tmpl-probe-python/branches --jq '.[].name'   # criterion 3
test ! -f .github/CODEOWNERS && echo "ok: no inert CODEOWNERS"     # criterion 8
pip install -e ".[dev]" -q && pytest -q && ruff check .            # criterion 1
```
Expected: three clean branches; `dev`/`main`/`staging`; no CODEOWNERS; tests and lint pass.

- [ ] **Step 4: The one that matters — `ci` must REPORT, not hang — criterion 13**

```bash
./scripts/apply-rulesets.sh
# Private repo on Free -> expect the honest SKIP message, exit 0 (criterion 6).
```

The repo is private on Free, so no ruleset applies. To test the *check-name* invariant — the actual trap — open a PR and confirm a check literally named `ci` reports a result:

```bash
git checkout -b feat/ci-probe dev
echo "" >> README.md && git commit -aqm "test: does the ci check report?" && git push -u origin feat/ci-probe
gh pr create --base dev --head feat/ci-probe --title "probe: ci reports" --body "criterion 13"
sleep 90
gh pr checks --json name,state -q '.[] | "\(.name)\t\(.state)"'
```
Expected: a row whose name is exactly **`ci`** with a state of `SUCCESS` (or `FAILURE`) — **never `PENDING`**. Also expect `guard-base-branch` and `secret-scan`.

**If no row named `ci` appears,** the job id in `templates/python/.github/workflows/ci.yml` does not match the `"context": "ci"` that `apply-rulesets.sh` adds. Fix the job id — that is the hang-pending bug, caught exactly where it lives.

- [ ] **Step 5: Repeat for node**

```bash
gh repo create Avenue-Z/tmpl-probe-node --private --template Avenue-Z/repo-template
git clone git@github.com:Avenue-Z/tmpl-probe-node.git /tmp/tmpl-probe-node && cd /tmp/tmpl-probe-node
./scripts/init-repo.sh node
git checkout -b feat/ci-probe dev && echo "" >> README.md
git commit -aqm "test: ci reports" && git push -u origin feat/ci-probe
gh pr create --base dev --head feat/ci-probe --title "probe: ci reports" --body "criterion 13 (node)"
sleep 90 && gh pr checks --json name,state -q '.[] | "\(.name)\t\(.state)"'
```
Expected: a check named exactly `ci`, reporting — not pending.

- [ ] **Step 6: Delete the probe repos**

```bash
gh repo delete Avenue-Z/tmpl-probe-python --yes
gh repo delete Avenue-Z/tmpl-probe-node --yes
rm -rf /tmp/tmpl-probe /tmp/tmpl-probe-node
```

- [ ] **Step 7: Record the outcome in the spec's review log**

Append a "Build verified — <date>" section to
`template-docs/specs/2026-07-13-avenue-z-repo-template-design.md` listing each of the 15 criteria
and whether it passed, with the command output that proves it. Commit on a `docs/*` branch and PR into
`dev`.

---

## Deferred: blocked on a GitHub Team upgrade

Not tasks — they cannot be executed on the Free plan. Do them the day Avenue-Z upgrades:

1. `gh auth refresh -h github.com -s admin:org`, then `./scripts/apply-org-ruleset.sh --dry-run`
   and, once the plan looks right, `./scripts/apply-org-ruleset.sh` (it will make you type a
   challenge phrase — there is no `--yes`, and it cannot run unattended).
2. **Answer open question 1:** does a repo creator in Avenue-Z actually receive the Admin role?
3. **Answer open question 2:** does a repo-level bypass actor survive an org-level ruleset, or does the
   org ruleset outrank it? This determines whether the emergency-bypass design works at all.
4. Only after 2 and 3 are answered, write the confirmed behavior into `CONTRIBUTING.md`.
