# `next` stack + Vercel linking — design

**Date:** 2026-07-14
**Repo:** `Avenue-Z/repo-template`

## Problem

The template ships `python` and `node` stacks. `node` is a **library** — a `greet()` function, `tsc --noEmit`, no framework, no build. But a large share of Avenue Z's real repos are Next.js front-ends on Vercel (`reporting-dashboard-*`, `aeo-audit-deck`, the template's own design spec names `avenue-z-reporting-v2` as a "TypeScript/Vercel" reference repo).

Today those repos are hand-rolled, so they get none of the governance core. The only trace of Vercel in the template is `.next/` and `.vercel/` in `.gitignore` — ignore rules for a stack that does not exist. That is a **false promise**: it implies support the template does not have.

## Goals

1. `init-repo.sh next` produces a working Next.js repo with CI.
2. Linking a Vercel app is **as easy as possible** — one command.
3. Deploys **cannot run wild**. Human gates, enforced by mechanism rather than by warning.

## The landmine: default branch = production

Vercel picks the production branch from `main`, `master`, or **the repository's default branch**. There is **no documented API** to set it — only an undocumented `/v9/projects/:id/branch` endpoint the dashboard uses. Vercel's own official workaround is: *use the repository default branch, and change it via your git provider's API.*

This template's default branch was **`dev`**. So a linked repo would have taken **`dev` as production** — every merged PR deploying straight to prod, bypassing `staging` entirely, inverting the whole branch flow. Silently.

**Resolution: the template's default branch becomes `main`.** Vercel's production branch then follows it correctly, with no undocumented endpoints. This is the *only* non-fragile fix; baking an unsupported API call into a script would break silently later.

### Costs of the switch, accepted knowingly

- **PR base.** GitHub has no separate "default PR base" setting, so a PR opened in the UI targets `main`. The author changes the base with a dropdown (`guard-base-branch` re-runs on the `edited` event and goes green), or uses `gh pr create --base dev`. A miss is caught **loudly** by a red check — never silently.
- **`init-repo.sh`.** A fresh "Use this template" copy now starts on `main`, so it needs one `git checkout -b dev` first. The script already requires `HEAD = dev` and says so. Crucially, `ensure_branches` then **fast-forwards** the local `main` past the cleanup commit — which only works because of the PR #13 fix. Before that fix, this switch would have stranded `main` on the raw template.

The `dev` default bought convenience on two things that fail **loudly**. It cost correctness on a class of thing that fails **silently** — any tool that equates the default branch with production. That is a bad trade, so we stop making it.

## The `next` stack

`templates/next/` — Next.js App Router + TypeScript.

- `package-lock.json` committed, so CI uses `npm ci` (reproducible, matching the `node` stack).
- `.github/workflows/ci.yml` with a job named **literally `ci`** — the rulesets require that exact status-check context, and a required check that never reports hangs every PR pending forever. `template-tests/test_rulesets.sh` already iterates `templates/*/` and enforces this, so the new stack is policed for free.
- CI runs lint → typecheck → test → **build**. `build` matters here in a way it does not for a library: a Next app that type-checks can still fail to build.
- `init-repo.sh` accepts `next` and maps it to the `npm` dependabot ecosystem.

## Vercel linking — easy to link, hard to deploy

The two are deliberately separated. **Linking is one command. Deploying is a reviewed code change.**

### `scripts/link-vercel.sh`

- **Requires a TTY.** No CI, no automation.
- **Requires a logged-in Vercel CLI.** The script will *not* log you in; `vercel login` is the human's to run.
- Runs `vercel link` — interactive; the human picks the scope and project.
- **Verifies, and refuses to finish if wrong:**
  - GitHub's default branch is `main`.
  - Vercel's production branch is `main`, or unset (thus inheriting `main`).
  - It **never** silently "fixes" this via the undocumented endpoint. It reports the problem and tells the human to set it in the dashboard. A failure to verify is never treated as a verified pass — the same rule the rest of this repo runs on.
- **Never runs `vercel deploy`.** Not once, under any flag.

### Deploys ship OFF

`templates/next/vercel.json`:

```json
{ "git": { "deploymentEnabled": false } }
```

Linking creates the Vercel project and deploys **nothing** — not even previews. Unspecified branches default to `true` in Vercel, so a bare `false` is the only posture that is safe by default.

**Turning a branch on means editing `vercel.json`, which means a PR, which means review and the branch flow.** That is the human gate. Runaway deploys are not prevented by a warning that nobody reads — they are prevented by the fact that enabling a deploy is a reviewed change to a tracked file.

## Testing

- `test_next_stack.sh` — the `ci` job is named `ci`; CI runs a real `build`; `vercel.json` ships deploys disabled.
- `test_link_vercel.sh` — driven by a stub `vercel` and stub `gh` (the pattern already used for `gh` elsewhere): refuses without a TTY; refuses when the default branch is not `main`; refuses when the Vercel production branch is something else; **never invokes `vercel deploy`** (asserted by a stub that records every call).
- `test_rulesets.sh` picks up `templates/next/` automatically.

## Out of scope

- A deploy workflow / `VERCEL_TOKEN` in CI. Vercel's native Git integration handles deploys once a branch is enabled; adding a token-driven workflow is a separate decision, and a bigger one — it would be the first time the template holds a third-party credential.
- Migrating existing Vercel repos onto the template.

## Success criteria

- `init-repo.sh next` yields a repo whose CI passes and whose `ci` check is reachable.
- A linked repo deploys **nothing** until a human edits `vercel.json` in a reviewed PR.
- No repo made from this template can have `dev` as its Vercel production branch without someone deliberately overriding a verified check.
