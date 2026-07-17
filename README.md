# Avenue-Z Repo Template

A GitHub template repository that a new Avenue Z project is created from in one click plus one
script, and that **starts life with the org's conventions already in place** — branch flow, secret
scanning, branch protection (where the plan allows it), CODEOWNERS, dependabot, and a working CI
pipeline for the stack you pick.

> This page is the template's front door. A repo **created** from it starts from a clean skeleton
> instead — `scripts/init-repo.sh` swaps this README for `README.repo.tmpl` at generation, so none
> of this text ships into your new repo.

## Stacks

`scripts/init-repo.sh <python|node|next>` selects one and deletes the rest:

- **`python`** — hatchling, `src/` layout, ruff + mypy + pytest (3.11–3.13 matrix), Cloud Run Dockerfile.
- **`node`** — a TypeScript library: vitest + eslint + `tsc --noEmit`.
- **`next`** — Next.js App Router + TypeScript, CI that also runs `next build`, and one-command Vercel
  linking that **cannot deploy by accident** (`scripts/link-vercel.sh`).

## The one idea

Every control states plainly **what it does not do**, and **a failure to verify is never treated as
a verified pass.** The branch guard cannot stop a direct push, and says so. Secret scanning protects
*merge*, not *push* — a leaked key that reached the remote is burned, so rotate it. A CODEOWNERS
entry for a team without write access is silently ignored, so the script grants write or ships no
file at all — and CODEOWNERS **routes** reviewers, it does not **require** their approval (the
ruleset ships `required_approving_review_count: 0`). No enforcement theater; each layer is honest
about its own boundary. See [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`SECURITY.md`](SECURITY.md).

## Quick start (net-new repo)

1. Click **Use this template** on this repo → create a new **private** repo (it copies only the
   default branch, `main`).
2. Clone it, then:

       git checkout -b dev
       ./scripts/init-repo.sh <python|node|next> [--team <slug>]

   This copies the stack, strips the template's own machinery, commits once, and pushes
   `dev`/`staging`/`main`. **Run it from `dev`** — the default branch is `main` on purpose (Vercel
   and most tooling take *production* from the repo default), so a fresh copy lands you on `main` and
   the script refuses to run until you branch.
3. `./scripts/apply-rulesets.sh` — applies branch protection where the plan allows, and prints
   exactly what it skipped.
4. `next` stack: `vercel login`, then `./scripts/link-vercel.sh`. Nothing deploys until someone
   enables a branch in `vercel.json` via a reviewed PR.

**→ Full playbook, including existing repos and the org-wide path: [`docs/ADOPTION.md`](docs/ADOPTION.md).**

## Scripts

- `scripts/init-repo.sh <python|node|next> [--team <slug>]` — stack select, branch lineage, CODEOWNERS.
- `scripts/apply-rulesets.sh [--dry-run]` — branch protection for **this** repo, where the plan allows.
- `scripts/apply-org-ruleset.sh [--dry-run]` — org-wide ruleset; deliberately hard to run (needs Team).
- `scripts/link-vercel.sh [--dry-run]` — (`next`) link a Vercel project; never deploys.

## How it was designed

- [`template-docs/specs/`](template-docs/specs/) — the design specs, with their review logs.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — the branch flow. **Never push directly to `main`.**
- [`SECURITY.md`](SECURITY.md) — credential handling and the merge-not-push boundary.
