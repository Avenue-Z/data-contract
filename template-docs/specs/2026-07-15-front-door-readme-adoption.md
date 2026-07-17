# Front-door README + adoption playbook — design

**Date:** 2026-07-15
**Repo:** `Avenue-Z/repo-template`

## Problem

The repository's own `README.md` is authored as the **seed** for a generated repo — a skeleton of
`<!-- TODO -->` markers that `init-repo.sh` leaves in place for the new repo's author to fill in.
That is correct for a generated repo, but it means the **template's own GitHub landing page** is a
blank product skeleton. Someone who opens `Avenue-Z/repo-template` sees no explanation of what the
template is, which stacks it offers, or how to adopt it. The "how do I use this" story lives only in
`docs/superpowers/specs/` and at the bottom of the seed README — the house has no sign on the door.

There is also no written **adoption playbook**. The net-new flow is one-click-plus-one-script and
`repo-template-first` routes to it, but nothing documents adopting the template into an **existing**
repo, or the org-wide path — including the hazards the design deliberately refuses to script
(making a private repo public exposes git history; existing repos may carry credentials).

## Constraint: README double-duty

`README.md` is both the template's front door **and** the seed every generated repo inherits.
`init-repo.sh` strips `templates/`, `template-tests/`, the template-tests workflow, and the
template's own spec/plan from a generated repo, but it deliberately does **not** touch `README.md`.
So any front-door content added to `README.md` would ship into every generated repo — exactly the
template cruft the repo works to eliminate.

## Decision: README-swap, mirroring `CODEOWNERS.tmpl`

The repo already ships template-only files that `init-repo.sh` materializes or strips at generation.
The README joins that set:

| File | Role | `init-repo.sh` action at generation |
|---|---|---|
| `README.md` | **Front door** — rendered on the template's GitHub page | Overwritten by the seed |
| `README.repo.tmpl` (new, root) | The seed skeleton (today's `README.md`, verbatim) | `mv -f README.repo.tmpl README.md` |
| `docs/ADOPTION.md` (new) | Full adoption playbook | Added to the existing `rm -f` strip list |

- The `.tmpl` suffix keeps GitHub from rendering the seed instead of the front door — the same
  reason `CODEOWNERS.tmpl` is not named `CODEOWNERS`.
- The swap lands in the existing cleanup block, next to the spec/plan strip. The idempotency
  short-circuit (`[ ! -d templates ]`) already makes a re-run a no-op, so it will not double-swap.
- The seed retains the existing **"Repo setup scripts (template-derived repos)"** section — those
  scripts do ship to generated repos, so their docs must too.

## Content

**`README.md` (front door)** — concise and skimmable: one-line what-it-is → the three stacks → the
enforcement philosophy in one line (*every control states what it does NOT do; a failure to verify
is not a verified pass*) → net-new quick-start (Use this template → `git checkout -b dev` →
`init-repo.sh`) → link to `docs/ADOPTION.md` → pointers to the scripts and the design specs.

**`docs/ADOPTION.md` (playbook)** — three tracks:
- **Net-new** — the full step-by-step; ready today, also skill-routed via `repo-template-first`.
- **Existing repos** — the careful manual port, **secret-audit-first**, and the private→public
  git-history hazard the design refuses to script.
- **Org-wide** — needs GitHub Team; the two still-open questions (does a repo creator receive Admin;
  does a repo-level bypass actor survive an org ruleset).

## Testing

Extend `template-tests/test_init_repo.sh`: after `init-repo.sh` runs, assert that the generated
`README.md` is the **seed** (carries the `<!-- TODO: repo-name -->` marker, not the front-door
title), and that `README.repo.tmpl` and `docs/ADOPTION.md` are **gone**. This holds the
"generated repos carry zero template cruft" invariant, alongside the existing `templates/` and
`template-tests/` assertions.

## Out of scope

- `CLAUDE.md` (also a seed skeleton) — not part of this request.
- Restructuring `docs/`.
## Folded in: the design-doc strip rotted

While adding this feature's own spec, a pre-existing bug surfaced: `init-repo.sh` stripped the
template's design docs by **listing their filenames**, so `2026-07-14-next-stack-vercel-design.md`
(and this spec) shipped into generated repos untouched, and the test only asserted the `2026-07-13`
files by name. Fixed by pattern: `init-repo.sh` now deletes every `*.md` under
`docs/superpowers/{specs,plans}/` that is not a `README.md`, and the test asserts the same by
pattern rather than by filename — so the next template spec cannot rot the same way.
