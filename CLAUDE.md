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
1. Branch flow is `feat/* | fix/* | docs/* | chore/* | ci/* | dependabot/* → dev → staging → main`.
   **Never push directly to `main`.** `CONTRIBUTING.md` is canonical; `guard-base-branch` enforces it
   and **fails closed on any prefix not in that list**.
2. Sync before you start: `git fetch --all --prune && git log origin/dev..HEAD`.
3. Verify before claiming done — run the tests and read the output. Do not assert a pass you
   have not seen.
4. Never commit credentials. `.gitignore` is a denylist and denylists leak; `secret-scan` is the
   real control.

## Project rules
<!-- TODO: the rules specific to THIS repo. Keep them durable. -->
